"""The depth view: a side-on window onto the project that you can ROTATE, so it is not stuck looking from the front.

You look along a compass bearing at a slab of the site: the slab starts at an alignment line (the "depth line", drawn on the
plan view while this window is open) and runs a chosen depth beyond it.  The ground is shown as sections cut through the
surface at the line and at planes further in (fainter with depth), survey points and linework inside the slab are drawn
dimmer and smaller the deeper they are.  Drag to pan, wheel to zoom, right-drag to rotate the bearing.
"""
from __future__ import annotations

import math
import threading

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QCheckBox, QDial, QDoubleSpinBox, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from ..core import scene3d as S
from ..core import units as U
from . import theme
from .render import make_path, nice_length, pen_for
from .view3d import SceneProvider, _btn

_COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def compass(az: float) -> str:
    return _COMPASS[int(((az % 360.0) + 22.5) // 45) % 8]


def _decimals(step: float) -> int:
    return max(0, -int(math.floor(math.log10(max(step, 1e-12)))))


# ============================================================================ the drawing widget
class DepthView(QWidget):
    changed = Signal()                 # the view moved / rotated / re-sliced (controls and the plan overlay follow)

    def __init__(self, state, provider: SceneProvider, canvas, parent=None):
        super().__init__(parent)
        self.state, self.provider, self.canvas = state, provider, canvas
        self.spec = S.DepthSpec()
        self.show_ground = self.show_lines = self.show_points = True
        self.show_numbers = False
        self.follow = True
        self.station_offset = 0.0              # added to the horizontal axis labels (station 0 at a picked line's start)
        self._inited_for = None
        self._drag = None
        self._cache: dict = {}
        self._preparing = False
        self.setMinimumSize(260, 200)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setCursor(Qt.OpenHandCursor)
        provider.changed.connect(self._scene_changed)
        state.selection_changed.connect(self.update)
        canvas.view_changed.connect(self._plan_moved)

    # ------------------------------------------------------------------ parameters
    def _emit(self):
        self.update()
        self.changed.emit()

    def set_azimuth(self, az: float):
        self.spec.azimuth = float(az) % 360.0
        self.station_offset = 0.0
        self._emit()

    def rotate(self, delta: float):
        self.set_azimuth(self.spec.azimuth + delta)

    def set_slab(self, near: float | None = None, far: float | None = None):
        if near is not None:
            self.spec.near = float(near)
        if far is not None:
            self.spec.far = float(far)
        if self.spec.far < self.spec.near:
            self.spec.far = self.spec.near
        self._emit()

    def set_vexag(self, v: float):
        self.spec.vexag = max(float(v), 0.01)
        self._emit()

    def set_option(self, name: str, value: bool):
        setattr(self, name, bool(value))
        self.update()

    def set_follow(self, on: bool):
        self.follow = bool(on)
        if self.follow:
            self.spec.center = (self.canvas.view.cx, self.canvas.view.cy)
            self.station_offset = 0.0
        self._emit()

    def auto_vexag(self):
        sc = self.provider.scene()
        if sc.bounds is not None:
            self.spec.vexag = S.auto_vexag(sc.bounds)
        self._emit()

    def fit(self):
        sc = self.provider.scene()
        if sc.bounds is not None and self.width() > 20:
            self.follow = False
            self.station_offset = 0.0
            self.spec.fit_bounds(sc.bounds, self.width(), self.height())
        self._emit()

    def set_line(self, a, b):
        """Look across the line a -> b: it runs left to right and the view looks to its left."""
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-9:
            return
        self.follow = False
        self.spec.fit_line(a, b, max(self.width(), 50))
        self.station_offset = math.hypot(b[0] - a[0], b[1] - a[1]) / 2.0
        sc = self.provider.scene()
        if sc.bounds is not None:
            self.spec.zc = (sc.bounds[2] + sc.bounds[5]) / 2.0
        self._emit()

    def _plan_moved(self):
        if self.follow:
            self.spec.center = (self.canvas.view.cx, self.canvas.view.cy)
            self._emit()

    def _scene_changed(self):
        self._cache.clear()
        self.update()

    def _first_fit(self):
        pid = id(self.state.project)
        sc = self.provider.scene()
        if self._inited_for != pid and sc.bounds is not None and self.width() > 60:
            self._inited_for = pid
            x0, y0, z0, x1, y1, z1 = sc.bounds
            s = self.spec
            s.vexag = S.auto_vexag(sc.bounds)
            s.azimuth, s.near = 0.0, 0.0
            s.far = nice_length(max(x1 - x0, y1 - y0, 1.0) * 0.25)
            s.center = (self.canvas.view.cx, self.canvas.view.cy) if self.follow else ((x0 + x1) / 2, (y0 + y1) / 2)
            s.zc = (z0 + z1) / 2.0
            s.scale = min(self.width() * 0.9 / max(x1 - x0, 1e-9), self.height() * 0.8 / max((z1 - z0) * s.vexag, 1e-9))
            self.changed.emit()

    # ------------------------------------------------------------------ ground sections (cached; pan / zoom just reproject)
    def _surface_tin(self, mesh):
        s = self.state.project.surfaces.get(mesh.id)
        return None if s is None or len(s.tris) == 0 else s.tin()

    def _prepare(self, tin):
        if self._preparing:
            return
        self._preparing = True

        def run():
            try:
                tin.prepare()
            finally:
                self._preparing = False

        threading.Thread(target=run, daemon=True).start()
        QTimer.singleShot(250, self._poll_prepared)

    def _poll_prepared(self):
        if self._preparing:
            QTimer.singleShot(250, self._poll_prepared)
        else:
            self.update()

    def _planes(self):
        s = self.spec
        if s.far - s.near < 1e-9:
            return [s.near]
        return list(np.linspace(s.near, s.far, 7))

    def _section_profiles(self, sc):
        """[(plane offset, [(h, z) runs])] for every surface: h = absolute coordinate along the alignment direction."""
        s = self.spec
        d, r = s.axes()
        dc = float(np.asarray(s.center, float) @ d)
        key = (round(s.azimuth, 4), round(dc, 6), round(s.near, 6), round(s.far, 6), sc.rev, id(sc))
        hit = self._cache.get("prof")
        if hit and hit[0] == key:
            return hit[1]
        x0, y0, _, x1, y1, _ = sc.bounds
        corners = np.array([[x, y] for x in (x0, x1) for y in (y0, y1)])
        hs = corners @ r
        hmin, hmax = float(hs.min()) - 1.0, float(hs.max()) + 1.0
        out = []
        for mesh in sc.meshes:
            tin = self._surface_tin(mesh)
            if tin is None:
                continue
            if tin._finder is None:
                if tin.n_tris < 30000:
                    tin.prepare()                            # quick
                else:
                    self._prepare(tin)                       # big: on a worker thread, we repaint when it is ready
                    return None
            for off in self._planes():
                A = r * hmin + d * (dc + off)
                B = r * hmax + d * (dc + off)
                st, z, _ = tin.profile(np.array([A, B]))
                if len(st) < 2:
                    continue
                runs, cur = [], []
                for sti, zi in zip(st, z):
                    if math.isfinite(zi):
                        cur.append((hmin + sti, zi))
                    elif cur:
                        runs.append(cur)
                        cur = []
                if cur:
                    runs.append(cur)
                out.append((off, runs))
        self._cache["prof"] = (key, out)
        return out

    # ------------------------------------------------------------------ painting
    def paintEvent(self, ev):
        self._first_fit()
        p = QPainter(self)
        col = theme.colors()
        p.fillRect(self.rect(), QColor(col["canvas"]))
        sc = self.provider.scene()
        W, H = self.width(), self.height()
        if sc.bounds is None:
            p.setPen(QColor(col["dim"]))
            p.drawText(self.rect(), Qt.AlignCenter, "Nothing to show yet.\nImport points with elevations or build a surface.")
            p.end()
            return
        p.setRenderHint(QPainter.Antialiasing, True)
        self._paint_grid(p, W, H)
        if self.show_ground and sc.meshes:
            self._paint_ground(p, sc, W, H)
        if self.show_lines:
            self._paint_lines(p, sc, W, H)
        if self.show_points:
            self._paint_points(p, sc, W, H)
        self._paint_edges(p, W, H)
        p.end()

    def _font(self, px=10, bold=False):
        f = QFont()
        f.setPixelSize(px)
        f.setBold(bold)
        return f

    def _paint_grid(self, p, W, H):
        s, col = self.spec, theme.colors()
        kh, kv = s.scale, s.scale * s.vexag
        p.setFont(self._font(10))
        zt = S.nice_ticks(s.zc - H / 2 / kv, s.zc + H / 2 / kv, max(3, H // 70))
        dec = _decimals(float(np.diff(zt)[0])) if len(zt) > 1 else 1
        for z in zt:
            y = H / 2 - (z - s.zc) * kv
            p.setPen(QPen(QColor(col["grid"]), 1.0))
            p.drawLine(QPointF(0, y), QPointF(W, y))
            p.setPen(QColor(col["dim"]))
            p.drawText(QPointF(4, y - 3), f"{z:,.{dec}f}")
        off = self.station_offset
        ht = S.nice_ticks(-W / 2 / kh + off, W / 2 / kh + off, max(3, W // 110))
        dec = _decimals(float(np.diff(ht)[0])) if len(ht) > 1 else 1
        for t in ht:
            x = W / 2 + (t - off) * kh
            p.setPen(QPen(QColor(col["grid"]), 1.0))
            p.drawLine(QPointF(x, 0), QPointF(x, H))
            p.setPen(QColor(col["dim"]))
            p.drawText(QPointF(x + 3, H - 5), f"{t:,.{dec}f}")

    def _ground_color(self):
        return (120, 190, 140) if theme.current() == "dark" else (50, 120, 80)

    def _paint_ground(self, p, sc, W, H):
        s = self.spec
        profs = self._section_profiles(sc)
        if profs is None:
            p.setPen(QColor(theme.colors()["warn"]))
            p.setFont(self._font(11))
            p.drawText(QPointF(12, 34), "Preparing the surface...")
            return
        kh, kv = s.scale, s.scale * s.vexag
        cr = float(np.asarray(s.center, float) @ s.axes()[1])
        gc = self._ground_color()
        span = max(s.far - s.near, 1e-9)
        for off, runs in sorted(profs, key=lambda t: -t[0]):                 # far planes first
            t = (off - s.near) / span if span > 1e-9 else 0.0
            near_plane = off == s.near
            alpha = 255 if near_plane else int(215 * (1 - 0.8 * t))
            width = 2.4 if near_plane else 1.3
            for run in runs:
                a = np.array(run)
                if len(a) < 2:
                    continue
                X = W / 2 + (a[:, 0] - cr) * kh
                Y = H / 2 - (a[:, 1] - s.zc) * kv
                if X.max() < -5 or X.min() > W + 5:
                    continue
                if near_plane:                                                # the mass under the cut
                    poly = QPolygonF([QPointF(x, y) for x, y in zip(X, Y)] + [QPointF(X[-1], H + 5), QPointF(X[0], H + 5)])
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(gc[0], gc[1], gc[2], 38))
                    p.drawPolygon(poly)
                    p.setBrush(Qt.NoBrush)
                codes = np.ones(len(X), np.int64)
                codes[0] = 0
                p.setPen(pen_for(gc, width, alpha=alpha))
                p.drawPath(make_path(np.column_stack([X, Y]), codes))

    def _bins(self, depth):
        span = max(self.spec.far - self.spec.near, 1e-9)
        t = np.clip((depth - self.spec.near) / span, 0.0, 1.0)
        return t, np.minimum((t * 5).astype(int), 4)

    def _paint_lines(self, p, sc, W, H):
        s = self.spec
        for ls in sc.lines:
            a, b = ls.segments()
            if not len(a):
                continue
            a2, b2, _ = S.clip_segments_to_slab(a, b, s)
            if not len(a2):
                continue
            A, B = s.to_screen(a2, W, H), s.to_screen(b2, W, H)
            vis = ~((np.maximum(A[:, 0], B[:, 0]) < -5) | (np.minimum(A[:, 0], B[:, 0]) > W + 5) |
                    (np.maximum(A[:, 1], B[:, 1]) < -5) | (np.minimum(A[:, 1], B[:, 1]) > H + 5))
            A, B = A[vis], B[vis]
            if not len(A):
                continue
            _, bins = self._bins((A[:, 2] + B[:, 2]) / 2.0)
            for k in range(4, -1, -1):                                        # deepest first
                m = bins == k
                if not m.any():
                    continue
                xy = np.empty((int(m.sum()) * 2, 2))
                xy[0::2], xy[1::2] = A[m][:, :2], B[m][:, :2]
                p.setPen(pen_for(ls.rgb, 1.5 - 0.15 * k, alpha=int(255 * (1 - 0.14 * k))))
                p.drawPath(make_path(xy, np.tile([0, 1], int(m.sum()))))

    def _paint_points(self, p, sc, W, H):
        if not len(sc.pts_xyz):
            return
        s = self.spec
        P = s.to_screen(sc.pts_xyz, W, H)
        ok = (P[:, 2] >= s.near) & (P[:, 2] <= s.far) & (P[:, 0] > -8) & (P[:, 0] < W + 8) & (P[:, 1] > -8) & (P[:, 1] < H + 8)
        idx = np.nonzero(ok)[0]
        if not len(idx):
            return
        if len(idx) > 60000:
            idx = idx[:: int(math.ceil(len(idx) / 60000))]
        _, bins = self._bins(P[idx, 2])
        rgb = sc.pts_rgb[idx]
        key = rgb[:, 0].astype(np.int64) * 65536 + rgb[:, 1].astype(np.int64) * 256 + rgb[:, 2]
        p.setBrush(Qt.NoBrush)
        for k in range(4, -1, -1):
            for kc in np.unique(key[bins == k]):
                m = (bins == k) & (key == kc)
                c = QColor(int(kc >> 16 & 255), int(kc >> 8 & 255), int(kc & 255), int(255 * (1 - 0.12 * k)))
                pen = QPen(c, 6.5 - 0.9 * k)
                pen.setCapStyle(Qt.RoundCap)
                p.setPen(pen)
                p.drawPoints(QPolygonF([QPointF(x, y) for x, y in P[idx[m]][:, :2]]))
        sel = self.state.sel_points
        if sel:
            m = np.isin(sc.pts_id[idx], np.fromiter(sel, np.int64, len(sel)))
            p.setPen(QPen(QColor(theme.colors()["select"]), 1.8))
            for x, y in P[idx[m]][:, :2]:
                p.drawEllipse(QPointF(x, y), 7, 7)
        if self.show_numbers:
            near_first = np.argsort(P[idx, 2])[:200]
            p.setFont(self._font(10))
            p.setPen(QColor(theme.colors()["text"]))
            for j in near_first:
                i = idx[j]
                p.drawText(QPointF(P[i, 0] + 6, P[i, 1] - 5), f"{sc.pts_num[i]}  {sc.pts_xyz[i, 2]:,.2f}")

    def _paint_edges(self, p, W, H):
        s = self.spec
        col = QColor(theme.colors()["dim"])
        left, right = compass(s.azimuth - 90), compass(s.azimuth + 90)
        p.setFont(self._font(11, True))
        p.setPen(QColor(theme.colors()["text"]))
        p.drawText(QRectF(4, H / 2 - 22, 40, 16), Qt.AlignLeft, f"< {left}")
        p.drawText(QRectF(W - 44, H / 2 - 22, 40, 16), Qt.AlignRight, f"{right} >")
        u = U.LABEL.get(self.state.project.h_unit, self.state.project.h_unit)
        p.setFont(self._font(11))
        p.setPen(col)
        p.drawText(QPointF(10, 16), f"Looking {compass(s.azimuth)}  ({s.azimuth:05.1f} deg)   slab {s.near:g} to {s.far:g} {u} beyond the line   vertical x{s.vexag:g}")

    # ------------------------------------------------------------------ the slab on the plan view
    def paint_plan_overlay(self, p: QPainter, view):
        """Called by the plan canvas: the alignment line, the slab and the viewing direction."""
        sc = self.provider.scene()
        if sc.bounds is None or self.width() < 20:
            return
        s = self.spec
        acc = QColor(theme.colors()["accent"])
        poly = s.plan_polygon(self.width())
        pts = [QPointF(*view.to_screen(x, y)) for x, y in poly]
        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        fill = QColor(acc)
        fill.setAlpha(34)
        p.setBrush(fill)
        edge = QColor(acc)
        edge.setAlpha(150)
        p.setPen(QPen(edge, 1.2, Qt.DashLine))
        p.drawPolygon(QPolygonF(pts))
        p.setPen(QPen(acc, 2.6))
        p.drawLine(pts[0], pts[1])                                            # the alignment line = where the slab starts
        d, _ = s.axes()
        mid = QPointF(*view.to_screen(*(np.asarray(s.center, float) + d * s.near)))
        length = max(34.0, min(abs(s.far - s.near) * view.scale * 0.6, 160.0))
        tip = QPointF(mid.x() + d[0] * length, mid.y() - d[1] * length)
        p.setPen(QPen(acc, 2.2))
        p.drawLine(mid, tip)
        ang = math.atan2(-(tip.y() - mid.y()), tip.x() - mid.x())
        head = QPolygonF([tip, QPointF(tip.x() - 11 * math.cos(ang - 0.45), tip.y() + 11 * math.sin(ang - 0.45)),
                          QPointF(tip.x() - 11 * math.cos(ang + 0.45), tip.y() + 11 * math.sin(ang + 0.45))])
        p.setBrush(acc)
        p.setPen(Qt.NoPen)
        p.drawPolygon(head)
        f = QFont()
        f.setPixelSize(11)
        f.setBold(True)
        p.setFont(f)
        p.setPen(acc)
        p.drawText(QPointF(mid.x() + 8, mid.y() - 8), f"Depth view - looking {compass(s.azimuth)} {s.azimuth:03.0f}\u00b0")
        p.restore()

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, ev):
        self.setFocus()
        if ev.button() == Qt.RightButton:
            self._drag = "rotate"
        elif ev.button() in (Qt.LeftButton, Qt.MiddleButton):
            self._drag = "pan"
        else:
            return
        self._last = ev.position()
        self.setCursor(Qt.ClosedHandCursor if self._drag == "pan" else Qt.SizeHorCursor)

    def mouseMoveEvent(self, ev):
        if not self._drag:
            return
        pos = ev.position()
        dx, dy = pos.x() - self._last.x(), pos.y() - self._last.y()
        self._last = pos
        s = self.spec
        if self._drag == "pan":
            _, r = s.axes()
            if abs(dx) > 0:
                if self.follow:
                    self.follow = False
                s.center = tuple(np.asarray(s.center, float) - r * (dx / s.scale))
            s.zc += dy / (s.scale * s.vexag)
        else:
            s.azimuth = (s.azimuth - dx * 0.4) % 360.0
            self.station_offset = 0.0
        self._emit()

    def mouseReleaseEvent(self, ev):
        self._drag = None
        self.setCursor(Qt.OpenHandCursor)

    def mouseDoubleClickEvent(self, ev):
        self.fit()

    def wheelEvent(self, ev):
        d = ev.angleDelta().y()
        if not d:
            return
        s = self.spec
        f = 1.18 ** (d / 120.0)
        if ev.modifiers() & Qt.ControlModifier:                               # Ctrl + wheel: vertical exaggeration
            s.vexag = float(np.clip(s.vexag * f, 0.1, 50.0))
        else:                                                                 # zoom about the cursor
            W, H = self.width(), self.height()
            pos = ev.position()
            _, r = s.axes()
            hc = (pos.x() - W / 2) / s.scale
            zc = s.zc - (pos.y() - H / 2) / (s.scale * s.vexag)
            s.scale = float(np.clip(s.scale * f, 1e-6, 1e7))
            s.center = tuple(np.asarray(s.center, float) + r * (hc - (pos.x() - W / 2) / s.scale))
            s.zc = zc + (pos.y() - H / 2) / (s.scale * s.vexag)
            if self.follow and abs(hc - (pos.x() - W / 2) / s.scale) > 1e-9:
                self.follow = False
        self._emit()
        ev.accept()

    def keyPressEvent(self, ev):
        k = ev.key()
        if k == Qt.Key_Left:
            self.rotate(5.0)
        elif k == Qt.Key_Right:
            self.rotate(-5.0)
        elif k == Qt.Key_Home:
            self.fit()
        else:
            super().keyPressEvent(ev)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self.update()


# ============================================================================ the panel (controls + view)
def _spin(lo, hi, step, dec, tip, width=76):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(dec)
    s.setToolTip(tip)
    s.setFixedWidth(width)
    s.setKeyboardTracking(False)
    return s


class DepthPanel(QWidget):
    pick_line_requested = Signal()

    def __init__(self, state, provider: SceneProvider, canvas, parent=None):
        super().__init__(parent)
        self.state = state
        self.view = DepthView(state, provider, canvas)
        v = self.view
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)

        # row 1: which way to look
        r1 = QHBoxLayout()
        r1.setSpacing(4)
        r1.addWidget(QLabel("Look:"))
        for text, az, tip in (("N", 0, "Look north (front view)"), ("E", 90, "Look east"), ("S", 180, "Look south"),
                              ("W", 270, "Look west")):
            r1.addWidget(_btn(text, tip, lambda _=False, a=az: v.set_azimuth(a)))
        self.dial = QDial()
        self.dial.setRange(0, 359)
        self.dial.setWrapping(True)
        self.dial.setNotchesVisible(True)
        self.dial.setFixedSize(54, 54)
        self.dial.setToolTip("Rotate the viewing direction")
        self.dial.valueChanged.connect(lambda val: v.set_azimuth(float((val - 180) % 360)))     # a QDial rests at the bottom: 180 = north
        r1.addWidget(self.dial)
        self.sp_az = _spin(0.0, 359.9, 5.0, 1, "Bearing the view looks along, degrees clockwise from north", 84)
        self.sp_az.setSuffix("\u00b0")
        self.sp_az.setWrapping(True)
        self.sp_az.valueChanged.connect(v.set_azimuth)
        r1.addWidget(self.sp_az)
        self.lbl_dir = QLabel("")
        self.lbl_dir.setMinimumWidth(26)
        r1.addWidget(self.lbl_dir)
        r1.addStretch(1)

        # row 2: step the rotation, aim with two clicks, fit
        r2 = QHBoxLayout()
        r2.setSpacing(4)
        r2.addWidget(_btn("-15\u00b0", "Rotate the view 15 degrees counter-clockwise", lambda _=False: v.rotate(-15)))
        r2.addWidget(_btn("+15\u00b0", "Rotate the view 15 degrees clockwise", lambda _=False: v.rotate(15)))
        r2.addWidget(_btn("Flip", "Look back the other way", lambda _=False: v.rotate(180)))
        r2.addSpacing(8)
        r2.addWidget(_btn("Pick line on plan...", "Click two points on the plan: the view looks across that line", lambda _=False: self.pick_line_requested.emit()))
        r2.addWidget(_btn("Fit", "Zoom to everything (double-click the view)", lambda _=False: v.fit()))
        r2.addStretch(1)

        # row 3: the slab and the exaggeration
        r3 = QHBoxLayout()
        r3.setSpacing(5)
        r3.addWidget(QLabel("Start"))
        self.sp_near = _spin(-1e7, 1e7, 5.0, 1, "Where the slab begins, measured from the depth line along the viewing direction")
        self.sp_near.valueChanged.connect(lambda x: v.set_slab(near=x, far=x + (v.spec.far - v.spec.near)))
        r3.addWidget(self.sp_near)
        r3.addWidget(QLabel("Depth"))
        self.sp_far = _spin(0.0, 1e7, 5.0, 1, "How far beyond the start the slab reaches")
        self.sp_far.valueChanged.connect(lambda x: v.set_slab(far=self.sp_near.value() + x))
        r3.addWidget(self.sp_far)
        self.lbl_unit = QLabel("")
        r3.addWidget(self.lbl_unit)
        r3.addSpacing(6)
        r3.addWidget(QLabel("Vertical x"))
        self.sp_vex = _spin(0.1, 50.0, 0.5, 1, "Vertical exaggeration (Ctrl + wheel in the view)", 64)
        self.sp_vex.valueChanged.connect(v.set_vexag)
        r3.addWidget(self.sp_vex)
        r3.addWidget(_btn("Auto", "Pick a readable exaggeration", lambda _=False: v.auto_vexag()))
        r3.addStretch(1)

        # row 4: what to show, and how to aim
        r4 = QHBoxLayout()
        r4.setSpacing(6)
        for text, attr, on in (("Ground", "show_ground", True), ("Lines", "show_lines", True), ("Points", "show_points", True),
                               ("Numbers", "show_numbers", False)):
            c = QCheckBox(text)
            c.setChecked(on)
            c.toggled.connect(lambda val, a=attr: v.set_option(a, val))
            r4.addWidget(c)
        self.chk_follow = QCheckBox("Follow plan")
        self.chk_follow.setToolTip("Keep the depth line through the center of the plan view as you pan it")
        self.chk_follow.setChecked(True)
        self.chk_follow.toggled.connect(v.set_follow)
        r4.addWidget(self.chk_follow)
        r4.addStretch(1)

        for r in (r1, r2, r3, r4):
            lay.addLayout(r)
        lay.addWidget(v, 1)
        hint = QLabel("Drag to pan - wheel to zoom - right-drag to rotate - Ctrl+wheel for vertical exaggeration - double-click to fit")
        hint.setProperty("hint", "true")
        hint.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        lay.addWidget(hint)
        v.changed.connect(self._sync)
        state.project_replaced.connect(self._units)
        self._units()
        self._sync()

    def _units(self):
        self.lbl_unit.setText(U.LABEL.get(self.state.project.h_unit, self.state.project.h_unit))

    def _sync(self):
        s = self.view.spec
        for w, val in ((self.sp_az, s.azimuth), (self.sp_near, s.near), (self.sp_far, s.far - s.near), (self.sp_vex, s.vexag)):
            w.blockSignals(True)
            w.setValue(val)
            w.blockSignals(False)
        self.dial.blockSignals(True)
        self.dial.setValue((int(round(s.azimuth)) + 180) % 360)
        self.dial.blockSignals(False)
        self.chk_follow.blockSignals(True)
        self.chk_follow.setChecked(self.view.follow)
        self.chk_follow.blockSignals(False)
        self.lbl_dir.setText(compass(s.azimuth))
