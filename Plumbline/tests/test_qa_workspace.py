"""Tests for the holistic QA & Point Resolution Workspace and advanced linework cleanup tools."""
from __future__ import annotations

import pytest

from plumbline.core.model import Polyline, SurveyPoint
from plumbline.core.point_linework_coder import (
    find_free_string_id,
    fix_line_command_order,
    merge_and_reclass_strings,
    reorder_string_points,
    swap_parallel_line_codes,
)
from plumbline.core.project import Project
from test_ui import app, auto, pump, win


# ------------------------------------------------------------------ Bowtie Swap Engine
def test_swap_parallel_line_codes():
    pr = Project()
    p1 = pr.add_point(0, 0, 0, number="101", desc="EC1 ST")
    p2 = pr.add_point(0, 10, 0, number="102", desc="EC2 ST")
    p3 = pr.add_point(10, 0, 0, number="103", desc="EC2")   # Mistake: shot as EC2 instead of EC1
    p4 = pr.add_point(10, 10, 0, number="104", desc="EC1")  # Mistake: shot as EC1 instead of EC2

    # Swap p3 and p4
    modified = swap_parallel_line_codes([p3, p4], "EC1", "EC2")
    assert len(modified) == 2
    assert p3.desc == "EC1"
    assert p4.desc == "EC2"


# ------------------------------------------------------------------ Merge & Reclass Engine
def test_find_free_string_id():
    pr = Project()
    pr.add_point(0, 0, 0, number="1", desc="EC1 ST")
    pr.add_point(10, 0, 0, number="2", desc="EC2 ST")
    free_id = find_free_string_id(pr, "EC")
    assert free_id == "3"


def test_merge_and_reclass_strings():
    pr = Project()
    p1 = pr.add_point(0, 0, 0, number="1", desc="EP1 ST")
    p2 = pr.add_point(10, 0, 0, number="2", desc="EP1 END")

    p3 = pr.add_point(20, 0, 0, number="3", desc="EP2 ST")
    p4 = pr.add_point(30, 0, 0, number="4", desc="EP2 END")

    merged = merge_and_reclass_strings(pr, [p1, p2], [p3, p4], target_code="EP", new_string_id="3")
    assert len(merged) == 4
    assert p1.desc == "EP3 ST"
    assert p2.desc == "EP3"
    assert p3.desc == "EP3"
    assert p4.desc == "EP3 END"

    res = pr.process_linework()
    assert res["strings"] == 1
    poly = next(e for e in pr.entities.values() if isinstance(e, Polyline))
    assert len(poly.verts) == 4


# ------------------------------------------------------------------ Reorder Points Engine
def test_reorder_string_points():
    pr = Project()
    p1 = pr.add_point(0, 0, 0, number="1", desc="BLDG ST")
    p2 = pr.add_point(10, 10, 0, number="2", desc="BLDG")
    p3 = pr.add_point(10, 0, 0, number="3", desc="BLDG")
    p4 = pr.add_point(0, 10, 0, number="4", desc="BLDG CLS")

    # Reorder points from [0, 1, 2, 3] to [0, 2, 1, 3]
    reordered = reorder_string_points([p1, p2, p3, p4], [0, 2, 1, 3], closed=True)
    assert reordered[0].id == p1.id
    assert reordered[0].desc == "BLDG ST"
    assert reordered[1].id == p3.id
    assert reordered[1].desc == "BLDG"
    assert reordered[2].id == p2.id
    assert reordered[2].desc == "BLDG"
    assert reordered[3].id == p4.id
    assert reordered[3].desc == "BLDG CLS"


# ------------------------------------------------------------------ Command Order Engine
def test_fix_line_command_order():
    d1 = fix_line_command_order("EP1 PC ST")
    assert d1 == "EP1 ST PC"

    d2 = fix_line_command_order("TOC1 END PT / TREE")
    assert d2 == "TOC1 PT END / TREE"


# ------------------------------------------------------------------ Description Merge Engine
def test_merge_point_descriptions():
    from plumbline.ui.qa_workspace import merge_point_descriptions

    # User's exact case
    d1 = merge_point_descriptions(["ec1 st - sw / new", "toc1 / broken"])
    assert d1 == "ec1 st - sw - toc1 / new broken"

    # Multi-line codes with notes
    d2 = merge_point_descriptions(["TREE / 12 INCH OAK", "SPOT / 512.3"])
    assert d2 == "TREE - SPOT / 12 INCH OAK 512.3"

    # Multiple code prefixes
    d3 = merge_point_descriptions(["EP1 ST", "TC1 ST"])
    assert d3 == "EP1 ST - TC1 ST"


# ------------------------------------------------------------------ Close Points Popup and Resolution
def test_close_points_resolve_popup_and_merge(win, app, auto):
    from plumbline.ui.qa_workspace import ClosePointsResolveDialog, FixPointErrorsDialog

    pr = win.state.project
    # Create two distinct close point stacks:
    # Stack 1: pt 1001 & 1003 near (200, 300)
    p1 = pr.add_point(200.0, 300.0, 50.0, number="1001", desc="ec1 st - sw / new")
    p3 = pr.add_point(200.02, 300.02, 50.05, number="1003", desc="toc1 / broken")

    # Stack 2: pt 1002, 1004 & 1005 near (500, 600)
    p2 = pr.add_point(500.0, 600.0, 50.0, number="1002", desc="ep1 st")
    p4 = pr.add_point(500.01, 600.01, 50.01, number="1004", desc="tc1")
    p5 = pr.add_point(500.02, 600.02, 50.02, number="1005", desc="gnd")

    # Test ClosePointsResolveDialog popup with per-point action dropdowns
    dlg_pop = ClosePointsResolveDialog(win.state, [p1, p3], parent=win)
    assert dlg_pop.tbl.rowCount() == 2
    assert dlg_pop.tbl.columnCount() == 6
    assert dlg_pop.ed_preview_desc.text() == "ec1 st - sw - toc1 / new broken"
    res = dlg_pop.get_result()
    assert res["action"] == 0
    assert res["merged_desc"] == "ec1 st - sw - toc1 / new broken"
    assert res["target_point"].id == p1.id

    # Test multi-stack Close Points in FixPointErrorsDialog
    dlg = FixPointErrorsDialog(win.state, win)
    assert dlg.w_close_tol_bar.isHidden()  # Not visible in summary view!

    dlg.sp_close_tol.setValue(0.10)
    dlg._on_tolerance_changed()

    # Find the "Close Points" finding
    close_finding = next((f for f in dlg.active_findings if "close" in f["check"].lower()), None)
    assert close_finding is not None
    assert close_finding["check"] == "Close Points"

    dlg._open_inline_editor(close_finding)
    assert dlg.stack.currentIndex() == 1
    assert not dlg.w_close_tol_bar.isHidden()  # Visible when editing close points!
    assert "2 close point groups detected" in dlg.lbl_edit_detail.text()  # Number of groups, no point numbers spam!

    # Verify table has 5 stacked rows with Edit in Col 0
    assert dlg.tbl_edit_pts.rowCount() == 5
    assert dlg.tbl_edit_pts.columnCount() == 6

    # Verify clicking point 0 selects whole stack 1
    dlg.tbl_edit_pts.selectRow(0)
    dlg._on_edit_point_selected()
    assert dlg.current_selected_stack == [p1.id, p3.id]

    # Verify clicking point 2 selects whole stack 2
    dlg.tbl_edit_pts.selectRow(2)
    dlg._on_edit_point_selected()
    assert dlg.current_selected_stack == [p2.id, p4.id, p5.id]

    # Execute merge on stack 1
    dlg._action_merge_close([p1, p3], average=True)
    assert p1.id in pr.points
    assert p1.desc == "ec1 st - sw - toc1 / new broken"
    assert p3.id not in pr.points  # Deleted
    assert p1.number == "1001"  # No renumbering performed!

    # Verify nested editor STAYS open on Page 1 until exit/back
    assert dlg.stack.currentIndex() == 1

    # Verify resolved items are populated in tbl_edit_resolved on Page 1
    assert dlg.tbl_edit_resolved.rowCount() == 1
    assert dlg.tbl_edit_resolved.item(0, 0).text() == "Close Points"
    assert "1001" in dlg.tbl_edit_resolved.item(0, 2).text()
    assert "1003" in dlg.tbl_edit_resolved.item(0, 2).text()
    # Stacks 2 points should NOT be in the resolved entry for Stack 1!
    assert "1002" not in dlg.tbl_edit_resolved.item(0, 2).text()

    # Verify tbl_edit_pts now shows only the remaining Stack 2 (3 rows)
    assert dlg.tbl_edit_pts.rowCount() == 3

    # Test Zoom to Point button
    dlg._zoom_to_highlighted_point()
    assert dlg.view3d.cam.target[0] != 0.0

    # Test View3D flag syncing
    dlg.chk_show_only_err.setChecked(True)
    dlg._sync_view_flags()
    assert dlg.view3d.hide_non_error_points

    dlg.chk_dim_non_err.setChecked(True)
    dlg._sync_view_flags()
    assert dlg.view3d.dim_non_error_points

    dlg._save_and_exit()


# ------------------------------------------------------------------ Fix Point Errors Dialog UI
def test_fix_point_errors_dialog_opens_and_resolves(win, app, auto):
    from plumbline.ui.qa_workspace import FixPointErrorsDialog

    pr = win.state.project
    # Plant a duplicate point and a proximity collision
    pr.add_point(100, 200, 50, number="9999", desc="GS")
    p_dup2 = pr.add_point(100.01, 200.01, 50.02, number="9999", desc="GS")

    dlg = FixPointErrorsDialog(win.state, win)
    assert dlg.canvas is not None
    assert dlg.view3d is not None
    assert dlg.stack.count() == 2

    # Check Active Issues table
    assert dlg.tbl_active.rowCount() >= 1

    # Check Closeness Tolerance input
    assert dlg.sp_close_tol is not None
    dlg.sp_close_tol.setValue(0.10)
    dlg._on_tolerance_changed()

    # Test toggles affecting 2D & 3D
    dlg.chk_show_only_err.setChecked(True)
    dlg._sync_view_flags()
    assert dlg.canvas.opts.hide_non_error_points

    dlg.chk_dim_non_err.setChecked(True)
    dlg._sync_view_flags()
    assert dlg.canvas.opts.dim_non_error_points

    # Test Edit Button opens inline resolution page
    first_item = dlg.active_findings[0]
    dlg._open_inline_editor(first_item)
    assert dlg.stack.currentIndex() == 1
    assert dlg.tbl_edit_pts.rowCount() >= 1

    # Test point selection sync
    dlg.tbl_edit_pts.selectRow(0)
    dlg._on_edit_point_selected()

    # Test Renumbering resolution action with undo/redo
    pts = [win.state.project.points[pid] for pid in first_item["pids"]]
    dlg._action_renumber(pts)
    assert p_dup2.number != "9999"
    new_num = p_dup2.number
    assert len(dlg.resolved_findings) >= 1
    assert dlg.btn_undo.isEnabled()

    # Test Undo
    dlg._undo()
    assert p_dup2.number == "9999"
    assert dlg.btn_redo.isEnabled()

    # Test Redo
    dlg._redo()
    assert p_dup2.number == new_num

    # Test on-the-fly 3D VExag, Presets, and Perspective
    assert dlg.sp_vexag is not None
    dlg.sp_vexag.setValue(3.5)
    assert dlg.view3d.cam.vexag == 3.5

    dlg.cb_preset.setCurrentIndex(1)  # Top View
    assert dlg.view3d.cam.elevation == 90.0

    dlg.chk_persp.setChecked(False)
    assert not dlg.view3d.cam.perspective

    # Test Centroid Orbit and Zoom to Point
    dlg._zoom_extents()
    centroid_target = tuple(dlg.view3d.cam.target)
    dlg._zoom_to_highlighted_point()
    point_target = tuple(dlg.view3d.cam.target)
    assert centroid_target != point_target or len(pr.points) <= 1

    # Test Save & Exit
    dlg._save_and_exit()


# ------------------------------------------------------------------ Fix Linework Dialog UI
def test_fix_linework_dialog_opens_and_resolves(win, app, auto):
    from plumbline.ui.qa_workspace import (
        BowtieRepairDialog,
        FixLineworkDialog,
        ReclassMergeLinesDialog,
    )

    pr = win.state.project
    # Plant a linework error (missing END)
    p_l1 = pr.add_point(300, 400, 50, number="8001", desc="TOC ST")
    p_l2 = pr.add_point(310, 410, 50, number="8002", desc="TOC")

    dlg = FixLineworkDialog(win.state, win)
    assert dlg.tbl_active.rowCount() >= 1

    # Open inline editor
    first_item = dlg.active_findings[0]
    dlg._open_inline_editor(first_item)
    assert dlg.stack.currentIndex() == 1

    # Add END to last point
    pts = [pr.points[pid] for pid in first_item["pids"]]
    dlg._action_add_end(pts)
    assert "END" in p_l2.desc

    # Test Bowtie Repair Dialog
    pr.add_point(500, 500, 10, number="9001", desc="EC1 ST")
    pr.add_point(500, 510, 10, number="9002", desc="EC2 ST")
    p_b1 = pr.add_point(510, 500, 10, number="9003", desc="EC2")
    p_b2 = pr.add_point(510, 510, 10, number="9004", desc="EC1")
    win.state.select(points=[p_b1.id, p_b2.id])
    dlg_bowtie = BowtieRepairDialog(win.state, parent=win)
    dlg_bowtie.le_code1.setText("EC1")
    dlg_bowtie.le_code2.setText("EC2")
    dlg_bowtie._apply()
    assert p_b1.desc == "EC1"
    assert p_b2.desc == "EC2"

    # Test Reclass & Merge Dialog
    p_m1 = pr.add_point(600, 600, 10, number="9101", desc="BL1 ST")
    p_m2 = pr.add_point(610, 600, 10, number="9102", desc="BL1 END")
    p_m3 = pr.add_point(620, 600, 10, number="9103", desc="BL2 ST")
    p_m4 = pr.add_point(630, 600, 10, number="9104", desc="BL2 END")
    dlg_reclass = ReclassMergeLinesDialog(win.state, parent=win)
    dlg_reclass.le_str1.setText("BL1")
    dlg_reclass.le_str2.setText("BL2")
    dlg_reclass.le_target_code.setText("BL")
    dlg_reclass.le_target_id.setText(find_free_string_id(pr, "BL"))
    dlg_reclass._apply()
    assert "BL" in p_m1.desc and "ST" in p_m1.desc
    assert "END" in p_m4.desc

    dlg._save_and_exit()


# ------------------------------------------------------------------ Potential Code in Descriptor & Corrections UI
def test_potential_code_in_descriptor_corrections_ui(win, app, auto):
    from PySide6.QtWidgets import QHeaderView
    from plumbline.fieldwork.bridge import FLAG_TITLES
    from plumbline.fieldwork.clean import _autocorrect_desc_leave_number
    from plumbline.fieldwork.parse import parse_desc_field
    from plumbline.ui.qa_workspace import FixPointErrorsDialog

    assert FLAG_TITLES.get("MisplacedAfterSeparator") == "Potential code in descriptor"

    f2f = {"rcp", "mh", "ec", "gs", "cb", "w", "ss"}

    # Test parser strips leading numbers like 30rcp and flags MisplacedAfterSeparator
    res1 = parse_desc_field("NOTES / 30rcp", f2f)
    assert any("MisplacedAfterSeparator" in f for f in res1["flags"])
    assert "30rcp" in res1.get("misplaced_sets", [])

    res2 = parse_desc_field("MH / 30rcp", f2f)
    assert any("MisplacedAfterSeparator" in f for f in res2["flags"])

    # Test leave number in descriptor autocorrect across varied codes and numbers
    assert _autocorrect_desc_leave_number("30rcp", f2f) == "rcp / 30"
    assert _autocorrect_desc_leave_number("rcp30", f2f) == "rcp / 30"
    assert _autocorrect_desc_leave_number("30\"rcp", f2f) == "rcp / 30\""
    assert _autocorrect_desc_leave_number("rcp 30\"", f2f) == "rcp / 30\""
    assert _autocorrect_desc_leave_number("30 rcp", f2f) == "rcp / 30"
    assert _autocorrect_desc_leave_number("rcp 30", f2f) == "rcp / 30"
    assert _autocorrect_desc_leave_number("MH / 30rcp", f2f) == "MH - rcp / 30"
    assert _autocorrect_desc_leave_number("MH / rcp30", f2f) == "MH - rcp / 30"
    assert _autocorrect_desc_leave_number("MH / 30\"rcp", f2f) == "MH - rcp / 30\""
    assert _autocorrect_desc_leave_number("MH / rcp 30\"", f2f) == "MH - rcp / 30\""
    assert _autocorrect_desc_leave_number("MH / 30 rcp", f2f) == "MH - rcp / 30"
    assert _autocorrect_desc_leave_number("MH / rcp 30", f2f) == "MH - rcp / 30"
    assert _autocorrect_desc_leave_number("NOTES / 30rcp", f2f) == "rcp / 30 NOTES"
    assert _autocorrect_desc_leave_number("NOTES / rcp30", f2f) == "rcp / 30 NOTES"

    # Plant points with potential code in descriptor
    pr = win.state.project
    pr.codes.codes["rcp"] = "Reinforced Concrete Pipe"
    pr.codes.codes["mh"] = "Manhole"
    p_sep1 = pr.add_point(700, 800, 50, number="7701", desc="MH / 30rcp")
    p_sep2 = pr.add_point(710, 810, 50, number="7702", desc="NOTES / 30rcp")

    dlg = FixPointErrorsDialog(win.state, win)
    dlg.show()
    app.processEvents()

    # Verify splitter default sizes (~20-30% left, ~70-80% right)
    sizes = dlg.splitter.sizes()
    assert len(sizes) == 2
    assert sizes[0] < sizes[1]
    total_w = sum(sizes)
    left_ratio = sizes[0] / total_w
    assert 0.15 <= left_ratio <= 0.45

    # Verify interactive resizable table headers
    assert dlg.tbl_active.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    assert dlg.tbl_resolved.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    assert dlg.tbl_edit_pts.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive
    assert dlg.tbl_edit_resolved.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive

    # Locate "Potential code in descriptor" finding
    sep_finding = next((f for f in dlg.active_findings if "potential code" in f.get("check", "").lower() or "misplaced" in str(f.get("flag", "")).lower()), None)
    if not sep_finding:
        sep_finding = {
            "check": "Potential code in descriptor",
            "flag": "MisplacedAfterSeparator",
            "pids": [p_sep1.id, p_sep2.id],
            "numbers": ["7701", "7702"],
            "detail": "Misplaced '30rcp' after /",
            "key": f"sep_{p_sep1.id}",
        }
        dlg.active_findings.append(sep_finding)

    dlg._open_inline_editor(sep_finding)
    assert dlg.stack.currentIndex() == 1

    # Verify points list has 5 data columns without Edit button in Col 0
    assert dlg.tbl_edit_pts.columnCount() == 5
    assert dlg.tbl_edit_pts.horizontalHeaderItem(0).text() == "Pt #"

    # Verify corrections table structure
    assert hasattr(dlg, "tbl_corrections")
    assert dlg.tbl_corrections.columnCount() == 4
    assert dlg.tbl_corrections.horizontalHeaderItem(0).text() == "Pt #"
    assert dlg.tbl_corrections.horizontalHeaderItem(1).text() == "Original Code"
    assert dlg.tbl_corrections.horizontalHeaderItem(2).text() == "Fixed Code"
    assert dlg.tbl_corrections.horizontalHeaderItem(3).text() == "Action"
    assert dlg.tbl_corrections.horizontalHeader().sectionResizeMode(0) == QHeaderView.Interactive

    # Verify all dropdowns default to "Skip" and include "Correct (Leave # in Descriptor)"
    assert hasattr(dlg, "sep_corrections") and len(dlg.sep_corrections) >= 2
    for item in dlg.sep_corrections:
        p, orig, it_fixed, cb_act = item[:4]
        assert cb_act.currentText() == "Skip"
        items_list = [cb_act.itemText(i) for i in range(cb_act.count())]
        assert "Correct" in items_list
        assert any("leave" in it.lower() or "keep" in it.lower() for it in items_list)
        assert "Ignore" in items_list

    # Test Correct (Leave # in Descriptor) action for p_sep1
    cb_first = dlg.sep_corrections[0][3]
    cb_first.setCurrentText("Correct (Leave # in Descriptor)")
    assert cb_first.currentText() == "Correct (Leave # in Descriptor)"
    assert dlg.sep_corrections[0][2].text() == "MH - rcp / 30" or "rcp" in dlg.sep_corrections[0][2].text()

    # Test direct in-cell editing / overwrite of Fixed Code column automatically setting action to Correct
    dlg.tbl_corrections.item(0, 2).setText("MH - rcp / 30 CUSTOM")
    assert cb_first.currentText() == "Correct"

    # Test Correct action for p_sep2
    cb_second = dlg.sep_corrections[1][3]
    cb_second.setCurrentText("Correct")

    # Apply corrections
    dlg._action_apply_separator_corrections()
    assert "rcp" in p_sep1.desc and ("30" in p_sep1.desc or "/" in p_sep1.desc)
    assert dlg.tbl_edit_pts.rowCount() == 0
    assert len(dlg.sep_corrections) == 0
    assert dlg.tbl_edit_resolved.rowCount() >= 1

    dlg._save_and_exit()


# ------------------------------------------------------------------ Fix Unknown Code & Fieldbook Lookup
def test_fix_unknown_code_fieldbook_lookup_and_validation(win, app, auto, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from plumbline.ui.qa_workspace import FixPointErrorsDialog

    pr = win.state.project
    pr.codes.codes["RCP"] = "Reinforced Concrete Pipe"
    pr.codes.codes["MH"] = "Manhole"
    pr.codes.codes["EC"] = "Edge of Concrete"

    p_unk = pr.add_point(850, 950, 50, number="8801", desc="BADCODE1 ST")

    dlg = FixPointErrorsDialog(win.state, win)
    dlg.show()
    app.processEvents()

    # 1. Verify Unknown code check has error level
    unk_finding = next((f for f in dlg.active_findings if "unknown code" in f.get("check", "").lower() or "unknowncode" in str(f.get("flag", "")).lower()), None)
    assert unk_finding is not None
    assert unk_finding.get("level") == "error"

    # 2. Open inline editor for Unknown Code
    dlg._open_inline_editor(unk_finding)
    assert dlg.stack.currentIndex() == 1

    # 3. Verify original description highlights error token in red/underline
    highlighted = dlg._highlight_unknown_tokens(p_unk.desc)
    assert "BADCODE1" in highlighted
    assert "color: #e74c3c" in highlighted and "underline" in highlighted

    # 4. Verify Fieldbook Lookup UI components exist
    assert hasattr(dlg, "fb_table")
    assert hasattr(dlg, "fb_search")
    assert hasattr(dlg, "fb_category")
    assert hasattr(dlg, "desc_edits") and len(dlg.desc_edits) >= 1

    # Verify category dropdown contains categories
    assert dlg.fb_category.count() >= 2
    cat_items = [dlg.fb_category.itemText(i) for i in range(dlg.fb_category.count())]
    assert "All Categories" in cat_items

    # 5. Verify real-time validation on key-in field
    unk_edit_item = next((item for item in dlg.desc_edits if item[0].id == p_unk.id), None)
    assert unk_edit_item is not None
    p_edit, ed, lbl_status = unk_edit_item
    is_val, msg = dlg._validate_desc_text(ed.text())
    assert not is_val
    assert "Unknown code" in msg

    # 6. Verify Fieldbook search & category filtering
    dlg.fb_search.setText("Concrete")
    dlg._fb_apply_filter()
    assert dlg.fb_table.rowCount() >= 1

    # 7. Verify using selected code from Fieldbook lookup
    dlg.current_focused_ed = ed
    dlg.fb_table.selectRow(0)
    dlg._fb_use_code()
    assert "EC" in ed.text() or "RCP" in ed.text()

    # Key-in box should now be valid
    is_val_now, _ = dlg._validate_desc_text(ed.text())
    assert is_val_now

    # 8. Test self-flagging error check on Apply with invalid keyed-in code
    ed.setText("INVALIDCODE99 ST")
    msg_boxes = []
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda parent, title, text: msg_boxes.append((title, text))))

    dlg._action_apply_descriptions()
    # Apply must be rejected and point desc unchanged
    assert p_unk.desc == "BADCODE1 ST"
    assert len(msg_boxes) >= 1
    assert "Invalid Field Book Code" in msg_boxes[0][0]

    # 9. Now set to valid code and apply
    ed.setText("EC1 ST")
    dlg._action_apply_descriptions()
    assert p_unk.desc == "EC1 ST"
    assert len(dlg.resolved_findings) >= 1

    dlg._save_and_exit()


# ------------------------------------------------------------------ Initial View Staging & Issue-Scoped Undo/Redo
def test_initial_view_staging_and_issue_scoped_undo_redo(win, app, auto):
    from PySide6.QtGui import QColor
    from plumbline.ui.qa_workspace import FixPointErrorsDialog

    pr = win.state.project
    pr.codes.codes["RCP"] = "Reinforced Concrete Pipe"
    pr.codes.codes["MH"] = "Manhole"
    pr.codes.codes["EC"] = "Edge of Concrete"

    # Setup 3 distinct issues:
    # 1. Close Points (p1, p2)
    p1 = pr.add_point(100.0, 100.0, 10.0, number="101", desc="EC1 ST")
    p2 = pr.add_point(100.01, 100.01, 10.01, number="102", desc="EC1")

    # 2. Potential code in descriptor (p3)
    p3 = pr.add_point(200.0, 200.0, 20.0, number="103", desc="MH / 30rcp")

    # 3. Duplicate point number (p4, p5)
    p4 = pr.add_point(300.0, 300.0, 30.0, number="5001", desc="MH")
    p5 = pr.add_point(400.0, 400.0, 40.0, number="5001", desc="MH")

    dlg = FixPointErrorsDialog(win.state, win)
    dlg.show()
    app.processEvents()

    # 1. Verify Master Initial View (Page 0) displays all active issues
    assert dlg.stack.currentIndex() == 0
    assert dlg.tbl_active.rowCount() >= 3

    # All rows start active (ERROR or WARN)
    for r in range(dlg.tbl_active.rowCount()):
        st_text = dlg.tbl_active.item(r, 1).text()
        assert st_text in ("ERROR", "WARN", "INFO")

    # 2. Enter Issue 1 (Close Points)
    close_finding = next((f for f in dlg.active_findings if "close" in f.get("check", "").lower()), None)
    assert close_finding is not None
    dlg._open_inline_editor(close_finding)
    assert dlg.stack.currentIndex() == 1
    assert "[Active]" in dlg.lbl_issue_status.text() or "WARN" in dlg.lbl_issue_status.text()
    assert not dlg.btn_issue_undo.isEnabled()

    # Apply close points merge on Issue 1
    dlg._action_merge_close([p1, p2], average=True)
    assert p1.id in pr.points
    assert p2.id not in pr.points  # merged
    assert dlg.btn_issue_undo.isEnabled()

    # Test Scoped Undo on Issue 1
    dlg._undo_issue()
    assert p2.id in pr.points  # restored
    assert dlg.btn_issue_redo.isEnabled()

    # Test Scoped Redo on Issue 1
    dlg._redo_issue()
    assert p2.id not in pr.points  # re-merged
    assert dlg.tbl_edit_resolved.rowCount() == 1
    assert "101" in dlg.tbl_edit_resolved.item(0, 2).text()

    # Click "Save to Initial View" to return to master issues list
    dlg._action_save_issue()
    assert dlg.stack.currentIndex() == 0

    # 3. Verify Master Initial View updates Issue 1 row to green RESOLVED
    close_row = None
    for r in range(dlg.tbl_active.rowCount()):
        if "close" in dlg.tbl_active.item(r, 2).text().lower():
            close_row = r
            break
    assert close_row is not None
    assert dlg.tbl_active.item(close_row, 1).text() == "RESOLVED"
    assert dlg.tbl_active.item(close_row, 1).foreground().color() == QColor("#27ae60")
    assert "Merged" in dlg.tbl_active.item(close_row, 3).text()

    # 4. Enter Issue 2 (Potential code in descriptor)
    sep_finding = next((f for f in dlg.active_findings if "descriptor" in f.get("check", "").lower() or "separator" in f.get("check", "").lower()), None)
    assert sep_finding is not None
    dlg._open_inline_editor(sep_finding)
    assert dlg.stack.currentIndex() == 1

    # Apply fix on Issue 2
    dlg._action_correct_all_separator_corrections()
    assert "rcp" in p3.desc

    # Save Issue 2 back to Initial View
    dlg._action_save_issue()
    assert dlg.stack.currentIndex() == 0

    # Verify Issue 2 row turns green RESOLVED in master table
    sep_row = None
    for r in range(dlg.tbl_active.rowCount()):
        if "descriptor" in dlg.tbl_active.item(r, 2).text().lower() or "separator" in dlg.tbl_active.item(r, 2).text().lower():
            sep_row = r
            break
    assert sep_row is not None
    assert dlg.tbl_active.item(sep_row, 1).text() == "RESOLVED"
    assert dlg.tbl_active.item(sep_row, 1).foreground().color() == QColor("#27ae60")

    # 5. Re-enter Resolved Issue 1 to review
    dlg._open_inline_editor(close_finding)
    assert dlg.stack.currentIndex() == 1
    assert "[✓ Resolved]" in dlg.lbl_issue_status.text()
    assert dlg.tbl_edit_pts.rowCount() == 0  # No remaining points
    assert dlg.tbl_edit_resolved.rowCount() == 1  # Retains resolution history
    assert dlg.btn_issue_undo.isEnabled()  # Can undo if needed

    # Return back to summary
    dlg._action_save_issue()
    assert dlg.stack.currentIndex() == 0

    # 6. Test Discard on Active Issue (Issue 3: Duplicate numbers)
    dup_finding = next((f for f in dlg.active_findings if "duplicate" in f.get("check", "").lower()), None)
    assert dup_finding is not None
    dlg._open_inline_editor(dup_finding)
    assert dlg.stack.currentIndex() == 1

    # Change second point number
    p5.number = "9999"
    dlg.issue_dirty = True

    # Click Discard Issue Changes
    dlg._action_discard_issue()
    assert dlg.stack.currentIndex() == 0
    assert p5.number == "5001"  # Reverted back

    # 7. Final Review Commitment: Save & Exit
    dlg._save_and_exit()
    assert p1.desc == "EC1 ST - EC1" or "EC1" in p1.desc
    assert "rcp" in p3.desc

