"""Independent numerical validation of Plumbline's surface math.

Checks _split_volumes (the exact cut/fill integrator) against Monte-Carlo integration,
and contour evaluation against a known analytic plane.
"""
import sys
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # repo root (import plumbline.*)
from plumbline.core.surface import _split_volumes, TIN, build_tin, contour_levels, is_index_level

rng = np.random.default_rng(1234)
FAIL = []


# ---------------------------------------------------------------- _split_volumes
def exact_tri_area(A, B, C):
    return 0.5 * abs((B[0] - A[0]) * (C[1] - A[1]) - (C[0] - A[0]) * (B[1] - A[1]))


def volume_piecewise_linear_analytic(A, B, C, zA, zB, zC, datum):
    """Exact integral of positive/negative part of a linear function over a triangle.

    Uses a subdivide-and-triangulate approach: split the triangle by the zero line and
    integrate exactly over each piece (each piece is a polygon or triangle where the
    plane is linear).
    """
    import shapely
    from shapely.geometry import Polygon
    # barycentric linear interpolation
    M = np.array([[A[0], A[1], 1.0], [B[0], B[1], 1.0], [C[0], C[1], 1.0]])
    try:
        coef = np.linalg.solve(M, np.array([zA, zB, zC], float))
    except np.linalg.LinAlgError:
        return 0.0, 0.0, 0.0, 0.0
    a, b, c = coef  # z = a x + b y + c

    def z_at(p):
        return a * p[0] + b * p[1] + c

    tri = Polygon([A, B, C])
    if not tri.is_valid or tri.area == 0:
        return 0.0, 0.0, 0.0, 0.0
    # clip against half planes z>=datum  =>  a x + b y + (c-datum) >= 0
    import math
    from shapely.geometry import Point
    norm = math.hypot(a, b)

    def half(inside):
        # build a very large polygon on the correct side of the line
        if norm == 0:
            return tri if ((c - datum) >= 0) == inside else Polygon()
        # line: a x + b y + (c-datum) = 0 ; inside means a x + b y + (c-datum) > 0
        sign = 1.0 if inside else -1.0
        # point far along normal
        import shapely.affinity
        px = -a / norm * 1e5 * sign + ((-b / norm) * 0 + 0)
        py = -b / norm * 1e5 * sign
        # Construct half-plane polygon using a huge box and clip
        box = Polygon([(-1e6, -1e6), (1e6, -1e6), (1e6, 1e6), (-1e6, 1e6)])
        d = (a * 0 + b * 0 + c - datum)
        # translate: distance from origin scaled
        off = d / norm
        # build the half-plane as a big rectangle on the + side then move
        big = Polygon([(-1e6, 0), (1e6, 0), (1e6, 2e6), (-1e6, 2e6)])
        ang = math.atan2(b, a) - math.pi / 2  # rotate so +y axis aligns to normal
        rot = shapely.affinity.rotate(big, math.degrees(ang), origin=(0, 0), use_radians=False)
        rot = shapely.affinity.translate(rot, 0, off)
        if not inside:
            rot = shapely.affinity.scale(rot, 1, -1, origin=(0, 0))
            # careful: mirroring changes things; instead build the other side directly
        return rot

    # simpler: build both half planes as large polygons via shapely.ops.split on the line
    from shapely.geometry import LineString
    from shapely.ops import split as shp_split
    if norm > 0:
        # direction along line
        ux, uy = -b / norm, a / norm
        # point on line closest to origin
        t0 = -(c - datum) / (norm * norm)
        ox, oy = a * t0, b * t0
        L = 1e6
        line = LineString([(ox - ux * L, oy - uy * L), (ox + ux * L, oy + uy * L)])
        parts = list(shp_split(tri, line).geoms)
    else:
        parts = [tri]
    pos_area = neg_area = 0.0
    pos_vol = neg_vol = 0.0
    for pg in parts:
        if pg.is_empty or pg.area <= 1e-18:
            continue
        cen = np.array(pg.centroid.coords[0])
        # exact integral of a linear function over a polygon, done by triangulating the
        # polygon from its centroid (function is linear so this is exact)
        pts = list(pg.exterior.coords)[:-1]
        # shoelace on the fan from centroid
        for i in range(len(pts)):
            p1 = np.array(pts[i])
            p2 = np.array(pts[(i + 1) % len(pts)])
            a_tri = 0.5 * abs((p1[0] - cen[0]) * (p2[1] - cen[1]) - (p2[0] - cen[0]) * (p1[1] - cen[1]))
            z_avg = (z_at(cen) + z_at(p1) + z_at(p2)) / 3.0
            side_z = z_avg - (0 if False else 0)
            if z_at(cen) >= 0:  # relative to the datum-shifted plane
                pass
            # relative volume to datum
            v = a_tri * ((z_at(cen) - datum) + (z_at(p1) - datum) + (z_at(p2) - datum)) / 3.0
            if v >= 0:
                pos_vol += v
                pos_area += a_tri
            else:
                neg_vol += v
                neg_area += a_tri
    return pos_vol, neg_vol, pos_area, neg_area


print("=== _split_volumes vs analytic, 20000 random triangles ===")
worst = 0.0
worst_case = None
n_bad = 0
for _ in range(20000):
    A = rng.uniform(-50, 50, 2)
    B = rng.uniform(-50, 50, 2)
    C = rng.uniform(-50, 50, 2)
    area = exact_tri_area(A, B, C)
    if area < 1e-6:
        continue
    zs = rng.uniform(-10, 10, 3)
    datum = float(rng.uniform(-12, 12))
    h = np.array([zs[0] - datum, zs[1] - datum, zs[2] - datum])[None, :]
    pos, neg, apos, aneg = _split_volumes(np.array([area]), h)
    gp, gn, gap, gan = volume_piecewise_linear_analytic(A, B, C, zs[0], zs[1], zs[2], datum)
    # compare
    scale = max(abs(gp), abs(gn), 1e-9)
    err = max(abs(pos[0] - gp), abs(neg[0] - gn)) / scale
    err_area = max(abs(apos[0] - gap), abs(aneg[0] - gan)) / area
    e = max(err, err_area)
    if e > worst:
        worst = e
        worst_case = (A, B, C, zs, datum, pos[0], gp, neg[0], gn, apos[0], gap)
    if e > 1e-6:
        n_bad += 1
print(f"  worst relative error: {worst:.3e}   (cases > 1e-6: {n_bad})")
if worst > 1e-6:
    FAIL.append(f"_split_volumes worst rel err {worst:.2e}")
    print("  WORST CASE:", worst_case)


# ---------------------------------------------------------------- volume_to_datum on a plane
print("\n=== volume_to_datum on an exact inclined plane ===")
n = 40
x = np.linspace(0, 100, n)
y = np.linspace(0, 100, n)
XX, YY = np.meshgrid(x, y)
ZZ = 0.02 * XX + 0.01 * YY   # plane
pts = np.column_stack([XX.ravel(), YY.ravel(), ZZ.ravel()])
tin, rep = build_tin(pts)
# exact: integral over square of (0.02x + 0.01y - datum)
for datum in (0.0, 1.0, 2.0, 5.0):
    r = tin.volume_to_datum(datum)
    # analytic integral over the square
    import sympy as sp
    X, Y = sp.symbols("X Y")
    f = 0.02 * X + 0.01 * Y - datum
    pos = sp.integrate(sp.Max(f, 0), (X, 0, 100), (Y, 0, 100))
    neg = sp.integrate(sp.Min(f, 0), (X, 0, 100), (Y, 0, 100))
    try:
        ep, en = float(pos), float(neg)
    except Exception:
        ep = en = float("nan")
    print(f"  datum {datum:5.2f}: cut {r.cut:12.4f} (exact {ep:12.4f})  fill {r.fill:12.4f} (exact {abs(en):12.4f})"
          f"  err {abs(r.cut-ep)/max(ep,1):.2e} / {abs(r.fill-abs(en))/max(abs(en),1):.2e}")
    if abs(r.cut - ep) > 1e-6 * max(ep, 1) or abs(r.fill - abs(en)) > 1e-6 * max(abs(en), 1):
        FAIL.append(f"plane volume mismatch at datum {datum}: {r.cut} vs {ep}, {r.fill} vs {abs(en)}")


# ---------------------------------------------------------------- contours on a plane
print("\n=== contours on an exact plane (level 5.0 should be a straight line) ===")
t = np.linspace(0, 10, 30)
XX, YY = np.meshgrid(t, t)
ZZ = 0.5 * XX + 0.25 * YY          # plane; level 5 -> 0.5x+0.25y=5
pts = np.column_stack([XX.ravel(), YY.ravel(), ZZ.ravel()])
tin, _ = build_tin(pts)
cs = tin.contours([5.0])
print(f"  contours returned: {len(cs)}")
maxdev = 0.0
for lvl, v, closed in cs:
    # every vertex must satisfy the plane equation
    dev = np.max(np.abs(0.5 * v[:, 0] + 0.25 * v[:, 1] - lvl))
    maxdev = max(maxdev, dev)
    print(f"    level {lvl}: {len(v)} verts, closed={closed}, max |0.5x+0.25y-level| = {dev:.3e}")
if maxdev > 1e-6:
    FAIL.append(f"contour vertices off the analytic plane by {maxdev:.2e}")

# ---------------------------------------------------------------- closed contours
# A cone on a SQUARE grid: z = 10 - r over [-10,10]^2.  A contour at level L is a circle of
# radius 10-L, so levels >= 0 sit inside the square (closed loops) and levels < 0 are cut by
# the square boundary (correctly open).  The contour is exact on the TIN, which is a
# piecewise-linear approximation of the cone, so radii deviate from a true circle by the
# inscribed-polygon sagitta - which must shrink as the grid is refined.
print("\n=== contour closure + convergence on a cone ===")
def cone_error(n):
    tt = np.linspace(-10, 10, n)
    XX, YY = np.meshgrid(tt, tt)
    RR = np.hypot(XX, YY)
    ZZ = 10.0 - RR
    pts = np.column_stack([XX.ravel(), YY.ravel(), ZZ.ravel()])
    tin, _ = build_tin(pts)
    cs = tin.contours(contour_levels(ZZ.min(), ZZ.max(), 1.0))
    return tin, cs


tin, cs = cone_error(60)
bad_closed, bad_open, rerr, n_closed, n_open = [], [], 0.0, 0, 0
cell = 20.0 / 59.0
for lvl, v, closed in cs:
    inside = lvl >= 0.0                      # radius 10-lvl stays within the square
    if closed:
        n_closed += 1
    else:
        n_open += 1
    if inside and not closed:
        bad_closed.append(lvl)
    if not inside and closed:
        bad_open.append(lvl)
    r = np.hypot(v[:, 0], v[:, 1])
    rerr = max(rerr, float(np.max(np.abs(r - (10 - lvl)))))
print(f"  {n_closed} closed, {n_open} open;  levels >=0 that came back open: {bad_closed};"
      f"  levels <0 that came back closed: {bad_open}")
if bad_closed:
    FAIL.append(f"contours that should close came back open at levels {bad_closed}")
if bad_open:
    FAIL.append(f"contours clipped by the domain reported closed at levels {bad_open}")
# the deviation from a true circle must be the inscribed-polygon sagitta, ~cell^2/(8 r)
sag = cell ** 2 / (8 * 1.0)
print(f"  worst radius error {rerr:.4e}  (expected sagitta ~{sag:.4e} at the smallest radius)")
if not (0.2 * sag < rerr < 3 * sag):
    FAIL.append(f"cone radius error {rerr:.2e} is not explained by the mesh sagitta ~{sag:.2e}")
# ...and it must shrink when the mesh is refined: proof it is discretisation, not a bug
_, cs_fine = cone_error(120)
rerr_fine = 0.0
for lvl, v, closed in cs_fine:
    r = np.hypot(v[:, 0], v[:, 1])
    rerr_fine = max(rerr_fine, float(np.max(np.abs(r - (10 - lvl)))))
ratio = rerr / max(rerr_fine, 1e-300)
print(f"  refined 60 -> 120 grid: error {rerr:.4e} -> {rerr_fine:.4e}  (ratio {ratio:.2f}, expect ~4)")
if ratio < 2.5:
    FAIL.append(f"cone contour error did not converge with mesh refinement (ratio {ratio:.2f})")

# ---------------------------------------------------------------- index levels
print("\n=== index level helper ===")
ok = all(is_index_level(l, 1.0, 5, 0.0) == (round(l) % 5 == 0) for l in range(-20, 21))
print(f"  intervals at every 5th consistent: {ok}")
if not ok:
    FAIL.append("is_index_level disagrees with modulo check")

print("\n" + "=" * 60)
print("FAILURES:" if FAIL else "ALL SURFACE MATH CHECKS PASSED")
for f in FAIL:
    print("  -", f)
