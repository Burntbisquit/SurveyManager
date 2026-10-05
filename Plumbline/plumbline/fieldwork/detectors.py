
# detectors.py — exact/similar/closeNE + bearing helpers
import re, math
from collections import defaultdict
from pathlib import Path
from .config import XY_TOLERANCE, NE_TOLERANCE, ELEV_TOLERANCE
from .utils_sort import natural_key

def _working_row_to_float(value):
    try:
        return float(str(value).strip()) if str(value).strip() != "" else None
    except (ValueError, TypeError):
        return None

def _cardinal_direction(dN, dE):
    if dN is None or dE is None:
        return ""
    if abs(dN) < 1e-9 and abs(dE) < 1e-9:
        return "—"
    ang = (math.degrees(math.atan2(dE, dN)) + 360) % 360
    dirs = ["N","NE","E","SE","S","SW","W","NW"]
    idx = int((ang + 22.5) // 45) % 8
    return dirs[idx]

def _bearing_deg(dN, dE):
    if dN is None or dE is None:
        return None
    if abs(dN) < 1e-9 and abs(dE) < 1e-9:
        return None
    return (math.degrees(math.atan2(dE, dN)) + 360) % 360

def _format_dms(deg_float):
    d = int(math.floor(deg_float))
    rem = (deg_float - d) * 60
    m = int(math.floor(rem))
    s = (rem - m) * 60
    s = round(s, 1)
    if s >= 60:
        s -= 60
        m += 1
    if m >= 60:
        m -= 60
        d += 1
    return f"{d}°{m:02d}'{s:04.1f}\""

def _bearing_dms(dN, dE):
    if dN is None or dE is None:
        return ""
    if abs(dN) < 1e-9 and abs(dE) < 1e-9:
        return "—"
    az = (math.degrees(math.atan2(dE, dN)) + 360) % 360
    if 0 <= az < 90:
        quad_deg = az
        return f"N {_format_dms(quad_deg)} E"
    elif 90 <= az < 180:
        quad_deg = 180 - az
        return f"S {_format_dms(quad_deg)} E"
    elif 180 <= az < 270:
        quad_deg = az - 180
        return f"S {_format_dms(quad_deg)} W"
    else:
        quad_deg = 360 - az
        return f"N {_format_dms(quad_deg)} W"

def _format_distance_direction(dN, dE):
    if dN is None or dE is None:
        return ""
    dist = math.hypot(dN, dE)
    if dist < 1e-9:
        return "0.000 —"
    bear = _bearing_dms(dN, dE)
    return f"{dist:.3f} {bear}"

def normalize_point_number(pn: str) -> str:
    """Trim + casefold for exact grouping. Empty -> ''."""
    if pn is None:
        return ""
    return str(pn).strip().casefold()


def point_number_core(pn: str) -> str:
    """Core numeric part: strip leading/trailing letters (A-Z) case-insensitively.

    Examples: 'a602'->'602', '602a'->'602', '602'->'602', '53602a'->'53602',
    '6a'->'6', 'PRS843728484041'->'843728484041'. Returns '' if no digits.
    The remaining core is casefolded for grouping.
    """
    if pn is None:
        return ""
    s = str(pn).strip()
    if s == "":
        return ""
    # Remove leading letters
    s = re.sub(r'^[A-Za-z]+', '', s)
    # Remove trailing letters
    s = re.sub(r'[A-Za-z]+$', '', s)
    s = s.strip()
    return s.casefold()


def _working_row_to_float(value):
    try:
        return float(str(value).strip()) if str(value).strip() != "" else None
    except (ValueError, TypeError):
        return None


def find_exact_duplicate_groups(working_rows):
    """Exact point-number groups (case-insensitive trimmed).

    working_rows: list of 8-col lists [OID, PtNum, N, E, Z, Desc, Parent, Source].
    Returns list of groups, each group is list of row indices into working_rows
    where normalized point number repeats (len>1). Sorted by first OID.
    """
    buckets = defaultdict(list)
    for idx, row in enumerate(working_rows):
        pn = row[1] if len(row) > 1 else ""
        norm = normalize_point_number(pn)
        if norm == "":
            continue
        buckets[norm].append(idx)
    groups = [idxs for idxs in buckets.values() if len(idxs) > 1]
    # Canonical order: by smallest OID numeric
    def group_key(idxs):
        try:
            return min(int(working_rows[i][0]) for i in idxs if str(working_rows[i][0]).isdigit())
        except Exception:
            return idxs[0]
    groups.sort(key=group_key)
    return groups


def find_similar_number_groups(working_rows):
    """Suggestive similar-number groups: same core after stripping edge letters,
    but at least 2 distinct normalized point numbers in the group.

    Excludes pure-exact-only groups (distinct count ==1). Allows overlap with
    exact groups — a point may appear in both Exact and Similar reports.
    """
    buckets = defaultdict(list)
    for idx, row in enumerate(working_rows):
        pn = row[1] if len(row) > 1 else ""
        norm = normalize_point_number(pn)
        if norm == "":
            continue
        core = point_number_core(pn)
        if core == "":
            continue
        # Core that is purely numeric/alpha? Keep any non-empty core.
        buckets[core].append(idx)
    groups = []
    for core, idxs in buckets.items():
        if len(idxs) < 2:
            continue
        distinct = {normalize_point_number(working_rows[i][1]) for i in idxs}
        if len(distinct) < 2:
            continue
        # Core equality already groups; distinct ensures variant decor.
        groups.append(idxs)
    def group_key(idxs):
        try:
            return min(int(working_rows[i][0]) for i in idxs if str(working_rows[i][0]).isdigit())
        except Exception:
            return idxs[0]
    groups.sort(key=group_key)
    return groups


def find_close_ne_groups(working_rows, tol=NE_TOLERANCE, elev_tol=ELEV_TOLERANCE):
    """Spatial near-duplicates: horizontal distance on N(X)/E(Y) ≤ tol and elev diff ≤ elev_tol.

    Horizontal is pseudo-Euclidean sqrt(dN^2+dE^2) (USft). Elevation is separate diff |dZ| ≤ elev_tol.
    Builds adjacency where both conditions hold, then connected components. Keeps only components
    where ≥2 distinct point numbers (different numbers to merge).

    Returns list of groups (list of indices). Sorted by smallest OID.
    """
    n = len(working_rows)
    if n < 2:
        return []
    # Pre-parse floats; skip rows with missing N/E
    coords = []  # (n, e, z)
    valid_idx = []
    for idx, row in enumerate(working_rows):
        n_val = _working_row_to_float(row[2] if len(row) > 2 else "")
        e_val = _working_row_to_float(row[3] if len(row) > 3 else "")
        z_val = _working_row_to_float(row[4] if len(row) > 4 else "")
        if n_val is None or e_val is None:
            continue
        coords.append((n_val, e_val, z_val))
        valid_idx.append(idx)
    m = len(valid_idx)
    if m < 2:
        return []
    parent = list(range(m))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    tol2 = tol * tol
    order = sorted(range(m), key=lambda i: coords[i][0])
    for pos_a, a in enumerate(order):
        na, ea, za = coords[a]
        for pos_b in range(pos_a + 1, m):
            b = order[pos_b]
            nb, eb, zb = coords[b]
            dN = nb - na
            if dN > tol:
                break
            if dN < -tol:
                continue
            dE = eb - ea
            if abs(dE) > tol:
                continue
            if dN * dN + dE * dE > tol2 + 1e-9:
                continue
            # Elev diff check (if both have elev)
            if za is not None and zb is not None:
                if abs(zb - za) > elev_tol + 1e-9:
                    continue
            # If one elev missing, treat as pass (horizontal only)
            union(a, b)

    # Collect components
    comps = defaultdict(list)
    for i in range(m):
        r = find(i)
        comps[r].append(valid_idx[i])

    groups = []
    for members in comps.values():
        if len(members) < 2:
            continue
        distinct = {normalize_point_number(working_rows[idx][1]) for idx in members}
        # Keep only groups where different point numbers to merge
        if len(distinct) < 2:
            continue
        groups.append(sorted(members, key=lambda idx: int(working_rows[idx][0]) if str(working_rows[idx][0]).isdigit() else idx))
    groups.sort(key=lambda idxs: min(int(working_rows[i][0]) for i in idxs if str(working_rows[i][0]).isdigit()) if any(str(working_rows[i][0]).isdigit() for i in idxs) else idxs[0])
    return groups

# Alias for older callers

find_close_xy_groups = find_close_ne_groups
