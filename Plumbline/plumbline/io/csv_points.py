"""Point-file (CSV / TXT / PNEZD) import and export with column sniffing."""
from __future__ import annotations

import csv
import io
import math
import re
from dataclasses import dataclass, field

import numpy as np

from ..core.model import ImportBatch, SurveyPoint

ROLES = ["number", "northing", "easting", "elevation", "description", "latitude", "longitude", "attr", "ignore"]
ROLE_LABELS = {"number": "Point #", "northing": "Northing (Y)", "easting": "Easting (X)", "elevation": "Elevation (Z)",
               "description": "Description", "latitude": "Latitude", "longitude": "Longitude",
               "attr": "Extra attribute", "ignore": "(ignore)"}

PRESETS = {
    "P, N, E, Z, D   (Point, Northing, Easting, Elev, Desc)": ["number", "northing", "easting", "elevation", "description"],
    "P, E, N, Z, D   (Point, Easting, Northing, Elev, Desc)": ["number", "easting", "northing", "elevation", "description"],
    "P, N, E, Z": ["number", "northing", "easting", "elevation"],
    "P, E, N, Z": ["number", "easting", "northing", "elevation"],
    "N, E, Z, D": ["northing", "easting", "elevation", "description"],
    "E, N, Z, D": ["easting", "northing", "elevation", "description"],
    "E, N, Z": ["easting", "northing", "elevation"],
    "N, E, Z": ["northing", "easting", "elevation"],
    "P, Lat, Lon, Z, D": ["number", "latitude", "longitude", "elevation", "description"],
    "P, Lon, Lat, Z, D": ["number", "longitude", "latitude", "elevation", "description"],
}

_SYN = {
    "number": {"point", "pt", "ptno", "pointno", "pointnumber", "pointid", "id", "name", "number", "pnt", "pno", "pointname", "ptid"},
    "northing": {"northing", "north", "n", "y", "ny", "nort"},
    "easting": {"easting", "east", "e", "x", "ex", "eastg"},
    "elevation": {"elevation", "elev", "z", "height", "h", "ele", "el", "orthoheight", "orthometricheight"},
    "description": {"description", "desc", "code", "descr", "feature", "fc", "featurecode", "note", "notes", "remarks", "comment", "dsc"},
    "latitude": {"latitude", "lat", "latd"},
    "longitude": {"longitude", "lon", "long", "lng", "lond"},
}


@dataclass
class CsvSniff:
    delimiter: str = ","
    has_header: bool = False
    header: list = field(default_factory=list)
    rows: list = field(default_factory=list)
    n_columns: int = 0
    roles: list = field(default_factory=list)
    encoding: str = "utf-8"
    n_lines: int = 0


@dataclass
class CsvMapping:
    delimiter: str = ","
    skip_rows: int = 0                    # leading lines to skip (header etc.)
    roles: list = field(default_factory=list)
    attr_names: list = field(default_factory=list)       # names for 'attr' columns (by order)
    z_scale: float = 1.0                  # multiply elevations (e.g. metres -> feet)
    null_z: float | None = None           # value meaning "no elevation" (e.g. -9999)
    start_number: int = 1                 # used when there is no Point # column


def read_text(path) -> tuple[str, str]:
    raw = open(path, "rb").read()
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1", "replace"), "latin-1"


def _is_num(s: str) -> bool:
    try:
        float(s.replace(",", "") if "," in s and "." in s else s)
        return True
    except ValueError:
        return False


def _split(line: str, delim: str, ncols_hint: int = 5):
    if delim == " ":
        return line.strip().split(None, ncols_hint - 1)
    try:
        return next(csv.reader([line], delimiter=delim, skipinitialspace=True))
    except Exception:
        return line.split(delim)


def detect_delimiter(lines: list[str]) -> str:
    best, best_score = ",", -1.0
    for d in [",", "\t", ";", "|", " "]:
        if d == " ":
            counts = [len(l.strip().split()) for l in lines]
        else:
            counts = [len(l.split(d)) for l in lines]
        if not counts or max(counts) < 2:
            continue
        mode = max(set(counts), key=counts.count)
        if mode < 2:
            continue
        consistency = counts.count(mode) / len(counts)
        score = consistency * 10 + min(mode, 8) * 0.1 - (0.5 if d == " " else 0)
        if score > best_score:
            best, best_score = d, score
    return best


def guess_roles(header: list[str] | None, rows: list[list[str]]) -> list[str]:
    n = max((len(r) for r in rows), default=0)
    if header:
        n = max(n, len(header))
    roles = ["ignore"] * n
    if header:
        used = set()
        for i, h in enumerate(header[:n]):
            key = re.sub(r"[^a-z0-9]", "", h.lower())
            for role, names in _SYN.items():
                if key in names and role not in used:
                    roles[i] = role
                    used.add(role)
                    break
        if {"easting", "northing"} <= used or {"latitude", "longitude"} <= used:
            # the header named a complete coordinate pair - trust it as-is rather than letting
            # the structural guess below add roles the header did not ask for
            return roles
    # structural guess
    numeric_cols = []
    for i in range(n):
        vals = [r[i] for r in rows[:50] if i < len(r) and r[i].strip() != ""]
        numeric_cols.append(bool(vals) and sum(_is_num(v) for v in vals) / len(vals) > 0.9)
    guess = ["ignore"] * n
    if n >= 4 and not numeric_cols[0] or (n >= 4 and numeric_cols[0] and numeric_cols[1] and numeric_cols[2] and numeric_cols[3]):
        guess[0] = "number"
        guess[1:4] = ["northing", "easting", "elevation"]
        if n >= 5:
            guess[4] = "description"
    elif n == 3 and all(numeric_cols):
        guess = ["northing", "easting", "elevation"]
    elif n == 4 and all(numeric_cols[:3]) and not numeric_cols[3]:
        guess = ["northing", "easting", "elevation", "description"]
    elif n >= 2 and numeric_cols[0] and numeric_cols[1]:
        guess[0:2] = ["northing", "easting"]
    # geographic data?
    try:
        ys = [float(r[guess.index("northing")]) for r in rows[:50]] if "northing" in guess else []
        xs = [float(r[guess.index("easting")]) for r in rows[:50]] if "easting" in guess else []
        if ys and xs and max(map(abs, ys)) <= 90 and max(map(abs, xs)) <= 180:
            guess = ["latitude" if g == "northing" else "longitude" if g == "easting" else g for g in guess]
    except (ValueError, IndexError):
        pass
    if header and any(r != "ignore" for r in roles):
        # header-derived roles win; fill gaps from structure
        return [r if r != "ignore" else (g if g in ("number",) and "number" not in roles else "ignore")
                for r, g in zip(roles, guess)]
    return guess


def sniff(path, preview: int = 80) -> CsvSniff:
    text, enc = read_text(path)
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith(("#", "//"))]
    s = CsvSniff(encoding=enc, n_lines=len(lines))
    if not lines:
        return s
    sample = lines[:30]
    s.delimiter = detect_delimiter(sample)
    rows = [[c.strip() for c in _split(l, s.delimiter)] for l in lines[:preview]]
    s.n_columns = max(len(r) for r in rows)
    first = rows[0]
    second = rows[1] if len(rows) > 1 else []
    first_num = sum(_is_num(c) for c in first)
    second_num = sum(_is_num(c) for c in second)
    s.has_header = bool(first) and first_num <= max(0, len(first) // 3) and second_num >= 2
    if s.has_header:
        s.header = first
        s.rows = rows[1:]
    else:
        s.rows = rows
    s.roles = guess_roles(s.header if s.has_header else None, s.rows)
    s.roles += ["ignore"] * (s.n_columns - len(s.roles))
    return s


def _f(v: str) -> float:
    v = v.strip().strip('"')
    if v == "" or v.lower() in ("nan", "null", "none", "-", "na", "n/a"):
        return math.nan
    return float(v.replace(",", "")) if ("," in v and "." in v) else float(v)


def read_points(path, m: CsvMapping, max_msgs: int = 25, limit: int | None = None) -> ImportBatch:
    text, _ = read_text(path)
    lines = [l for l in text.splitlines() if l.strip() and not l.lstrip().startswith(("#", "//"))]
    lines = lines[m.skip_rows:]
    if limit:
        lines = lines[:limit]
    batch = ImportBatch()
    roles = m.roles
    ix = {r: roles.index(r) for r in ("number", "northing", "easting", "elevation", "description", "latitude", "longitude")
          if r in roles}
    attr_cols = [i for i, r in enumerate(roles) if r == "attr"]
    geographic = "latitude" in ix and "longitude" in ix
    if not geographic and not ("northing" in ix and "easting" in ix):
        raise ValueError("Map the Northing and Easting (or Latitude and Longitude) columns first.")
    bad = 0
    num = m.start_number
    ncols = len(roles)
    for ln, line in enumerate(lines, start=m.skip_rows + 1):
        cells = [c.strip() for c in _split(line, m.delimiter, ncols)]
        try:
            if geographic:
                y, x = _f(cells[ix["latitude"]]), _f(cells[ix["longitude"]])
            else:
                y, x = _f(cells[ix["northing"]]), _f(cells[ix["easting"]])
            if not (math.isfinite(x) and math.isfinite(y)):
                raise ValueError("non-numeric coordinate")
            z = math.nan
            if "elevation" in ix and ix["elevation"] < len(cells):
                try:
                    z = _f(cells[ix["elevation"]])
                except ValueError:
                    z = math.nan
                if m.null_z is not None and z == m.null_z:
                    z = math.nan
                z = z * m.z_scale if math.isfinite(z) else math.nan
            if "number" in ix and ix["number"] < len(cells) and cells[ix["number"]]:
                number = cells[ix["number"]]
            else:
                number = str(num)
                num += 1
            desc = cells[ix["description"]] if "description" in ix and ix["description"] < len(cells) else ""
            attrs = {}
            for k, i in enumerate(attr_cols):
                if i < len(cells) and cells[i] != "":
                    name = m.attr_names[k] if k < len(m.attr_names) and m.attr_names[k] else f"attr{k + 1}"
                    attrs[name] = cells[i]
            batch.points.append(SurveyPoint(0, number, x, y, z, desc, "POINTS", attrs))
        except (ValueError, IndexError) as e:
            bad += 1
            if bad <= max_msgs:
                batch.messages.append(f"line {ln}: skipped ({e}): {line[:60]}")
    if bad > max_msgs:
        batch.messages.append(f"... and {bad - max_msgs} more skipped lines")
    batch.info["geographic"] = geographic
    batch.info["skipped"] = bad
    return batch


def guess_ne_order(batch: ImportBatch, project_crs, swapped: bool = False) -> str | None:
    """Which order of the two coordinate columns lands inside the CRS area of use?

    Returns "ok", "swap" (swapping N/E would fit) or None (can't tell).
    """
    pts = batch.points[:: max(1, len(batch.points) // 200)]
    if not pts or batch.info.get("geographic"):
        return None
    x = np.array([p.x for p in pts]); y = np.array([p.y for p in pts])
    a_ok, tot = project_crs.area_of_use_ok(x, y)
    b_ok, _ = project_crs.area_of_use_ok(y, x)
    if a_ok == tot:
        return "ok"
    if b_ok == tot and a_ok < tot:
        return "swap"
    return None


def write_points_csv(path, points, columns=("number", "northing", "easting", "elevation", "description"),
                     delimiter: str = ",", header: bool = True, decimals: int = 3, xy_fn=None,
                     z_scale: float = 1.0, nodata: str = ""):
    """Write points. xy_fn(x_array, y_array) -> (x', y') converts coordinates (e.g. to another CRS)."""
    pts = list(points)
    if xy_fn is not None and pts:
        x, y = xy_fn(np.array([p.x for p in pts]), np.array([p.y for p in pts]))
    else:
        x, y = np.array([p.x for p in pts]), np.array([p.y for p in pts])
    geo = "latitude" in columns or "longitude" in columns
    names = {"number": "Point", "northing": "Northing", "easting": "Easting", "elevation": "Elevation",
             "description": "Description", "latitude": "Latitude", "longitude": "Longitude"}
    dec = 8 if geo else decimals
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=delimiter)
        if header:
            w.writerow([names[c] for c in columns])
        for p, xx, yy in zip(pts, x, y):
            row = []
            for c in columns:
                if c == "number":
                    row.append(p.number)
                elif c in ("northing", "latitude"):
                    row.append(f"{yy:.{dec}f}")
                elif c in ("easting", "longitude"):
                    row.append(f"{xx:.{dec}f}")
                elif c == "elevation":
                    row.append(nodata if math.isnan(p.z) else f"{p.z * z_scale:.{decimals}f}")
                elif c == "description":
                    row.append(p.desc)
            w.writerow(row)
    return len(pts)
