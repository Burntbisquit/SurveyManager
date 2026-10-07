"""Unit tests for Phase 1: Error point editing, point baseline tracking, and interactive QA resolution."""
from __future__ import annotations

import math
import pytest
from PySide6.QtWidgets import QApplication

from plumbline.core.model import ImportBatch, SurveyPoint
from plumbline.core.project import Project
from plumbline.core import provenance as PROV
from plumbline.ui.app_state import AppState
from plumbline.ui.check_dock import (CheckFieldworkDock, DuplicateResolveDialog,
                                     DescriptionFixDialog, LineRepairDialog,
                                     auto_fix_descriptions)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_survey_point_baseline_tracking_and_revert():
    """Verify original state tracking on SurveyPoint when modified and reverted."""
    p = SurveyPoint(id=1, number="101", x=5000.0, y=10000.0, z=125.5, desc="IPF", layer="PROP")
    p.set_original_state()

    assert not p.is_modified
    assert p.orig_number == "101"
    assert p.orig_x == 5000.0
    assert p.orig_y == 10000.0
    assert p.orig_z == 125.5
    assert p.orig_desc == "IPF"
    assert p.orig_layer == "PROP"
    assert p.delta_xy == 0.0

    # Modify position and description
    p.x = 5003.0
    p.y = 10004.0
    p.desc = "1/2 IPF"
    assert p.is_modified
    assert p.delta_xy == pytest.approx(5.0)

    # Revert back to original state
    p.revert_to_original()
    assert not p.is_modified
    assert p.x == 5000.0
    assert p.y == 10000.0
    assert p.desc == "IPF"
    assert p.delta_xy == 0.0


def test_project_add_point_initializes_original_state():
    """Points added to a project should have their original baseline state initialized."""
    pr = Project("Test")
    p = pr.add_point(100.0, 200.0, 50.0, desc="EOP", number="1")
    assert "orig_x" in p.attrs
    assert p.orig_x == 100.0
    assert p.orig_y == 200.0
    assert p.orig_z == 50.0
    assert p.orig_desc == "EOP"
    assert p.orig_number == "1"
    assert not p.is_modified


def test_apply_batch_initializes_original_state_and_keeps_source_number():
    pr = Project("Batch")
    pr.add_point(0.0, 0.0, 1.0, number="10", desc="CONTROL")
    imported = SurveyPoint(id=0, number="10", x=12.0, y=34.0, z=56.0,
                           desc="EP ST", layer="FIELD")

    result = pr.apply_batch(ImportBatch(points=[imported]), dup_policy="renumber",
                            layer_override="IMPORTED", code_layers=False)
    point = pr.points[result["point_ids"][0]]

    assert point.number == "11"
    assert point.orig_number == "10"
    assert point.orig_x == 12.0
    assert point.orig_y == 34.0
    assert point.orig_z == 56.0
    assert point.orig_desc == "EP ST"
    assert point.orig_layer == "IMPORTED"
    assert point.is_modified  # the project renumbering remains visible as a modification


def test_apply_batch_overwrite_tracks_changes_to_legacy_points():
    pr = Project("Overwrite")
    point = pr.add_point(1.0, 2.0, 3.0, number="20", desc="OLD")
    point.attrs.clear()  # simulate an older project without a saved baseline
    incoming = SurveyPoint(id=0, number="20", x=4.0, y=5.0, z=6.0, desc="NEW")

    pr.apply_batch(ImportBatch(points=[incoming]), dup_policy="overwrite", code_layers=False)

    assert point.orig_x == 1.0
    assert point.orig_y == 2.0
    assert point.orig_z == 3.0
    assert point.orig_desc == "OLD"
    assert point.is_modified


def test_is_modified_detects_nan_elevation_transitions():
    finite = SurveyPoint(id=1, number="1", x=0.0, y=0.0, z=12.0)
    finite.set_original_state()
    finite.z = math.nan
    assert finite.is_modified
    finite.z = 12.0
    assert not finite.is_modified

    missing = SurveyPoint(id=2, number="2", x=0.0, y=0.0, z=math.nan)
    missing.set_original_state()
    missing.z = 8.0
    assert missing.is_modified
    missing.z = math.nan
    assert not missing.is_modified


def test_provenance_value_tracking():
    """Test provenance helper values for modified and shift fields."""
    p = SurveyPoint(id=1, number="1", x=100.0, y=200.0, z=50.0, desc="EOP", layer="POINTS")
    p.set_original_state()
    assert PROV.value(p, "modified") == "No"
    assert PROV.value(p, "orig_coords") == ""
    assert PROV.value(p, "delta_xy") == ""

    p.x = 103.0
    p.y = 204.0
    assert PROV.value(p, "modified") == "Yes"
    assert "N 200.000" in PROV.value(p, "orig_coords")
    assert PROV.value(p, "delta_xy") == "5.000"


def test_auto_fix_descriptions(qapp):
    """Test batch auto-fixing common typos against vocabulary with undo support."""
    state = AppState(Project("Test"))
    pr = state.project
    p1 = pr.add_point(100.0, 100.0, 0.0, desc="ipf 1/2 pin", number="1")
    p2 = pr.add_point(100.0, 200.0, 0.0, desc="REBAR5/8", number="2")
    p3 = pr.add_point(100.0, 300.0, 0.0, desc="EOP.", number="3")
    p4 = pr.add_point(100.0, 400.0, 0.0, desc="CORNER", number="4")

    code_set = {"IPF", "REBAR", "EOP"}
    fixed = auto_fix_descriptions(state, code_set)
    assert fixed == 3
    assert p1.desc == "IPF 1/2 pin"
    assert p2.desc == "REBAR 5/8"
    assert p3.desc == "EOP"
    assert p4.desc == "CORNER"

    # Undo restores project state
    state.undo()
    assert state.project.points[p1.id].desc == "ipf 1/2 pin"
    assert state.project.points[p2.id].desc == "REBAR5/8"
    assert state.project.points[p3.id].desc == "EOP."


def test_duplicate_resolve_dialog_renumber(qapp):
    """Test renumbering duplicate points via DuplicateResolveDialog."""
    state = AppState(Project("Test"))
    pr = state.project
    p1 = pr.add_point(100.0, 100.0, 10.0, desc="IPF", number="100")
    p2 = pr.add_point(100.0, 100.0, 10.0, desc="IPF", number="100")

    dlg = DuplicateResolveDialog(state, [p1.id, p2.id])
    dlg.rb_renumber.setChecked(True)
    dlg._apply()

    assert p1.number == "100"
    assert p2.number == "1000"


def test_duplicate_resolve_dialog_keep_first_and_average(qapp):
    """Test delete and coordinate averaging in DuplicateResolveDialog."""
    state = AppState(Project("Test"))
    pr = state.project
    p1 = pr.add_point(100.0, 100.0, 10.0, desc="IPF", number="100")
    p2 = pr.add_point(106.0, 108.0, 20.0, desc="IPF", number="100")

    # Average
    dlg = DuplicateResolveDialog(state, [p1.id, p2.id])
    dlg.rb_average.setChecked(True)
    dlg._apply()

    assert len(pr.points) == 1
    p_rem = next(iter(pr.points.values()))
    assert p_rem.x == pytest.approx(103.0)
    assert p_rem.y == pytest.approx(104.0)
    assert p_rem.z == pytest.approx(15.0)


def test_description_fix_dialog(qapp):
    """Test interactive description fixer dialog with fuzzy match and batch actions."""
    state = AppState(Project("Test"))
    pr = state.project
    p1 = pr.add_point(100.0, 100.0, 0.0, desc="IP", number="1")
    p2 = pr.add_point(100.0, 200.0, 0.0, desc="eop st", number="2")

    vocab = {"IPF", "EOP"}
    dlg = DescriptionFixDialog(state, [p1.id, p2.id], vocabulary=vocab)
    assert dlg.tbl.rowCount() == 2
    # Suggested fix for IP should be IPF
    assert dlg.tbl.item(0, 3).text() == "IPF"

    dlg._apply_all_suggested()
    dlg._apply()

    assert p1.desc == "IPF"
    assert p2.desc == "EOP st"


def test_line_repair_dialog(qapp):
    """Test linework repair dialog adding ST/END codes."""
    state = AppState(Project("Test"))
    pr = state.project
    p1 = pr.add_point(10.0, 10.0, 0.0, desc="EP", number="1")
    p2 = pr.add_point(20.0, 20.0, 0.0, desc="EP", number="2")
    p3 = pr.add_point(30.0, 30.0, 0.0, desc="EP", number="3")

    dlg = LineRepairDialog(state, [p1.id, p2.id, p3.id])
    assert dlg.tbl.rowCount() == 3
    # Proposed for first is EP ST, last is EP END
    dlg._apply()

    assert p1.desc == "EP ST"
    assert p2.desc == "EP"
    assert p3.desc == "EP END"


def test_check_dock_action_buttons(qapp):
    """Test that CheckFieldworkDock generates action buttons for findings."""
    state = AppState(Project("Test"))
    pr = state.project
    pr.add_point(100.0, 100.0, 0.0, desc="UNKNOWN_CODE", number="1")
    pr.add_point(100.0, 100.0, 0.0, desc="UNKNOWN_CODE", number="1")

    dock = CheckFieldworkDock(state)
    dock.code_set = {"IPF", "EOP"}
    dock.run(store=False)

    assert dock.tbl.columnCount() == 5
    assert dock.tbl.horizontalHeaderItem(4).text() == "Action"
