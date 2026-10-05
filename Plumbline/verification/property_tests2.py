"""Round 2: deeper behavioural tests on Plumbline, with corrected expectations."""
import math
import os
import sys
from pathlib import Path
import tempfile

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root (import plumbline.*)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from plumbline.core.project import Project
from plumbline.core import units as U
from plumbline.core.crs import ProjectCRS, resolve_crs, make_transform
from plumbline.core.model import NAN, Polyline, TextEntity, ImportBatch, Surface, SurveyPoint
from plumbline.core.featurecodes import parse_description, build_linework, default_codes
from plumbline.core.surface import build_tin, TIN, volume_between, contour_levels, is_index_level

FAIL = []
NOTE = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + ("" if cond else f"    <-- {detail}"))
    if not cond:
        FAIL.append(f"{name}  ({detail})")


# ============================================================ reproject, done right
print("\n=== A. Project.reproject between units (realistic TX NC point) ===")
p = Project("RP", ProjectCRS.from_epsg(2276))       # ftUS
# a real point inside the zone, expressed in ftUS
x_ft, y_ft = 2429371.50, 6977276.03   # real TX NC location (lon -97, lat 32.8)
pt = p.add_point(x_ft, y_ft, 500.0, "1")
p.add_text(x_ft, y_ft, "x", 2.0)
p.settings["contour_interval"] = 1.0
p.reproject(ProjectCRS.from_epsg(32138))            # same zone, metres (32138 = TX NC in m)
print(f"    x: {x_ft:,.2f} ftUS -> {pt.x:,.4f} m      (expected {x_ft * U.M_PER_UNIT['ftUS']:,.4f})")
print(f"    z: 500 ftUS -> {pt.z:.6f} m            (expected {500 * U.M_PER_UNIT['ftUS']:.6f})")
check("horizontal unit converted", abs(pt.x - x_ft * U.M_PER_UNIT["ftUS"]) < 1e-3)
check("vertical unit converted", abs(pt.z - 500 * U.M_PER_UNIT["ftUS"]) < 1e-9)
check("crs unit reported as m", p.crs.unit == "m", p.crs.unit)
check("vunit follows", p.v_unit == "m", p.v_unit)
check("text height scaled", abs(next(e for e in p.entities.values() if isinstance(e, TextEntity)).height - 2.0 * U.M_PER_UNIT["ftUS"]) < 1e-9)
check("contour interval scaled", abs(p.settings["contour_interval"] - U.M_PER_UNIT["ftUS"]) < 1e-9,
      str(p.settings["contour_interval"]))
# and back
p.reproject(ProjectCRS.from_epsg(2276))
check("round trip x", abs(pt.x - x_ft) < 1e-3, f"{pt.x}")
check("round trip z", abs(pt.z - 500.0) < 1e-9, f"{pt.z}")
check("contour interval round trips", abs(p.settings["contour_interval"] - 1.0) < 1e-9,
      str(p.settings["contour_interval"]))

# ============================================================ local CRS safety
print("\n=== B. local-coordinate safety rails ===")
loc = Project("Local", ProjectCRS.local("ftUS"))
check("local project reports is_local", loc.crs.is_local)
loc.add_point(0, 0, 0, "1")
try:
    loc.reproject(ProjectCRS.from_epsg(2276))
    check("local -> geodetic raises", False, "no exception raised")
except Exception as e:
    check("local -> geodetic raises LocalCRSError", type(e).__name__ == "LocalCRSError", f"{type(e).__name__}: {e}")
try:
    loc.crs.to_lonlat(0, 0)
    check("to_lonlat on local raises", False, "no exception")
except Exception as e:
    check("to_lonlat on local raises", type(e).__name__ == "LocalCRSError", str(e))

# ============================================================ feature code parsing
print("\n=== C. feature-code parsing ===")
cases = [
    ("EP", ("EP", "", frozenset())),
    ("EP1", ("EP", "1", frozenset())),
    ("EP 1", ("EP", "1", frozenset())),
    ("EP B", ("EP", "", frozenset({"B"}))),
    ("EP CLS", ("EP", "", frozenset({"CLS"}))),
    ("TREE 18 OAK", ("TREE", "18", frozenset())),
    ("GS", ("GS", "", frozenset())),
    ("EP-1", ("EP", "1", frozenset())),
    ("EP E", ("EP", "", frozenset({"E"}))),
    ("", ("", "", frozenset())),
]
for desc, (code, string, flags) in cases:
    pd = parse_description(desc)
    ok = pd.code == code and pd.string == string and pd.flags == flags
    check(f"parse {desc!r} -> ({code!r},{string!r},{sorted(flags)})", ok,
          f"got ({pd.code!r},{pd.string!r},{sorted(pd.flags)})")

# linework building
print("\n=== D. linework assembly ===")
pr = Project("LW")
tbl = default_codes()
seq = [("EP B", 0, 0), ("EP", 10, 0), ("EP E", 20, 0),
       ("EP B", 0, 50), ("EP", 10, 50), ("EP E", 20, 50),
       ("BLDG B", 0, 100), ("BLDG", 10, 100), ("BLDG", 10, 110), ("BLDG CLS", 0, 110)]
for desc, x, y in seq:
    pr.add_point(x, y, 0.0, None, desc)
res = pr.process_linework()
lws = [e for e in pr.entities.values() if e.derived == "linework"]
print(f"    {res}  -> {len(lws)} strings")
check("two EP strings + one polygon", res["strings"] == 3, str(res))
poly = [e for e in lws if e.attrs.get("code") == "BLDG"]
check("BLDG string is closed", len(poly) == 1 and poly[0].closed, str([(e.attrs.get('code'), e.closed) for e in lws]))
ep = [e for e in lws if e.attrs.get("code") == "EP"]
check("EP strings are open with 3 points", all(len(e.verts) == 3 and not e.closed for e in ep),
      str([(len(e.verts), e.closed) for e in ep]))
check("EP is a breakline", all(e.kind == "breakline" for e in ep), str([e.kind for e in ep]))
# re-running replaces rather than duplicates
pr.process_linework()
lws2 = [e for e in pr.entities.values() if e.derived == "linework"]
check("re-running linework does not duplicate", len(lws2) == len(lws), f"{len(lws2)} vs {len(lws)}")

# ============================================================ duplicate handling
print("\n=== E. import duplicate policies ===")
for policy, expect_n, expect_key in (("renumber", 3, "renumbered"), ("skip", 2, "skipped"),
                                     ("overwrite", 2, "overwritten"), ("keep", 3, None)):
    prj = Project("Dup")
    prj.add_point(0, 0, 0, "1", "GS")
    prj.add_point(1, 1, 1, "2", "GS")
    b = ImportBatch()
    b.points.append(SurveyPoint(0, "1", 99, 99, 9, "NEW"))
    st = prj.apply_batch(b, dup_policy=policy)
    n_ok = len(prj.points) == expect_n
    extra = (st.get(expect_key, 0) >= 1) if expect_key else True
    check(f"dup_policy={policy} -> {expect_n} points", n_ok and extra, f"n={len(prj.points)} st={st}")
    if policy == "overwrite":
        got = prj.point_by_number("1")
        check("overwrite replaced coords", abs(got.x - 99) < 1e-9 and got.desc == "NEW", f"{got.x},{got.desc}")
    if policy == "renumber":
        check("renumber kept original number in attrs",
              any(p.attrs.get("orig_number") == "1" for p in prj.points.values()),
              str([p.attrs for p in prj.points.values()]))

# ============================================================ contour helpers
print("\n=== F. contour level helpers ===")
check("contour_levels basic", contour_levels(0.0, 10.0, 1.0) == [0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0],
      str(contour_levels(0.0, 10.0, 1.0)))
check("contour_levels with base", contour_levels(0.2, 2.2, 1.0, 0.5) == [0.5, 1.5], str(contour_levels(0.2, 2.2, 1.0, 0.5)))
check("contour_levels with base, wider window", contour_levels(0.2, 3.2, 1.0, 0.5) == [0.5, 1.5, 2.5], str(contour_levels(0.2, 3.2, 1.0, 0.5)))
check("contour_levels negative range", contour_levels(-3.5, -0.5, 1.0) == [-3.0, -2.0, -1.0], str(contour_levels(-3.5, -0.5, 1.0)))
check("contour_levels interval 0 -> []", contour_levels(0, 10, 0) == [])
check("contour_levels tiny interval count", len(contour_levels(0, 1, 0.05)) == 21, str(len(contour_levels(0, 1, 0.05))))
# index levels with a base that is not a multiple of the interval
check("index with base 0.5 interval 2 every 5", is_index_level(10.5, 2.0, 5, 0.5) and not is_index_level(8.5, 2.0, 5, 0.5),
      f"{is_index_level(10.5, 2.0, 5, 0.5)}, {is_index_level(8.5, 2.0, 5, 0.5)}")

# ============================================================ contour labels
print("\n=== G. contour label placement ===")
from plumbline.core.surface import _place_labels
prj = Project("Lab")
ring = np.column_stack([100 * np.cos(np.linspace(0, 2 * np.pi, 80, endpoint=False)),
                        100 * np.sin(np.linspace(0, 2 * np.pi, 80, endpoint=False)),
                        np.full(80, 5.0)])
n = _place_labels(prj, ring, True, 5.0, 2.0, "contours:Site")
print(f"    labels placed on a 628-long loop with text height 2.0: {n}")
check("labels placed", n >= 1, str(n))
labels = [e for e in prj.entities.values() if isinstance(e, TextEntity)]
check("all labels lie on the contour", all(abs(math.hypot(e.x, e.y) - 100) < 0.5 for e in labels),
      str([round(math.hypot(e.x, e.y), 2) for e in labels[:5]]))
check("labels tagged with the surface", all(e.derived == "contours:Site" for e in labels))
check("labels carry the elevation attr", all(e.attrs.get("elevation") == 5.0 for e in labels))
check("label text is 5", all(e.text == "5" for e in labels))
# short contour gets no label
prj2 = Project("Lab2")
n2 = _place_labels(prj2, np.array([[0, 0, 1], [1, 0, 1]]), False, 1.0, 2.0, "t")
check("short contour gets no label", n2 == 0, str(n2))

# ============================================================ TIN breaklines
print("\n=== H. TIN honours breaklines ===")
rng = np.random.default_rng(3)
gx, gy = np.meshgrid(np.linspace(0, 100, 22), np.linspace(0, 100, 22))
base = 10 + 0.0 * gx
pts = np.column_stack([gx.ravel(), gy.ravel(), base.ravel()])
# a ridge breakline across the middle, 2 units higher than the surrounding ground
bl = np.column_stack([np.linspace(0, 100, 60), np.full(60, 50.0), np.full(60, 12.0)])
tin, rep = build_tin(pts, [bl])
print(f"    report: added={rep.n_added} unenforced={rep.n_unenforced} tris={rep.n_triangles} warnings={rep.warnings}")
check("breakline fully enforced", rep.n_unenforced == 0, str(rep.n_unenforced))
# sample either side of the ridge - a linear interpolation across the ridge would halve the step
z_below = float(tin.z_at(50.0, 49.0))
z_above = float(tin.z_at(50.0, 51.0))
z_on = float(tin.z_at(50.0, 50.0))
print(f"    z just south={z_below:.4f}  on ridge={z_on:.4f}  just north={z_above:.4f}  (ridge z=12, ground 10)")
check("ridge elevation honoured at the breakline", abs(z_on - 12.0) < 1e-6, f"{z_on}")
check("surface ramps linearly from the ridge (not flattened to ground)",
      abs(z_below - z_above) < 1e-9 and 11.0 < z_below <= 12.0, f"{z_below},{z_above}")

# ============================================================ imagery check stats
print("\n=== I. imagery check statistics (NSSDA) ===")
from plumbline.core.imagery import compute_check_stats, fit_similarity
rng = np.random.default_rng(11)
n = 30
true_dx, true_dy = 3.5, -1.2
dx = true_dx + rng.normal(0, 0.4, n)
dy = true_dy + rng.normal(0, 0.4, n)
s = compute_check_stats(dx, dy, tol=5.0)
print(f"    mean dx={s.mean_dx:.3f} dy={s.mean_dy:.3f}  rmse_r={s.rmse_r:.3f}  nssda95={s.nssda_95:.3f}"
      f"  suggested nudge=({s.shift_dx:.3f},{s.shift_dy:.3f})")
check("suggested nudge cancels the true offset", abs(s.shift_dx + true_dx) < 0.3 and abs(s.shift_dy + true_dy) < 0.3,
      f"{s.shift_dx:.3f},{s.shift_dy:.3f} vs {-true_dx},{-true_dy}")
ratio_nssda = min(s.rmse_x, s.rmse_y) / max(s.rmse_x, s.rmse_y)
if ratio_nssda >= 0.6:
    check("nssda95 uses 2.4477*0.5*(rmsex+rmsey)", abs(s.nssda_95 - 2.4477 * 0.5 * (s.rmse_x + s.rmse_y)) < 1e-9)
else:
    check("nssda95 falls back to 1.7308*rmse_r when the axes differ",
          abs(s.nssda_95 - 1.7308 * s.rmse_r) < 1e-9 and "approximate" in s.nssda_note)
check("shift_dx == -mean_dx", abs(s.shift_dx + s.mean_dx) < 1e-12)
# one bad outlier must show up in the max but not wreck the mean
dx2 = np.append(dx, 40.0)
dy2 = np.append(dy, 40.0)
s2 = compute_check_stats(dx2, dy2, tol=5.0)
check("outlier shows in max_d", s2.max_d > 50, f"{s2.max_d}")
check("outlier pulls the mean", s2.mean_d > s.mean_d, f"{s2.mean_d} vs {s.mean_d}")
check("n_within_tol counts only in-tolerance picks", s2.n_within_tol <= n, str(s2.n_within_tol))

# fit_similarity sanity: rotate+scale+translate a known set
src = rng.normal(0, 10, (25, 2))
ang = math.radians(37.0)
R = np.array([[math.cos(ang), -math.sin(ang)], [math.sin(ang), math.cos(ang)]])
dst = (2.5 * (R @ src.T)).T + np.array([100.0, -50.0])
sc, rot, t, rmse = fit_similarity(src, dst)
print(f"    fit: scale={sc:.6f} (2.5)  rot={math.degrees(rot):.6f} deg (37)  rmse={rmse:.2e}")
check("similarity fit recovers scale", abs(sc - 2.5) < 1e-9, f"{sc}")
check("similarity fit recovers rotation", abs(math.degrees(rot) - 37.0) < 1e-9, f"{math.degrees(rot)}")
check("similarity fit rmse ~ 0", rmse < 1e-9, f"{rmse}")

# ============================================================ QA checks
print("\n=== J. survey data-quality check ===")
from plumbline.core import qa
prj = Project("QA", ProjectCRS.from_epsg(2276))
# build a tidy grid with one planted elevation bust
xs, ys = np.meshgrid(np.arange(0, 500, 25.0), np.arange(0, 500, 25.0))
for i, (x, y) in enumerate(zip(xs.ravel(), ys.ravel())):
    prj.add_point(2100000 + x, 11200000 + y, 500.0, str(i + 1), "GS")
bust = prj.point_by_number("186")
bust.z = 504.9
issues = qa.run_checks(prj) if hasattr(qa, "run_checks") else None
print(f"    qa module functions: {[f for f in dir(qa) if not f.startswith('_')]}")
if issues is not None:
    print(f"    issues found: {len(issues)}")
    found = any("186" in str(i) for i in issues)
    check("planted bust on point 186 is found", found, str(issues[:3]))
else:
    NOTE.append("qa.run_checks is not the entry point - inspect manually")

print("\n" + "=" * 70)
print(("FAILURES: " + str(len(FAIL))) if FAIL else "ALL CHECKS PASSED")
for f in FAIL:
    print("  -", f)
for nn in NOTE:
    print("  *", nn)
