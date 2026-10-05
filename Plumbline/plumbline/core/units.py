"""Linear-unit helpers.

US survey feet and international feet differ by 2 ppm.  That is invisible on a
small site but matters on State Plane coordinates, so they are distinct units.
"""
from __future__ import annotations

M_PER_UNIT = {
    "m": 1.0,
    "ft": 0.3048,
    "ftUS": 1200.0 / 3937.0,
    "in": 0.0254,
    "yd": 0.9144,
    "km": 1000.0,
    "mi": 1609.344,
}

LABEL = {"m": "m", "ft": "ft", "ftUS": "US ft", "in": "in", "yd": "yd", "km": "km", "mi": "mi"}
LINEAR_CHOICES = ["ftUS", "ft", "m"]


def factor_to_m(unit: str) -> float:
    return M_PER_UNIT[unit]


def unit_from_factor(factor: float | None, name: str = "") -> str:
    """Map a pyproj unit (factor to metres and/or name) to one of our unit codes."""
    if factor:
        for code, f in M_PER_UNIT.items():
            if abs(factor - f) < 1e-9:
                return code
    n = (name or "").lower()
    if "us survey" in n or "survey foot" in n or "survey feet" in n:
        return "ftUS"
    if "foot" in n or "feet" in n:
        return "ft"
    if "metre" in n or "meter" in n:
        return "m"
    return "m"


def convert(value, from_unit: str, to_unit: str):
    return value * (M_PER_UNIT[from_unit] / M_PER_UNIT[to_unit])


def is_foot(unit: str) -> bool:
    return unit in ("ft", "ftUS")


# Land-measure and earthwork quantities in the US use the *conventional* definitions
# (43,560 sq ft = 1 acre, 27 cu ft = 1 cu yd), not the metric-exact ones.  A foot-based job
# must agree with an estimator doing `feet / 27`, so both conversions below follow the
# convention for foot units and convert exactly for metric.  The two agree to ~6 ppm for
# US survey feet, so this is a consistency choice, not an accuracy one - but mixing the two
# conventions (as this module used to) makes areas and volumes disagree with each other.
SQ_FT_PER_ACRE = 43560.0
CU_FT_PER_CU_YD = 27.0
CU_M_PER_CU_YD = 0.9144 ** 3


def area_to_acres(area: float, unit: str) -> float:
    """Area in unit^2 -> acres (43,560 sq ft for foot units, as surveyors use)."""
    if is_foot(unit):
        return area / SQ_FT_PER_ACRE
    return area * M_PER_UNIT[unit] ** 2 / 4046.8564224


def area_to_hectares(area: float, unit: str) -> float:
    return area * M_PER_UNIT[unit] ** 2 / 10000.0


def volume_to_cubic_yards(vol: float, h_unit: str, v_unit: str | None = None) -> float:
    """Volume (h_unit^2 * v_unit) -> cubic yards.

    For foot units this is the earthwork convention `vol / 27` (so 27 cu ft = 1 cu yd
    whatever kind of foot you measure in), matching how `area_to_acres` is defined.
    For metric areas it converts exactly (1 cu yd = 0.9144^3 m^3).
    """
    v_unit = v_unit or h_unit
    if is_foot(h_unit) and is_foot(v_unit):
        return vol / CU_FT_PER_CU_YD
    return volume_to_cubic_meters(vol, h_unit, v_unit) / CU_M_PER_CU_YD


def volume_to_cubic_feet(vol: float, h_unit: str, v_unit: str | None = None) -> float:
    """Volume (h_unit^2 * v_unit) -> cubic feet."""
    v_unit = v_unit or h_unit
    return vol * (M_PER_UNIT[h_unit] ** 2 * M_PER_UNIT[v_unit]) / (0.3048 ** 3)


def volume_to_cubic_meters(vol: float, h_unit: str, v_unit: str | None = None) -> float:
    v_unit = v_unit or h_unit
    return vol * M_PER_UNIT[h_unit] ** 2 * M_PER_UNIT[v_unit]


def fmt_len(value: float, unit: str, decimals: int = 3) -> str:
    return f"{value:,.{decimals}f} {LABEL.get(unit, unit)}"
