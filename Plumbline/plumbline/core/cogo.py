"""Coordinate geometry: bearings, inverses, traverses, closure."""
from __future__ import annotations

import math
import re

import numpy as np

from . import geometry as G


def azimuth_deg(dx: float, dy: float) -> float:
    """Azimuth clockwise from grid north, 0..360."""
    return math.degrees(math.atan2(dx, dy)) % 360.0


def inverse(x1, y1, x2, y2) -> tuple[float, float]:
    dx, dy = x2 - x1, y2 - y1
    return azimuth_deg(dx, dy), math.hypot(dx, dy)


def direct(x, y, az_deg: float, dist: float) -> tuple[float, float]:
    a = math.radians(az_deg)
    return x + dist * math.sin(a), y + dist * math.cos(a)


def to_dms(deg: float, decimals: int = 0):
    """(d, m, s) with correct carry after rounding."""
    deg = abs(deg)
    d = int(deg)
    m = int((deg - d) * 60)
    s = round((deg - d - m / 60.0) * 3600.0, decimals)
    if s >= 60:
        s -= 60; m += 1
    if m >= 60:
        m -= 60; d += 1
    return d, m, s


def format_azimuth(az: float, dms: bool = True, decimals: int = 0) -> str:
    az %= 360.0
    if not dms:
        return f"{az:.{max(decimals, 2)}f}°"
    d, m, s = to_dms(az, decimals)
    if d >= 360:
        d = 0
    return f"{d}°{m:02d}'{s:0{3 + decimals if decimals else 2}.{decimals}f}\""


def quadrant_bearing(az: float):
    az %= 360.0
    if az <= 90:
        return "N", az, "E"
    if az <= 180:
        return "S", 180 - az, "E"
    if az <= 270:
        return "S", az - 180, "W"
    return "N", 360 - az, "W"


def format_bearing(az: float, dms: bool = True, decimals: int = 0) -> str:
    ns, ang, ew = quadrant_bearing(az)
    if not dms:
        return f"{ns} {ang:.{max(decimals, 2)}f}° {ew}"
    d, m, s = to_dms(ang, decimals)
    sfmt = f"{s:0{3 + decimals if decimals else 2}.{decimals}f}"
    return f"{ns} {d}°{m:02d}'{sfmt}\" {ew}"


def format_angle(az: float, mode: str = "quadrant", dms: bool = True, decimals: int = 0) -> str:
    return format_bearing(az, dms, decimals) if mode == "quadrant" else format_azimuth(az, dms, decimals)


_BEAR = re.compile(r"^([NS])?\s*([0-9.\s]+?)\s*([EW])?$")


def parse_bearing(text: str) -> float | None:
    """Parse "N45-30-15E", "S 12°30'W", "N45.5E", "45.5" (azimuth), "45 30 15" -> azimuth degrees."""
    if text is None:
        return None
    t = text.strip().upper()
    for ch in "°'\"-_,D":
        t = t.replace(ch, " ")
    t = re.sub(r"\s+", " ", t).strip()
    m = _BEAR.match(t)
    if not m:
        return None
    ns, nums, ew = m.groups()
    if bool(ns) != bool(ew):
        return None
    try:
        parts = [float(p) for p in nums.split()]
    except ValueError:
        return None
    if not parts or len(parts) > 3:
        return None
    deg = parts[0] + (parts[1] / 60 if len(parts) > 1 else 0) + (parts[2] / 3600 if len(parts) > 2 else 0)
    if not ns:
        return deg % 360.0 if 0 <= deg <= 360 else None
    if deg > 90 + 1e-9:
        return None
    if ns == "N":
        return deg if ew == "E" else (360 - deg) % 360
    return (180 - deg) if ew == "E" else 180 + deg


def traverse(start, courses, close: bool = True) -> dict:
    """Run a traverse of (azimuth_deg, distance) courses from a start point.

    Returns points, misclosure (dE, dN), linear error, perimeter, precision ratio and area
    (unadjusted).  `close` assumes the traverse is meant to return to the start.
    """
    x, y = float(start[0]), float(start[1])
    pts = [(x, y)]
    perim = 0.0
    for az, dist in courses:
        x, y = direct(x, y, az, dist)
        pts.append((x, y))
        perim += abs(dist)
    pts_arr = np.array(pts)
    res = {"points": pts_arr, "perimeter": perim}
    if close and len(pts) > 2:
        dE, dN = pts_arr[-1, 0] - pts_arr[0, 0], pts_arr[-1, 1] - pts_arr[0, 1]
        err = math.hypot(dE, dN)
        res.update({"misclosure_e": dE, "misclosure_n": dN, "linear_error": err,
                    "precision": (perim / err) if err > 1e-12 else math.inf,
                    "error_bearing": azimuth_deg(dE, dN) if err > 0 else 0.0})
        ring = pts_arr[:-1] if err < 1e-9 else pts_arr
        v = np.column_stack([ring, np.zeros(len(ring))])
        res["area"] = G.polygon_area(v)
    return res


def bowditch(points: np.ndarray, courses_len: list[float]) -> np.ndarray:
    """Compass-rule adjustment of a closed traverse (returns adjusted points, same shape)."""
    pts = np.asarray(points, float)
    mis = pts[-1] - pts[0]
    cum = np.concatenate([[0.0], np.cumsum(courses_len)])
    total = cum[-1]
    adj = pts - np.outer(cum / total, mis) if total > 0 else pts.copy()
    return adj
