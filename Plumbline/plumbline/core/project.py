"""The Project: everything in one drawing/job, plus (de)serialisation and undo snapshots."""
from __future__ import annotations

import json
import math
import os
import pickle
import time
import zlib
from pathlib import Path

import numpy as np

from . import units as U
from .crs import ProjectCRS
from .featurecodes import FeatureCodeTable, build_linework, default_codes, parse_description
from .groups import GroupSet
from .model import (ImageryCheck, ImageryLayer, ImportBatch, Layer, NAN, Polyline, SurveyPoint,
                    Surface, TextEntity)

FORMAT = "plumbline-project"
VERSION = 1

PALETTE = [(255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0), (255, 0, 255), (255, 128, 0),
           (0, 160, 255), (255, 90, 90), (170, 255, 120), (200, 160, 255), (255, 200, 120), (120, 220, 200)]

DEFAULT_SETTINGS = {
    "contour_interval": 1.0,
    "index_every": 5,
    "contour_base": 0.0,
    "contour_smooth": 0,
    "contour_labels": True,
    "text_height": 2.0,          # drawing units (ground) for generated labels
    "plot_scale": 20.0,          # 1 in = N units, used by DXF text sizing
    "f2f_path": "",              # the office's field-to-finish code table last converted from
}

# Everything an edit can change, and therefore everything undo/redo must carry.  `name` is in
# here so undo can restore a rename (and so AppState.edit(discard_if_unchanged=True) notices
# one); `path` deliberately is not - undoing an edit should never change which file you are
# saving to.
_STATE_KEYS = ("name", "crs", "settings", "layers", "points", "entities", "surfaces",
               "imagery", "checks", "codes", "_next_id", "notes", "groups")


class Project:
    def __init__(self, name: str = "Untitled", crs: ProjectCRS | None = None):
        self.name = name
        self.path: str | None = None
        # No silent geodetic assumption: a project without a CRS uses plain local coordinates (US survey feet)
        self.crs: ProjectCRS = crs or ProjectCRS.local("ftUS")
        self.settings: dict = dict(DEFAULT_SETTINGS)
        self.layers: dict[str, Layer] = {}
        self.points: dict[int, SurveyPoint] = {}
        self.entities: dict[int, object] = {}          # Polyline | TextEntity
        self.surfaces: dict[int, Surface] = {}
        self.imagery: dict[int, ImageryLayer] = {}
        self.checks: dict[int, ImageryCheck] = {}
        # Named sets of objects that can be switched on and off together (core/groups.py).  A
        # group switched off hides its objects **everywhere** - drawing, exports and surfaces.
        self.groups: GroupSet = GroupSet()
        self.codes: FeatureCodeTable = default_codes()
        self.notes: str = ""
        self._next_id = 1
        self.revision = 0
        self._pa_cache = None
        self.ensure_layer("POINTS", (255, 255, 255))
        self.ensure_layer("0", (230, 230, 230))
        for fc in self.codes:                      # make sure code layers exist with their colours
            if fc.layer:
                self.ensure_layer(fc.layer, fc.color, fc.linetype if fc.kind != "point" else "CONTINUOUS")

    # ------------------------------------------------------------------ basics
    @property
    def h_unit(self) -> str:
        return self.crs.unit

    @property
    def v_unit(self) -> str:
        return self.crs.vunit

    def new_id(self) -> int:
        i = self._next_id
        self._next_id += 1
        return i

    def touch(self):
        self.revision += 1
        self._pa_cache = None

    def ensure_layer(self, name: str, color=None, linetype: str = "CONTINUOUS") -> Layer:
        lay = self.layers.get(name)
        if lay is None:
            if color is None:
                color = PALETTE[len(self.layers) % len(PALETTE)]
            lay = self.layers[name] = Layer(name, tuple(color), linetype)
        return lay

    def layer_color(self, name: str) -> tuple:
        lay = self.layers.get(name)
        return lay.color if lay else (255, 255, 255)

    # ------------------------------------------------------------------ points
    def next_point_number(self) -> str:
        mx = 0
        for p in self.points.values():
            try:
                mx = max(mx, int(p.number))
            except ValueError:
                pass
        return str(mx + 1)

    def point_by_number(self, number: str) -> SurveyPoint | None:
        number = str(number)
        for p in self.points.values():
            if p.number == number:
                return p
        return None

    def add_point(self, x, y, z=NAN, number: str | None = None, desc: str = "", layer: str | None = None,
                  attrs: dict | None = None) -> SurveyPoint:
        number = str(number) if number not in (None, "") else self.next_point_number()
        p = SurveyPoint(self.new_id(), number, float(x), float(y), NAN if z is None else float(z), desc,
                        layer or "POINTS", attrs or {})
        self.ensure_layer(p.layer)
        self.points[p.id] = p
        self.touch()
        return p

    def add_polyline(self, verts, layer: str = "0", closed: bool = False, bulges=None, kind: str = "line",
                     derived: str = "", attrs: dict | None = None, color=None, linetype=None) -> Polyline:
        self.ensure_layer(layer)
        pl = Polyline(self.new_id(), layer, np.asarray(verts, float), closed, bulges, kind, color, linetype,
                      attrs or {}, derived)
        self.entities[pl.id] = pl
        self.touch()
        return pl

    def add_text(self, x, y, text, height: float | None = None, rotation: float = 0.0, layer: str = "TEXT",
                 derived: str = "", color=None, attrs=None) -> TextEntity:
        self.ensure_layer(layer, (200, 255, 200))
        t = TextEntity(self.new_id(), layer, float(x), float(y), text,
                       height or self.settings.get("text_height", 2.0), rotation, color, attrs or {}, derived)
        self.entities[t.id] = t
        self.touch()
        return t

    def add_surface(self, surface: Surface) -> Surface:
        surface.id = self.new_id()
        self.surfaces[surface.id] = surface
        self.touch()
        return surface

    def surface_by_name(self, name: str) -> Surface | None:
        for s in self.surfaces.values():
            if s.name == name:
                return s
        return None

    def remove_points(self, ids):
        gone = [i for i in list(ids) if i in self.points]
        for i in gone:
            self.points.pop(i, None)
        self.groups.remove_objects(gone)          # a deleted object is not a group member
        self.touch()

    def remove_entities(self, ids):
        gone = [i for i in list(ids) if i in self.entities]
        for i in gone:
            self.entities.pop(i, None)
        self.groups.remove_objects(gone)
        self.touch()

    # ------------------------------------------------------------------ groups / visibility
    def hidden_ids(self) -> set:
        """Object ids hidden by a group that is switched off.  Empty when there are no groups."""
        return self.groups.hidden_ids()

    def visible_points(self) -> list:
        h = self.hidden_ids()
        return [p for p in self.points.values() if p.id not in h]

    def visible_entities(self) -> list:
        h = self.hidden_ids()
        return [e for e in self.entities.values() if getattr(e, "id", None) not in h]

    def visible_surfaces(self) -> list:
        h = self.hidden_ids()
        return [s for s in self.surfaces.values() if s.id not in h]

    def hidden_count(self) -> dict:
        h = self.hidden_ids()
        return {"points": sum(1 for i in self.points if i in h),
                "entities": sum(1 for i in self.entities if i in h),
                "surfaces": sum(1 for i in self.surfaces if i in h),
                "total": len(h)}

    def remove_derived(self, prefix: str) -> int:
        dead = [i for i, e in self.entities.items() if e.derived and e.derived.startswith(prefix)]
        for i in dead:
            del self.entities[i]
        if dead:
            self.touch()
        return len(dead)

    # ------------------------------------------------------------------ bulk ops
    def apply_batch(self, batch: ImportBatch, dup_policy: str = "renumber", layer_override: str | None = None,
                    code_layers: bool = True, reference_role: str | None = None) -> dict:
        """Merge an ImportBatch.  dup_policy: renumber | skip | overwrite | keep.

        *reference_role* is set when the batch is reference data (stake-out / control / other).
        A duplicate number then means "duplicate of the same reference list", never of the field
        points: the two lists keep their own numbering, which is the whole point of keeping them
        apart (see :mod:`plumbline.core.reference`).
        """
        from . import reference as REF

        st = dict(points=0, duplicates=0, renumbered=0, skipped=0, overwritten=0, polylines=0, texts=0,
                  surfaces=0, point_ids=[])
        for name, lay in batch.layers.items():
            if name not in self.layers:
                self.layers[name] = lay
        if reference_role:
            def in_scope(other):                    # noqa: E306 - a one-line predicate, kept close to its use
                return REF.role_of(other) == reference_role
        else:
            def in_scope(other):
                return not REF.is_reference(other)
        num_index = {p.number: p.id for p in self.points.values() if in_scope(p)}
        mx = 0
        for n in num_index:
            try:
                mx = max(mx, int(n))
            except ValueError:
                pass
        for p in batch.points:
            if layer_override:
                p.layer = layer_override
            if p.number in num_index and dup_policy != "keep":
                st["duplicates"] += 1
                if dup_policy == "skip":
                    st["skipped"] += 1
                    continue
                if dup_policy == "overwrite":
                    old = self.points[num_index[p.number]]
                    old.x, old.y, old.z, old.desc = p.x, p.y, p.z, p.desc
                    st["overwritten"] += 1
                    st["point_ids"].append(old.id)          # the batch landed on this point
                    continue
                mx += 1
                p.attrs["orig_number"] = p.number
                p.number = str(mx)
                st["renumbered"] += 1
            else:
                try:
                    mx = max(mx, int(p.number))
                except ValueError:
                    pass
            p.id = self.new_id()
            self.ensure_layer(p.layer)
            self.points[p.id] = p
            num_index[p.number] = p.id
            st["points"] += 1
            st["point_ids"].append(p.id)
        for pl in batch.polylines:
            if layer_override:
                pl.layer = layer_override
            pl.id = self.new_id()
            self.ensure_layer(pl.layer)
            self.entities[pl.id] = pl
            st["polylines"] += 1
        for t in batch.texts:
            if layer_override:
                t.layer = layer_override
            t.id = self.new_id()
            self.ensure_layer(t.layer)
            self.entities[t.id] = t
            st["texts"] += 1
        for s in batch.surfaces:
            base, k = s.name, 1
            while self.surface_by_name(s.name):
                k += 1
                s.name = f"{base} ({k})"
            s.id = self.new_id()
            self.surfaces[s.id] = s
            st["surfaces"] += 1
        if code_layers and batch.points and not layer_override:
            self.apply_codes_to_points([p for p in batch.points if p.id in self.points])
        self.touch()
        return st

    # ------------------------------------------------------------------ feature codes
    def apply_codes_to_points(self, pts=None) -> dict:
        """Move points onto the layer of their feature code.  Returns matched/unknown counts."""
        pts = list(self.points.values()) if pts is None else list(pts)
        matched, unknown = 0, {}
        for p in pts:
            pd = parse_description(p.desc)
            fc = self.codes.get(pd.code) if pd.code else None
            if fc is not None:
                if fc.layer:
                    self.ensure_layer(fc.layer, fc.color, fc.linetype if fc.kind != "point" else "CONTINUOUS")
                    p.layer = fc.layer
                matched += 1
            elif pd.code:
                unknown[pd.code] = unknown.get(pd.code, 0) + 1
        self.touch()
        return {"matched": matched, "unknown": unknown}

    def process_linework(self, order: str = "file") -> dict:
        """(Re)build linework from coded points.  Replaces previously generated linework."""
        removed = self.remove_derived("linework")
        strings = build_linework(self.points.values(), self.codes, order)
        made = 0
        for ls in strings:
            fc = self.codes.get(ls.code)
            pts = [self.points[i] for i in ls.ids if i in self.points]
            if len(pts) < 2:
                continue
            verts = np.array([[p.x, p.y, p.z] for p in pts])
            self.add_polyline(verts, fc.layer or "0", ls.closed, None,
                              "breakline" if fc.breakline else "line", "linework",
                              {"code": ls.code, "string": ls.string, "points": [p.number for p in pts]})
            made += 1
        self.touch()
        return {"strings": made, "replaced": removed}

    # ------------------------------------------------------------------ arrays
    def point_arrays(self, ids=None):
        """(ids (n,), xyz (n,3)) - cached per revision when ids is None."""
        if ids is None and self._pa_cache and self._pa_cache[0] == self.revision:
            return self._pa_cache[1], self._pa_cache[2]
        pts = self.points.values() if ids is None else [self.points[i] for i in ids if i in self.points]
        n = len(self.points) if ids is None else len(pts)
        out_ids = np.empty(n, np.int64)
        xyz = np.empty((n, 3))
        for k, p in enumerate(pts):
            out_ids[k] = p.id
            xyz[k] = (p.x, p.y, p.z)
        if ids is None:
            self._pa_cache = (self.revision, out_ids, xyz)
        return out_ids, xyz

    def extents(self):
        """(xmin, ymin, xmax, ymax) over everything, or None when empty."""
        boxes = []
        if self.points:
            _, xyz = self.point_arrays()
            boxes.append((xyz[:, 0].min(), xyz[:, 1].min(), xyz[:, 0].max(), xyz[:, 1].max()))
        for e in self.entities.values():
            if isinstance(e, Polyline) and len(e.verts):
                v = e.verts
                boxes.append((np.nanmin(v[:, 0]), np.nanmin(v[:, 1]), np.nanmax(v[:, 0]), np.nanmax(v[:, 1])))
            elif isinstance(e, TextEntity):
                boxes.append((e.x, e.y, e.x, e.y))
        for s in self.surfaces.values():
            if len(s.pts):
                boxes.append((s.pts[:, 0].min(), s.pts[:, 1].min(), s.pts[:, 0].max(), s.pts[:, 1].max()))
        boxes = [b for b in boxes if all(math.isfinite(v) for v in b)]
        if not boxes:
            return None
        b = np.array(boxes)
        return float(b[:, 0].min()), float(b[:, 1].min()), float(b[:, 2].max()), float(b[:, 3].max())

    def polylines(self, kinds=None, layers=None, derived=None):
        for e in self.entities.values():
            if not isinstance(e, Polyline):
                continue
            if kinds and e.kind not in kinds:
                continue
            if layers and e.layer not in layers:
                continue
            if derived is not None and not e.derived.startswith(derived):
                continue
            yield e

    # ------------------------------------------------------------------ CRS operations
    def assign_crs(self, new_crs: ProjectCRS):
        """Re-label the coordinate system WITHOUT moving any data."""
        self.crs = new_crs
        self.touch()

    def reproject(self, new_crs: ProjectCRS, strategy: str | None = None, convert_z: bool = True):
        """Transform every coordinate into a new CRS (data physically moves)."""
        old_crs = self.crs
        fn = self.crs.transform_to(new_crs, strategy)
        zs = U.M_PER_UNIT[self.crs.vunit] / U.M_PER_UNIT[new_crs.vunit] if convert_z else 1.0
        hs = U.M_PER_UNIT[self.crs.unit] / U.M_PER_UNIT[new_crs.unit]
        if self.points:
            ids, xyz = self.point_arrays()
            nx, ny = fn(xyz[:, 0], xyz[:, 1])
            for i, a, b in zip(ids, nx, ny):
                p = self.points[int(i)]
                p.x, p.y = float(a), float(b)
                if not math.isnan(p.z):
                    p.z *= zs
        for e in self.entities.values():
            if isinstance(e, Polyline):
                nx, ny = fn(e.verts[:, 0], e.verts[:, 1])
                e.verts = np.column_stack([nx, ny, e.verts[:, 2] * zs])
            elif isinstance(e, TextEntity):
                nx, ny = fn(np.array([e.x]), np.array([e.y]))
                e.x, e.y = float(nx[0]), float(ny[0])
                e.height *= hs
        for s in self.surfaces.values():
            nx, ny = fn(s.pts[:, 0], s.pts[:, 1])
            s.set_geometry(np.column_stack([nx, ny, s.pts[:, 2] * zs]), s.tris)
        for c in self.checks.values():
            sx, sy = fn(np.array([c.survey_xy[0]]), np.array([c.survey_xy[1]]))
            ix, iy = fn(np.array([c.image_xy[0]]), np.array([c.image_xy[1]]))
            c.survey_xy, c.image_xy = (float(sx[0]), float(sy[0])), (float(ix[0]), float(iy[0]))
        for im in self.imagery.values():
            im.nudge = (im.nudge[0] * hs, im.nudge[1] * hs)
        self.settings["text_height"] = self.settings.get("text_height", 2.0) * hs
        self.settings["contour_interval"] = self.settings.get("contour_interval", 1.0) * zs
        self.crs = new_crs
        # The Point(s) Audit's record of what the points were is in coordinates too, so it is
        # moved with them.  Done here, at the one moment the system change and the coordinate
        # change are both known: told afterwards, a reprojection and an assignment (which changes
        # the name and keeps every number) look identical, and the wrong guess reports the whole
        # job as having moved.  See core/audit.py.
        from . import audit as AUD
        AUD.reprojected(self, old_crs)
        self.touch()

    # ------------------------------------------------------------------ persistence
    def to_dict(self) -> dict:
        return {
            "format": FORMAT, "version": VERSION, "name": self.name, "saved": time.strftime("%Y-%m-%d %H:%M:%S"),
            "crs": self.crs.to_dict(), "settings": self.settings, "notes": self.notes,
            "layers": [l.to_dict() for l in self.layers.values()],
            "points": [p.to_list() for p in self.points.values()],
            "entities": [e.to_dict() for e in self.entities.values()],
            "surfaces": [s.to_dict() for s in self.surfaces.values()],
            "imagery": [i.to_dict() for i in self.imagery.values()],
            "checks": [c.to_dict() for c in self.checks.values()],
            "codes": self.codes.to_list(), "next_id": self._next_id,
            "groups": self.groups.to_list(),
        }

    def save(self, path: str | os.PathLike | None = None):
        path = Path(path or self.path or "")
        if not str(path):
            raise ValueError("no path")
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, separators=(",", ":"))
        os.replace(tmp, path)
        self.path = str(path)

    @classmethod
    def from_dict(cls, d: dict) -> "Project":
        if d.get("format") != FORMAT:
            raise ValueError("Not a Plumbline project file")
        p = cls(d.get("name", "Untitled"), ProjectCRS.from_dict(d["crs"]))
        p.settings = {**DEFAULT_SETTINGS, **d.get("settings", {})}
        p.notes = d.get("notes", "")
        p.layers = {l["name"]: Layer.from_dict(l) for l in d.get("layers", [])}
        p.points = {v[0]: SurveyPoint.from_list(v) for v in d.get("points", [])}
        for e in d.get("entities", []):
            ent = Polyline.from_dict(e) if e.get("t") == "pl" else TextEntity.from_dict(e)
            p.entities[ent.id] = ent
        for s in d.get("surfaces", []):
            sf = Surface.from_dict(s)
            p.surfaces[sf.id] = sf
        for i in d.get("imagery", []):
            im = ImageryLayer.from_dict(i)
            p.imagery[im.id] = im
        for c in d.get("checks", []):
            ck = ImageryCheck.from_dict(c)
            p.checks[ck.id] = ck
        p.groups = GroupSet.from_list(d.get("groups", []))
        if d.get("codes"):
            p.codes = FeatureCodeTable.from_list(d["codes"])
        p._next_id = int(d.get("next_id", 1))
        p.ensure_layer("0", (230, 230, 230))
        p.ensure_layer("POINTS", (255, 255, 255))
        p.touch()
        return p

    @classmethod
    def load(cls, path) -> "Project":
        with open(path, "r", encoding="utf-8") as f:
            d = json.load(f)
        p = cls.from_dict(d)
        p.path = str(path)
        return p

    # ------------------------------------------------------------------ transforms
    def apply_similarity(self, base=(0.0, 0.0), scale: float = 1.0, rot_deg: float = 0.0, shift=(0.0, 0.0),
                         dz: float = 0.0, z_scale: float = 1.0, point_ids=None, entity_ids=None,
                         include_surfaces: bool = True) -> dict:
        """Scale and rotate (counter-clockwise) about `base`, then shift.  None ids = everything.

        Surfaces move with a whole-project transform; for a partial transform they are left alone (and will report stale).
        """
        bx, by = base
        a = math.radians(rot_deg)
        c, s = math.cos(a) * scale, math.sin(a) * scale

        def xf(x, y):
            x = np.asarray(x, float) - bx
            y = np.asarray(y, float) - by
            return bx + c * x - s * y + shift[0], by + s * x + c * y + shift[1]

        n_p = n_e = n_s = 0
        for p in self.points.values():
            if point_ids is None or p.id in point_ids:
                p.x, p.y = (float(v) for v in xf(p.x, p.y))
                if not math.isnan(p.z):
                    p.z = p.z * z_scale + dz
                n_p += 1
        for e in self.entities.values():
            if entity_ids is None or e.id in entity_ids:
                if isinstance(e, Polyline):
                    x, y = xf(e.verts[:, 0], e.verts[:, 1])
                    z = e.verts[:, 2] * z_scale + dz
                    e.verts = np.column_stack([x, y, z])
                    if e.bulges is not None and scale < 0:
                        e.bulges = -e.bulges
                else:
                    e.x, e.y = (float(v) for v in xf(e.x, e.y))
                    e.rotation = (e.rotation + rot_deg) % 360.0
                    e.height *= abs(scale)
                n_e += 1
        if include_surfaces and point_ids is None and entity_ids is None:
            for sf in self.surfaces.values():
                x, y = xf(sf.pts[:, 0], sf.pts[:, 1])
                sf.set_geometry(np.column_stack([x, y, sf.pts[:, 2] * z_scale + dz]), sf.tris)
                n_s += 1
        self.touch()
        return {"points": n_p, "entities": n_e, "surfaces": n_s}

    # ------------------------------------------------------------------ undo snapshots
    def snapshot(self) -> bytes:
        state = {k: getattr(self, k) for k in _STATE_KEYS}
        return zlib.compress(pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL), 1)

    def restore(self, blob: bytes):
        state = pickle.loads(zlib.decompress(blob))
        for k, v in state.items():
            setattr(self, k, v)
        self.touch()

    # ------------------------------------------------------------------ misc
    def summary(self) -> dict:
        return {"points": len(self.points),
                "polylines": sum(1 for e in self.entities.values() if isinstance(e, Polyline)),
                "texts": sum(1 for e in self.entities.values() if isinstance(e, TextEntity)),
                "surfaces": len(self.surfaces), "layers": len(self.layers),
                "checks": len(self.checks), "crs": self.crs.label}
