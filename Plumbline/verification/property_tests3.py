"""Round 3: corrected expectations - verifying Plumbline's unit/quantity behaviour."""
import math
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root (import plumbline.*)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from plumbline.core.project import Project
from plumbline.core import units as U
from plumbline.core.crs import ProjectCRS
from plumbline.core.model import NAN, TextEntity
from plumbline.core.surface import build_tin, contour_levels

FAIL = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"    <-- {detail}"))
    if not cond:
        FAIL.append(f"{name} ({detail})")


print("\n=== reproject ftUS -> metres, correct EPSG pair (2276 -> 32138) ===")
x_ft, y_ft = 2429371.50, 6977276.03
p = Project("RP", ProjectCRS.from_epsg(2276))
pt = p.add_point(x_ft, y_ft, 500.0, "1")
p.add_text(x_ft, y_ft, "x", 2.0)
p.settings["contour_interval"] = 1.0
p.reproject(ProjectCRS.from_epsg(32138))
print(f"    x: {x_ft:,.2f} ftUS -> {pt.x:,.4f} m")
print(f"    z: 500 ftUS -> {pt.z:.6f} m")
print(f"    crs unit={p.crs.unit!r} vunit={p.v_unit!r} label={p.crs.label}")
check("horizontal unit converted", abs(pt.x - x_ft * U.M_PER_UNIT["ftUS"]) < 0.01, f"{pt.x}")
check("vertical unit converted", abs(pt.z - 500 * U.M_PER_UNIT["ftUS"]) < 1e-6, f"{pt.z}")
check("crs unit reports m", p.crs.unit == "m", p.crs.unit)
check("vunit follows", p.v_unit == "m", p.v_unit)
th = next(e for e in p.entities.values() if isinstance(e, TextEntity)).height
check("text height scaled", abs(th - 2.0 * U.M_PER_UNIT["ftUS"]) < 1e-9, f"{th}")
check("contour interval scaled", abs(p.settings["contour_interval"] - U.M_PER_UNIT["ftUS"]) < 1e-9,
      str(p.settings["contour_interval"]))
p.reproject(ProjectCRS.from_epsg(2276))
check("round trip x", abs(pt.x - x_ft) < 0.01, f"{pt.x}")
check("round trip z", abs(pt.z - 500.0) < 1e-9, f"{pt.z}")
check("contour interval round trips", abs(p.settings["contour_interval"] - 1.0) < 1e-9,
      str(p.settings["contour_interval"]))

print("\n=== contour_levels with a base offset ===")
check("base 0.5 interval 1 over [0.2,2.2]", contour_levels(0.2, 2.2, 1.0, 0.5) == [0.5, 1.5],
      str(contour_levels(0.2, 2.2, 1.0, 0.5)))
check("base 0.5 interval 1 over [0.2,3.2]", contour_levels(0.2, 3.2, 1.0, 0.5) == [0.5, 1.5, 2.5],
      str(contour_levels(0.2, 3.2, 1.0, 0.5)))

print("\n=== breakline: exact ridge, and the ramp either side ===")
gx, gy = np.meshgrid(np.linspace(0, 100, 22), np.linspace(0, 100, 22))
pts = np.column_stack([gx.ravel(), gy.ravel(), (10 + 0 * gx).ravel()])
bl = np.column_stack([np.linspace(0, 100, 60), np.full(60, 50.0), np.full(60, 12.0)])
tin, rep = build_tin(pts, [bl])
print(f"    added={rep.n_added} unenforced={rep.n_unenforced}")
for y in (49.99, 50.0, 50.01):
    print(f"    z_at(50, {y}) = {float(tin.z_at(50.0, y)):.6f}")
check("exact on the breakline", abs(float(tin.z_at(50.0, 50.0)) - 12.0) < 1e-9)
check("approaches the ridge from below", 11.9 < float(tin.z_at(50.0, 49.9)) <= 12.0)
check("approaches the ridge from above", 11.9 < float(tin.z_at(50.0, 50.1)) <= 12.0)
check("back to ground where the next row is", abs(float(tin.z_at(50.0, 52.38)) - 10.0) < 0.01,
      f"{float(tin.z_at(50.0, 52.38))}")
# a breakline must never be crossed by a triangle edge
T = tin.tris
P = tin.pts
bl_idx = [int(np.argmin(np.hypot(P[:, 0] - bx, P[:, 1] - 50.0))) for bx in np.linspace(0, 100, 60)]
edge_set = set()
for a, b, c in T:
    for u, v in ((a, b), (b, c), (c, a)):
        edge_set.add((min(u, v), max(u, v)))
missing = [(bl_idx[i], bl_idx[i + 1]) for i in range(len(bl_idx) - 1)
           if bl_idx[i] != bl_idx[i + 1] and (min(bl_idx[i], bl_idx[i + 1]), max(bl_idx[i], bl_idx[i + 1])) not in edge_set]
print(f"    breakline sub-segments present as TIN edges: {len(bl_idx)-1 - len(missing)}/{len(bl_idx)-1}")
check("every breakline segment is a TIN edge", not missing, f"{len(missing)} missing")

print("\n=== acre / cubic-yard conventions (consistency check) ===")
ac_ftus = U.area_to_acres(43560.0, "ftUS")
metric_acre_from_ftus = 43560.0 * U.M_PER_UNIT["ftUS"] ** 2
cy_ftus = U.volume_to_cubic_yards(27.0, "ftUS")
print(f"    43560 ftUS^2 -> {ac_ftus:.9f} acres  (by construction 1.0)")
print(f"    but 43560 ftUS^2 = {metric_acre_from_ftus:.6f} m^2 vs a true acre = 4046.856422 m^2"
      f"  -> {metric_acre_from_ftus / 4046.8564224 - 1:+.2e} relative")
print(f"    27 ftUS^3 -> {cy_ftus:.9f} cy   (27 ftUS^3 is {(27*U.M_PER_UNIT['ftUS']**3)/(0.9144**3)-1:+.2e} vs 1 yd^3)")
check("area_to_acres treats ft and ftUS identically (43560)",
      U.area_to_acres(43560.0, "ft") == U.area_to_acres(43560.0, "ftUS") == 1.0)
check("volume_to_cubic_yards NOW matches it (27 cu ft = 1 cu yd for both feet)",
      abs(U.volume_to_cubic_yards(27.0, "ft") - 1.0) < 1e-12 and abs(U.volume_to_cubic_yards(27.0, "ftUS") - 1.0) < 1e-12,
      f"{U.volume_to_cubic_yards(27.0,'ft'):.12f}, {U.volume_to_cubic_yards(27.0,'ftUS'):.12f}")
check("area and volume now use one convention",
      abs(U.volume_to_cubic_yards(1.0, "m") - 1.0 / 0.9144 ** 3) < 1e-12)

print("\n" + "=" * 70)
print(("FAILURES: " + str(len(FAIL))) if FAIL else "ALL CHECKS PASSED")
for f in FAIL:
    print("  -", f)
