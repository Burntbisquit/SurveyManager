"""Field codes ("descriptions") -> layers, symbols and linework.

A point description is parsed as:   CODE[string] [flags...] [free notes]

    EP        edge-of-pavement point (string "")
    EP1       string 1            EP 1   (same)
    EP B      begin a new EP string here
    EP E      this point ends the string
    EP CLS    this point closes the string back to its first point
    TREE 18 OAK     point code with notes "18 OAK"

Points with the same code and string number are joined in point order.
"""
from __future__ import annotations

import functools
import math
import re
from dataclasses import dataclass, field

import numpy as np

BEGIN_FLAGS = {"B", "BEG", "BEGIN", "START"}
END_FLAGS = {"E", "END"}
CLOSE_FLAGS = {"C", "CLS", "CLOSE"}

_TOKEN = re.compile(r"^([A-Za-z][A-Za-z_\-]*?)(\d+)?$")

#: The whole leading word of a description, digits included: "THACK22", "T05", "EC".
#: Used to try an exact code match *before* treating trailing digits as a string number.
_LEAD_WORD = re.compile(r"^[A-Za-z][A-Za-z0-9_\-]*")

#: Carlson writes the entity type as a *number* in its own field-to-finish export and as a
#: word in a table somebody has edited by hand, so both spellings have to be understood.
#: Fieldwork Manager keeps its own copy of this table (it ships as a separate program and must
#: not import Plumbline); a test pins the two copies equal so they cannot drift apart.
CARLSON_ENTITY_TYPES = {"0": "Point", "1": "Line", "2": "2D Polyline", "3": "3D Polyline"}

#: A code table's entity type -> (Plumbline kind, is it a breakline).  An entity type that is
#: not listed is treated as a point: a stray line through the wrong points damages a surface,
#: a stray point does not.
ENTITY_TO_KIND = {
    "point": ("point", False),
    "line": ("line", True),
    "2d polyline": ("line", True),
    "polyline": ("line", True),
    "3d polyline": ("line", True),
    "arc": ("line", True),
    "circle": ("polygon", True),
    "polygon": ("polygon", True),
    "text": ("point", False),
    "block": ("point", False),
}


def kind_for_entity(entity: str) -> tuple[str, bool, bool]:
    """(kind, breakline, recognised) for the "Entity Type" cell of a code table.

    Recognised means "this file said something we understand", which is what the conversion
    reports back to the user - an office's custom entity type should be heard, not silently
    rounded off to a point.
    """
    word = (entity or "").strip().casefold()
    word = CARLSON_ENTITY_TYPES.get(word, word).casefold()
    if word in ENTITY_TO_KIND:
        kind, breakline = ENTITY_TO_KIND[word]
        return kind, breakline, True
    return "point", False, False


@dataclass
class FeatureCode:
    code: str
    name: str = ""
    kind: str = "point"                  # point | line | polygon
    layer: str = ""
    symbol: str = "cross"
    color: tuple = (255, 255, 255)
    linetype: str = "CONTINUOUS"
    breakline: bool = False              # line strings become TIN breaklines
    ground: bool = True                  # points contribute to the ground surface

    def to_dict(self):
        return {"code": self.code, "name": self.name, "kind": self.kind, "layer": self.layer,
                "symbol": self.symbol, "color": list(self.color), "linetype": self.linetype,
                "breakline": self.breakline, "ground": self.ground}

    @classmethod
    def from_dict(cls, d):
        return cls(d["code"].upper(), d.get("name", ""), d.get("kind", "point"), d.get("layer", ""),
                   d.get("symbol", "cross"), tuple(d.get("color", (255, 255, 255))),
                   d.get("linetype", "CONTINUOUS"), bool(d.get("breakline", False)),
                   bool(d.get("ground", True)))


class FeatureCodeTable:
    def __init__(self, codes=None):
        self.codes: dict[str, FeatureCode] = {}
        for c in codes or []:
            self.codes[c.code.upper()] = c

    def get(self, code: str) -> FeatureCode | None:
        return self.codes.get((code or "").upper())

    def resolve(self, desc: str) -> FeatureCode | None:
        """Feature code for a raw description, honouring both field conventions.

        There are two ways a crew writes a numbered code and they collide:

        * Carlson / office F2F treat the digits as part of the code - ``THACK22``
          and ``T05`` are codes in their own right (1,314 of the 1,717 codes in a
          real Texas office standard end in a digit).
        * Plumbline treats them as a *string number* - ``EP1`` is edge of pavement,
          string 1, so the tenth shot on that string is ``EP10``.

        Resolving the whole leading word first satisfies the first convention, and
        falling back to base+string satisfies the second.  A code that is literally
        in the table always wins, which is what "the office standard says so" means.
        """
        text = (desc or "").strip()
        if not text:
            return None
        lead = _LEAD_WORD.match(text)
        if lead:
            exact = self.codes.get(lead.group(0).upper())
            if exact is not None:
                return exact
        pd = parse_description(text)
        return self.codes.get(pd.code) if pd.code else None

    def resolve_parts(self, desc: str) -> tuple[FeatureCode | None, str]:
        """(feature code, string number) - the pair linework groups points by.

        When the code matched as a whole word the string number comes from a *separate*
        bare-number token if there is one: ``THACK22`` has no string (it is its own
        office code), but a hypothetical ``THACK22 3`` would be string 3.  This keeps
        ``THACK06`` and ``THACK10`` from being chained into one line just because both
        end in digits, while still honouring ``EP 1``-style strings.
        """
        text = (desc or "").strip()
        lead = _LEAD_WORD.match(text)
        if lead:
            exact = self.codes.get(lead.group(0).upper())
            if exact is not None:
                rest = text[lead.end():].strip().split()
                if rest and rest[0].isdigit():
                    return exact, rest[0]
                return exact, ""
        pd = parse_description(text)
        return (self.codes.get(pd.code) if pd.code else None), pd.string

    def add(self, fc: FeatureCode):
        self.codes[fc.code.upper()] = fc

    def remove(self, code: str):
        self.codes.pop(code.upper(), None)

    def items(self):
        return self.codes.items()

    def keys(self):
        return self.codes.keys()

    def values(self):
        return self.codes.values()

    def __contains__(self, code: str):
        return (code or "").upper() in self.codes

    def __getitem__(self, code: str):
        return self.codes[(code or "").upper()]

    def __iter__(self):
        return iter(self.codes.values())

    def __len__(self):
        return len(self.codes)

    def to_list(self):
        return [c.to_dict() for c in self.codes.values()]

    @classmethod
    def from_list(cls, lst):
        return cls([FeatureCode.from_dict(d) for d in lst])


@dataclass
class ParsedDesc:
    code: str = ""
    string: str = ""
    flags: frozenset = frozenset()
    note: str = ""


@functools.lru_cache(maxsize=65536)
def parse_description(desc: str) -> ParsedDesc:
    tokens = (desc or "").strip().split()
    if not tokens:
        return ParsedDesc()
    m = _TOKEN.match(tokens[0])
    if not m:
        return ParsedDesc(code=tokens[0].upper(), note=" ".join(tokens[1:]))
    code = m.group(1).rstrip("-_").upper()
    string = m.group(2) or ""
    flags, notes = set(), []
    rest = tokens[1:]
    if not string and rest and rest[0].isdigit():
        string = rest[0]
        rest = rest[1:]
    for t in rest:
        u = t.upper()
        if u in BEGIN_FLAGS or u in END_FLAGS or u in CLOSE_FLAGS:
            flags.add(u)
        else:
            notes.append(t)
    return ParsedDesc(code, string, frozenset(flags), " ".join(notes))


def _fc(code, name, kind, layer, symbol="cross", color=(255, 255, 255), linetype="CONTINUOUS",
        breakline=False, ground=True):
    return FeatureCode(code, name, kind, layer, symbol, color, linetype, breakline, ground)


def default_codes() -> FeatureCodeTable:
    """A generic topo/planimetric starter library - edit freely."""
    L = [
        # ground & control
        _fc("GS", "Ground shot", "point", "TOPO-GROUND", "cross", (200, 200, 200)),
        _fc("SPOT", "Spot elevation", "point", "TOPO-SPOT", "cross", (200, 200, 200)),
        _fc("BM", "Benchmark", "point", "CONTROL-BM", "triangle", (255, 90, 90), ground=False),
        _fc("CP", "Control point", "point", "CONTROL-CP", "triangle", (255, 90, 90), ground=False),
        # pavement & curb
        _fc("EP", "Edge of pavement", "line", "ROAD-EP", color=(255, 255, 0), breakline=True),
        _fc("TC", "Top of curb", "line", "ROAD-CURB-TOP", color=(255, 190, 0), breakline=True),
        _fc("TOC", "Top of curb", "line", "ROAD-CURB-TOP", color=(255, 190, 0), breakline=True),
        _fc("BC", "Back of curb", "line", "ROAD-CURB-BACK", color=(255, 150, 0), breakline=True),
        _fc("FL", "Flowline / gutter", "line", "ROAD-FL", color=(0, 200, 255), breakline=True),
        _fc("CL", "Centerline", "line", "ROAD-CL", color=(255, 0, 255), linetype="CENTER"),
        _fc("EG", "Edge of gravel", "line", "ROAD-GRAVEL", color=(200, 160, 100), linetype="DASHED", breakline=True),
        _fc("SW", "Sidewalk edge", "line", "ROAD-SIDEWALK", color=(190, 190, 190), breakline=True),
        _fc("DW", "Driveway edge", "line", "ROAD-DRIVE", color=(170, 170, 255), breakline=True),
        # structures & site
        _fc("BLDG", "Building", "polygon", "STRUCT-BLDG", color=(255, 128, 0), ground=False),
        _fc("FFE", "Finished floor elevation", "point", "STRUCT-FFE", "square", (255, 128, 0), ground=False),
        _fc("WALL", "Wall", "line", "STRUCT-WALL", color=(220, 120, 60), ground=False),
        _fc("RW", "Retaining wall", "line", "STRUCT-RW", color=(220, 120, 60), breakline=True),
        _fc("FNC", "Fence", "line", "SITE-FENCE", color=(140, 255, 140), linetype="DASHDOT", ground=False),
        _fc("SIGN", "Sign", "point", "SITE-SIGN", "square", (255, 255, 120), ground=False),
        # drainage & water
        _fc("CRK", "Creek centerline", "line", "HYDRO-CREEK", color=(0, 140, 255), breakline=True),
        _fc("TOB", "Top of bank", "line", "HYDRO-BANK-TOP", color=(120, 200, 120), breakline=True),
        _fc("BOB", "Bottom of bank", "line", "HYDRO-BANK-BOT", color=(60, 170, 220), breakline=True),
        _fc("WE", "Water edge", "line", "HYDRO-WATEREDGE", color=(80, 180, 255), breakline=True),
        _fc("SWL", "Swale / ditch flowline", "line", "HYDRO-SWALE", color=(0, 220, 200), breakline=True),
        _fc("TOS", "Top of slope", "line", "GRADE-TOS", color=(160, 255, 80), breakline=True),
        _fc("TOE", "Toe of slope", "line", "GRADE-TOE", color=(255, 160, 80), breakline=True),
        # utilities
        _fc("MH", "Manhole", "point", "UTIL-MH", "manhole", (0, 255, 255), ground=False),
        _fc("SSMH", "Sanitary sewer manhole", "point", "UTIL-SS", "manhole", (0, 220, 0), ground=False),
        _fc("SDMH", "Storm drain manhole", "point", "UTIL-SD", "manhole", (0, 180, 255), ground=False),
        _fc("CI", "Curb inlet", "point", "UTIL-SD", "square", (0, 180, 255), ground=False),
        _fc("WV", "Water valve", "point", "UTIL-WATER", "valve", (80, 140, 255), ground=False),
        _fc("FH", "Fire hydrant", "point", "UTIL-WATER", "hydrant", (255, 70, 70), ground=False),
        _fc("WM", "Water meter", "point", "UTIL-WATER", "square", (80, 140, 255), ground=False),
        _fc("PP", "Power pole", "point", "UTIL-POWER", "pole", (255, 100, 255), ground=False),
        _fc("LP", "Light pole", "point", "UTIL-POWER", "pole", (255, 255, 120), ground=False),
        _fc("GUY", "Guy anchor", "point", "UTIL-POWER", "x", (255, 100, 255), ground=False),
        _fc("OHE", "Overhead electric", "line", "UTIL-OHE", color=(255, 100, 255), linetype="DASHDOT", ground=False),
        # vegetation
        _fc("TREE", "Tree", "point", "VEG-TREE", "tree", (40, 200, 60), ground=False),
        _fc("BRUSH", "Brush line", "line", "VEG-BRUSH", color=(40, 160, 60), linetype="DASHED", ground=False),
        # boundaries
        _fc("PL", "Property line", "line", "BNDY-PL", color=(255, 255, 255), linetype="PHANTOM", ground=False),
        _fc("ROW", "Right of way", "line", "BNDY-ROW", color=(255, 120, 120), linetype="PHANTOM", ground=False),
        _fc("EASE", "Easement", "line", "BNDY-EASE", color=(180, 120, 255), linetype="HIDDEN", ground=False),
    ]
    return FeatureCodeTable(L)


# ----------------------------------------------------------------------------- linework builder
@dataclass
class LineString:
    code: str
    string: str
    ids: list = field(default_factory=list)       # point ids in order
    closed: bool = False


def build_linework(points, table: FeatureCodeTable, order: str = "file") -> list[LineString]:
    """Group coded points into strings. order: "file" (import order) | "number"."""
    pts = list(points)
    if order == "number":
        def nk(p):
            try:
                return (0, float(p.number), p.id)
            except ValueError:
                return (1, 0.0, p.id)
        pts.sort(key=nk)
    else:
        pts.sort(key=lambda p: p.id)
    open_: dict[tuple, LineString] = {}
    out: list[LineString] = []

    def flush(key, closed=False):
        ls = open_.pop(key, None)
        if ls and len(ls.ids) >= 2:
            ls.closed = ls.closed or closed
            out.append(ls)

    for p in pts:
        pd = parse_description(p.desc)
        fc, string = table.resolve_parts(p.desc)
        if fc is None or fc.kind == "point":
            continue
        key = (fc.code, string)
        if pd.flags & BEGIN_FLAGS:
            flush(key)
        ls = open_.get(key)
        if ls is None:
            ls = open_[key] = LineString(fc.code, string)
            ls.closed = fc.kind == "polygon"
        ls.ids.append(p.id)
        if pd.flags & CLOSE_FLAGS:
            flush(key, closed=True)
        elif pd.flags & END_FLAGS:
            flush(key)
    for key in list(open_):
        flush(key)
    return out


def point_style(desc: str, table: FeatureCodeTable):
    """(layer, symbol, color) for a point description, or None when the code is unknown."""
    fc = table.resolve(desc)
    if fc is None:
        return None
    return fc.layer or "POINTS", fc.symbol, fc.color
