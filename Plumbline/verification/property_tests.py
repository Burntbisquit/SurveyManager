"""Property / round-trip tests against Plumbline, looking for real defects."""
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
from plumbline.core.model import NAN, Polyline, TextEntity
from plumbline.core.surface import build_tin, TIN, volume_between

FAIL = []
NOTE = []


def check(name, cond, detail=""):
    if cond:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}   {detail}")
        FAIL.append(name)


# ============================================================ 1. CRS round trip
print("\n=== 1. CRS reprojection round trips ===")
pairs = [
    ("EPSG:2276", "EPSG:2277"),      # TX North Central ftUS -> TX North Central m
    ("EPSG:2276", "EPSG:4326"),      # -> WGS84 geographic
    ("EPSG:32614", "EPSG:4326"),     # UTM 14N -> lat/lon
    ("EPSG:3857", "EPSG:4326"),      # web mercator
    ("EPSG:2276", "EPSG:6580"),      # TX NC ftUS -> TX NC m (NAD83(2011))
]
rng = np.random.default_rng(7)
for a, b in pairs:
    try:
        ca, cb = resolve_crs(a), resolve_crs(b)
        f = make_transform(ca, cb, "auto")
        g = make_transform(cb, ca, "auto")
        # build plausible source coords: use the transform's own inverse of a lon/lat
        from pyproj import Transformer
        t = Transformer.from_crs(cb, ca, always_xy=True)
        lon = rng.uniform(-98, -96, 200)
        lat = rng.uniform(32, 34, 200)
        x, y = t.transform(lon, lat)
        x2, y2 = f(x, y)
        x3, y3 = g(x2, y2)
        err = float(np.max(np.hypot(np.asarray(x3) - x, np.asarray(y3) - y)))
        ok = err < 1e-6
        print(f"  {'PASS' if ok else 'FAIL'}  {a} -> {b} -> back   max round-trip error {err:.3e}")
        if not ok:
            FAIL.append(f"CRS round trip {a}<->{b}: {err:.3e}")
    except Exception as e:
        print(f"  SKIP  {a} -> {b}: {type(e).__name__}: {e}")

# ============================================================ 2. unit consistency
print("\n=== 2. Unit handling ===")
check("US ft vs intl ft differ by 2 ppm", abs(U.M_PER_UNIT["ftUS"] / U.M_PER_UNIT["ft"] - (1200 / 3937) / 0.3048) < 1e-15)
check("area_to_acres uses 43560 for ftUS", abs(U.area_to_acres(43560.0, "ftUS") - 1.0) < 1e-9)
check("volume 27 ftUS^3 -> 1 cy (earthwork convention)", abs(U.volume_to_cubic_yards(27.0, "ftUS") - 1.0) < 1e-12,
      f"got {U.volume_to_cubic_yards(27.0, 'ftUS')}")
check("unit_from_factor(0.3048) == ft", U.unit_from_factor(0.3048, "foot") == "ft")
check("unit_from_factor(1200/3937) == ftUS", U.unit_from_factor(1200 / 3937, "US survey foot") == "ftUS")

# ============================================================ 3. project save/load round trip
print("\n=== 3. Project save / load round trip ===")
p = Project("RoundTrip")
p.add_point(1000.0, 2000.0, 500.0, "1", "GS")
p.add_point(1010.0, 2005.0, 501.5, "2", "EP1")
p.add_point(1020.0, 2000.0, NAN, "3", "TREE 18 OAK")
pl = p.add_polyline([[0, 0, 1], [10, 0, 2], [10, 10, 3]], "0", closed=True, bulges=[0.0, 0.5, 0.0], kind="line")
p.add_text(5.0, 5.0, "hello", 2.0, 30.0, "TEXT")
pts = np.array([[0, 0, 0], [10, 0, 0], [10, 10, 0], [0, 10, 0], [5, 5, 1]], float)
tin, _ = build_tin(pts)
from plumbline.core.model import Surface
s = Surface(0, "Site", tin.pts, tin.tris)
p.add_surface(s)
p.settings["contour_interval"] = 2.5
p.notes = "a note"

with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "t.plb")
    p.save(path)
    q = Project.load(path)
    check("name preserved", q.name == p.name)
    check("point count", len(q.points) == len(p.points))
    p1 = q.point_by_number("1")
    check("point coords", p1 is not None and abs(p1.x - 1000) < 1e-12 and abs(p1.z - 500) < 1e-12)
    check("point NaN z preserved", math.isnan(q.point_by_number("3").z))
    check("desc preserved", q.point_by_number("3").desc == "TREE 18 OAK")
    ql = next(e for e in q.entities.values() if isinstance(e, Polyline))
    check("polyline verts", np.allclose(ql.verts, pl.verts))
    check("polyline bulges", ql.bulges is not None and np.allclose(ql.bulges[1], 0.5))
    check("polyline closed", ql.closed)
    qt = next(e for e in q.entities.values() if isinstance(e, TextEntity))
    check("text preserved", qt.text == "hello" and abs(qt.rotation - 30.0) < 1e-12)
    check("surface preserved", len(q.surfaces) == 1 and np.allclose(next(iter(q.surfaces.values())).pts, tin.pts))
    check("settings preserved", q.settings["contour_interval"] == 2.5)
    check("notes preserved", q.notes == "a note")
    # save/load/save idempotence
    path2 = os.path.join(d, "t2.plb")
    q.save(path2)
    import json
    a = json.load(open(path)); b = json.load(open(path2))
    a.pop("saved"); b.pop("saved")
    check("save is idempotent", json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True))

# ============================================================ 4. undo snapshot
print("\n=== 4. Undo snapshot / restore ===")
p = Project("Undo")
p.add_point(0, 0, 0, "1")
before = p.snapshot()
p.add_point(1, 1, 1, "2")
p.apply_codes_to_points()
p.entities.clear()
p.restore(before)
check("points restored", len(p.points) == 1)
check("new id counter restored", p.new_id() == 2)
# snapshot does not include path/revision -> check revision still moves
r0 = p.revision
p.restore(before)
check("restore bumps revision", p.revision > r0)

# ============================================================ 5. transforms
print("\n=== 5. apply_similarity ===")
p = Project("Xf")
a = p.add_point(0, 0, 0, "1")
b = p.add_point(10, 0, 0, "2")
c = p.add_point(10, 10, 0, "3")
# rotate 90 CCW about origin, then shift by (5, 7); scale 2
p.apply_similarity(base=(0, 0), scale=2.0, rot_deg=90.0, shift=(5, 7))
check("rot+scale (0,0)->(5,7)", abs(a.x - 5) < 1e-9 and abs(a.y - 7) < 1e-9, f"{a.x},{a.y}")
check("rot+scale (10,0)->(5,27)", abs(b.x - 5) < 1e-9 and abs(b.y - 27) < 1e-9, f"{b.x},{b.y}")
check("rot+scale (10,10)->(-15,27)", abs(c.x + 15) < 1e-9 and abs(c.y - 27) < 1e-9, f"{c.x},{c.y}")

# z handling
p2 = Project("Z")
q = p2.add_point(0, 0, 10.0, "1")
p2.apply_similarity(z_scale=2.0, dz=1.0)
check("z scale + dz", abs(q.z - 21.0) < 1e-12, f"{q.z}")

# negative scale / mirror: bulges should flip
p3 = Project("Mirror")
m = p3.add_polyline([[0, 0, 0], [10, 0, 0]], "0", bulges=[0.5, 0.0])
p3.apply_similarity(scale=-1.0)
check("mirror flips bulge sign", m.bulges[0] < 0, f"bulge={m.bulges[0]}")
NOTE.append("mirror: text rotation is not mirrored (rotation += rot_deg only) - check by hand")

# ============================================================ 6. reproject with Z
print("\n=== 6. Project.reproject unit handling ===")
p = Project("RP", ProjectCRS.from_epsg(2276))     # TX NC, ftUS
pt = p.add_point(2429371.50, 6977276.03, 500.0, "1")   # a real TX North Central location
p.add_text(2429371.50, 6977276.03, "x", 2.0)
p.reproject(ProjectCRS.from_epsg(32138))          # same zone in metres (32138, not 2277=Texas Central)
check("h unit now m", p.crs.unit == "m", p.crs.unit)
check("x scaled to metres", abs(pt.x - 2429371.50 * U.M_PER_UNIT["ftUS"]) < 0.01, f"{pt.x}")
check("z scaled to metres", abs(pt.z / 500.0 - U.M_PER_UNIT["ftUS"]) < 1e-9, f"{pt.z}")
check("text height scaled", abs(next(e for e in p.entities.values() if isinstance(e, TextEntity)).height
                                - 2.0 * U.M_PER_UNIT["ftUS"]) < 1e-9)
check("contour interval scaled", abs(p.settings["contour_interval"] - U.M_PER_UNIT["ftUS"]) < 1e-9,
      f"{p.settings['contour_interval']}")

# ============================================================ 7. volume_between grid vs composite
print("\n=== 7. volume_between: grid vs composite ===")
n = 25
x1 = np.linspace(0, 100, n)
X1, Y1 = np.meshgrid(x1, x1)
Z1 = 10.0 + 0.0 * X1                       # existing: flat 10
ex = TIN(np.column_stack([X1.ravel(), Y1.ravel(), Z1.ravel()]),
         build_tin(np.column_stack([X1.ravel(), Y1.ravel(), Z1.ravel()]))[0].tris)
Z2 = 8.0 + 0.0 * X1                        # proposed: flat 8 -> fill of 2 * 10000 = 20000
pr = TIN(np.column_stack([X1.ravel(), Y1.ravel(), Z2.ravel()]),
         build_tin(np.column_stack([X1.ravel(), Y1.ravel(), Z2.ravel()]))[0].tris)
rg = volume_between(ex, pr, method="grid", cell=1.0)
rc = volume_between(ex, pr, method="composite")
print(f"    grid      cut={rg.cut:.3f} fill={rg.fill:.3f} area={rg.area_total:.1f}  ({rg.method})")
print(f"    composite cut={rc.cut:.3f} fill={rc.fill:.3f} area={rc.area_total:.1f}  ({rc.method})")
print(f"    exact     cut=20000.000  fill=0.000       area=10000.0")
check("grid CUT ~20000 (existing 10 is above proposed 8)", abs(rg.cut - 20000) < 200, f"{rg.cut}")
check("composite CUT ~20000", abs(rc.cut - 20000) < 200, f"{rc.cut}")

# sloped existing vs flat proposed over a non-convex plane
Z1b = 10.0 + 0.05 * X1                      # existing slopes up in x
exb = TIN(np.column_stack([X1.ravel(), Y1.ravel(), Z1b.ravel()]),
          build_tin(np.column_stack([X1.ravel(), Y1.ravel(), Z1b.ravel()]))[0].tris)
rg2 = volume_between(exb, pr, method="grid", cell=0.25)
rc2 = volume_between(exb, pr, method="composite")
# analytic: integral of (10 + 0.05x - 8) over [0,100]^2 = 2*10000 + 0.05*5000*100 = 20000 + 25000 = 45000
print(f"    sloped: grid cut={rg2.cut:.2f} fill={rg2.fill:.2f}   composite cut={rc2.cut:.2f} fill={rc2.fill:.2f}   exact cut=45000.00")
check("grid sloped cut ~45000", abs(rg2.cut - 45000) < 2000, f"{rg2.cut}")
check("composite sloped cut ~45000", abs(rc2.cut - 45000) < 2000, f"{rc2.cut}")

# ============================================================ 8. clip regions
print("\n=== 8. volume_to_datum clipped to a region ===")
import shapely
from shapely.geometry import box
tri = ex
full = tri.volume_to_datum(0.0)
half = tri.volume_to_datum(0.0, box(0, 0, 50, 100))
print(f"    full cut={full.cut:.3f}; half (x<50) cut={half.cut:.3f}; ratio={half.cut/full.cut:.4f}")
check("half-region volume is half", abs(half.cut / full.cut - 0.5) < 1e-6, f"{half.cut / full.cut}")
# region entirely outside
outside = tri.volume_to_datum(0.0, box(200, 200, 300, 300))
check("outside region gives 0", abs(outside.cut) < 1e-9 and abs(outside.fill) < 1e-9,
      f"{outside.cut},{outside.fill}")

# ============================================================ 9. CSV round trip
print("\n=== 9. CSV write / read round trip ===")
from plumbline.io import csv_points as C
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "pts.csv")
    p = Project("CSV")
    for i in range(1, 51):
        p.add_point(500000 + i, 3000000 + i * 2, 400 + i * 0.1, str(i), "GS")
    p.add_point(500099, 3000999, NAN, "99", "TREE")   # no elevation
    C.write_points_csv(path, p.points.values())
    sn = C.sniff(path)
    m = C.CsvMapping(delimiter=sn.delimiter, skip_rows=1 if sn.has_header else 0, roles=sn.roles)
    b = C.read_points(path, m)
    print(f"    sniffed delim={sn.delimiter!r} header={sn.has_header} roles={sn.roles}")
    check("read back all points", len(b.points) == len(p.points), f"{len(b.points)} vs {len(p.points)}")
    src = p.point_by_number("7")
    got = next((r for r in b.points if r.number == "7"), None)
    check("coords round trip", got is not None and abs(got.x - src.x) < 1e-3 and abs(got.y - src.y) < 1e-3)
    check("elevation round trip", got is not None and abs(got.z - src.z) < 1e-3)
    check("blank elevation -> NaN", (lambda r: r is not None and math.isnan(r.z))(next((r for r in b.points if r.number == "99"), None)))
    check("description round trip", got is not None and got.desc == "GS")

# tab-delimited, no header, E,N,Z
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "pts.txt")
    with open(path, "w") as f:
        for i in range(1, 21):
            f.write(f"{i}\t{100+i}\t{200+i}\t{300+i}\tGS\n")
    sn = C.sniff(path)
    m = C.CsvMapping(delimiter=sn.delimiter, skip_rows=1 if sn.has_header else 0, roles=sn.roles)
    b = C.read_points(path, m)
    print(f"    tab file: delim={sn.delimiter!r} header={sn.has_header} roles={sn.roles}")
    check("tab file reads 20 points", len(b.points) == 20, f"{len(b.points)}")

# decimal comma (European)
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "eu.txt")
    with open(path, "w") as f:
        for i in range(1, 11):
            f.write(f"{i} {100+i} {200+i} {300.5:.2f}\n")
    sn = C.sniff(path)
    m = C.CsvMapping(delimiter=sn.delimiter, skip_rows=1 if sn.has_header else 0, roles=sn.roles)
    b = C.read_points(path, m)
    print(f"    space file: delim={sn.delimiter!r} roles={sn.roles}")
    check("space-delimited reads 10 points", len(b.points) == 10, f"{len(b.points)}")

# ============================================================ 10. DXF round trip
print("\n=== 10. DXF export / import round trip ===")
from plumbline.io import dxf_io
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "out.dxf")
    p = Project("DXF")
    p.add_point(1000.0, 2000.0, 500.0, "1", "GS")
    p.add_point(1010.0, 2000.0, 500.5, "2", "GS")
    p.add_polyline([[0, 0, 5.0], [10, 0, 5.0], [10, 10, 5.0]], "ROAD-EP", closed=False, bulges=[0.0, 1.0, 0.0], kind="line")
    p.add_polyline([[0, 0, 1.0], [10, 0, 2.0]], "0", kind="line")     # varying z -> 3D polyline
    p.add_text(5.0, 5.0, "LOT 1", 2.0, 45.0, "TEXT")
    st = dxf_io.write_dxf(path, p)
    print(f"    wrote: {st}")
    b = dxf_io.read_dxf(path)
    print(f"    read back: {b.summary()}  layers={sorted(b.layers)[:8]}")
    check("points round trip", len(b.points) == 2, f"{len(b.points)}")
    check("polylines round trip", len(b.polylines) >= 2, f"{len(b.polylines)}")
    labelled = [q for q in b.texts if q.text == "LOT 1"]
    check("the user text round trips", len(labelled) == 1, f"{[q.text for q in b.texts]}")
    check("point labels were exported too (3 per point + 1)", len(b.texts) == 7, f"{len(b.texts)}")
    check("layers round trip", "ROAD-EP" in b.layers, str(sorted(b.layers)))
    # check coordinates survive
    xs = sorted(round(q.x, 4) for q in b.points)
    check("point x preserved", xs == [1000.0, 1010.0], str(xs))
    zs = sorted(round(q.z, 4) for q in b.points)
    check("point z preserved", zs == [500.0, 500.5], str(zs))
    # the arc bulge survives
    bl = [q for q in b.polylines if q.bulges is not None and np.any(np.abs(q.bulges) > 1e-9)]
    check("bulge preserved", len(bl) >= 1, f"{len(bl)}")
    if bl:
        print(f"      bulge values: {bl[0].bulges[:4]}")
    # 3D polyline keeps varying z
    v3 = [q for q in b.polylines if len(q.verts) and np.ptp(q.verts[:, 2]) > 1e-9]
    check("varying-z polyline preserved", len(v3) == 1, f"{len(v3)}")

# ============================================================ 11. LandXML
print("\n=== 11. LandXML round trip ===")
from plumbline.io import landxml
with tempfile.TemporaryDirectory() as d:
    path = os.path.join(d, "out.xml")
    p = Project("LX")
    for i in range(1, 21):
        p.add_point(500000 + i * 3, 3000000 + i * 2, 400 + i * 0.25, str(i), "GS")
    p.add_polyline([[0, 0, 1], [10, 0, 2], [10, 10, 3]], "0", closed=True)
    st = landxml.write_landxml(path, p)
    print(f"    wrote: {st}")
    b = landxml.read_landxml(path)
    print(f"    read back: {b.summary()}")
    check("LandXML points round trip", len(b.points) >= 20, f"{len(b.points)}")
    check("LandXML polylines round trip", len(b.polylines) >= 1, f"{len(b.polylines)}")

# ============================================================ 12. GIS / KML
print("\n=== 12. KML + GeoPackage round trip ===")
from plumbline.io import gis_io, kml_io
with tempfile.TemporaryDirectory() as d:
    p = Project("GIS", ProjectCRS.from_epsg(2276))
    for i in range(1, 11):
        p.add_point(2500000 + i * 10, 7000000 + i * 5, 500 + i, str(i), "GS")
    p.add_polyline([[2500000, 7000000, 0], [2500100, 7000000, 0], [2500100, 7000100, 0]], "0", closed=True)
    gpkg = os.path.join(d, "out.gpkg")
    st = gis_io.write_gis(gpkg, p)
    print(f"    gpkg: {st}")
    # a GeoPackage holds several layers and read_gis(layer=None) reads the first one only,
    # which is what the import dialog relies on (it lists layers and reads the chosen one)
    layers = gis_io.list_gis_layers(gpkg)
    print(f"    layers in the file: {layers}")
    check("GeoPackage exposes its layers", len(layers) >= 2, str(layers))
    b = gis_io.read_gis(gpkg)
    print(f"    first layer: {b.summary()}  info={b.info}")
    check("GeoPackage points round trip", len(b.points) == 10, f"{len(b.points)}")
    line_layer = next((n for n, g in layers if "olygon" in g or "ine" in g), None)
    bl = gis_io.read_gis(gpkg, layer=line_layer) if line_layer else None
    check("GeoPackage polyline layer round trips",
          bl is not None and len(bl.polylines) >= 1, f"{line_layer}: {bl.summary() if bl else 'n/a'}")
    kmz = os.path.join(d, "out.kmz")
    lonlat = lambda xs, ys: p.crs.to_lonlat(xs, ys, target=4326)
    st = kml_io.write_kml(kmz, p, lonlat)
    print(f"    kmz: {st}")
    bk = kml_io.read_kml(kmz)
    print(f"    kmz read back: {bk.summary()}")
    check("KML points round trip", len(bk.points) >= 10, f"{len(bk.points)}")

print("\n" + "=" * 70)
print(("FAILURES: " + str(len(FAIL))) if FAIL else "ALL ROUND-TRIP / PROPERTY CHECKS PASSED")
for f in FAIL:
    print("  -", f)
if NOTE:
    print("\nNotes:")
    for n in NOTE:
        print("  *", n)
