"""3D scene snapshot, camera maths and a small software renderer for the orbit view and the depth view.

Qt-free: numpy does the geometry and matplotlib's Agg rasteriser (already used by the plan view for the shaded
surface) draws the pixels, so everything here can be tested without a window.

Conventions
-----------
* World coordinates are the project's: easting x, northing y, elevation z.
* ``azimuth`` is a compass bearing (degrees clockwise from north) of the direction the camera LOOKS.
* ``elevation`` is the camera's height angle above the horizon (90 = straight down with north at the top of the screen).
* Vertical exaggeration scales z about the camera target; lighting and depth sorting use the scaled geometry.
* Painter's algorithm: every triangle (surface faces, point markers, line quads) goes into ONE list sorted far to near
  and is drawn in a single Gouraud pass, so points and lines are hidden correctly by terrain in front of them.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from . import geometry as G
from .model import Polyline
from .ramps import RAMPS, SLOPE_EDGES, lut


# ============================================================================ camera
@dataclass
class Camera:
    target: np.ndarray = field(default_factory=lambda: np.zeros(3))
    azimuth: float = 30.0            # bearing the camera looks along
    elevation: float = 35.0          # camera height angle above the horizon
    distance: float = 1000.0         # eye to target, in scaled units (also sets the zoom of an orthographic view)
    fov: float = 40.0                # vertical field of view, degrees
    perspective: bool = True
    vexag: float = 1.0

    def copy(self) -> "Camera":
        return Camera(np.array(self.target, float), self.azimuth, self.elevation, self.distance, self.fov,
                      self.perspective, self.vexag)

    # ---------------------------------------------------------------- basis / projection
    def basis(self):
        """(right, up, forward) unit vectors in scaled world space."""
        az, el = math.radians(self.azimuth), math.radians(self.elevation)
        f = np.array([math.cos(el) * math.sin(az), math.cos(el) * math.cos(az), -math.sin(el)])
        r = np.array([math.cos(az), -math.sin(az), 0.0])
        return r, np.cross(r, f), f

    @property
    def near(self) -> float:
        return max(self.distance * 0.01, 1e-9)

    def px_per_unit(self, H: float) -> float:
        """Pixels per (scaled) world unit at the target plane."""
        return (H / 2.0) / (self.distance * math.tan(math.radians(self.fov) / 2.0))

    def view_coords(self, xyz) -> np.ndarray:
        """(n,3) world -> camera space (x right, y up, z = distance from the eye along the view direction)."""
        p = (np.asarray(xyz, float).reshape(-1, 3) - self.target) * np.array([1.0, 1.0, self.vexag])
        r, u, f = self.basis()
        return np.column_stack([p @ r, p @ u, p @ f + self.distance])

    def to_screen(self, v: np.ndarray, W: float, H: float) -> np.ndarray:
        """camera-space (n,3) -> (n,3) pixel x, pixel y (down), depth.  Depth <= near gives NaN for perspective."""
        k = self.px_per_unit(H)
        if self.perspective:
            with np.errstate(divide="ignore", invalid="ignore"):
                s = np.where(v[:, 2] > 1e-12, k * self.distance / v[:, 2], np.nan)
        else:
            s = np.full(len(v), k)
        return np.column_stack([W / 2.0 + v[:, 0] * s, H / 2.0 - v[:, 1] * s, v[:, 2]])

    def project(self, xyz, W: float, H: float) -> np.ndarray:
        return self.to_screen(self.view_coords(xyz), W, H)

    # ---------------------------------------------------------------- navigation
    def orbit(self, d_az: float, d_el: float):
        self.azimuth = (self.azimuth + d_az) % 360.0
        self.elevation = float(np.clip(self.elevation + d_el, 0.0, 90.0))

    def zoom(self, factor: float, lo: float = 1e-6, hi: float = 1e12):
        self.distance = float(np.clip(self.distance / factor, lo, hi))

    def pan(self, dx_px: float, dy_px: float, H: float):
        """Drag the scene by (dx, dy) pixels along the ground (the target stays at its elevation)."""
        r, u, f = self.basis()
        unit = 1.0 / self.px_per_unit(H)
        fh = np.array([f[0], f[1], 0.0])
        n = float(np.linalg.norm(fh))
        if n < 1e-9:                                     # looking straight down: screen-up is the azimuth direction
            az = math.radians(self.azimuth)
            fh, n = np.array([math.sin(az), math.cos(az), 0.0]), 1.0
        fh = fh / n
        sin_el = max(math.sin(math.radians(self.elevation)), 0.25)
        move = -dx_px * unit * r + dy_px * unit * fh / sin_el
        self.target = np.array([self.target[0] + move[0], self.target[1] + move[1], self.target[2]])

    def set_view(self, azimuth: float, elevation: float):
        self.azimuth, self.elevation = azimuth % 360.0, float(np.clip(elevation, 0.0, 90.0))

    def fit(self, bounds, W: float, H: float, fill: float = 0.9):
        """Center on a bounding box (x0,y0,z0,x1,y1,z1) and pick the distance so it fills `fill` of the window."""
        x0, y0, z0, x1, y1, z1 = bounds
        self.target = np.array([(x0 + x1) / 2.0, (y0 + y1) / 2.0, (z0 + z1) / 2.0])
        corners = np.array([[x, y, z] for x in (x0, x1) for y in (y0, y1) for z in (z0, z1)], float)
        ext = float(np.linalg.norm([x1 - x0, y1 - y0, (z1 - z0) * self.vexag]))
        self.distance = max(ext, 1e-6) * 1.6
        for _ in range(6):
            v = self.view_coords(corners)
            ok = v[:, 2] > self.near
            if not ok.all():
                self.distance *= 1.5
                continue
            s = self.to_screen(v, W, H)
            need = max(float(np.abs(s[:, 0] - W / 2).max()) / (W / 2 * fill), float(np.abs(s[:, 1] - H / 2).max()) / (H / 2 * fill), 1e-9)
            self.distance = max(self.distance * need, 1e-6)
            if abs(need - 1) < 0.01:
                break


def auto_vexag(bounds) -> float:
    """A vertical exaggeration that makes a flat site readable: relief about 12 % of the plan extent, 1x to 20x."""
    x0, y0, z0, x1, y1, z1 = bounds
    ext, relief = max(x1 - x0, y1 - y0, 1e-9), max(z1 - z0, 1e-9)
    return float(np.clip(round(0.12 * ext / relief * 2) / 2, 1.0, 20.0))


# ============================================================================ scene snapshot
class LineSet:
    """Polylines of one colour, flattened: all vertices in one (K,3) array with per-polyline start / count."""

    def __init__(self, layer: str, rgb: tuple, xyz: np.ndarray, starts: np.ndarray, counts: np.ndarray):
        self.layer, self.rgb, self.xyz, self.starts, self.counts = layer, rgb, xyz, starts, counts
        self._seg = None

    def segments(self):
        """(a, b): (S,3) arrays of consecutive vertex pairs, never joining two different polylines."""
        if self._seg is None:
            i = np.arange(len(self.xyz) - 1)
            last = np.zeros(len(self.xyz), bool)
            last[self.starts + self.counts - 1] = True
            i = i[~last[:-1]]
            self._seg = (self.xyz[i], self.xyz[i + 1])
        return self._seg


class Mesh:
    """A TIN prepared for drawing: vertex normals / colours are computed lazily and cached."""

    def __init__(self, sid, name, pts, tris, mode: str = "elevation", edges: bool = False, z_range=None):
        self.id, self.name = sid, name
        self.pts = np.ascontiguousarray(pts, float).reshape(-1, 3)
        self.tris = np.ascontiguousarray(tris, np.int64).reshape(-1, 3)
        self.mode, self.edges = mode, edges
        n = len(self.pts)
        z = self.pts[:, 2]
        if z_range is None:
            z_range = (float(np.percentile(z, 1)), float(np.percentile(z, 99))) if n else (0.0, 1.0)
        self.z_range = z_range
        self.vz = np.clip((z - z_range[0]) / max(z_range[1] - z_range[0], 1e-9), 0, 1)
        self._normals: dict = {}
        self._vslope = None
        self._edge_idx = None
        self._coarse: dict = {}
        self._edge_len = None

    @property
    def n_tris(self) -> int:
        return len(self.tris)

    def bounds(self):
        p = self.pts
        return (float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 2].min()),
                float(p[:, 0].max()), float(p[:, 1].max()), float(p[:, 2].max()))

    def typical_edge(self) -> float:
        """A typical triangle edge length (plan units): used to lift points / lines just in front of their own surface."""
        if self._edge_len is None:
            if not self.n_tris:
                self._edge_len = 0.0
            else:
                P = self.pts[self.tris][:, :, :2]
                a2 = 0.5 * np.abs((P[:, 1, 0] - P[:, 0, 0]) * (P[:, 2, 1] - P[:, 0, 1]) - (P[:, 2, 0] - P[:, 0, 0]) * (P[:, 1, 1] - P[:, 0, 1]))
                self._edge_len = float(math.sqrt(2.0 * max(float(np.median(a2)), 0.0)))
        return self._edge_len

    def edge_index(self) -> np.ndarray:
        if self._edge_idx is None:
            e = np.concatenate([self.tris[:, [0, 1]], self.tris[:, [1, 2]], self.tris[:, [2, 0]]])
            e.sort(axis=1)
            _, idx = np.unique(e[:, 0] * max(len(self.pts), 1) + e[:, 1], return_index=True)
            self._edge_idx = e[idx]
        return self._edge_idx

    def vertex_slope(self) -> np.ndarray:
        if self._vslope is None:
            P = self.pts[self.tris]
            nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
            nrm[nrm[:, 2] < 0] *= -1
            with np.errstate(divide="ignore", invalid="ignore"):
                sl = np.nan_to_num(np.hypot(nrm[:, 0], nrm[:, 1]) / np.where(nrm[:, 2] == 0, np.nan, nrm[:, 2]) * 100.0, nan=0.0, posinf=1e6)
            acc, cnt = np.zeros(len(self.pts)), np.zeros(len(self.pts))
            for k in range(3):
                np.add.at(acc, self.tris[:, k], sl)
                np.add.at(cnt, self.tris[:, k], 1)
            self._vslope = acc / np.maximum(cnt, 1)
        return self._vslope

    def normals(self, vexag: float) -> np.ndarray:
        """Smooth (area-weighted) vertex normals of the vertically exaggerated surface, pointing up."""
        key = round(float(vexag), 3)
        vn = self._normals.get(key)
        if vn is None:
            P = self.pts[self.tris] * np.array([1.0, 1.0, key])
            nrm = np.cross(P[:, 1] - P[:, 0], P[:, 2] - P[:, 0])
            nrm[nrm[:, 2] < 0] *= -1
            vn = np.zeros((len(self.pts), 3))
            for k in range(3):
                np.add.at(vn, self.tris[:, k], nrm)
            ln = np.linalg.norm(vn, axis=1)
            ln[ln == 0] = 1.0
            vn /= ln[:, None]
            if len(self._normals) > 6:
                self._normals.clear()
            self._normals[key] = vn
        return vn

    def colors(self, cam: Camera, dark: bool) -> np.ndarray:
        """(n,3) vertex colours 0..1: elevation / slope / hill-shade ramp times a camera-relative light."""
        r, u, f = cam.basis()
        L = -f * 0.55 + u * 0.55 - r * 0.35               # light from up-left of the viewer (NW when looking down)
        L = L / np.linalg.norm(L)
        sh = np.clip(self.normals(cam.vexag) @ L, 0.0, 1.0)
        hs = 0.55 + 0.64 * sh                              # flat ground facing the light -> about 1.0
        ramps = RAMPS["dark" if dark else "light"]
        if self.mode == "hillshade":
            g = np.clip(70 + 150 * sh, 0, 255) * (0.6 if dark else 1.0)
            rgb = np.repeat(g[:, None], 3, axis=1)
        elif self.mode == "slope":
            cls = np.clip(np.searchsorted(SLOPE_EDGES, self.vertex_slope()), 0, 7)
            rgb = np.array(ramps["slope"] + [ramps["slope"][-1]], float)[:8][cls] * hs[:, None]
        else:
            rgb = lut(ramps["elev"])[(self.vz * 255).astype(int)] * hs[:, None]
        return np.clip(rgb, 0, 255) / 255.0

    # ---------------------------------------------------------------- level of detail
    def coarse(self, max_tris: int) -> "Mesh":
        """A cheaper stand-in for dragging: vertices merged on a grid and re-triangulated (no breaklines)."""
        if self.n_tris <= max_tris:
            return self
        c = self._coarse.get(max_tris)
        if c is None:
            from scipy.spatial import Delaunay
            x0, y0, _, x1, y1, _ = self.bounds()
            target_v = max(60, max_tris // 2)
            cell = math.sqrt(max((x1 - x0) * (y1 - y0), 1e-9) / target_v)
            ij = np.floor((self.pts[:, :2] - [x0, y0]) / cell).astype(np.int64)
            nj = int(ij[:, 1].max()) + 1
            key = ij[:, 0] * nj + ij[:, 1]
            uniq, inv = np.unique(key, return_inverse=True)
            cnt = np.bincount(inv).astype(float)
            P = np.column_stack([np.bincount(inv, weights=self.pts[:, k]) / cnt for k in range(3)])
            try:
                tri = Delaunay(P[:, :2]).simplices
            except Exception:
                tri = np.empty((0, 3), np.int64)
            if len(tri):
                Q = P[tri][:, :, :2]
                e = np.stack([np.linalg.norm(Q[:, i] - Q[:, (i + 1) % 3], axis=1) for i in range(3)], axis=1)
                tri = tri[e.max(axis=1) <= 3.2 * cell]          # do not bridge holes / concave outlines
            c = Mesh(self.id, self.name, P, tri, self.mode, self.edges, self.z_range)
            self._coarse[max_tris] = c
        return c


class Scene:
    """Everything the 3D and depth views draw, flattened to arrays (rebuilt when the project revision changes)."""

    def __init__(self):
        self.rev = -1
        self.pid = 0
        self.pts_xyz = np.empty((0, 3))
        self.pts_rgb = np.empty((0, 3), np.uint8)
        self.pts_id = np.empty(0, np.int64)
        self.pts_num: list[str] = []
        self.pts_skipped = 0                      # points without an elevation (cannot be placed in 3D)
        self.lines: list[LineSet] = []
        self.meshes: list[Mesh] = []
        self.bounds: tuple | None = None

    @property
    def empty(self) -> bool:
        return self.bounds is None

    def summary(self) -> str:
        parts = []
        if len(self.pts_xyz):
            parts.append(f"{len(self.pts_xyz):,} points")
        n = sum(len(ls.counts) for ls in self.lines)
        if n:
            parts.append(f"{n:,} polylines")
        t = sum(m.n_tris for m in self.meshes)
        if t:
            parts.append(f"{t:,} triangles")
        return ", ".join(parts)


def build_scene(project, color_map=None) -> Scene:
    """Snapshot the visible part of a project.  `color_map(rgb) -> rgb` adapts CAD colours to the display theme."""
    cm = color_map or (lambda c: tuple(c))
    sc = Scene()
    sc.rev, sc.pid = project.revision, id(project)
    vis = {n: l for n, l in project.layers.items() if l.visible}

    # ---- surfaces
    for s in project.surfaces.values():
        st = s.style or {}
        mode = st.get("mode") or ("elevation" if st.get("shade", True) else "off")
        if (mode == "off" and not st.get("edges", False)) or len(s.tris) == 0:
            continue
        sc.meshes.append(Mesh(s.id, s.name, s.pts, s.tris, mode, bool(st.get("edges", False))))

    # ---- points  (a group switched off is out of the 3D view too)
    hidden = project.hidden_ids()
    pts = [p for p in project.points.values() if p.layer in vis and p.id not in hidden]
    if pts:
        z = np.array([p.z for p in pts], float)
        ok = np.isfinite(z)
        sc.pts_skipped = int((~ok).sum())
        pts = [p for p, k in zip(pts, ok) if k]
        if pts:
            sc.pts_xyz = np.array([(p.x, p.y, p.z) for p in pts], float)
            pal = {n: tuple(cm(l.color)) for n, l in vis.items()}
            sc.pts_rgb = np.array([pal[p.layer] for p in pts], np.uint8).reshape(-1, 3)
            sc.pts_id = np.array([p.id for p in pts], np.int64)
            sc.pts_num = [p.number for p in pts]

    # ---- polylines (arcs tessellated; missing elevations draped on the first surface, else on the mean point elevation)
    groups: dict = {}
    for e in project.entities.values():
        lay = vis.get(e.layer)
        if lay is None or not isinstance(e, Polyline) or len(e.verts) < 2:
            continue
        v = G.flatten_polyline(e.verts, e.bulges, e.closed, max_step=math.radians(4.0))
        if e.closed and len(v):
            v = np.vstack([v, v[:1]])
        rgb = cm(tuple(e.color) if e.color else tuple(lay.color))
        groups.setdefault((e.layer, tuple(rgb)), []).append(v)
    if groups:
        allv = np.concatenate([v for vs in groups.values() for v in vs])
        need = ~np.isfinite(allv[:, 2])
        fill_z = None
        if need.any():
            zs = np.full(len(allv), np.nan)
            surf = max(project.surfaces.values(), key=lambda q: len(q.tris), default=None)
            if surf is not None and len(surf.tris):
                try:
                    zs[need] = surf.tin().z_at(allv[need, 0], allv[need, 1])
                except Exception:
                    pass
            base = float(np.nanmean(sc.pts_xyz[:, 2])) if len(sc.pts_xyz) else (float(np.nanmean(allv[np.isfinite(allv[:, 2]), 2])) if (~need).any() else 0.0)
            fill_z = np.where(np.isfinite(zs), zs, base)
        k = 0
        for (layer, rgb), vs in groups.items():
            arr = np.concatenate(vs)
            if fill_z is not None:
                bad = ~np.isfinite(arr[:, 2])
                if bad.any():
                    arr = arr.copy()
                    arr[bad, 2] = fill_z[k:k + len(arr)][bad]
            k += len(arr)
            counts = np.array([len(v) for v in vs], np.int64)
            starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
            sc.lines.append(LineSet(layer, rgb, arr, starts, counts))

    # ---- bounds
    boxes = []
    if len(sc.pts_xyz):
        boxes.append((*sc.pts_xyz.min(axis=0), *sc.pts_xyz.max(axis=0)))
    for ls in sc.lines:
        good = ls.xyz[np.isfinite(ls.xyz).all(axis=1)]
        if len(good):
            boxes.append((*good.min(axis=0), *good.max(axis=0)))
    for m in sc.meshes:
        boxes.append(m.bounds())
    if boxes:
        b = np.array(boxes, float)
        sc.bounds = (float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].min()),
                     float(b[:, 3].max()), float(b[:, 4].max()), float(b[:, 5].max()))
    return sc


# ============================================================================ the orbit renderer
@dataclass
class RenderOptions:
    surface: bool = True
    points: bool = True
    lines: bool = True
    wire: bool = False
    point_px: float = 6.0
    line_px: float = 1.6
    dark: bool = True
    max_tris: int = 0                  # 0 = full detail; otherwise swap in a coarse mesh above this size
    max_points: int = 0                # 0 = all
    max_segments: int = 0              # 0 = all line segments; otherwise draw an evenly thinned subset
    selected: frozenset = frozenset()  # point ids to highlight
    sel_rgb: tuple = (0, 229, 255)
    error_point_ids: frozenset = frozenset()
    hide_non_error_points: bool = False
    dim_non_error_points: bool = False


def _quads(pa: np.ndarray, pb: np.ndarray, width: float):
    """Screen-space segments (n,2) -> two triangles each, as (2n,3,2)."""
    d = pb - pa
    ln = np.linalg.norm(d, axis=1)
    ok = ln > 1e-6
    n = np.zeros_like(d)
    n[ok] = np.column_stack([-d[ok, 1], d[ok, 0]]) / ln[ok, None] * (width / 2.0)
    n[~ok] = [0.0, width / 2.0]
    a1, a2, b1, b2 = pa + n, pa - n, pb - n, pb + n
    return np.concatenate([np.stack([a1, a2, b1], axis=1), np.stack([a1, b1, b2], axis=1)])


def _clip_to_rect(sa, sb, na, nb, x0, y0, x1, y1):
    """Liang-Barsky clip of screen segments; the nearness values are interpolated along with the end points."""
    d = sb - sa
    t0 = np.zeros(len(sa))
    t1 = np.ones(len(sa))
    ok = np.ones(len(sa), bool)
    for p, q in ((-d[:, 0], sa[:, 0] - x0), (d[:, 0], x1 - sa[:, 0]), (-d[:, 1], sa[:, 1] - y0), (d[:, 1], y1 - sa[:, 1])):
        par = np.abs(p) < 1e-12
        ok &= ~(par & (q < 0))
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(par, 0.0, q / p)
        t0 = np.where(~par & (p < 0), np.maximum(t0, r), t0)
        t1 = np.where(~par & (p > 0), np.minimum(t1, r), t1)
    ok &= t0 <= t1
    sa2, sb2 = sa + d * t0[:, None], sa + d * t1[:, None]
    return sa2[ok], sb2[ok], (na + (nb - na) * t0)[ok], (na + (nb - na) * t1)[ok]


def render_orbit(scene: Scene, cam: Camera, W: int, H: int, opts: RenderOptions | None = None) -> np.ndarray:
    """Draw the scene -> (H, W, 4) uint8 RGBA (straight alpha, transparent where nothing is drawn).

    Pass 1 paints the surface triangles far to near (and, in a second buffer, their depth).  Pass 2 paints points and
    lines that survive a per-pixel depth test against that buffer, so terrain hides what is behind it while anything
    sitting ON the surface (survey points, breaklines, contours) stays visible.
    """
    from matplotlib.backends.backend_agg import RendererAgg
    from matplotlib.transforms import Affine2D

    opts = opts or RenderOptions()
    W, H = max(1, int(W)), max(1, int(H))
    near = cam.near
    persp = cam.perspective

    def nearness(zv):                       # larger = nearer, and affine along a projected straight line
        return (1.0 / zv) if persp else -zv

    # ------------------------------------------------------------ surfaces: triangles + their depth
    s_xy, s_col, s_key, s_n = [], [], [], []
    decimated = False
    wire_meshes = []
    if opts.surface or opts.wire:
        for m in scene.meshes:
            mm = m.coarse(opts.max_tris) if (opts.max_tris and m.n_tris > opts.max_tris) else m
            decimated |= mm is not m
            if not mm.n_tris:
                continue
            S = cam.project(mm.pts, W, H)
            tris = mm.tris
            zv = S[:, 2][tris]
            sx, sy = S[:, 0][tris], S[:, 1][tris]
            ok = (zv > near).all(axis=1) & np.isfinite(sx).all(axis=1) & np.isfinite(sy).all(axis=1)
            ok &= ~((sx.max(axis=1) < -5) | (sx.min(axis=1) > W + 5) | (sy.max(axis=1) < -5) | (sy.min(axis=1) > H + 5))
            idx = np.nonzero(ok)[0]
            if (opts.surface and m.mode != "off") and len(idx):
                col = mm.colors(cam, opts.dark)
                xy = np.stack([sx[idx], H - sy[idx]], axis=2)                      # (k,3,2), Agg origin bottom-left
                d = xy - xy.mean(axis=1, keepdims=True)
                xy = xy + d / np.maximum(np.linalg.norm(d, axis=2, keepdims=True), 1e-6) * 0.6    # 0.6 px bigger: AA seams close
                rgba = np.ones((len(idx), 3, 4))
                rgba[..., :3] = col[tris[idx]]
                s_xy.append(xy)
                s_col.append(rgba)
                s_key.append(zv[idx].mean(axis=1))
                s_n.append(nearness(zv[idx]))
            if opts.wire or m.edges:
                wire_meshes.append(mm)

    r = RendererAgg(W, H, 100)
    r.clear()
    D = None
    nmin, span = 0.0, 1.0
    if s_xy:
        xy = np.ascontiguousarray(np.concatenate(s_xy))
        col = np.ascontiguousarray(np.concatenate(s_col))
        order = np.argsort(-np.concatenate(s_key), kind="stable")                    # far first
        r.draw_gouraud_triangles(r.new_gc(), xy[order], col[order], Affine2D())
        if not decimated:
            nn = np.concatenate(s_n)
            nmin = float(nn.min())
            span = max(float(nn.max()) - nmin, 1e-12)
            dcol = np.ones((len(xy), 3, 4))
            dcol[..., :3] = ((nn - nmin) / span)[:, :, None]
            rd = RendererAgg(W, H, 100)
            rd.clear()
            rd.draw_gouraud_triangles(rd.new_gc(), xy[order], dcol[order], Affine2D())
            D = np.asarray(rd.buffer_rgba())

    TOL = 4.0 / 255.0

    def visible(sx, sy, n):
        if D is None:
            return np.ones(len(sx), bool)
        d = D[np.clip(sy.astype(int), 0, H - 1), np.clip(sx.astype(int), 0, W - 1)]
        return (d[:, 3] < 128) | ((n - nmin) / span >= d[:, 0] / 255.0 - TOL)

    # ------------------------------------------------------------ points + lines, tested against the surface
    o_xy, o_col, o_key = [], [], []

    def add(xy, col, key):
        if len(xy):
            o_xy.append(xy)
            o_col.append(col)
            o_key.append(key)

    def add_segments(a3, b3, rgb, width):
        va, vb = cam.view_coords(a3), cam.view_coords(b3)
        keep = (va[:, 2] > near) | (vb[:, 2] > near)
        if not keep.any():
            return
        va, vb = va[keep].copy(), vb[keep].copy()
        m = va[:, 2] <= near
        if m.any():
            t = (near - va[m, 2]) / (vb[m, 2] - va[m, 2])
            va[m] = va[m] + t[:, None] * (vb[m] - va[m])
        m = vb[:, 2] <= near
        if m.any():
            t = (near - vb[m, 2]) / (va[m, 2] - vb[m, 2])
            vb[m] = vb[m] + t[:, None] * (va[m] - vb[m])
        A, B = cam.to_screen(va, W, H), cam.to_screen(vb, W, H)
        fin = np.isfinite(A[:, :2]).all(axis=1) & np.isfinite(B[:, :2]).all(axis=1)
        A, B = A[fin], B[fin]
        if not len(A):
            return
        sa, sb, na, nb = _clip_to_rect(A[:, :2], B[:, :2], nearness(A[:, 2]), nearness(B[:, 2]), -4, -4, W + 4, H + 4)
        if not len(sa):
            return
        if D is not None:                                           # cut into short pieces, keep the visible ones
            ln = np.linalg.norm(sb - sa, axis=1)
            cnt = np.clip(np.ceil(ln / 12.0).astype(int), 1, 40)
            seg = np.repeat(np.arange(len(sa)), cnt)
            k = np.arange(len(seg)) - np.repeat(np.cumsum(cnt) - cnt, cnt)
            t0, t1 = k / cnt[seg], (k + 1) / cnt[seg]
            tm = (t0 + t1) / 2.0
            pm = sa[seg] + (sb[seg] - sa[seg]) * tm[:, None]
            ok = visible(pm[:, 0], pm[:, 1], na[seg] + (nb[seg] - na[seg]) * tm)
            seg, t0, t1 = seg[ok], t0[ok], t1[ok]
            if not len(seg):
                return
            pa = sa[seg] + (sb[seg] - sa[seg]) * t0[:, None]
            pb = sa[seg] + (sb[seg] - sa[seg]) * t1[:, None]
            u = pb - pa
            u = u / np.maximum(np.linalg.norm(u, axis=1, keepdims=True), 1e-9)
            pa, pb = pa - u * 0.4, pb + u * 0.4                       # overlap neighbouring pieces: no hairline gaps
            nm = (na[seg] + (nb[seg] - na[seg]) * (t0 + t1) / 2.0)
        else:
            pa, pb, nm = sa, sb, (na + nb) / 2.0
        q = _quads(pa, pb, width)
        q[:, :, 1] = H - q[:, :, 1]
        c = np.ones((len(q), 3, 4))
        c[..., :3] = np.asarray(rgb, float) / 255.0
        add(q, c, np.concatenate([-nm, -nm]))

    for mm in wire_meshes:
        e = mm.edge_index()
        if len(e) <= 120_000:
            add_segments(mm.pts[e[:, 0]], mm.pts[e[:, 1]], (150, 190, 230) if opts.dark else (70, 110, 160), 1.0)
    if opts.lines:
        total = sum(len(ls.segments()[0]) for ls in scene.lines)
        stride = int(math.ceil(total / opts.max_segments)) if opts.max_segments and total > opts.max_segments else 1
        for ls in scene.lines:
            a, b = ls.segments()
            if len(a):
                add_segments(a[::stride], b[::stride], ls.rgb, opts.line_px)

    sel_items = None
    if opts.points and len(scene.pts_xyz):
        idx = np.arange(len(scene.pts_xyz))
        if opts.hide_non_error_points and opts.error_point_ids:
            err_arr = np.fromiter(opts.error_point_ids, np.int64, len(opts.error_point_ids))
            err_mask = np.isin(scene.pts_id[idx], err_arr)
            if opts.selected:
                sel_arr = np.fromiter(opts.selected, np.int64, len(opts.selected))
                err_mask |= np.isin(scene.pts_id[idx], sel_arr)
            idx = idx[err_mask]
        elif opts.max_points and len(idx) > opts.max_points:
            idx = idx[:: int(math.ceil(len(idx) / opts.max_points))]
        if len(idx):
            S = cam.project(scene.pts_xyz[idx], W, H)
            ok = (S[:, 2] > near) & np.isfinite(S[:, 0]) & np.isfinite(S[:, 1])
            ok &= (S[:, 0] > -10) & (S[:, 0] < W + 10) & (S[:, 1] > -10) & (S[:, 1] < H + 10)
            sel = np.isin(scene.pts_id[idx], np.fromiter(opts.selected, np.int64, len(opts.selected))) if opts.selected else np.zeros(len(idx), bool)
            err = np.isin(scene.pts_id[idx], np.fromiter(opts.error_point_ids, np.int64, len(opts.error_point_ids))) if opts.error_point_ids else np.zeros(len(idx), bool)
            keep = np.nonzero(ok)[0]
            if len(keep):
                S = S[keep]
                n = nearness(S[:, 2])
                selk = sel[keep]
                errk = err[keep]
                vis = visible(S[:, 0], S[:, 1], n) | selk | errk                    # selected and error points show even behind terrain
                keep, S, n, selk, errk = keep[vis], S[vis], n[vis], selk[vis], errk[vis]
                half = opts.point_px / 2.0 * (np.clip(cam.distance / S[:, 2], 0.55, 2.2) if persp else 1.0)
                half = np.where(selk, np.maximum(half * 1.7, 5.0), half)
                half = np.where(errk & ~selk, np.maximum(half * 1.3, 4.0), half)
                cx, cy = S[:, 0], H - S[:, 1]
                T, R_ = np.column_stack([cx, cy + half]), np.column_stack([cx + half, cy])
                B_, L_ = np.column_stack([cx, cy - half]), np.column_stack([cx - half, cy])
                tri = np.concatenate([np.stack([T, R_, B_], axis=1), np.stack([T, B_, L_], axis=1)])
                rgb = scene.pts_rgb[idx][keep].astype(float) / 255.0
                if opts.dim_non_error_points and opts.error_point_ids:
                    dim_mask = ~(errk | selk)
                    rgb[dim_mask] = rgb[dim_mask] * 0.25 + 0.15
                rgb = np.where(selk[:, None], np.array(opts.sel_rgb, float) / 255.0, rgb)
                c = np.ones((len(tri), 3, 4))
                c[..., :3] = np.concatenate([rgb, rgb])[:, None, :]
                key = np.where(selk, -1e30, np.where(errk, -1e20, -n))                              # selected & error markers are painted last
                add(tri, c, np.concatenate([key, key]))

    if o_xy:
        xy = np.ascontiguousarray(np.concatenate(o_xy))
        col = np.ascontiguousarray(np.concatenate(o_col))
        order = np.argsort(-np.concatenate(o_key), kind="stable")
        r.draw_gouraud_triangles(r.new_gc(), xy[order], col[order], Affine2D())
    return np.array(r.buffer_rgba(), copy=True)


# ============================================================================ the depth view (rotatable elevation)
def depth_axes(azimuth: float):
    """(d, r): unit vectors in plan - d = the direction we look, r = screen-right (looking north, right is east)."""
    a = math.radians(azimuth)
    return np.array([math.sin(a), math.cos(a)]), np.array([math.cos(a), -math.sin(a)])


def azimuth_from_line(a, b) -> float:
    """View direction (bearing) for an alignment drawn from a to b: the line runs left to right on screen and the
    view looks across it to its LEFT, so for a line drawn west -> east you look north."""
    rx, ry = b[0] - a[0], b[1] - a[1]
    return math.degrees(math.atan2(-ry, rx)) % 360.0


@dataclass
class DepthSpec:
    center: tuple = (0.0, 0.0)       # plan point where the alignment line crosses the middle of the window
    azimuth: float = 0.0             # bearing of the viewing direction
    near: float = 0.0                # slab start, along the viewing direction from the alignment line
    far: float = 100.0               # slab end
    zc: float = 0.0                  # elevation at the vertical middle of the window
    scale: float = 1.0               # pixels per plan unit
    vexag: float = 1.0               # vertical exaggeration (vertical px per unit = scale * vexag)

    def copy(self) -> "DepthSpec":
        return DepthSpec(tuple(self.center), self.azimuth, self.near, self.far, self.zc, self.scale, self.vexag)

    def axes(self):
        return depth_axes(self.azimuth)

    def depth_of(self, xy) -> np.ndarray:
        d, _ = self.axes()
        return (np.asarray(xy, float).reshape(-1, 2) - self.center) @ d

    def to_screen(self, xyz, W: float, H: float) -> np.ndarray:
        """(n,3) world -> (n,3) pixel x, pixel y (down), depth along the view direction (0 = the alignment line)."""
        p = np.asarray(xyz, float).reshape(-1, 3)
        d, r = self.axes()
        q = p[:, :2] - self.center
        return np.column_stack([W / 2.0 + (q @ r) * self.scale, H / 2.0 - (p[:, 2] - self.zc) * self.scale * self.vexag, q @ d])

    def to_world_h(self, sx: float, W: float) -> float:
        return (sx - W / 2.0) / self.scale

    def half_width(self, W: float) -> float:
        return W / 2.0 / self.scale

    def baseline(self, W: float, offset: float = 0.0):
        """World (x,y) end points of the visible alignment line at `offset` along the view direction."""
        d, r = self.axes()
        c = np.asarray(self.center, float) + d * offset
        hw = self.half_width(W)
        return c - r * hw, c + r * hw

    def plan_polygon(self, W: float) -> np.ndarray:
        """(4,2) world corners of the slab, for drawing it on the plan view."""
        a0, b0 = self.baseline(W, self.near)
        a1, b1 = self.baseline(W, self.far)
        return np.array([a0, b0, b1, a1])

    def fit_line(self, a, b, W: float, margin: float = 0.06):
        """Look at the alignment a -> b: centered on it, as wide as the window."""
        self.azimuth = azimuth_from_line(a, b)
        self.center = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0)
        length = max(math.hypot(b[0] - a[0], b[1] - a[1]), 1e-9)
        self.scale = W / (length * (1 + 2 * margin))

    def fit_bounds(self, bounds, W: float, H: float, fill: float = 0.9):
        """Slide along the alignment and zoom so the data (x0,y0,z0,x1,y1,z1) fills the window."""
        x0, y0, z0, x1, y1, z1 = bounds
        _, r = self.axes()
        corners = np.array([[x, y] for x in (x0, x1) for y in (y0, y1)], float)
        h = (corners - self.center) @ r
        hmin, hmax = float(h.min()), float(h.max())
        self.center = tuple(np.asarray(self.center, float) + r * (hmin + hmax) / 2.0)
        self.zc = (z0 + z1) / 2.0
        self.scale = min(W * fill / max(hmax - hmin, 1e-9), H * fill / max((z1 - z0) * self.vexag, 1e-9))


def clip_segments_to_slab(a: np.ndarray, b: np.ndarray, spec: DepthSpec):
    """3D segments a->b clipped to near <= depth <= far.  Returns (a', b', keep_mask) for the kept segments."""
    d, _ = spec.axes()
    da = (a[:, :2] - spec.center) @ d
    db = (b[:, :2] - spec.center) @ d
    lo, hi = np.minimum(da, db), np.maximum(da, db)
    keep = (hi >= spec.near) & (lo <= spec.far)
    a, b, da, db = a[keep], b[keep], da[keep], db[keep]
    delta = db - da
    with np.errstate(divide="ignore", invalid="ignore"):
        t_near = np.where(np.abs(delta) > 1e-12, (spec.near - da) / delta, 0.0)
        t_far = np.where(np.abs(delta) > 1e-12, (spec.far - da) / delta, 1.0)
    t0 = np.clip(np.minimum(t_near, t_far), 0.0, 1.0)
    t1 = np.clip(np.maximum(t_near, t_far), 0.0, 1.0)
    flat = np.abs(delta) <= 1e-12                      # parallel to the planes (already inside the slab)
    t0 = np.where(flat, 0.0, t0)
    t1 = np.where(flat, 1.0, t1)
    return a + (b - a) * t0[:, None], a + (b - a) * t1[:, None], keep


def nice_ticks(lo: float, hi: float, target: int = 6) -> np.ndarray:
    """Round tick positions covering [lo, hi]."""
    span = max(hi - lo, 1e-12)
    raw = span / max(target, 1)
    e = math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        step = m * 10 ** e
        if step >= raw:
            break
    first = math.ceil(lo / step - 1e-9) * step
    n = int(math.floor((hi - first) / step + 1e-9)) + 1
    return first + step * np.arange(max(n, 0))
