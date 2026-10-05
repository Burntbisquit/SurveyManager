"""Surface, contour, volume and profile dialogs."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import shapely
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QRadioButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import geometry as G
from ..core import units as U
from ..core.model import Polyline
from ..core.surface import suggest_max_edge, volume_between
from .widgets import Banner, FormDialog, Hint, dspin, error_box, info_box, ispin, run_blocking


def _layer_counts(project):
    pts, lines = {}, {}
    for p in project.points.values():
        pts[p.layer] = pts.get(p.layer, 0) + 1
    for e in project.polylines():
        if np.isfinite(e.verts[:, 2]).any():
            lines[e.layer] = lines.get(e.layer, 0) + 1
    return pts, lines


def _checklist(items, checked=True, max_h=130):
    lst = QListWidget()
    for key, label in items:
        it = QListWidgetItem(label)
        it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
        it.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        it.setData(Qt.UserRole, key)
        lst.addItem(it)
    lst.setMaximumHeight(max_h)
    return lst


def _checked(lst: QListWidget):
    return [lst.item(i).data(Qt.UserRole) for i in range(lst.count()) if lst.item(i).checkState() == Qt.Checked]


# ----------------------------------------------------------------------------- build a surface
class SurfaceDialog(FormDialog):
    def __init__(self, state, surface=None, parent=None):
        super().__init__(parent, "Edit Surface" if surface else "Create Surface",
                         "A TIN surface from your ground shots, with linework used as breaklines so curbs, ditches and banks stay sharp.",
                         "Rebuild" if surface else "Create", 600)
        self.state = state
        pr = state.project
        p0 = dict(surface.params) if surface else {}
        self.ed_name = QLineEdit(surface.name if surface else f"Surface {len(pr.surfaces) + 1}")
        self.form.addRow("Name:", self.ed_name)
        self.chk_ground = QCheckBox("Only ground points (leave out buildings, trees, poles, manholes, boundaries...)")
        self.chk_ground.setChecked(p0.get("ground_only", True))
        self.chk_sel = QCheckBox("Use only the selected points")
        self.chk_sel.setEnabled(bool(state.sel_points))
        self.chk_sel.setChecked(bool(p0.get("point_ids")) and bool(state.sel_points))
        pc, lc = _layer_counts(pr)
        self.lst_layers = _checklist([(n, f"{n}   ({c:,} points)") for n, c in sorted(pc.items())], True, 120)
        if p0.get("layers"):
            for i in range(self.lst_layers.count()):
                it = self.lst_layers.item(i)
                it.setCheckState(Qt.Checked if it.data(Qt.UserRole) in p0["layers"] else Qt.Unchecked)
        self.chk_kind = QCheckBox("Use linework coded as breaklines (EP, TC, FL, TOB ... - see Feature Codes)")
        self.chk_kind.setChecked(p0.get("use_breakline_kind", True))
        self.lst_bl = _checklist([(n, f"{n}   ({c} polylines with elevations)") for n, c in sorted(lc.items())], False, 100)
        for i in range(self.lst_bl.count()):
            if self.lst_bl.item(i).data(Qt.UserRole) in (p0.get("breakline_layers") or []):
                self.lst_bl.item(i).setCheckState(Qt.Checked)
        self.chk_selbl = QCheckBox("Also use the selected polylines as breaklines")
        sel_pl = [e for e in (pr.entities.get(i) for i in state.sel_entities) if isinstance(e, Polyline)]
        self.chk_selbl.setEnabled(bool(sel_pl))
        self.form.addRow("Points:", self.chk_ground)
        self.form.addRow("", self.chk_sel)
        self.form.addRow("From layers:", self.lst_layers)
        self.form.addRow("Breaklines:", self.chk_kind)
        self.form.addRow("Also from layers:", self.lst_bl)
        self.form.addRow("", self.chk_selbl)
        # boundary / holes from selection
        self._boundary = list(p0.get("boundary_ids") or [])
        self._holes = list(p0.get("hole_ids") or [])
        self.lbl_b = QLabel("")
        self.lbl_h = QLabel("")
        b1 = QPushButton("Use selected closed polyline(s) as boundary")
        b2 = QPushButton("Use selected closed polyline(s) as holes")
        b3 = QPushButton("Clear")
        row = QHBoxLayout()
        for b in (b1, b2, b3):
            row.addWidget(b)
        w = QWidget()
        w.setLayout(row)
        self.form.addRow("Limits:", w)
        self.form.addRow("", self.lbl_b)
        self.form.addRow("", self.lbl_h)
        b1.clicked.connect(lambda: self._take("b"))
        b2.clicked.connect(lambda: self._take("h"))
        b3.clicked.connect(self._clear)
        # max edge
        self.chk_edge = QCheckBox("Drop triangles with an edge longer than:")
        self.sp_edge = dspin(float(p0.get("max_edge") or 0) or 100.0, 0.001, 1e9, 2, 10)
        self.chk_edge.setChecked(bool(p0.get("max_edge")))
        b4 = QPushButton("Suggest")
        row = QHBoxLayout()
        row.addWidget(self.chk_edge)
        row.addWidget(self.sp_edge)
        row.addWidget(QLabel(U.LABEL.get(pr.h_unit, pr.h_unit)))
        row.addWidget(b4)
        w2 = QWidget()
        w2.setLayout(row)
        self.form.addRow("Edges:", w2)
        self.form.addRow("", Hint("Long thin triangles across gaps (outside the survey, around buildings) are false surface - a maximum edge length or a boundary removes them."))
        b4.clicked.connect(self._suggest)
        self._refresh_limits()

    def _closed_selected(self):
        pr = self.state.project
        return [e.id for e in (pr.entities.get(i) for i in self.state.sel_entities) if isinstance(e, Polyline) and e.closed]

    def _take(self, which):
        ids = self._closed_selected()
        if not ids:
            error_box(self, "Surface", "Select one or more CLOSED polylines in the drawing first (this dialog is non-blocking for the selection - close it, select, then reopen via Edit Surface).")
            return
        if which == "b":
            self._boundary = ids
        else:
            self._holes = ids
        self._refresh_limits()

    def _clear(self):
        self._boundary, self._holes = [], []
        self._refresh_limits()

    def _refresh_limits(self):
        self.lbl_b.setText(f"Boundary: {len(self._boundary)} polyline(s)" if self._boundary else "Boundary: none (whole survey)")
        self.lbl_h.setText(f"Holes: {len(self._holes)} polyline(s)" if self._holes else "Holes: none")

    def _suggest(self):
        pr = self.state.project
        ids, xyz = pr.point_arrays()
        if len(ids):
            self.sp_edge.setValue(suggest_max_edge(xyz[:, :2]))
            self.chk_edge.setChecked(True)

    def params(self) -> dict:
        pr = self.state.project
        allp = [self.lst_layers.item(i).data(Qt.UserRole) for i in range(self.lst_layers.count())]
        chosen = _checked(self.lst_layers)
        sel_ids = [e.id for e in (pr.entities.get(i) for i in self.state.sel_entities) if isinstance(e, Polyline)]
        bl_ids = sel_ids if self.chk_selbl.isChecked() else []
        p = {"ground_only": self.chk_ground.isChecked(),
             "layers": chosen if len(chosen) != len(allp) else None,
             "point_ids": sorted(self.state.sel_points) if self.chk_sel.isChecked() else None,
             "use_breakline_kind": self.chk_kind.isChecked(), "breakline_layers": _checked(self.lst_bl),
             "breakline_ids": bl_ids, "boundary_ids": self._boundary, "hole_ids": self._holes,
             "max_edge": self.sp_edge.value() if self.chk_edge.isChecked() else None}
        return p

    def validate(self):
        if not self.ed_name.text().strip():
            return "Give the surface a name."
        if not _checked(self.lst_layers):
            return "Select at least one layer of points."
        return None


def build_report_text(rep: dict, unit: str) -> str:
    lines = [f"Points used: {rep.get('n_input', 0):,}   (duplicates removed: {rep.get('n_duplicates', 0)})",
             f"Breakline vertices: {rep.get('n_breakline_vertices', 0):,}   (added by conforming: {rep.get('n_added', 0)})",
             f"Triangles: {rep.get('n_triangles', 0):,}   removed by max edge: {rep.get('n_removed_edge', 0):,}   by boundary/holes: {rep.get('n_removed_boundary', 0):,}"]
    if rep.get("n_unenforced"):
        lines.append(f"WARNING: {rep['n_unenforced']} breakline segment(s) could not be enforced.")
    for w in rep.get("warnings", []):
        lines.append(f"Note: {w}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- contours
class ContourDialog(FormDialog):
    def __init__(self, state, surface, parent=None):
        super().__init__(parent, f"Contours - {surface.name}", "Contours are generated entities: running this again replaces the previous ones for this surface.",
                         "Create contours", 480)
        pr = state.project
        s = pr.settings
        u = U.LABEL.get(pr.h_unit, pr.h_unit)
        tin = surface.tin()
        zmin, zmax = tin.bounds()[2], tin.bounds()[5]
        self.sp_int = dspin(float(s.get("contour_interval", 1.0)), 0.001, 1e6, 3, 0.5)
        self.sp_idx = ispin(int(s.get("index_every", 5)), 1, 100)
        self.sp_base = dspin(float(s.get("contour_base", 0.0)), -1e6, 1e6, 3)
        self.cmb_smooth = QComboBox()
        for lbl, v in [("None (exact on the TIN)", 0), ("Light", 1), ("Medium", 2), ("Heavy", 3)]:
            self.cmb_smooth.addItem(lbl, v)
        self.cmb_smooth.setCurrentIndex(max(0, self.cmb_smooth.findData(int(s.get("contour_smooth", 0)))))
        self.chk_lab = QCheckBox("Label the index contours")
        self.chk_lab.setChecked(bool(s.get("contour_labels", True)))
        self.sp_th = dspin(float(s.get("text_height", 2.0)), 0.001, 1e5, 3, 0.5)
        self.sp_min = dspin(0.0, 0.0, 1e9, 2, 1.0)
        self.lbl = Hint(f"Surface elevations run from {zmin:,.2f} to {zmax:,.2f}.")
        self.form.addRow("Contour interval:", self.sp_int)
        self.form.addRow("Index contour every:", self.sp_idx)
        self.form.addRow("Base elevation:", self.sp_base)
        self.form.addRow("Smoothing:", self.cmb_smooth)
        self.form.addRow("", self.chk_lab)
        self.form.addRow(f"Label height ({u}):", self.sp_th)
        self.form.addRow(f"Drop contours shorter than ({u}):", self.sp_min)
        self.form.addRow("", self.lbl)
        self.sp_int.valueChanged.connect(self._count)
        self._zr = (zmin, zmax)
        self._count()

    def _count(self):
        zmin, zmax = self._zr
        n = max(0, int(math.floor((zmax - self.sp_base.value()) / self.sp_int.value()) - math.ceil((zmin - self.sp_base.value()) / self.sp_int.value()) + 1))
        self.lbl.setText(f"Surface elevations run from {zmin:,.2f} to {zmax:,.2f}  ->  about {n} contour levels." +
                         ("  That is a lot - consider a larger interval." if n > 400 else ""))

    def validate(self):
        zmin, zmax = self._zr
        if (zmax - zmin) / self.sp_int.value() > 3000:
            return "That interval would create thousands of contour levels. Use a larger interval."
        return None

    def values(self) -> dict:
        return {"interval": self.sp_int.value(), "index_every": self.sp_idx.value(), "base": self.sp_base.value(),
                "smooth": self.cmb_smooth.currentData(), "labels": self.chk_lab.isChecked(), "text_height": self.sp_th.value(),
                "min_length": self.sp_min.value() or None}


# ----------------------------------------------------------------------------- volumes
class VolumeDialog(QDialog):
    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Earthwork Volumes")
        self.setMinimumWidth(640)
        pr = state.project
        self.result = None
        self.title = ""
        root = QVBoxLayout(self)
        form = QFormLayout()
        self.r_datum = QRadioButton("Surface to a flat elevation (stockpile, pad, pond, trench bottom)")
        self.r_surf = QRadioButton("Surface to surface (existing ground vs. proposed grading)")
        self.r_datum.setChecked(True)
        root.addWidget(self.r_datum)
        root.addWidget(self.r_surf)
        self.cmb_a = QComboBox()
        self.cmb_b = QComboBox()
        for s in pr.surfaces.values():
            self.cmb_a.addItem(s.name, s.id)
            self.cmb_b.addItem(s.name, s.id)
        a = state.active_surface()
        if a:
            self.cmb_a.setCurrentIndex(max(0, self.cmb_a.findData(a.id)))
        if self.cmb_b.count() > 1:
            self.cmb_b.setCurrentIndex(1 if self.cmb_a.currentIndex() == 0 else 0)
        zr = a.tin().bounds() if a else (0, 0, 0, 0, 0, 0)
        self.sp_datum = dspin(round(zr[2], 2), -1e6, 1e6, 3, 0.5)
        form.addRow("Existing / base surface:", self.cmb_a)
        form.addRow("Datum elevation:", self.sp_datum)
        form.addRow("Proposed surface:", self.cmb_b)
        root.addLayout(form)
        reg = QGroupBox("Area")
        rl = QVBoxLayout(reg)
        self.r_all = QRadioButton("Entire surface")
        self.r_poly = QRadioButton("Inside the selected closed polyline")
        self.r_all.setChecked(True)
        self._poly = self._selected_polygon()
        self.r_poly.setEnabled(self._poly is not None)
        rl.addWidget(self.r_all)
        rl.addWidget(self.r_poly)
        root.addWidget(reg)
        row = QHBoxLayout()
        self.cmb_method = QComboBox()
        self.cmb_method.addItem("Exact on the triangles (composite)", "composite")
        self.cmb_method.addItem("Grid method (compare with other software)", "grid")
        self.sp_cell = dspin(0.0, 0.0, 1e6, 3, 1.0)
        self.sp_cell.setSpecialValueText("auto")
        row.addWidget(QLabel("Surface to surface method:"))
        row.addWidget(self.cmb_method, 1)
        row.addWidget(QLabel("grid cell:"))
        row.addWidget(self.sp_cell)
        root.addLayout(row)
        self.btn_calc = QPushButton("Calculate")
        self.btn_calc.setProperty("accent", True)
        root.addWidget(self.btn_calc)
        self.table = QTableWidget(3, 5)
        self.table.setHorizontalHeaderLabels(["", "Cubic units", "Cubic yards", "Cubic metres", "Area"])
        self.table.setVerticalHeaderLabels(["Cut", "Fill", "Net"])
        self.table.setMaximumHeight(130)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table)
        self.note = Hint("Positive net = excess cut (export). Quantities are in-place (bank) volumes - apply swell / shrink separately.")
        root.addWidget(self.note)
        bb = QDialogButtonBox()
        self.btn_report = bb.addButton("Report...", QDialogButtonBox.ActionRole)
        bb.addButton(QDialogButtonBox.Close)
        bb.rejected.connect(self.reject)
        bb.accepted.connect(self.accept)
        self.btn_report.setEnabled(False)
        root.addWidget(bb)
        self.btn_calc.clicked.connect(self._calc)
        self.btn_report.clicked.connect(self._report)
        self.r_datum.toggled.connect(self._mode)
        self._mode()
        if not pr.surfaces:
            self.btn_calc.setEnabled(False)
            self.note.setText("Create a surface first (Surface menu).")

    def _selected_polygon(self):
        pr = self.state.project
        for i in self.state.sel_entities:
            e = pr.entities.get(i)
            if isinstance(e, Polyline) and e.closed and len(e.verts) >= 3:
                v = G.flatten_polyline(e.verts, e.bulges, True, max_dev=0.02)
                return shapely.Polygon(v[:, :2]).buffer(0)
        return None

    def _mode(self):
        d = self.r_datum.isChecked()
        self.sp_datum.setEnabled(d)
        self.cmb_b.setEnabled(not d)
        self.cmb_method.setEnabled(not d)
        self.sp_cell.setEnabled(not d)

    def _calc(self):
        pr = self.state.project
        a = pr.surfaces[self.cmb_a.currentData()]
        region = self._poly if self.r_poly.isChecked() else None
        try:
            if self.r_datum.isChecked():
                dv = self.sp_datum.value()
                res = run_blocking(self, "Computing volumes ...", a.tin().volume_to_datum, dv, region)
                self.title = f"Volume: {a.name} to elevation {dv:,.3f}"
                self.desc = [f"Existing surface: {a.name}", f"Datum elevation: {dv:,.3f} {U.LABEL.get(pr.v_unit, pr.v_unit)}"]
            else:
                b = pr.surfaces[self.cmb_b.currentData()]
                if b.id == a.id:
                    error_box(self, "Volumes", "Choose two different surfaces.")
                    return
                res = run_blocking(self, "Computing volumes ...", volume_between, a.tin(), b.tin(), region,
                                   self.cmb_method.currentData(), self.sp_cell.value() or None)
                self.title = f"Volume: {a.name} to {b.name}"
                self.desc = [f"Existing surface: {a.name}", f"Proposed surface: {b.name}",
                             "Cut = existing above proposed; fill = proposed above existing."]
            if region is not None:
                self.desc.append("Limited to the selected polygon.")
        except RuntimeError as ex:
            error_box(self, "Volumes", "The calculation failed.", str(ex))
            return
        self.result = res
        u, vu = pr.h_unit, pr.v_unit
        rows = [("cut", res.cut, res.area_cut), ("fill", res.fill, res.area_fill), ("net", res.net, None)]
        for r, (_, v, area) in enumerate(rows):
            vals = [f"{v:,.1f}", f"{U.volume_to_cubic_yards(v, u, vu):,.1f}", f"{U.volume_to_cubic_meters(v, u, vu):,.1f}",
                    "" if area is None else f"{area:,.0f} sq {u} ({U.area_to_acres(area, u):,.3f} ac)"]
            for c, t in enumerate(vals, start=1):
                it = QTableWidgetItem(t)
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        self.btn_report.setEnabled(True)

    def _report(self):
        from ..io import reports
        from .dialogs import ReportViewer
        rep = reports.volume_report(self.state.project, self.result, self.title, self.desc)
        ReportViewer(self, rep, "volume").exec()


# ----------------------------------------------------------------------------- profile
class ProfileView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(560, 300)
        self.setMouseTracking(True)
        self.st = np.array([])
        self.z = np.array([])
        self.xy = np.empty((0, 2))
        self.vexag = 0.0              # 0 = fit
        self.hover = None
        self.unit = "ft"
        self.dark = True

    def set_data(self, st, z, xy, unit="ft"):
        self.st, self.z, self.xy, self.unit = st, z, xy, unit
        self.update()

    def set_vexag(self, v):
        self.vexag = v
        self.update()

    def _frame(self):
        W, H = self.width(), self.height()
        return QRectF(64, 16, W - 80, H - 46)

    def _ranges(self, r: QRectF):
        ok = np.isfinite(self.z)
        if not ok.any():
            return 0, 1, 0, 1
        s0, s1 = float(self.st.min()), float(self.st.max())
        z0, z1 = float(self.z[ok].min()), float(self.z[ok].max())
        if self.vexag > 0 and s1 > s0:
            ppu_x = r.width() / (s1 - s0)
            span = r.height() / (ppu_x * self.vexag)
            mid = (z0 + z1) / 2
            return s0, s1, mid - span / 2, mid + span / 2
        pad = max((z1 - z0) * 0.08, 0.5)
        return s0, s1, z0 - pad, z1 + pad

    def paintEvent(self, ev):
        from . import theme
        col = theme.colors()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(self.rect(), QColor(col["base"]))
        r = self._frame()
        s0, s1, z0, z1 = self._ranges(r)
        f = QFont()
        f.setPixelSize(11)
        p.setFont(f)
        if not np.isfinite(self.z).any():
            p.setPen(QColor(col["dim"]))
            p.drawText(self.rect(), Qt.AlignCenter, "The line does not cross the surface.")
            return

        def X(s):
            return r.left() + (s - s0) / max(s1 - s0, 1e-12) * r.width()

        def Y(z):
            return r.bottom() - (z - z0) / max(z1 - z0, 1e-12) * r.height()

        from .render import nice_length
        step = nice_length((z1 - z0) / 6)
        p.setPen(QPen(QColor(col["grid"]).lighter(140), 1))
        g = math.ceil(z0 / step) * step
        while g <= z1:
            p.drawLine(QPointF(r.left(), Y(g)), QPointF(r.right(), Y(g)))
            p.setPen(QColor(col["dim"]))
            p.drawText(QPointF(6, Y(g) + 4), f"{g:,.2f}")
            p.setPen(QPen(QColor(col["grid"]).lighter(140), 1))
            g += step
        sstep = nice_length((s1 - s0) / 8)
        g = math.ceil(s0 / sstep) * sstep
        while g <= s1:
            p.setPen(QPen(QColor(col["grid"]).lighter(140), 1))
            p.drawLine(QPointF(X(g), r.top()), QPointF(X(g), r.bottom()))
            p.setPen(QColor(col["dim"]))
            p.drawText(QPointF(X(g) - 14, r.bottom() + 15), f"{g:,.0f}")
            g += sstep
        p.setPen(QPen(QColor(col["border"]), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r)
        # profile polyline with gaps at NaN
        path = QPainterPath()
        fill = []
        pen_on = False
        for s, z in zip(self.st, self.z):
            if not math.isfinite(z):
                pen_on = False
                continue
            pt = QPointF(X(s), min(max(Y(z), r.top() - 40), r.bottom() + 40))
            if not pen_on:
                path.moveTo(pt)
                pen_on = True
            else:
                path.lineTo(pt)
        p.setClipRect(r)
        p.setPen(QPen(QColor(col["accent"]).lighter(130), 2.2))
        p.drawPath(path)
        p.setClipping(False)
        p.setPen(QColor(col["dim"]))
        p.drawText(QPointF(r.left(), r.bottom() + 30), f"Station ({self.unit})")
        if self.vexag > 0:
            p.drawText(QPointF(r.right() - 150, r.top() - 4), f"vertical exaggeration {self.vexag:g}x")
        if self.hover is not None:
            s = self.hover
            z = np.interp(s, self.st[np.isfinite(self.z)], self.z[np.isfinite(self.z)]) if np.isfinite(self.z).sum() > 1 else math.nan
            p.setPen(QPen(QColor(col["snap"]), 1, Qt.DashLine))
            p.drawLine(QPointF(X(s), r.top()), QPointF(X(s), r.bottom()))
            if math.isfinite(z):
                p.setPen(QColor(col["text"]))
                p.setBrush(QColor(0, 0, 0, 170))
                txt = f"Sta {s:,.2f}   Elev {z:,.3f}"
                tw = p.fontMetrics().horizontalAdvance(txt) + 12
                bx = min(X(s) + 8, r.right() - tw)
                p.drawRoundedRect(QRectF(bx, r.top() + 6, tw, 20), 4, 4)
                p.setPen(QColor(255, 255, 255))
                p.drawText(QPointF(bx + 6, r.top() + 20), txt)
        p.end()

    def mouseMoveEvent(self, ev):
        r = self._frame()
        if len(self.st) and r.contains(ev.position()):
            s0, s1, *_ = self._ranges(r)
            self.hover = s0 + (ev.position().x() - r.left()) / r.width() * (s1 - s0)
        else:
            self.hover = None
        self.update()

    def leaveEvent(self, ev):
        self.hover = None
        self.update()


class ProfileDialog(QDialog):
    def __init__(self, state, surface, poly: Polyline, parent=None):
        super().__init__(parent)
        self.state = state
        self.surface = surface
        self.setWindowTitle(f"Profile — {surface.name}")
        self.resize(900, 560)
        pr = state.project
        self.poly = poly
        v = G.flatten_polyline(poly.verts, poly.bulges, poly.closed, max_dev=0.02)
        if poly.closed:
            v = np.vstack([v, v[:1]])
        self.line = v[:, :2]
        self.st, self.z, self.xy = surface.tin().profile(self.line)
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Vertical exaggeration:"))
        self.cmb_v = QComboBox()
        for lbl, val in [("Fit", 0.0), ("1x", 1.0), ("2x", 2.0), ("5x", 5.0), ("10x", 10.0), ("20x", 20.0)]:
            self.cmb_v.addItem(lbl, val)
        top.addWidget(self.cmb_v)
        top.addStretch(1)
        self.btn_csv = QPushButton("Export profile CSV...")
        self.btn_png = QPushButton("Save image...")
        top.addWidget(self.btn_csv)
        top.addWidget(self.btn_png)
        root.addLayout(top)
        self.view = ProfileView()
        self.view.set_data(self.st, self.z, self.xy, U.LABEL.get(pr.h_unit, pr.h_unit))
        root.addWidget(self.view, 1)
        ok = np.isfinite(self.z)
        total = float(G.cumulative_stations(self.line)[-1])
        info = f"Length {total:,.2f} {pr.h_unit}"
        if ok.any():
            info += f"   |   Elevation {self.z[ok].min():,.3f} to {self.z[ok].max():,.3f}   |   {100 * (self.z[ok][-1] - self.z[ok][0]) / max(total, 1e-9):+.2f}% overall (first to last point on surface)"
        self.lbl = QLabel(info)
        root.addWidget(self.lbl)
        # sections
        gb = QGroupBox("Cross-sections Along This Line")
        gl = QHBoxLayout(gb)
        self.sp_int = dspin(max(round(total / 10, 0), 1.0), 0.01, 1e6, 2, 10)
        self.sp_hw = dspin(max(round(total / 10, 0), 5.0), 0.01, 1e6, 2, 5)
        gl.addWidget(QLabel("every"))
        gl.addWidget(self.sp_int)
        gl.addWidget(QLabel("half-width"))
        gl.addWidget(self.sp_hw)
        self.btn_sec = QPushButton("Export sections CSV...")
        gl.addWidget(self.btn_sec)
        gl.addStretch(1)
        root.addWidget(gb)
        self.cmb_v.currentIndexChanged.connect(lambda: self.view.set_vexag(self.cmb_v.currentData()))
        self.btn_csv.clicked.connect(self._csv)
        self.btn_png.clicked.connect(self._png)
        self.btn_sec.clicked.connect(self._sections)

    def _csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export profile", "profile.csv", "CSV (*.csv)")
        if not path:
            return
        import csv
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Station", "Elevation", "Easting", "Northing"])
            for s, z, (x, y) in zip(self.st, self.z, self.xy):
                w.writerow([f"{s:.3f}", "" if not math.isfinite(z) else f"{z:.3f}", f"{x:.3f}", f"{y:.3f}"])
        self.state.log(f"Profile written to {path}", "ok")

    def _png(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save profile image", "profile.png", "PNG (*.png)")
        if path:
            self.view.grab().save(path)

    def _sections(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export sections", "sections.csv", "CSV (*.csv)")
        if not path:
            return
        import csv
        secs = self.surface.tin().sections(self.line, self.sp_int.value(), self.sp_hw.value())
        n = 0
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Station", "Offset (- right / + left)", "Elevation", "Easting", "Northing"])
            for sc in secs:
                for off, z, (x, y) in zip(sc["offset"], sc["z"], sc["xy"]):
                    if math.isfinite(z):
                        w.writerow([f"{sc['station']:.3f}", f"{off:.3f}", f"{z:.3f}", f"{x:.3f}", f"{y:.3f}"])
                        n += 1
        self.state.log(f"{len(secs)} sections ({n:,} rows) written to {path}", "ok")
