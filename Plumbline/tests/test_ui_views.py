"""The 3D view, the depth view (rotatable elevation) and the Google Maps action, driven through the real window."""
import math

import numpy as np
import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QImage, QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QMenu, QToolBar, QToolButton

from plumbline.core import maps
from plumbline.core import scene3d as S
from plumbline.core.project import Project
from plumbline.ui import theme
from test_ui import app, auto, click_world, pump, win  # noqa: F401  (fixtures + helpers)


# ------------------------------------------------------------------------------------------------ helpers
def button(panel, text):
    return next(b for b in panel.findChildren(QToolButton) if b.text() == text)


def wheel(widget, delta, pos=None, mods=Qt.NoModifier):
    pos = QPointF(widget.width() / 2, widget.height() / 2) if pos is None else QPointF(*pos)
    ev = QWheelEvent(pos, widget.mapToGlobal(pos), QPoint(0, 0), QPoint(0, delta), Qt.NoButton, mods, Qt.NoScrollPhase, False)
    QApplication.sendEvent(widget, ev)


def drag(widget, a, b, button=Qt.LeftButton, mods=Qt.NoModifier):
    QTest.mousePress(widget, button, mods, QPoint(*a))
    QTest.mouseMove(widget, QPoint((a[0] + b[0]) // 2, (a[1] + b[1]) // 2))
    QTest.mouseMove(widget, QPoint(*b))
    QTest.mouseRelease(widget, button, mods, QPoint(*b))


def opaque_pixels(img) -> int:
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width()]
    return int((arr[..., 3] > 0).sum())


def colour_pixels(widget, rgb, tol=40) -> int:
    img = widget.grab().toImage().convertToFormat(QImage.Format_ARGB32)
    arr = np.frombuffer(img.constBits(), np.uint8).reshape(img.height(), img.bytesPerLine() // 4, 4)[:, :img.width(), :3]
    return int((np.abs(arr[..., ::-1].astype(int) - np.array(rgb)).max(axis=2) <= tol).sum())      # BGRA -> RGB


def open_view(win, app, which):
    act = win.a_3d if which == "3d" else win.a_depth
    act.setChecked(True)
    pump(app, 4, 20)
    QTest.qWait(60)
    pump(app, 4)
    return win.view3d if which == "3d" else win.depth


# ------------------------------------------------------------------------------------------------ 3D view
def test_the_view_panels_do_not_force_the_dock_wide(win):
    assert win.view3d.minimumSizeHint().width() <= 500 and win.depth.minimumSizeHint().width() <= 500


def test_the_3d_view_docks_next_to_the_plan_draws_the_site_and_follows_its_dock(win, app):
    assert not win.d_3d.isVisible() and not win.a_3d.isChecked()
    panel = open_view(win, app, "3d")
    v = panel.view
    assert win.d_3d.isVisible() and win.a_3d.isChecked()
    assert "238 points" in panel.lbl_info.text() and "triangles" in panel.lbl_info.text()
    assert v.width() > 300 and v.height() > 150
    img = v.render_image()
    assert opaque_pixels(img) > 8000 and len(np.unique(np.frombuffer(img.constBits(), np.uint8).reshape(-1, 4)[::7], axis=0)) > 100
    assert v.cam.vexag == pytest.approx(6.0)                    # a readable exaggeration is picked for this flat site
    bx0, by0, bz0, bx1, by1, bz1 = v.provider.scene().bounds
    assert v.cam.target[0] == pytest.approx((bx0 + bx1) / 2) and v.cam.target[1] == pytest.approx((by0 + by1) / 2)
    win.d_3d.close()                                            # the user's X button
    pump(app)
    assert not win.a_3d.isChecked()
    win.a_3d.trigger()                                          # and back through the menu / toolbar action
    pump(app)
    assert win.d_3d.isVisible()


def test_orbit_pan_zoom_and_fit_with_the_mouse(win, app):
    v = open_view(win, app, "3d").view
    az0, el0, d0 = v.cam.azimuth, v.cam.elevation, v.cam.distance
    cx, cy = v.width() // 2, v.height() // 2
    drag(v, (cx, cy), (cx + 100, cy))                           # drag right: the scene turns clockwise (bearing decreases)
    assert (v.cam.azimuth - az0 + 180) % 360 - 180 == pytest.approx(-40.0, abs=1.5)
    el1 = v.cam.elevation
    drag(v, (cx, cy), (cx, cy + 30))                            # drag down: look from higher up
    assert v.cam.elevation == pytest.approx(min(el1 + 12.0, 90.0), abs=1.5)
    drag(v, (cx, cy), (cx, cy - 400))                           # drag far up: clamped at the horizon, never below it
    assert v.cam.elevation == 0.0
    v.cam.set_view(0, 90)
    t0 = v.cam.target.copy()
    drag(v, (cx, cy), (cx + 60, cy), mods=Qt.ShiftModifier)     # shift-drag pans: the target moves west, elevation untouched
    assert v.cam.target[0] < t0[0] and v.cam.target[2] == pytest.approx(t0[2]) and v.cam.elevation == 90.0
    t1 = v.cam.target.copy()
    drag(v, (cx, cy), (cx, cy + 40), button=Qt.RightButton)     # right-drag pans too (dragging down moves the target north)
    assert v.cam.target[1] > t1[1]
    wheel(v, 120)
    assert v.cam.distance < d0
    z1 = v.cam.distance
    wheel(v, -240)
    assert v.cam.distance > z1
    assert v._interacting                                       # the cheap level of detail is on while moving ...
    QTest.qWait(260)
    pump(app)
    assert not v._interacting                                   # ... and the full-quality picture comes back
    QTest.mouseDClick(v, Qt.LeftButton, Qt.NoModifier, QPoint(cx, cy))
    fit_target = v.cam.target.copy()
    b = v.provider.scene().bounds
    assert fit_target[0] == pytest.approx((b[0] + b[3]) / 2) and fit_target[1] == pytest.approx((b[1] + b[4]) / 2)
    a = v.cam.azimuth
    QTest.keyClick(v, Qt.Key_Left)                              # keyboard orbit: 5 degrees
    assert (v.cam.azimuth - a) % 360 == pytest.approx(5.0)


def test_preset_projection_exaggeration_and_layer_toggles(win, app):
    panel = open_view(win, app, "3d")
    v = panel.view
    button(panel, "Top").click()
    assert (v.cam.azimuth, v.cam.elevation) == (0.0, 90.0)
    button(panel, "Right").click()
    assert (v.cam.azimuth, v.cam.elevation) == (270.0, 0.0)
    button(panel, "Iso").click()
    assert v.cam.elevation == pytest.approx(35.0)
    panel.cmb_proj.setCurrentIndex(1)
    assert not v.cam.perspective
    panel.cmb_proj.setCurrentIndex(0)
    assert v.cam.perspective
    panel.sp_vex.setValue(12.0)
    assert v.cam.vexag == 12.0
    button(panel, "Auto").click()
    assert v.cam.vexag == pytest.approx(6.0) and panel.sp_vex.value() == pytest.approx(6.0)
    full = opaque_pixels(v.render_image())
    checks = {c.text(): c for c in panel.findChildren(QCheckBox)}
    checks["Surface"].setChecked(False)
    no_surface = opaque_pixels(v.render_image())
    assert 0 < no_surface < full * 0.9                           # only points and lines are left
    checks["Surface"].setChecked(True)
    checks["Points"].setChecked(False)
    checks["Lines"].setChecked(False)
    surface_only = opaque_pixels(v.render_image())
    assert 0 < surface_only <= full
    checks["Points"].setChecked(True)
    checks["Lines"].setChecked(True)
    checks["Mesh"].setChecked(True)
    checks["Numbers"].setChecked(True)
    v.grab()                                                     # draws the number labels without error
    assert opaque_pixels(v.render_image()) >= full * 0.98


def test_top_view_has_the_same_orientation_and_proportions_as_the_plan(win, app):
    panel = open_view(win, app, "3d")
    v = panel.view
    panel.cmb_proj.setCurrentIndex(1)                            # orthographic, so there is no perspective shift
    button(panel, "Top").click()
    pr = win.state.project
    pts = list(pr.points.values())
    a, b = pts[0], max(pts, key=lambda p: math.hypot(p.x - pts[0].x, p.y - pts[0].y))
    W, H = v.width(), v.height()
    sa, sb = v.cam.project(np.array([[a.x, a.y, a.z], [b.x, b.y, b.z]], float), W, H)
    cv = win.canvas.view
    pa, pb = cv.to_screen(a.x, a.y), cv.to_screen(b.x, b.y)
    k3, kp = v.cam.px_per_unit(H), cv.scale
    assert (sb[0] - sa[0]) / k3 == pytest.approx((pb[0] - pa[0]) / kp, rel=1e-6)          # east is right in both
    assert (sb[1] - sa[1]) / k3 == pytest.approx((pb[1] - pa[1]) / kp, rel=1e-6)          # north is up in both


def test_points_selected_on_the_plan_light_up_in_3d(win, app):
    panel = open_view(win, app, "3d")
    v = panel.view
    panel.cmb_proj.setCurrentIndex(1)
    button(panel, "Top").click()
    pr = win.state.project
    pt = next(iter(pr.points.values()))
    win.state.select(points=[pt.id])
    pump(app)
    img = v.render_image()
    W, H = v.width(), v.height()
    sx, sy, _ = v.cam.project(np.array([[pt.x, pt.y, pt.z]], float), W, H)[0]
    px = img.pixelColor(int(round(sx)), int(round(sy)))
    sel = QColor(theme.colors()["select"]).getRgb()[:3]
    assert (px.red(), px.green(), px.blue()) == sel
    win.state.clear_selection()
    pump(app)
    px = v.render_image().pixelColor(int(round(sx)), int(round(sy)))
    assert (px.red(), px.green(), px.blue()) != sel


def test_a_project_the_views_cannot_read_does_not_stop_painting(win, app, monkeypatch):
    p3, pd = open_view(win, app, "3d"), open_view(win, app, "depth")
    logged = []
    win.state.message.connect(lambda level, text: logged.append((level, text)))

    def boom(*a, **k):
        raise RuntimeError("damaged geometry")

    monkeypatch.setattr(S, "build_scene", boom)
    win.scene_provider.invalidate()
    p3.view.grab()
    pd.view.grab()
    assert win.scene_provider.scene().bounds is None                    # an empty scene, not a crash
    assert [t for level, t in logged if level == "error" and "damaged geometry" in t]
    assert len([1 for level, t in logged if level == "error"]) == 1     # reported once, not on every repaint


def test_both_views_rebuild_after_edits_theme_changes_and_a_new_project(win, app, auto):
    p3, pd = open_view(win, app, "3d"), open_view(win, app, "depth")
    before = p3.view.provider.scene()
    win.toggle_theme()
    pump(app, 4, 10)
    assert p3.view.provider.scene() is not before                 # snapshot rebuilt with the other theme's colours
    p3.view.grab()
    pd.view.grab()
    win.toggle_theme()
    with win.state.edit("add a high point"):
        win.state.project.add_point(2552900.0, 6967200.0, 540.0, desc="TOWER")
    pump(app)
    assert len(p3.view.provider.scene().pts_xyz) == 239
    win.state.new_project("Empty")                                # nothing to draw: a note, no crash
    pump(app, 4, 10)
    p3.view.grab()
    pd.view.grab()
    assert p3.view.provider.scene().bounds is None
    win.open_sample()
    pump(app, 4, 20)
    p3.view.grab()
    assert p3.view.provider.scene().bounds is not None and p3.view._fitted_for == id(win.state.project)


# ------------------------------------------------------------------------------------------------ depth view
def test_depth_view_opens_as_a_tab_and_shows_its_slab_on_the_plan(win, app):
    open_view(win, app, "3d")
    panel = open_view(win, app, "depth")
    v = panel.view
    assert win.d_depth.isVisible() and win.a_depth.isChecked()
    assert {win.d_depth, win.d_props} <= set(win.tabifiedDockWidgets(win.d_3d))   # both views are tabs beside Properties
    assert v.paint_plan_overlay in win.canvas.view_overlays                       # the slab is drawn on the plan
    cv = win.canvas.view
    assert v.spec.center == pytest.approx((cv.cx, cv.cy)) and v.spec.azimuth == 0.0 and v.spec.near == 0.0 and v.spec.far > 20
    plan = win.canvas.grab()
    assert not plan.isNull()
    win.d_depth.close()
    pump(app)
    assert v.paint_plan_overlay not in win.canvas.view_overlays and not win.a_depth.isChecked()


def test_toolbar_buttons_track_which_view_tab_is_on_top(win, app):
    """The 3D and depth views share a tab group (and Qt still calls the hidden tab 'visible'): the button of the tab that
    is behind the other must read 'off', and pressing it must bring that tab to the front - not hide a hidden dock."""
    overlay = win.depth.view.paint_plan_overlay
    open_view(win, app, "3d")
    open_view(win, app, "depth")
    pump(app, 4, 20)
    assert win.a_depth.isChecked() and not win.a_3d.isChecked() and overlay in win.canvas.view_overlays
    win.a_3d.trigger()                                                       # Ctrl+3 while the depth tab is on top
    pump(app, 4, 20)
    assert win.a_3d.isChecked() and not win.a_depth.isChecked()
    assert overlay not in win.canvas.view_overlays                           # no slab on the plan while the depth view is not showing
    assert win.d_3d in [d for d in win.findChildren(type(win.d_3d)) if not d.isHidden()]      # the 3D tab did not vanish
    win.a_depth.trigger()                                                    # and back again
    pump(app, 4, 20)
    assert win.a_depth.isChecked() and not win.a_3d.isChecked() and overlay in win.canvas.view_overlays
    win.a_depth.trigger()                                                    # pressing the button of the tab on top hides it
    pump(app, 4, 20)
    assert not win.a_depth.isChecked() and overlay not in win.canvas.view_overlays
    assert win.d_depth.isHidden() and not win.d_3d.isHidden()                # only that one: the other tab is still there


def test_depth_view_follows_the_plan_until_you_pan_it_yourself(win, app):
    panel = open_view(win, app, "depth")
    v = panel.view
    cv = win.canvas
    cv.pan_pixels(-120, 60)                                                      # pan the plan
    pump(app)
    assert v.spec.center == pytest.approx((cv.view.cx, cv.view.cy))
    assert panel.chk_follow.isChecked()
    c0 = v.spec.center
    drag(v, (200, 100), (260, 100))                                              # drag the depth view sideways: follow switches off
    assert not v.follow and not panel.chk_follow.isChecked() and v.spec.center != c0
    c1 = v.spec.center
    cv.pan_pixels(80, 0)
    pump(app)
    assert v.spec.center == c1                                                   # no longer follows
    panel.chk_follow.setChecked(True)                                            # and snaps back when asked
    assert v.spec.center == pytest.approx((cv.view.cx, cv.view.cy))


def test_rotating_the_depth_view_with_every_control(win, app):
    panel = open_view(win, app, "depth")
    v = panel.view
    for text, az in (("E", 90.0), ("S", 180.0), ("W", 270.0), ("N", 0.0)):
        button(panel, text).click()
        assert v.spec.azimuth == az and panel.sp_az.value() == pytest.approx(az) and panel.lbl_dir.text() == text
    button(panel, "+15\u00b0").click()
    assert v.spec.azimuth == 15.0
    button(panel, "-15\u00b0").click()
    button(panel, "-15\u00b0").click()
    assert v.spec.azimuth == 345.0                                               # wraps past north
    button(panel, "Flip").click()
    assert v.spec.azimuth == 165.0
    panel.sp_az.setValue(45.0)
    assert v.spec.azimuth == 45.0 and panel.lbl_dir.text() == "NE" and panel.dial.value() == (45 + 180) % 360
    panel.dial.setValue((300 + 180) % 360)                                       # the dial is a compass: 300 degrees
    assert v.spec.azimuth == pytest.approx(300.0)
    drag(v, (300, 100), (200, 100), button=Qt.RightButton)                       # right-drag left rotates the other way
    assert v.spec.azimuth == pytest.approx(300.0 + 40.0)
    QTest.keyClick(v, Qt.Key_Right)
    assert v.spec.azimuth == pytest.approx(335.0)
    # the slab on the plan turns with it
    poly0 = v.spec.plan_polygon(v.width()).copy()
    v.set_azimuth(80.0)
    assert not np.allclose(poly0, v.spec.plan_polygon(v.width()))


def test_depth_slab_exaggeration_and_display_controls(win, app):
    panel = open_view(win, app, "depth")
    v = panel.view
    panel.sp_near.setValue(25.0)
    assert v.spec.near == 25.0 and v.spec.far - v.spec.near == pytest.approx(panel.sp_far.value())     # moving the start keeps the depth
    panel.sp_far.setValue(60.0)
    assert v.spec.far == pytest.approx(85.0)
    panel.sp_vex.setValue(10.0)
    assert v.spec.vexag == 10.0
    button(panel, "Auto").click()
    assert v.spec.vexag == pytest.approx(6.0)
    checks = {c.text(): c for c in panel.findChildren(QCheckBox)}
    ground = (120, 190, 140)
    checks["Lines"].setChecked(False)                                             # isolate the ground from other green things
    checks["Points"].setChecked(False)
    with_ground = colour_pixels(v, ground, 30)
    checks["Ground"].setChecked(False)
    without = colour_pixels(v, ground, 30)
    assert with_ground > 500 and without < with_ground * 0.05                     # the ground section is really drawn
    checks["Ground"].setChecked(True)
    for name in ("Lines", "Points", "Numbers"):
        checks[name].setChecked(True)
    v.grab()                                                                      # everything on, including the labels


def test_depth_view_mouse_pan_zoom_and_fit(win, app):
    panel = open_view(win, app, "depth")
    v = panel.view
    panel.chk_follow.setChecked(False)
    s = v.spec
    c0, zc0, k0 = s.center, s.zc, s.scale
    drag(v, (300, 120), (360, 140))                                              # drag right + down: the scene follows the mouse
    assert s.center[0] < c0[0] and s.zc > zc0                                    # looking north: east is right, so centre moves west
    # zoom about the cursor keeps the point under it in place
    pos = (v.width() * 0.75, v.height() * 0.4)
    h_before = (pos[0] - v.width() / 2) / s.scale + (np.asarray(s.center) @ s.axes()[1])
    wheel(v, 240, pos)
    assert s.scale > k0
    h_after = (pos[0] - v.width() / 2) / s.scale + (np.asarray(s.center) @ s.axes()[1])
    assert h_after == pytest.approx(h_before, rel=1e-9)
    vex = s.vexag
    wheel(v, 120, mods=Qt.ControlModifier)                                       # Ctrl + wheel = vertical exaggeration
    assert s.vexag > vex
    QTest.mouseDClick(v, Qt.LeftButton, Qt.NoModifier, QPoint(50, 50))
    b = v.provider.scene().bounds
    assert s.zc == pytest.approx((b[2] + b[5]) / 2) and not v.follow


def test_the_depth_line_tool_sets_the_alignment_from_two_clicks(win, app):
    panel = open_view(win, app, "depth")
    v = panel.view
    button(panel, "Pick line on plan...").click()
    tool = win.canvas.tool
    assert tool.name == "depth_line" and win.tool_acts["depth_line"].isChecked()
    # exact coordinates through the command line route: drawn south -> north, so the view looks WEST
    tool.enter_coordinate(2552800.0, 6967100.0)
    assert tool.a == (2552800.0, 6967100.0) and win.canvas.tool is tool
    tool.enter_coordinate(2552800.0, 6967300.0)
    assert win.canvas.tool.name == "select" and tool.a is None
    assert v.spec.azimuth == pytest.approx(270.0) and v.spec.center == pytest.approx((2552800.0, 6967200.0))
    assert not v.follow and v.station_offset == pytest.approx(100.0)
    assert v.spec.scale == pytest.approx(v.width() / (200.0 * 1.12), rel=1e-6)                              # the line spans the window
    poly = v.spec.plan_polygon(v.width())                                         # the slab lies WEST of the line (the line's left)
    assert poly[:, 0].max() <= 2552800.0 + 1e-6 and poly[:, 0].min() < 2552800.0 - 10
    # the same by clicking on the plan: drawn west -> east, so the view looks NORTH
    button(panel, "Pick line on plan...").click()
    ax, ay, bx, by = 2552650.0, 6967100.0, 2552950.0, 6967100.0
    click_world(win, ax, ay)
    click_world(win, bx, by)
    assert win.canvas.tool.name == "select"
    assert v.spec.azimuth == pytest.approx(0.0, abs=6.0) or abs(v.spec.azimuth - 360.0) < 6.0         # snapping may nudge the ends a little
    assert v.spec.center[0] == pytest.approx((ax + bx) / 2, abs=25.0)
    # Esc cancels a half-drawn line
    button(panel, "Pick line on plan...").click()
    tool = win.canvas.tool
    click_world(win, ax, ay)
    assert tool.a is not None
    QTest.keyClick(win.canvas, Qt.Key_Escape)
    assert tool.a is None
    win.set_tool("select")


def test_the_depth_view_draws_something_for_every_bearing(win, app):
    panel = open_view(win, app, "depth")
    v = panel.view
    v.fit()
    seen = []
    for az in (0, 45, 90, 135, 180, 225, 270, 315):
        v.set_azimuth(az)
        v.fit()
        seen.append(colour_pixels(v, (120, 190, 140), 30))
    assert min(seen) > 100, seen


# ------------------------------------------------------------------------------------------------ menus and Google Maps
def test_the_new_commands_are_in_the_menus_and_toolbars(win, app):
    texts = {a.text() for m in win.menuBar().findChildren(QMenu) for a in m.actions()}
    for t in ("&3D View", "&Depth View", "Depth Line", "Open View Center in &Google Maps (Satellite)",
              "Copy Google Maps &Link for View Center"):
        assert t in texts, t
    toolbar_actions = {a for tb in win.findChildren(QToolBar) for a in tb.actions()}
    assert win.a_3d in toolbar_actions and win.a_depth in toolbar_actions and win.a_gmaps in toolbar_actions
    assert win.a_gmaps.shortcut().toString() == "Ctrl+Shift+M" and win.a_3d.shortcut().toString() == "Ctrl+3"


def test_google_maps_opens_the_center_of_the_plan_view(win, app, auto, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    cv, pr = win.canvas, win.state.project
    lon, lat = maps.view_center_lonlat(pr, cv.view.cx, cv.view.cy)
    win.a_gmaps.trigger()
    assert len(opened) == 1
    url = opened[0]
    assert url.startswith("https://www.google.com/maps/place/") and url.endswith("/data=!3m1!1e3")      # satellite, with a pin
    assert f"{lat:.7f},{lon:.7f}" in url and 32.7 < lat < 32.9 and -96.7 < lon < -96.5
    z1 = float(url.split("@")[1].split(",")[2].split("z")[0])
    expect = maps.zoom_for_meters_per_pixel(maps.meters_per_pixel(cv.view.scale, pr.h_unit), lat)
    assert z1 == pytest.approx(round(expect, 2), abs=0.006)
    # the centre follows the view: pan the plan and the link moves with it; zoom in 2x and the zoom level rises by one
    cv.pan_pixels(-200, 0)
    cv.zoom_at(cv.width() / 2, cv.height() / 2, 2.0)
    win.a_gmaps.trigger()
    lon2, lat2 = maps.view_center_lonlat(pr, cv.view.cx, cv.view.cy)
    assert f"{lat2:.7f},{lon2:.7f}" in opened[1] and opened[1] != url
    z2 = float(opened[1].split("@")[1].split(",")[2].split("z")[0])
    assert z2 == pytest.approx(maps.zoom_for_meters_per_pixel(maps.meters_per_pixel(cv.view.scale, pr.h_unit), lat2), abs=0.006)
    assert z2 > z1 + 0.9
    win.a_gmaps_map.trigger()                                                    # the street map layer: no satellite switch
    assert "data=!3m1!1e3" not in opened[2] and opened[2].startswith("https://www.google.com/maps/place/")


def test_google_maps_copy_link_and_no_browser_fallback(win, app, auto, monkeypatch):
    opened, logged = [], []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    win.state.message.connect(lambda level, text: logged.append((level, text)))
    win.a_gmaps_copy.trigger()                                                   # copy only: the browser is not started
    assert not opened
    link = QGuiApplication.clipboard().text()
    assert link.startswith("https://www.google.com/maps/place/")
    assert any("copied" in t and link in t for _, t in logged)
    QGuiApplication.clipboard().setText("")
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: False))      # no browser available
    logged.clear()
    win.a_gmaps.trigger()
    assert QGuiApplication.clipboard().text() == link                            # the link is on the clipboard instead
    assert any(level == "warn" and "clipboard" in t for level, t in logged)


def test_google_maps_needs_a_real_coordinate_system(win, app, auto, monkeypatch):
    opened = []
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toString()) or True))
    win.state.set_project(Project("Local job"))                                  # local coordinates: no location on earth
    win.a_gmaps.trigger()
    assert not opened
    assert any("local coordinate system" in b for b in auto["boxes"])
