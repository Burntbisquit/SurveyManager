"""Plain data classes for everything stored in a Plumbline project."""
from __future__ import annotations

import base64
import math
import zlib
from dataclasses import dataclass, field

import numpy as np

NAN = float("nan")


# ----------------------------------------------------------------------------- array packing
def pack_array(a: np.ndarray) -> dict:
    a = np.ascontiguousarray(a)
    return {"dtype": a.dtype.str, "shape": list(a.shape),
            "data": base64.b64encode(zlib.compress(a.tobytes(), 3)).decode("ascii")}


def unpack_array(d: dict) -> np.ndarray:
    raw = zlib.decompress(base64.b64decode(d["data"]))
    return np.frombuffer(raw, dtype=np.dtype(d["dtype"])).reshape(d["shape"]).copy()


def _nz(v):
    return None if (v is None or (isinstance(v, float) and math.isnan(v))) else v


# ----------------------------------------------------------------------------- layers
@dataclass
class Layer:
    name: str
    color: tuple = (220, 220, 220)
    linetype: str = "CONTINUOUS"
    visible: bool = True
    locked: bool = False

    def to_dict(self):
        return {"name": self.name, "color": list(self.color), "linetype": self.linetype,
                "visible": self.visible, "locked": self.locked}

    @classmethod
    def from_dict(cls, d):
        return cls(d["name"], tuple(d.get("color", (220, 220, 220))), d.get("linetype", "CONTINUOUS"),
                   d.get("visible", True), d.get("locked", False))


# ----------------------------------------------------------------------------- points
@dataclass(slots=True)
class SurveyPoint:
    id: int
    number: str
    x: float                      # easting  (project coordinates)
    y: float                      # northing
    z: float = NAN                # elevation (NaN = none)
    desc: str = ""
    layer: str = "POINTS"
    attrs: dict = field(default_factory=dict)

    def to_list(self):
        return [self.id, self.number, self.x, self.y, _nz(self.z), self.desc, self.layer, self.attrs or None]

    @staticmethod
    def from_list(v):
        return SurveyPoint(int(v[0]), str(v[1]), float(v[2]), float(v[3]),
                           NAN if v[4] is None else float(v[4]), v[5] or "", v[6] or "POINTS", v[7] or {})


# ----------------------------------------------------------------------------- entities
@dataclass
class Polyline:
    id: int
    layer: str
    verts: np.ndarray                         # (N,3)  x,y,z (z may be NaN)
    closed: bool = False
    bulges: np.ndarray | None = None          # (N,) DXF-style bulge for segment i -> i+1
    kind: str = "line"                        # line | breakline | contour | parcel | boundary ...
    color: tuple | None = None                # None = by layer
    linetype: str | None = None               # None = by layer
    attrs: dict = field(default_factory=dict)
    derived: str = ""                         # non-empty => generated (e.g. "linework", "contours:Site")

    def __post_init__(self):
        v = np.asarray(self.verts, float)
        if v.ndim == 1:
            v = v.reshape(-1, v.size)
        if v.shape[1] == 2:
            v = np.column_stack([v, np.full(len(v), NAN)])
        self.verts = v
        if self.bulges is not None:
            self.bulges = np.asarray(self.bulges, float)
            if not np.any(np.abs(self.bulges) > 1e-14):
                self.bulges = None

    @property
    def xy(self) -> np.ndarray:
        return self.verts[:, :2]

    @property
    def elevation(self) -> float:
        z = self.verts[:, 2]
        z = z[np.isfinite(z)]
        return float(z[0]) if len(z) else NAN

    def to_dict(self):
        d = {"t": "pl", "id": self.id, "layer": self.layer, "closed": self.closed, "kind": self.kind,
             "verts": pack_array(self.verts)}
        if self.bulges is not None:
            d["bulges"] = pack_array(self.bulges)
        if self.color:
            d["color"] = list(self.color)
        if self.linetype:
            d["linetype"] = self.linetype
        if self.attrs:
            d["attrs"] = self.attrs
        if self.derived:
            d["derived"] = self.derived
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d["layer"], unpack_array(d["verts"]), d.get("closed", False),
                   unpack_array(d["bulges"]) if "bulges" in d else None, d.get("kind", "line"),
                   tuple(d["color"]) if d.get("color") else None, d.get("linetype"),
                   d.get("attrs", {}), d.get("derived", ""))


@dataclass
class TextEntity:
    id: int
    layer: str
    x: float
    y: float
    text: str
    height: float = 1.0           # drawing units
    rotation: float = 0.0         # degrees CCW from +x
    color: tuple | None = None
    attrs: dict = field(default_factory=dict)
    derived: str = ""

    def to_dict(self):
        d = {"t": "tx", "id": self.id, "layer": self.layer, "x": self.x, "y": self.y, "text": self.text,
             "height": self.height, "rotation": self.rotation}
        if self.color:
            d["color"] = list(self.color)
        if self.attrs:
            d["attrs"] = self.attrs
        if self.derived:
            d["derived"] = self.derived
        return d

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d["layer"], d["x"], d["y"], d["text"], d.get("height", 1.0), d.get("rotation", 0.0),
                   tuple(d["color"]) if d.get("color") else None, d.get("attrs", {}), d.get("derived", ""))


# ----------------------------------------------------------------------------- surfaces
@dataclass
class Surface:
    id: int
    name: str
    pts: np.ndarray                    # (N,3)
    tris: np.ndarray                   # (M,3) int
    params: dict = field(default_factory=dict)     # how it was built (re-buildable)
    style: dict = field(default_factory=lambda: {"edges": False, "mode": "elevation", "opacity": 0.85})
    stale: bool = False
    report: dict = field(default_factory=dict)
    _tin: object = field(default=None, repr=False, compare=False)

    def tin(self):
        from .surface import TIN
        if self._tin is None:
            self._tin = TIN(self.pts, self.tris)
        return self._tin

    def set_geometry(self, pts, tris):
        self.pts = np.asarray(pts, float).reshape(-1, 3)
        self.tris = np.asarray(tris, np.int64).reshape(-1, 3)
        self._tin = None

    def to_dict(self):
        return {"id": self.id, "name": self.name, "pts": pack_array(self.pts), "tris": pack_array(self.tris.astype(np.int32)),
                "params": self.params, "style": self.style, "stale": self.stale, "report": self.report}

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d["name"], unpack_array(d["pts"]), unpack_array(d["tris"]).astype(np.int64),
                   d.get("params", {}), d.get("style", {"edges": True, "shade": True, "contours": True}),
                   d.get("stale", False), d.get("report", {}))

    def __getstate__(self):
        s = dict(self.__dict__)
        s["_tin"] = None
        return s


# ----------------------------------------------------------------------------- imagery
@dataclass
class ImageryLayer:
    id: int
    name: str
    kind: str                           # "tiles" | "file"
    source: dict = field(default_factory=dict)
    visible: bool = True
    opacity: float = 1.0
    nudge: tuple = (0.0, 0.0)           # shift applied when drawing (project units)

    def to_dict(self):
        return {"id": self.id, "name": self.name, "kind": self.kind, "source": self.source,
                "visible": self.visible, "opacity": self.opacity, "nudge": list(self.nudge)}

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d["name"], d["kind"], d.get("source", {}), d.get("visible", True),
                   d.get("opacity", 1.0), tuple(d.get("nudge", (0.0, 0.0))))


@dataclass
class ImageryCheck:
    """One survey-point vs imagery comparison - a record kept for old project files.

    Checking points against imagery was removed from the program (measuring between two points
    covers the ground).  Projects saved by an older version still hold these records, so the class
    and ``Project.checks`` stay: an old job opens, shows what it holds and saves again unchanged.
    Nothing in the interface writes a check any more.

    image_xy is the position picked on the imagery in *raw* imagery coordinates (i.e. with any
    display nudge removed), so statistics describe the imagery's own registration error.
    """
    id: int
    point_id: int
    number: str
    survey_xy: tuple
    image_xy: tuple
    layer_name: str = ""
    note: str = ""
    stamp: str = ""
    thumb: str = ""                     # base64 PNG
    include: bool = True

    @property
    def dx(self) -> float:
        return self.image_xy[0] - self.survey_xy[0]

    @property
    def dy(self) -> float:
        return self.image_xy[1] - self.survey_xy[1]

    @property
    def dist(self) -> float:
        return math.hypot(self.dx, self.dy)

    def to_dict(self):
        return {"id": self.id, "point_id": self.point_id, "number": self.number,
                "survey_xy": list(self.survey_xy), "image_xy": list(self.image_xy),
                "layer_name": self.layer_name, "note": self.note, "stamp": self.stamp,
                "thumb": self.thumb, "include": self.include}

    @classmethod
    def from_dict(cls, d):
        return cls(d["id"], d["point_id"], d["number"], tuple(d["survey_xy"]), tuple(d["image_xy"]),
                   d.get("layer_name", ""), d.get("note", ""), d.get("stamp", ""), d.get("thumb", ""),
                   d.get("include", True))


# ----------------------------------------------------------------------------- import batch
@dataclass
class ImportBatch:
    """What an importer produces. Coordinates are in the *source* system until transformed."""
    points: list = field(default_factory=list)
    polylines: list = field(default_factory=list)
    texts: list = field(default_factory=list)
    surfaces: list = field(default_factory=list)
    layers: dict = field(default_factory=dict)
    messages: list = field(default_factory=list)
    info: dict = field(default_factory=dict)          # e.g. {"epsg": 2276, "units": "ftUS"}

    def is_empty(self) -> bool:
        return not (self.points or self.polylines or self.texts or self.surfaces)

    def summary(self) -> str:
        bits = []
        for label, lst in (("points", self.points), ("polylines", self.polylines),
                           ("texts", self.texts), ("surfaces", self.surfaces)):
            if lst:
                bits.append(f"{len(lst):,} {label}")
        return ", ".join(bits) or "nothing"

    def transform_xy(self, fn, z_scale: float = 1.0):
        """Apply fn(x_array, y_array) -> (x', y') to every coordinate; scale Z by z_scale."""
        if self.points:
            x = np.array([p.x for p in self.points]); y = np.array([p.y for p in self.points])
            nx, ny = fn(x, y)
            for p, a, b in zip(self.points, np.atleast_1d(nx), np.atleast_1d(ny)):
                p.x, p.y = float(a), float(b)
                if z_scale != 1.0 and not math.isnan(p.z):
                    p.z *= z_scale
        for pl in self.polylines:
            nx, ny = fn(pl.verts[:, 0], pl.verts[:, 1])
            pl.verts = np.column_stack([nx, ny, pl.verts[:, 2] * z_scale])
        for t in self.texts:
            nx, ny = fn(np.array([t.x]), np.array([t.y]))
            t.x, t.y = float(nx[0]), float(ny[0])
        for s in self.surfaces:
            nx, ny = fn(s.pts[:, 0], s.pts[:, 1])
            s.set_geometry(np.column_stack([nx, ny, s.pts[:, 2] * z_scale]), s.tris)

    def scale_xy(self, factor: float, z_scale: float | None = None):
        zs = factor if z_scale is None else z_scale
        self.transform_xy(lambda x, y: (np.asarray(x) * factor, np.asarray(y) * factor), zs)

    def bad_coordinates(self) -> int:
        n = 0
        for p in self.points:
            if not (math.isfinite(p.x) and math.isfinite(p.y)):
                n += 1
        for pl in self.polylines:
            if not np.all(np.isfinite(pl.verts[:, :2])):
                n += 1
        return n

    def sample_xy(self, n: int = 200) -> np.ndarray:
        """A small sample of coordinates (for plausibility checks)."""
        arrs = []
        if self.points:
            step = max(1, len(self.points) // n)
            arrs.append(np.array([[p.x, p.y] for p in self.points[::step]]))
        for pl in self.polylines[:n]:
            arrs.append(pl.verts[:1, :2])
        for s in self.surfaces:
            arrs.append(s.pts[:: max(1, len(s.pts) // n), :2])
        return np.vstack(arrs) if arrs else np.empty((0, 2))
