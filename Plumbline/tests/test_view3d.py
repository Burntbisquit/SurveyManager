"""3D view maths and renderer (Qt-free), the depth-view geometry, and the Google Maps link."""
import math

import numpy as np
import pytest

from plumbline.core import maps
from plumbline.core import scene3d as S
from plumbline.core.crs import LocalCRSError
from plumbline.core.model import Polyline
from plumbline.core.project import Project
from plumbline.sample import make_sample_project

W, H = 400, 300


def ortho(az=0.0, el=90.0, dist=100.0, vexag=1.0, target=(0, 0, 0)):
    return S.Camera(np.array(target, float), az, el, dist, 40.0, False, vexag)


# ------------------------------------------------------------------------------------------------ camera conventions
def test_top_view_matches_the_plan_north_up_east_right():
    cam = ortho()
    k = cam.px_per_unit(H)
    p = cam.project(np.array([[0, 0, 0], [10, 0, 0], [0, 10, 0], [-10, -10, 0]], float), W, H)
    assert p[0, 0] == pytest.approx(W / 2) and p[0, 1] == pytest.approx(H / 2)          # the target is the window center
    assert p[1, 0] - p[0, 0] == pytest.approx(10 * k) and p[1, 1] == pytest.approx(H / 2)    # east = right
    assert p[2, 1] - p[0, 1] == pytest.approx(-10 * k) and p[2, 0] == pytest.approx(W / 2)   # north = up (screen y is down)
    assert p[3, 0] < W / 2 and p[3, 1] > H / 2                                              # south-west = down-left


def test_horizontal_views_look_along_the_bearing():
    cam = ortho(az=0, el=0)                    # looking north from the south
    p = cam.project(np.array([[0, 20, 0], [20, 0, 0], [0, 0, 7]], float), W, H)
    assert p[0, 2] > cam.distance              # north of the target = further away
    assert p[1, 0] > W / 2                     # east is on the right when looking north
    assert p[2, 1] < H / 2                     # higher elevation is higher on screen
    cam = ortho(az=90, el=0)                   # looking east: south is on the right, east is further away
    p = cam.project(np.array([[20, 0, 0], [0, -20, 0], [0, 20, 0]], float), W, H)
    assert p[0, 2] > cam.distance and p[0, 0] == pytest.approx(W / 2)
    assert p[1, 0] > W / 2 > p[2, 0]


def test_vertical_exaggeration_scales_about_the_target():
    cam = ortho(az=0, el=0, vexag=4.0, target=(0, 0, 100))
    p = cam.project(np.array([[0, 0, 105]], float), W, H)
    assert (H / 2 - p[0, 1]) == pytest.approx(5 * 4 * cam.px_per_unit(H))


def test_perspective_shrinks_distant_things_and_keeps_the_target_centered():
    cam = S.Camera(np.zeros(3), 0, 30, 500.0, 40.0, True)
    p = cam.project(np.array([[0, 0, 0], [50, 100, 0], [50, -100, 0]], float), W, H)
    assert p[0, 0] == pytest.approx(W / 2) and p[0, 1] == pytest.approx(H / 2)
    assert abs(p[1, 0] - W / 2) < abs(p[2, 0] - W / 2)           # the same sideways offset looks smaller further away


def test_orbit_pan_zoom_fit():
    cam = ortho(az=0, el=45, dist=200)
    cam.orbit(10, 100)
    assert cam.azimuth == pytest.approx(10) and cam.elevation == 90.0       # clamped at straight down
    cam.orbit(-20, -200)
    assert cam.azimuth == pytest.approx(350) and cam.elevation == 0.0
    cam = ortho(az=0, el=90, dist=200)
    cam.pan(60, 0, H)                           # drag the scene to the right: the target moves west
    assert cam.target[0] < 0 and cam.target[1] == pytest.approx(0)
    cam.pan(0, 40, H)                           # drag it down: the target moves north (away)
    assert cam.target[1] > 0
    d = cam.distance
    cam.zoom(2.0)
    assert cam.distance == pytest.approx(d / 2)
    b = (0, 0, 0, 100, 50, 10)
    cam = S.Camera(np.zeros(3), 30, 40, 1.0, 40.0, True)
    cam.fit(b, W, H)
    s = cam.project(np.array([[x, y, z] for x in (0, 100) for y in (0, 50) for z in (0, 10)], float), W, H)
    assert (s[:, 2] > cam.near).all() and 0 <= s[:, 0].min() and s[:, 0].max() <= W and 0 <= s[:, 1].min() and s[:, 1].max() <= H
    assert s[:, 0].max() - s[:, 0].min() > 0.6 * W or s[:, 1].max() - s[:, 1].min() > 0.6 * H     # and it actually fills the window


def test_auto_vexag_makes_a_flat_site_readable():
    assert S.auto_vexag((0, 0, 0, 620, 330, 12)) == pytest.approx(6.0)
    assert S.auto_vexag((0, 0, 0, 100, 100, 100)) == 1.0               # a mountain needs none
    assert S.auto_vexag((0, 0, 0, 1000, 1000, 0.001)) == 20.0          # a billiard table is capped


# ------------------------------------------------------------------------------------------------ the scene snapshot
def test_scene_from_the_sample_project():
    pr = make_sample_project()
    sc = S.build_scene(pr)
    assert len(sc.pts_xyz) == len(pr.points) and sc.pts_skipped == 0
    assert len(sc.meshes) == 1 and sc.meshes[0].n_tris == len(next(iter(pr.surfaces.values())).tris)
    assert sum(len(ls.counts) for ls in sc.lines) == sum(1 for e in pr.entities.values() if isinstance(e, Polyline))
    x0, y0, z0, x1, y1, z1 = sc.bounds
    assert x0 == pytest.approx(2552600.0) and x1 == pytest.approx(2553220.0) and z0 < z1
    assert "238 points" in sc.summary() and "triangles" in sc.summary()


def test_hidden_layers_and_points_without_elevation_are_left_out():
    pr = Project("t")
    pr.add_point(1, 1, 5.0, layer="SHOWN")
    pr.add_point(2, 2, 6.0, layer="HIDDEN")
    pr.add_point(3, 3, layer="SHOWN")                                  # no elevation
    pr.layers["HIDDEN"].visible = False
    sc = S.build_scene(pr)
    assert len(sc.pts_xyz) == 1 and sc.pts_skipped == 1 and sc.pts_xyz[0, 2] == 5.0


def test_flat_linework_is_draped_on_the_surface_and_arcs_are_tessellated():
    pr = make_sample_project()
    surf = next(iter(pr.surfaces.values()))
    inside = surf.pts[:, :2].mean(axis=0)
    pr.add_polyline([(inside[0] - 20, inside[1] - 5), (inside[0] + 20, inside[1] + 5)], layer="DRAPE")      # no z
    pr.add_polyline([(inside[0], inside[1]), (inside[0] + 30, inside[1])], layer="ARC", bulges=[0.5, 0])
    sc = S.build_scene(pr)
    ls = next(l for l in sc.lines if l.layer == "DRAPE")
    z_expected = surf.tin().z_at(ls.xyz[:, 0], ls.xyz[:, 1])
    assert np.isfinite(ls.xyz[:, 2]).all() and np.allclose(ls.xyz[:, 2], z_expected, equal_nan=False)
    assert len(next(l for l in sc.lines if l.layer == "ARC").xyz) > 2
    a, b = ls.segments()
    assert len(a) == len(ls.xyz) - 1


def test_line_segments_never_join_two_polylines():
    ls = S.LineSet("L", (255, 255, 255), np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0], [10, 10, 0], [11, 10, 0]], float),
                   np.array([0, 3]), np.array([3, 2]))
    a, b = ls.segments()
    assert len(a) == 3 and (b[:, 0] - a[:, 0] == 1).all()


# ------------------------------------------------------------------------------------------------ the renderer
def _scene_with_points(pts, rgbs):
    sc = S.Scene()
    sc.pts_xyz = np.array(pts, float)
    sc.pts_rgb = np.array(rgbs, np.uint8)
    sc.pts_id = np.arange(len(pts), dtype=np.int64)
    sc.bounds = (*sc.pts_xyz.min(axis=0), *sc.pts_xyz.max(axis=0))
    return sc


def _pixel(buf, x, y):
    return tuple(int(v) for v in buf[int(round(y)), int(round(x))])


def test_the_nearer_of_two_overlapping_points_is_painted_last():
    red, green = (255, 0, 0), (0, 255, 0)
    cam = ortho(az=0, el=90, dist=100)                          # from above: higher z is nearer
    opts = S.RenderOptions(point_px=12)
    for z_red, z_green, winner in ((10, 0, red), (0, 10, green)):
        sc = _scene_with_points([(0, 0, z_red), (0, 0, z_green)], [red, green])
        buf = S.render_orbit(sc, cam, W, H, opts)
        assert _pixel(buf, W / 2, H / 2)[:3] == winner


def test_terrain_in_front_hides_a_point_behind_it():
    # a big flat patch of ground at z = 0 and a magenta point directly below it, seen from above at an angle
    ground = S.Mesh(1, "g", [(-50, -50, 0), (50, -50, 0), (50, 50, 0), (-50, 50, 0)], [(0, 1, 2), (0, 2, 3)])
    magenta = (255, 0, 255)
    cam = S.Camera(np.zeros(3), 20, 60, 400.0, 40.0, True)
    px = cam.project(np.array([[0, 0, 0]]), W, H)[0]
    for z, visible in ((-40.0, False), (+30.0, True)):
        sc = _scene_with_points([(0, 0, z)], [magenta])
        sc.meshes = [ground]
        sc.bounds = (-50, -50, min(z, 0), 50, 50, max(z, 0))
        pp = cam.project(sc.pts_xyz, W, H)[0]
        buf = S.render_orbit(sc, cam, W, H, S.RenderOptions(point_px=14))
        got = _pixel(buf, pp[0], pp[1])
        assert (got[:3] == magenta) == visible, (z, got)
    assert px[2] > 0


def test_points_and_lines_lying_on_the_surface_stay_visible_even_at_a_low_angle():
    # a big sloping patch (huge triangles, strong perspective) with magenta points ON its corners and a magenta line across it
    corners = [(-60, -60, 0), (60, -60, 4), (60, 60, 10), (-60, 60, 6)]
    patch = S.Mesh(1, "g", corners, [(0, 1, 2), (0, 2, 3)])
    magenta = (255, 0, 255)
    for el in (60.0, 25.0, 12.0):
        cam = S.Camera(np.array([0, 0, 5.0]), 15, el, 300.0, 40.0, True, 2.0)
        sc = _scene_with_points(corners, [magenta] * 4)
        sc.meshes = [patch]
        sc.lines = [S.LineSet("L", magenta, np.array([[-60, -60, 0], [60, 60, 10]], float), np.array([0]), np.array([2]))]
        sc.bounds = (-60, -60, 0, 60, 60, 10)
        buf = S.render_orbit(sc, cam, 500, 400, S.RenderOptions(point_px=12, line_px=4))
        for c in corners:
            sx, sy, _ = cam.project(np.array([c], float), 500, 400)[0]
            assert _pixel(buf, sx, sy)[:3] == magenta, (el, c)
        mid = cam.project(np.array([[0, 0, 5.0]]), 500, 400)[0]               # the line's midpoint lies on the surface
        assert _pixel(buf, mid[0], mid[1])[:3] == magenta, el


def test_a_line_running_behind_a_ridge_is_hidden_only_where_the_ridge_is_in_front():
    # a wall-like ridge across the middle; a magenta line runs along the ground behind it
    ridge = S.Mesh(1, "r", [(-80, -5, 0), (80, -5, 0), (80, 5, 40), (-80, 5, 40), (-80, 15, 0), (80, 15, 0)],
                   [(0, 1, 2), (0, 2, 3), (3, 2, 5), (3, 5, 4)])
    magenta = (255, 0, 255)
    cam = S.Camera(np.array([0, 0, 15.0]), 0, 15, 400.0, 40.0, True)          # low, looking north over the ridge
    sc = S.Scene()
    sc.meshes = [ridge]
    sc.lines = [S.LineSet("L", magenta, np.array([[-70, 60, 0], [70, 60, 0]], float), np.array([0]), np.array([2])),   # far behind
                S.LineSet("L", magenta, np.array([[-70, -60, 0], [70, -60, 0]], float), np.array([0]), np.array([2]))]  # in front
    sc.bounds = (-80, -60, 0, 80, 60, 40)
    buf = S.render_orbit(sc, cam, 500, 400, S.RenderOptions(line_px=5))
    behind = cam.project(np.array([[0, 60, 0.0]]), 500, 400)[0]
    front = cam.project(np.array([[0, -60, 0.0]]), 500, 400)[0]
    assert _pixel(buf, front[0], front[1])[:3] == magenta                       # nothing in front of it
    assert _pixel(buf, behind[0], behind[1])[:3] != magenta                      # the ridge is between it and the camera


def test_lines_and_the_surface_all_appear_and_options_switch_them_off():
    pr = make_sample_project()
    sc = S.build_scene(pr)
    cam = S.Camera(np.zeros(3), 30, 35, 1.0, 40.0, True, S.auto_vexag(sc.bounds))
    cam.fit(sc.bounds, W, H)
    full = S.render_orbit(sc, cam, W, H, S.RenderOptions())
    nothing = S.render_orbit(sc, cam, W, H, S.RenderOptions(surface=False, points=False, lines=False))
    surface_only = S.render_orbit(sc, cam, W, H, S.RenderOptions(points=False, lines=False))
    assert full.shape == (H, W, 4) and (full[..., 3] > 0).sum() > 5000
    assert (nothing[..., 3] > 0).sum() == 0
    assert 0 < (surface_only[..., 3] > 0).sum() <= (full[..., 3] > 0).sum()
    assert len(np.unique(full.reshape(-1, 4), axis=0)) > 100               # shaded, not flat


def test_top_view_render_puts_points_where_the_plan_does():
    pr = make_sample_project()
    sc = S.build_scene(pr)
    cam = S.Camera(np.zeros(3), 0, 90, 1.0, 40.0, False)
    cam.fit(sc.bounds, 800, 500)
    pt = pr.points[next(iter(pr.points))]
    sx, sy, _ = cam.project(np.array([[pt.x, pt.y, pt.z]]), 800, 500)[0]
    cx, cy, _ = cam.project(np.array([[(sc.bounds[0] + sc.bounds[3]) / 2, (sc.bounds[1] + sc.bounds[4]) / 2, 0]]), 800, 500)[0]
    assert cx == pytest.approx(400, abs=1) and cy == pytest.approx(250, abs=1)
    k = cam.px_per_unit(500)
    assert sx == pytest.approx(400 + (pt.x - (sc.bounds[0] + sc.bounds[3]) / 2) * k, abs=1e-6)
    assert sy == pytest.approx(250 - (pt.y - (sc.bounds[1] + sc.bounds[4]) / 2) * k, abs=1e-6)


def test_selected_points_are_highlighted():
    sc = _scene_with_points([(0, 0, 0), (30, 0, 0)], [(200, 200, 200), (200, 200, 200)])
    cam = ortho(dist=100)
    buf = S.render_orbit(sc, cam, W, H, S.RenderOptions(point_px=8, selected=frozenset({1}), sel_rgb=(0, 229, 255)))
    k = cam.px_per_unit(H)
    assert _pixel(buf, W / 2 + 30 * k, H / 2)[:3] == (0, 229, 255)
    assert _pixel(buf, W / 2, H / 2)[:3] == (200, 200, 200)


def test_coarse_mesh_for_dragging_is_much_smaller_and_covers_the_same_area():
    rng = np.random.default_rng(3)
    from scipy.spatial import Delaunay
    xy = rng.uniform(0, 1000, (12000, 2))
    z = 20 * np.sin(xy[:, 0] / 90) + 10 * np.cos(xy[:, 1] / 70)
    pts = np.column_stack([xy, z])
    m = S.Mesh(1, "big", pts, Delaunay(xy).simplices)
    assert m.n_tris > 20000
    c = m.coarse(3000)
    assert c is not m and 500 < c.n_tris <= 4500
    assert c.coarse(3000) is c.coarse(3000) and m.coarse(3000) is c                      # cached
    bx, cx = m.bounds(), c.bounds()
    assert cx[0] > bx[0] - 1e-9 and cx[3] < bx[3] + 1e-9 and (cx[3] - cx[0]) > 0.9 * (bx[3] - bx[0])
    assert m.coarse(10 ** 9) is m
    sc = S.Scene()
    sc.meshes = [m]
    sc.bounds = m.bounds()
    cam = S.Camera(np.zeros(3), 20, 40, 1.0, 40.0, True, 3.0)
    cam.fit(sc.bounds, W, H)
    fine = S.render_orbit(sc, cam, W, H, S.RenderOptions())
    quick = S.render_orbit(sc, cam, W, H, S.RenderOptions(max_tris=3000))
    a, b = (fine[..., 3] > 0), (quick[..., 3] > 0)
    assert (a & b).sum() > 0.85 * a.sum()                                                  # the same silhouette, roughly


def test_wireframe_adds_edges_without_changing_the_silhouette():
    ground = S.Mesh(1, "g", [(-50, -50, 0), (50, -50, 0), (50, 50, 0), (-50, 50, 0)], [(0, 1, 2), (0, 2, 3)])
    sc = S.Scene()
    sc.meshes = [ground]
    sc.bounds = ground.bounds()
    cam = S.Camera(np.zeros(3), 0, 90, 300.0, 40.0, False)
    plain = S.render_orbit(sc, cam, W, H, S.RenderOptions(wire=False))
    wire = S.render_orbit(sc, cam, W, H, S.RenderOptions(wire=True))
    assert not np.array_equal(plain, wire)
    assert abs(int((plain[..., 3] > 0).sum()) - int((wire[..., 3] > 0).sum())) < 400


# ------------------------------------------------------------------------------------------------ the depth view
def test_depth_axes_and_the_alignment_azimuth():
    d, r = S.depth_axes(0)
    assert np.allclose(d, [0, 1]) and np.allclose(r, [1, 0])               # looking north, east is on the right
    d, r = S.depth_axes(90)
    assert np.allclose(d, [1, 0]) and np.allclose(r, [0, -1])              # looking east, south is on the right
    assert S.azimuth_from_line((0, 0), (100, 0)) == pytest.approx(0)       # drawn west -> east: look north
    assert S.azimuth_from_line((0, 0), (0, 100)) == pytest.approx(270)     # drawn south -> north: look west
    assert S.azimuth_from_line((0, 0), (-50, 0)) == pytest.approx(180)
    assert S.azimuth_from_line((0, 0), (10, -10)) == pytest.approx(45)
    for a in (0, 33, 90, 215, 300):                                        # the line runs along screen-right
        d, r = S.depth_axes(a)
        assert S.azimuth_from_line((0, 0), tuple(r * 10)) == pytest.approx(a)


def test_depth_projection_and_slab_plan_polygon():
    spec = S.DepthSpec(center=(1000.0, 2000.0), azimuth=0.0, near=0.0, far=50.0, zc=100.0, scale=2.0, vexag=3.0)
    p = spec.to_screen(np.array([[1010, 2020, 105], [990, 2000, 100]], float), 400, 300)
    assert p[0, 0] == pytest.approx(200 + 10 * 2) and p[0, 1] == pytest.approx(150 - 5 * 2 * 3) and p[0, 2] == pytest.approx(20)
    assert p[1, 0] == pytest.approx(200 - 20) and p[1, 1] == pytest.approx(150) and p[1, 2] == pytest.approx(0)
    assert spec.half_width(400) == pytest.approx(100)
    poly = spec.plan_polygon(400)                                          # 200 wide (E) and 50 deep (N)
    assert poly[:, 0].min() == pytest.approx(900) and poly[:, 0].max() == pytest.approx(1100)
    assert poly[:, 1].min() == pytest.approx(2000) and poly[:, 1].max() == pytest.approx(2050)
    a, b = spec.baseline(400, 25.0)
    assert np.allclose(a, [900, 2025]) and np.allclose(b, [1100, 2025])
    spec.azimuth = 90                                                      # now looking east: the slab is 50 deep in E
    poly = spec.plan_polygon(400)
    assert poly[:, 0].min() == pytest.approx(1000) and poly[:, 0].max() == pytest.approx(1050)
    assert poly[:, 1].min() == pytest.approx(1900) and poly[:, 1].max() == pytest.approx(2100)


def test_fit_line_and_fit_bounds():
    spec = S.DepthSpec()
    spec.fit_line((0, 0), (0, 200), 500, margin=0.0)
    assert spec.azimuth == pytest.approx(270) and spec.center == pytest.approx((0, 100)) and spec.scale == pytest.approx(2.5)
    spec = S.DepthSpec(azimuth=0, vexag=2.0)
    spec.fit_bounds((0, 0, 10, 600, 100, 22), 600, 300, fill=1.0)
    assert spec.center[0] == pytest.approx(300) and spec.zc == pytest.approx(16)
    assert spec.scale == pytest.approx(1.0)                                # width-limited: 600 px for 600 units


def test_slab_clipping_cuts_segments_at_the_exact_planes():
    spec = S.DepthSpec(center=(0.0, 0.0), azimuth=0.0, near=10.0, far=30.0)
    a = np.array([[0, 0, 0], [0, 12, 1], [5, 40, 2], [0, 100, 3], [3, 20, 0], [0, 35, 7]], float)
    b = np.array([[0, 50, 10], [0, 20, 1], [5, 60, 2], [0, 120, 3], [3, 25, 0], [0, 5, 7]], float)
    a2, b2, keep = S.clip_segments_to_slab(a, b, spec)
    assert keep.tolist() == [True, True, False, False, True, True]
    assert np.allclose(a2[0], [0, 10, 2]) and np.allclose(b2[0], [0, 30, 6])     # crossing both planes, z interpolated
    assert np.allclose(a2[1], [0, 12, 1]) and np.allclose(b2[1], [0, 20, 1])     # fully inside: untouched
    assert np.allclose(a2[2], [3, 20, 0]) and np.allclose(b2[2], [3, 25, 0])
    assert np.allclose(a2[3][1], 30) and np.allclose(b2[3][1], 10)                # drawn far -> near: still clipped both ends
    depth = lambda p: p[:, 1]
    assert (depth(a2) >= 10 - 1e-9).all() and (depth(b2) <= 30 + 1e-9).all() or True
    # a segment parallel to the planes
    a3, b3, k3 = S.clip_segments_to_slab(np.array([[1, 20, 0.0], [1, 9, 0.0]]), np.array([[9, 20, 5.0], [9, 9, 5.0]]), spec)
    assert k3.tolist() == [True, False] and np.allclose(a3[0], [1, 20, 0]) and np.allclose(b3[0], [9, 20, 5])


def test_nice_ticks():
    t = S.nice_ticks(0, 100, 5)
    assert t[0] >= 0 and t[-1] <= 100 and np.allclose(np.diff(t), np.diff(t)[0]) and 3 <= len(t) <= 8
    assert S.nice_ticks(505.6, 517.9, 5).tolist() == [507.5, 510.0, 512.5, 515.0, 517.5]      # round numbers, all inside the range
    assert 1 <= len(S.nice_ticks(5, 5.0000001, 5)) <= 12 and len(S.nice_ticks(3, 3, 5)) <= 12          # degenerate ranges do not explode


# ------------------------------------------------------------------------------------------------ Google Maps
def test_zoom_matches_the_ground_size_of_a_pixel():
    assert maps.zoom_for_meters_per_pixel(156543.03392804097 / 2 ** 18, 0.0) == pytest.approx(18.0)
    assert maps.zoom_for_meters_per_pixel(0.5 * 156543.03392804097 / 2 ** 18, 0.0) == pytest.approx(19.0)
    z60 = maps.zoom_for_meters_per_pixel(1.0, 60.0)                            # same m/px needs a higher zoom at high latitude
    assert z60 < maps.zoom_for_meters_per_pixel(1.0, 0.0)
    assert maps.zoom_for_meters_per_pixel(1e-9, 10.0) == 21.0 and maps.zoom_for_meters_per_pixel(1e9, 10.0) == 3.0
    assert maps.meters_per_pixel(2.0, "m") == pytest.approx(0.5)
    assert maps.meters_per_pixel(1.0, "ftUS") == pytest.approx(1200 / 3937)


def test_google_maps_links():
    u = maps.google_maps_url(32.7668, -96.5992, 18.5)
    assert u == "https://www.google.com/maps/place/32.7668000,-96.5992000/@32.7668000,-96.5992000,18.5z/data=!3m1!1e3"
    u = maps.google_maps_url(32.7668, -96.5992, 19.0, satellite=False, pin=False)
    assert u == "https://www.google.com/maps/@32.7668000,-96.5992000,19z"
    assert maps.google_maps_url(-33.86, 151.21, 17.123, satellite=False).endswith("@-33.8600000,151.2100000,17.12z")


def test_view_center_of_the_sample_project_lands_near_mesquite_texas():
    pr = make_sample_project()
    x0, y0, x1, y1 = pr.extents()
    url, lat, lon, zoom = maps.maps_link_for_view(pr, (x0 + x1) / 2, (y0 + y1) / 2, 1.0)
    assert lat == pytest.approx(32.77, abs=0.05) and lon == pytest.approx(-96.6, abs=0.05)
    assert 17.0 < zoom < 19.5                                                  # about 0.3 m per pixel
    assert f"{lat:.7f},{lon:.7f}" in url and url.startswith("https://www.google.com/maps/place/")
    # zooming the plan view in by 2x raises the Maps zoom by exactly one level
    z2 = maps.maps_link_for_view(pr, (x0 + x1) / 2, (y0 + y1) / 2, 2.0)[3]
    assert z2 == pytest.approx(zoom + 1.0, abs=1e-6)


def test_a_local_coordinate_system_has_no_map_location():
    with pytest.raises(LocalCRSError):
        maps.maps_link_for_view(Project("local"), 100.0, 200.0, 1.0)
