"""Item 14, second half: the linework check and its three tools, in both windows.

A point check reads one description at a time.  A *line* is a sequence, and the two ends of one
mistake usually sit on two different points - so the issue is invisible to the description check
and the fix routinely clears something it was not aimed at.  These tests pin:

* the four ways a line can be incomplete, and that a finished line is not one of them;
* that a proposal is **placed** where the command order wants it (ST -> PC -> PT -> END/X), never
  appended, and that no proposal is invented when the description is not a single code;
* that a fix is **validated against the line** afterwards, and the answer names the second issue
  it cleared - and says so plainly when it cleared nothing;
* that a decision (Ignore) is written into the check report and read back, so a re-run does not
  reopen it;
* that the same reader serves the field window's Line Repair tab and the drawing window's Check
  Fieldwork dock, so the two cannot disagree about where a line ends;
* that the drawing side hears about it at all ("the field-side flags on the drawing side").

Qt-free where it can be: the engine tests import nothing from Qt, and the two window tests use the
same offscreen fixtures the other UI tests use.
"""
from __future__ import annotations

import pytest

from plumbline.fieldwork import linecheck as LC

from test_ui import app, auto, pump, win                              # noqa: E402  (the UI fixtures)

F2F = {"toc", "ec", "gs"}


def rows(*descs, first_oid=1):
    """Working rows (OID, Pt#, N, E, Z, Desc, Parent, Source) in file order."""
    return [[str(first_oid + i), str(first_oid + i), f"{1000.0 + i:.2f}", f"{2000.0 + i:.2f}",
             "500.00", d, "", ""]
            for i, d in enumerate(descs)]


def kinds(issues):
    return sorted(e["issue_type"] for e in issues)


# ------------------------------------------------------------------ the four issues
def test_each_way_a_line_can_be_incomplete_is_named():
    assert kinds(LC.detect_line_errors(rows("TOC PC"), f2f_set=F2F)) == \
        ["Missing END", "Missing PT", "Missing ST"]
    assert "Missing END" in kinds(LC.detect_line_errors(rows("TOC ST", "TOC PC"), f2f_set=F2F))
    assert "Missing PC" in kinds(LC.detect_line_errors(rows("TOC ST", "TOC PT", "TOC END"), f2f_set=F2F))
    assert "Missing PT" in kinds(LC.detect_line_errors(rows("TOC ST", "TOC PC", "TOC END"), f2f_set=F2F))


def test_a_finished_line_is_not_an_issue_not_even_two_of_them_in_a_row():
    assert LC.detect_line_errors(rows("TOC ST", "TOC PC", "TOC PT", "TOC END"), f2f_set=F2F) == []
    assert LC.detect_line_errors(rows("TOC ST", "TOC PC", "TOC PT", "TOC X"), f2f_set=F2F) == []
    # reuse after END is allowed, and a curve inside the second segment is fine too
    assert LC.detect_line_errors(
        rows("TOC ST", "TOC END", "TOC ST", "TOC PC", "TOC PT", "TOC END"), f2f_set=F2F) == []


def test_a_code_that_is_never_a_line_is_left_to_the_description_check():
    """Only a code that ever carries a line command is a line."""
    assert LC.detect_line_errors(rows("GS", "GS", "TOC ST", "TOC END"), f2f_set=F2F) == []


def test_custom_fieldbook_meanings_and_alphanumeric_separators_are_used():
    commands = {
        "start_line": "BEGINLN",
        "start_curve": "BC",
        "end_curve": "EC",
        "end_line": "FINISH",
        "close": "CLOSEFIG",
        "multicode": "PLUS",
        "description": "NOTE",
    }
    assert LC.detect_line_errors(
        rows("EA BEGINLN", "EA", "EA FINISH"), f2f_set={"ea"}, commands=commands) == []
    issues = LC.detect_line_errors(
        rows("EA BEGINLN", "EA"), f2f_set={"ea"}, commands=commands)
    assert "Missing END" in kinds(issues)

    from plumbline.fieldwork.parse import parse_desc_field
    parsed = parse_desc_field("EA BEGINLN PLUS SW NOTE roadway", {"ea", "sw"}, commands=commands)
    assert parsed["code_part"] == "EA BEGINLN PLUS SW"
    assert parsed["free_desc"] == "roadway"
    assert parsed["has_multicode_separator"]
    assert parsed["has_description_separator"]
    # Alphanumeric separators are whole tokens: NOTE inside a note is not a delimiter.
    parsed = parse_desc_field("EA NOTE noteworthy", {"ea"}, commands=commands)
    assert parsed["free_desc"] == "noteworthy"


def test_a_second_segment_starting_before_the_first_one_ends_is_a_missing_end():
    issues = LC.detect_line_errors(rows("TOC ST", "TOC ST", "TOC END"), f2f_set=F2F)
    assert "Missing END" in kinds(issues)
    assert "Line Order" in kinds(issues)
    assert "before a new Start Line" in " ".join(e["detail"] for e in issues)
    assert any(e["oid"] == "1" for e in issues), "the fix belongs on the point that should have ended"


def test_two_lines_are_judged_one_at_a_time():
    """A finished EP line must not be made unfinished by an unfinished TOC one."""
    issues = LC.detect_line_errors(rows("EP ST", "TOC ST", "EP END", "TOC END"),
                                   f2f_set={"ep", "toc"})
    assert issues == []


def test_curve_command_order_is_checked_across_points_and_repeated_curves_are_valid():
    out_of_order = LC.detect_line_errors(
        rows("TOC ST", "TOC PT", "TOC PC", "TOC END"), f2f_set=F2F)
    order_issues = [issue for issue in out_of_order if issue["issue_type"] == "Line Order"]
    assert len(order_issues) == 1
    assert order_issues[0]["oid"] == "2"
    assert "across its point sequence" in order_issues[0]["detail"]

    nested = LC.detect_line_errors(
        rows("TOC ST", "TOC PC", "TOC PC", "TOC PT", "TOC END"), f2f_set=F2F)
    assert any(issue["issue_type"] == "Line Order" and issue["oid"] == "3"
               for issue in nested), "a second Start Curve must follow the first End Curve"

    # End Curve must come before either End Line or Close; a terminator during an
    # open curve is an order error, even when the later End Curve is on another point.
    for terminator in ("END", "X"):
        ended_before_curve = LC.detect_line_errors(
            rows("TOC ST", "TOC PC", f"TOC {terminator}", "TOC PT"), f2f_set=F2F)
        assert any(issue["issue_type"] == "Line Order" and issue["oid"] == "3"
                   for issue in ended_before_curve), terminator

    # Detect invalid order within one description, plus a curve command that appears
    # after a prior point already ended the line.
    same_point = LC.detect_line_errors(
        rows("TOC PC ST", "TOC PT END"), f2f_set=F2F)
    assert any(issue["issue_type"] == "Line Order" and issue["oid"] == "1"
               for issue in same_point)
    after_end = LC.detect_line_errors(
        rows("TOC ST", "TOC END", "TOC PC", "TOC PT"), f2f_set=F2F)
    assert any(issue["issue_type"] == "Line Order" and issue["oid"] == "3"
               for issue in after_end)

    # A line may carry several properly paired curves; the state machine must allow PC/PT to repeat.
    assert LC.detect_line_errors(
        rows("TOC ST", "TOC PC", "TOC PT", "TOC PC", "TOC PT", "TOC END"),
        f2f_set=F2F) == []


def test_line_order_fix_validation_checks_the_whole_sequence_after_a_fix_moves_the_error():
    working = rows("TOC ST", "TOC PT", "TOC PC", "TOC END")
    result = LC.validate_fix(working, "2", "TOC PC", f2f_set=F2F)
    assert not result["ok"]
    assert result["still"] and result["still"][0]["issue_type"] == "Line Order"
    assert result["still"][0]["oid"] == "3"


# ------------------------------------------------------------------ the proposal
def test_a_proposal_is_placed_where_the_command_order_wants_it():
    assert LC.propose_fix("Missing ST", "TOC PC") == "TOC ST PC"
    assert LC.propose_fix("Missing PC", "TOC ST PT END") == "TOC ST PC PT END"
    assert LC.propose_fix("Missing PT", "TOC ST PC END") == "TOC ST PC PT END"
    assert LC.propose_fix("Missing END", "TOC ST PC PT") == "TOC ST PC PT END"


def test_no_proposal_is_invented_when_there_is_nothing_safe_to_say():
    assert LC.propose_fix("Missing ST", "TOC ST PC") == ""          # already there
    assert LC.propose_fix("Missing PT", "") == ""                   # nothing to work from
    assert LC.propose_fix("Missing ST", "TOC ST - EC PC") == ""     # two codes: a judgement call
    assert LC.propose_fix("Missing ST", "PC") == ""                 # starts with a command


def test_the_detector_hands_each_issue_its_own_proposal():
    issues = LC.detect_line_errors(rows("TOC ST", "TOC PC"), f2f_set=F2F)
    assert [e["oid"] for e in issues] == ["2", "2"]
    assert all(e["proposal"].startswith("TOC PC") for e in issues)
    assert all(e["line_id"] == "toc" and e["gid"] for e in issues)


# ------------------------------------------------------------------ the validation
def test_a_fix_is_read_back_from_the_line_and_names_the_issue_it_also_cleared():
    """The field book's own note asked for this: 'also cleared ... on OID 46'."""
    working = rows("TOC ST", "TOC PC")
    res = LC.validate_fix(working, 2, "TOC PC PT END", f2f_set=F2F)
    assert res["ok"] and res["cleared"]
    assert "also cleared Missing PT" in res["note"] or "Missing PT" in res["note"]
    assert "TOC PC PT END" in res["note"]


def test_a_fix_that_leaves_the_issue_standing_says_so_instead_of_claiming_success():
    res = LC.validate_fix(rows("TOC ST", "TOC PC"), 2, "TOC PC", f2f_set=F2F)
    assert not res["ok"]
    assert "still has" in res["note"] and "Key-In" in res["note"]


def test_validating_an_oid_that_is_not_in_the_file_changes_nothing():
    res = LC.validate_fix(rows("TOC ST", "TOC PC"), 999, "TOC PC PT END", f2f_set=F2F)
    assert res["ok"] is False and "no point with oid 999" in res["note"].lower()


def test_a_fix_at_one_point_can_clear_an_issue_reported_on_another():
    """A line whose second point never got its ST: start it, and the point after it closes it.

    This is the case the field book's note described ("also cleared LineOrderError on OID 46"):
    the second half of the mistake is somebody else's row, and a tool that only reported its own
    row would leave it looking like work still to do.
    """
    working = rows("TOC ST", "EC END", "EC END")
    before = LC.detect_line_errors(working, f2f_set=F2F)
    assert kinds(before) == ["Missing END", "Missing ST", "Missing ST"], \
        "the crew never started the EC line, and never closed the TOC one"
    res = LC.validate_fix(working, "2", "EC ST END", f2f_set=F2F)
    assert res["ok"], res["note"]
    assert [(e["issue_type"], e["oid"]) for e in res["also_cleared"]] == [("Missing ST", "3")]
    assert "also cleared Missing ST at OID 3" in res["note"]


# ------------------------------------------------------------------ the decisions
def test_an_ignored_issue_is_written_to_the_report_and_read_back():
    issues = LC.detect_line_errors(rows("TOC ST", "TOC PC"), f2f_set=F2F)
    statuses = {("Missing END", "2"): {"status": "Ignored", "comments": "crew wrote it that way"}}
    report = LC.report_rows(issues, statuses)
    assert report and report[0][1] == "Line"
    assert any(r[7] == "Ignored" for r in report)
    back = LC.statuses_from_rows(report)
    assert back[("Missing END", "2")]["status"] == "Ignored"
    assert LC.statuses_from_rows(LC.report_rows(issues)) == {}, "an Open row is not a decision"


def test_the_report_carries_the_line_issues_beside_the_duplicates():
    from plumbline.fieldwork.io_carlson import build_unified_report_rows
    working = rows("TOC ST", "TOC PC")
    line_issues = LC.detect_line_errors(working, f2f_set=F2F)
    report = build_unified_report_rows(working, [[0, 1]], [], [], [], line_issues=line_issues)
    displays = [r[1] for r in report]
    assert displays.count("Duplicate") == 2 and displays.count("Line") == len(line_issues)
    gids = [int(r[0]) for r in report]
    assert gids == sorted(gids), "group ids run in order"
    assert len(set(gids[-len(line_issues):])) == len(line_issues), "one id per line issue"
    line_row = next(r for r in report if r[1] == "Line")
    assert line_row[5] and line_row[6], "a line row carries its detail and its suggestion"


# ------------------------------------------------------------------ the drawing side
def test_the_project_side_reads_lines_with_the_same_reader(win, app):
    from plumbline.fieldwork import bridge as FB
    from plumbline.core.featurecodes import FeatureCode, FeatureCodeTable

    pr = win.state.project
    for p in list(pr.points.values()):
        del pr.points[p.id]
    pr.codes = FeatureCodeTable([FeatureCode("TOC", "Top of curb", "line", "ROAD-CURB-TOP")])
    for i, desc in enumerate(["TOC ST", "TOC PC"]):
        pr.add_point(2000.0 + i, 1000.0 + i, 500.0, number=f"80{i}", desc=desc)

    mine = FB.line_issues(pr, f2f={"toc"})
    theirs = LC.detect_line_errors(FB.working_rows_from_project(pr)[0], f2f_set={"toc"})
    assert [e["issue_type"] for e in mine] == [e["issue_type"] for e in theirs]
    assert mine and all(e["issue_type"] in LC.ISSUE_TYPES for e in mine)


def test_project_fieldwork_code_flags_ignore_deleted_points():
    from plumbline.core.project import Project
    from plumbline.fieldwork.bridge import check_project

    project = Project("Deleted code")
    active = project.add_point(0, 0, 0, number="1", desc="UNKNOWNCODE")
    deleted = project.add_point(10, 0, 0, number="2", desc="UNKNOWNCODE",
                                attrs={"qa_deleted": True})
    report = check_project(project, f2f={"toc"})
    unknown = next(finding for finding in report["findings"]
                   if finding.get("flag") == "UnknownCode")
    assert [report["ids"][i] for i in unknown["rows"]] == [active.id]
    assert all(str(oid) != str(deleted.id) for oid in report["flags"])


def test_empty_description_is_not_reported_as_a_fix_points_warning():
    from plumbline.core.project import Project
    from plumbline.fieldwork.bridge import check_project

    project = Project("Blank description")
    project.add_point(0, 0, 0, number="1", desc="")
    report = check_project(project, f2f={"toc"})
    assert all(finding.get("flag") != "EmptyDescription" for finding in report["findings"])


def test_line_order_findings_are_errors_not_warnings():
    from plumbline.core.project import Project
    from plumbline.fieldwork.bridge import check_project

    project = Project("Line order severity")
    project.add_point(0, 0, 0, number="1", desc="TOC ST PC END PT")
    report = check_project(project, f2f=F2F)
    line_order_findings = [finding for finding in report["findings"]
                           if finding.get("flag") == "LineOrderError"]
    assert line_order_findings
    assert all(finding["level"] == "error" for finding in line_order_findings)
    assert any(finding.get("check") == "line: line order" for finding in line_order_findings)
    assert any(finding.get("check") == "Line command out of order" for finding in line_order_findings)

    repeated_curve_project = Project("Repeated curve start")
    for i, desc in enumerate(("TOC ST", "TOC PC", "TOC PC", "TOC PT", "TOC END")):
        repeated_curve_project.add_point(i, 0, 0, number=str(i + 1), desc=desc)
    repeated_report = check_project(repeated_curve_project, f2f=F2F)
    repeated_order = [finding for finding in repeated_report["findings"]
                      if finding.get("check") == "line: line order"]
    assert repeated_order and all(finding["level"] == "error" for finding in repeated_order)


def test_the_dock_reports_the_line_issues_and_they_select_the_points(win, app):
    """The field-side flags, on the drawing side: findings over the project's own points."""
    from plumbline.ui.check_dock import CheckFieldworkDock

    pr = win.state.project
    for p in list(pr.points.values()):
        del pr.points[p.id]
    for i, desc in enumerate(["TOC ST", "TOC PC"]):
        pr.add_point(2000.0 + i, 1000.0 + i, 500.0, number=f"81{i}", desc=desc)
    ids = sorted(pr.points)

    dock = CheckFieldworkDock(win.state, job_root=lambda: None)
    dock.code_set = {"toc"}
    dock.result = None
    from plumbline.fieldwork import bridge as FB
    dock.result = FB.check_project(pr, f2f={"toc"}, fieldbook_path=None)

    line_findings = [f for f in dock.result["findings"] if f["check"].startswith("line:")]
    assert line_findings, [f["check"] for f in dock.result["findings"]]
    assert all(f["level"] == "warn" for f in line_findings)
    picked = {dock.result["ids"][i] for f in line_findings for i in f["rows"]}
    assert picked <= set(ids) and picked, "a finding names the points it is about"
    assert any(f["check"] == "line: missing end" for f in line_findings)
    assert any("never closed" in f["message"] for f in line_findings)


def test_a_job_with_no_vocabulary_is_told_the_line_check_cannot_run_and_is_not_faked(win, app):
    """No field book, no codes: the number checks run, the line check does not pretend."""
    from plumbline.ui.check_dock import CheckFieldworkDock
    from plumbline.fieldwork import bridge as FB

    pr = win.state.project
    for p in list(pr.points.values()):
        del pr.points[p.id]
    for i, desc in enumerate(["TOC ST", "TOC PC"]):
        pr.add_point(2000.0 + i, 1000.0 + i, 500.0, number=f"82{i}", desc=desc)
    pr.settings.pop("f2f_path", None)

    dock = CheckFieldworkDock(win.state, job_root=lambda: None)
    assert dock.code_set == set()
    dock.run()
    assert dock.result["line_issues"] == []
    assert not [f for f in dock.result["findings"] if f["check"].startswith("line:")]
    assert "line checks cannot" in dock.banner.text(), "and the banner says which half it ran"


def test_the_jobs_own_code_table_is_a_vocabulary_like_a_field_book(win, app, tmp_path):
    """The bug this pins: a feature-code table keeps its codes in capitals, the parser compares
    casefolded tokens, and passing the table's own keys made every code read as unknown - a
    hundred false alarms, which is how a check gets switched off and stays off."""
    from plumbline.ui.check_dock import CheckFieldworkDock

    pr = win.state.project
    for p in list(pr.points.values()):
        del pr.points[p.id]
    pr.settings["f2f_path"] = str(tmp_path / "office.csv")
    from plumbline.core.featurecodes import FeatureCode, FeatureCodeTable
    pr.codes = FeatureCodeTable([FeatureCode("TOC", "Top of curb", "line", "ROAD-CURB-TOP")])
    for i, desc in enumerate(["TOC ST", "TOC PC"]):
        pr.add_point(2000.0 + i, 1000.0 + i, 500.0, number=f"83{i}", desc=desc)

    dock = CheckFieldworkDock(win.state, job_root=lambda: None)
    assert dock.code_set == {"toc"}
    assert "all five checks" in dock.banner.text()
    dock.run()
    checks = {f["check"] for f in dock.result["findings"]}
    assert "Unknown code" not in checks, "the office's own table is a vocabulary, not a mystery"
    assert any(c.startswith("line: ") for c in checks), "and the line check could run on it"


# ------------------------------------------------------------------ the field window's tools
@pytest.fixture()
def field_window(app, tmp_path, monkeypatch):
    """The real field window (Survey > Fieldwork Manager), offscreen, pointed at a field book.

    The static QMessageBox helpers are the ones the tools speak through, and they run their own
    modal loop in C++ - so they are redirected here and their text is kept for the test to read.
    """
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtCore import QEvent
    said = []

    def record(kind):
        def _box(*args, **kwargs):
            title = str(args[2]) if len(args) > 2 else ""
            said.append((kind, title))
            return QMessageBox.StandardButton.Ok
        return staticmethod(_box)

    for kind in ("information", "warning", "critical"):
        monkeypatch.setattr(QMessageBox, kind, record(kind))
    monkeypatch.setenv("PLUMBLINE_HOME", str(tmp_path / "home"))
    from plumbline.core import settings as S
    S._instance = None
    from plumbline.fieldwork.ui_main import MainWindow as FieldMainWindow
    win = FieldMainWindow()
    win.resize(1200, 800)
    win.said = said
    yield win
    win.close()
    win.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    S._instance = None


def _fieldbook(path, codes=("TOC", "EC", "GS")):
    from plumbline.fieldwork.io_carlson import write_fwb_file
    path.parent.mkdir(parents=True, exist_ok=True)
    write_fwb_file(path, ["Code", "Description", "Symbol", "Layer", "Entity Type", "Category"],
                   [[c, c, "cross", "V-SITE", "1", ""] for c in codes],
                   commands=["ST", "PC", "PT", "END", "X"], rules=[])
    return path


def test_the_field_window_proposes_fixes_and_refuses_to_call_a_still_broken_line_fixed(
        field_window, tmp_path, app, auto):
    """Fix, then read the line again: the tool says what it did, including when it was not enough."""
    win = field_window
    win.fieldbook_path = str(_fieldbook(tmp_path / "office.fwb"))
    win._open_edit_tab(rows("TOC ST", "TOC PC"))
    win._refresh_line_repair()
    assert win.line_table.rowCount() == 2, [win.line_table.item(r, 1).text() for r in range(2)]
    assert "proposed:" in win.line_table.item(0, 6).text()

    # the first proposal closes the line; the curve inside it is still unfinished, and it says so
    win.line_table.selectRow(0)
    win._line_fix_first()
    assert win.edit_table.item(1, 5).text() == "TOC PC END"
    assert win.line_table.item(0, 7).text() == "Still flagged"
    assert "still has" in win.summary_label.text() and "Key-In" in win.summary_label.text()
    assert any("still stands" in t for _k, t in win.said), "and it says so in a box, not only in a strip"

    # ... so the second pass finishes it - and this time the answer is "corrected"
    win._refresh_line_repair()
    win.line_table.selectRow(0)
    win._line_fix_first()
    assert win.edit_table.item(1, 5).text() == "TOC PC PT END"
    assert "cleared" in win.summary_label.text()
    assert win._line_working_rows()[1][5] == "TOC PC PT END"


def test_key_in_writes_what_the_user_typed_and_validates_it(field_window, tmp_path, app, auto, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    win = field_window
    win.fieldbook_path = str(_fieldbook(tmp_path / "office.fwb"))
    win._open_edit_tab(rows("TOC ST", "TOC PC"))
    win._refresh_line_repair()
    win.line_table.selectRow(0)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("TOC PC PT END", True)))
    win._line_key_in()
    assert win.edit_table.item(1, 5).text() == "TOC PC PT END"
    assert win.line_table.item(0, 7).text() == "Corrected"


def test_an_ignored_line_issue_is_written_to_the_check_report_and_stays_ignored(
        field_window, tmp_path, app, auto):
    """A decision, kept: the next run reads it back instead of re-opening the issue."""
    from plumbline.fieldwork.io_carlson import (build_unified_report_rows, read_unified_report,
                                                write_unified_report)
    win = field_window
    win.fieldbook_path = str(_fieldbook(tmp_path / "office.fwb"))
    working = rows("TOC ST", "TOC PC")
    win._open_edit_tab(working)
    report = tmp_path / "check.fwc"
    write_unified_report(report, build_unified_report_rows(
        working, [], [], [], [], line_issues=LC.detect_line_errors(working, f2f_set=F2F)))
    win.check_report_path = str(report)

    win._refresh_line_repair()
    assert win.line_table.rowCount() == 2
    win.line_table.selectRow(0)
    win._line_ignore()
    assert win.line_table.item(0, 7).text() == "Ignored"
    assert "does not re-open" in win.summary_label.text()

    _h, written = read_unified_report(report)
    line_rows = [r for r in written if r[1] == "Line"]
    assert len(line_rows) == 2 and sum(1 for r in line_rows if r[7] == "Ignored") == 1

    win._line_decisions = {}                       # a fresh run, reading the report back
    win._refresh_line_repair()
    assert win.line_table.item(0, 7).text() == "Ignored"
    assert "Ignored in Line Repair" in win.line_table.item(0, 6).text()
