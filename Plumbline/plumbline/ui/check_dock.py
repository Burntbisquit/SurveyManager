"""The Check Fieldwork dock - the field-data checks, in the drawing window.

Two different questions get asked about a job, and they need two different tools:

* **Is this download right?** - the same point number twice, numbers that look like each other,
  two shots on the same spot, codes the office's field book does not have.  That is Fieldwork
  Manager's question, and it is asked *before* anything is imported: **Survey > Fieldwork
  Manager**.
* **Is what I am drawing right?** - the same checks over the points that are actually in this
  project, after the import renumbered them, after somebody edited a description, dropped a pin
  or merged a second download in.  That is this dock: *View > Panels > Check Fieldwork*.

It runs the checks the field window runs, through the same code
(:func:`plumbline.fieldwork.bridge.check_project` - the same three detectors and the same
description parser), so the two windows cannot disagree about what "a duplicate" means.  What this
dock adds is reach: click a finding to select those points in the drawing, double-click to zoom to
them, and the Points list's Source File / Parent Folder columns say which download and which crew
each one came from.

**A vocabulary is what makes the description check a check.**  Without the office's own codes the
parser would call every code unknown - a hundred false alarms, which is how a check gets switched
off and stays off.  So this dock runs what it can with what it has, and says which of the two it
did:

* a **field book** (``.fwb``) - the one the job remembers, or the first one in the job folder's
  ``Field Book`` folder: all five checks run;
* the **job's own feature codes** - when they came from the office's Carlson table (*Survey >
  Convert Field to Finish*), that table is the vocabulary, and all five checks run;
* **neither** - the three number checks run and the description and line checks do not, and the
  dock says so and offers both ways out.

**The fifth check is the linework.**  A line is not a point: ``TOC PC`` on one OID is a fine
description whose *meaning* is wrong, and it only shows when the line is read as a whole - a
segment that runs and stops without an ``END``, a curve that starts and never ends.  Those issues
are read by :mod:`plumbline.fieldwork.linecheck` - the same reader the field window's Line Repair
tab uses - and they come back here as findings that select the offending points in the drawing,
including the ones whose *other* end is a different point.  Fixing them is the field window's
Line Repair tab (Fix / Key-In / Ignore); this dock is where they are seen from the drawing side.

There are no tolerances to set here on purpose: the checks use the same tolerances the field
window uses, because a check that finds something in one window and not the other is worse than
no check at all.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
                               QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core import provenance as PROV
from .widgets import Banner, Hint

COLS = ("Level", "Check", "Finding", "Points")
COLORS = {"error": "#ff6b6b", "warn": "#f0b429", "info": "#8a94a1"}


def fieldbook_in(job_root) -> Path | None:
    """The first field book in a job folder's ``Field Book`` directory, if there is one.

    The field window picks its field book the same way (first ``*.fwb``, by name), so a job that
    works there works here.
    """
    if not job_root:
        return None
    book_dir = Path(job_root) / "Field Book"
    if book_dir.is_dir():
        books = sorted(book_dir.glob("*.fwb"))
        if books:
            return books[0]
    return None


def codes_from_fieldbook(path) -> set:
    """The code vocabulary of a field book (``.fwb``) or a Carlson F2F table (``.csv``)."""
    from ..fieldwork import parse as P

    p = Path(str(path))
    if p.suffix.lower() == ".csv":
        from ..fieldwork import bridge as FB
        return FB.f2f_code_set(p)
    return P.build_f2f_set_from_fieldbook(p)


class CheckFieldworkDock(QWidget):
    """Run the field-data checks over this project's points, and show what they found."""

    def __init__(self, state, job_root=None, on_convert=None, parent=None):
        super().__init__(parent)
        self.state = state
        self._job_root = job_root                # a callable () -> Path | None, or a path
        self._on_convert = on_convert            # the window's Convert Field to Finish command
        self._alerted = False
        self._stale = False
        self.result = None
        self.code_set: set = set()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.banner = Banner("", "info")
        lay.addWidget(self.banner)

        row = QHBoxLayout()
        self.btn_run = QPushButton("Run the Check")
        self.btn_run.setProperty("accent", True)
        self.btn_book = QPushButton("Field Book...")
        self.btn_book.setToolTip("Point this job at an existing field book (.fwb) - it is "
                                 "remembered on the job")
        self.btn_conv = QPushButton("Convert Field to Finish...")
        self.btn_conv.setToolTip("Build a code table from the office's Carlson Field-to-Finish "
                                 "export (Survey > Convert Field to Finish)")
        row.addWidget(self.btn_run)
        row.addWidget(self.btn_book)
        row.addWidget(self.btn_conv)
        row.addStretch(1)
        self.lbl_when = QLabel("")
        row.addWidget(self.lbl_when)
        lay.addLayout(row)

        self.tbl = QTableWidget(0, len(COLS))
        self.tbl.setHorizontalHeaderLabels(list(COLS))
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.setAlternatingRowColors(True)
        self.tbl.verticalHeader().setVisible(False)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeToContents)
        lay.addWidget(self.tbl, 1)

        lay.addWidget(Hint("Click a finding to select those points in the drawing; double-click to "
                           "zoom to them.  The three number checks use the same tolerances as the "
                           "field window (2 cm apart, 5 cm of height), and the line findings are "
                           "read by the same code the field window's Line Repair tab uses - fix "
                           "them there (Fix / Key-In / Ignore).  The drawing-wide checks stay on "
                           "Survey > Data Quality Check."))

        self.btn_save = QPushButton("Save Report...")
        self.btn_save.setToolTip("Write this check out as a .fwc - the same file the field window "
                                 "reads.  A run is already stored in the project, and written into "
                                 "the job's Reports folder when the job has one.")
        row.addWidget(self.btn_save)
        self.btn_run.clicked.connect(lambda *_: self.run(alert=True))
        self.btn_save.clicked.connect(self.save_report)
        self.btn_book.clicked.connect(self.choose_field_book)
        self.btn_conv.clicked.connect(self.build_code_table)
        self.tbl.itemSelectionChanged.connect(self._select)
        self.tbl.cellDoubleClicked.connect(self._zoom)
        state.project_replaced.connect(self._project_changed)
        state.changed.connect(self._changed)
        self.refresh_banner()
        # Reopening a project reopens its last check (item 13): the run is stored on the project,
        # so it is there before anything is run again - and if there is none, run one.
        if not self.show_stored():
            # Running the check is read-only, and this one is not the user's doing: opening a
            # project must leave it clean and the undo stack empty, so the automatic run does not
            # record itself.  Pressing "Run the Check" does.
            self.run(store=False)

    def save_report(self):
        """Copy this run out as a .fwc wherever the user wants it."""
        from ..fieldwork import bridge as FB
        if self.result is None:
            return
        default = self._last_report_file if getattr(self, "_last_report_file", "") else ""
        start = default or str(Path(self.job_root() or Path.home()) / "check.fwc")
        path, _ = QFileDialog.getSaveFileName(self, "Save the Check Report", start,
                                              "Check report (*.fwc);;All files (*)")
        if not path:
            return
        rows = FB.report_rows(self.state.project, self.result)
        if FB.write_report(path, rows):
            self.state.log(f"Check report written to {path} ({len(rows)} row(s)).", "ok")
            self.lbl_when.setText(self.lbl_when.text() + f"  |  saved {Path(path).name}")
        else:
            QMessageBox.warning(self, "Save the Check Report", f"Could not write {path}.")

    # --------------------------------------------------------------------- the field book
    def job_root(self):
        """The job folder this window is working in, if it has one."""
        root = self._job_root
        try:
            return root() if callable(root) else root
        except Exception:
            return None

    def fieldbook(self) -> Path | None:
        """The field book this job is using: the one it remembers, else the job folder's.

        Uses the same search as the vocabulary itself (``bridge.fieldbooks_in``: any ``*.fwb``
        under the job folder, the job's own name first), so the book the dock *says* it will use
        and the book the check actually reads cannot be two different files.  An office book in
        ``Source/`` or beside the download in ``Field Data/`` counts.
        """
        chosen = (self.state.project.settings or {}).get("fieldbook_file")
        if chosen and Path(chosen).exists():
            return Path(chosen)
        from ..fieldwork import bridge as FB
        books = FB.fieldbooks_in(self.job_root())
        return books[0] if books else fieldbook_in(self.job_root())

    def vocabulary(self) -> dict:
        """What the description check runs against - one resolver, in ``fieldwork.bridge``.

        It looks for the job's field book (the one the job remembers, else every ``*.fwb`` under
        the job folder, the job's own name first), falls back to the job's own feature codes, and
        says which of those it did.  A field book *with no code table* is not a vocabulary: a
        fresh job's template book is exactly that, and using its empty table would report every
        code as unknown.
        """
        from ..fieldwork import bridge as FB
        return FB.vocabulary_for(self.state.project, job_root=self.job_root(),
                                 fieldbook=self.fieldbook())

    def refresh_banner(self):
        """Say what the checks will be able to do, before anything is run."""
        v = self.vocabulary()
        self.code_set = set(v["codes"])
        self._vocabulary = v
        n = len(self.code_set)
        if v["source"] == "none":
            head = (f"{v['why']}.  " if v.get("why") else "No field book.  ")
            self.banner.set(head + "The number and position checks run, the description and line "
                            "checks cannot.  Point the job at a field book (Field Book...), or "
                            "build a code table from the office's Carlson export (Convert Field to "
                            "Finish...).", "warn")
            return
        if v["source"] == "field book":
            self.banner.set(f"Field book: {v['label']} - {n:,} codes.  All five checks run.", "info")
        elif v["source"] == "field book + job codes":
            self.banner.set(f"Field book {v['label']} holds no code table, so this job's own "
                            f"{n:,} feature codes are used as well - all five checks run.", "info")
        else:
            self.banner.set(f"No field book, but this job's {n:,} feature codes are the vocabulary "
                            f"({v['label']}) - all five checks run.", "info")

    def choose_field_book(self):
        book = self.fieldbook()
        start = str(book.parent) if book else str(self.job_root() or "")
        path, _ = QFileDialog.getOpenFileName(self, "Field Book", start,
                                              "Field Book (*.fwb);;Field Code Table (*.csv);;"
                                              "All Files (*)")
        if not path:
            return
        with self.state.edit("Choose field book"):
            self.state.project.settings["fieldbook_file"] = path
        self.state.log(f"Field book: {Path(path).name}.", "ok")
        self.refresh_banner()
        self.run()

    def build_code_table(self):
        """Hand off to the window's own Convert Field to Finish, then re-check with its codes."""
        if self._on_convert is None:
            return
        self._on_convert()
        self.refresh_banner()
        self.run()

    def alert_if_no_fieldbook(self):
        """Say it once, in a box, when a check is run on a job without a vocabulary.

        The banner says it every time the dock is looked at; this is the one that offers to *do*
        something about it, because a check that quietly cannot run is the failure this alert
        exists to prevent.  A second press of the button does not ask again.
        """
        if self._alerted or self.code_set:
            return
        if self._no_field_points():
            return                          # nothing to check yet - say nothing
        self._alerted = True
        m = QMessageBox(self)
        m.setIcon(QMessageBox.Warning)
        m.setWindowTitle("Field Book Needed")
        m.setText("No field book is loaded for this job, so the description check cannot run.\n\n"
                  "The number and position checks will run with or without it.")
        m.setInformativeText("Pick an existing .fwb now, or build a code table from the office's "
                             "Carlson Field-to-Finish export?")
        b_pick = m.addButton("Pick a Field Book...", QMessageBox.AcceptRole)
        b_conv = m.addButton("Convert Field to Finish...", QMessageBox.ActionRole)
        b_later = m.addButton("Run the Other Checks", QMessageBox.RejectRole)
        m.setDefaultButton(b_pick)
        m.exec()
        if m.clickedButton() is b_pick:
            self.choose_field_book()
        elif m.clickedButton() is b_conv:
            self.build_code_table()
        elif m.clickedButton() is b_later:
            self.run()

    def _no_field_points(self) -> bool:
        from ..fieldwork import bridge as FB
        try:
            return not FB.working_rows_from_project(self.state.project)[0]
        except Exception:
            return True

    # --------------------------------------------------------------------- the check
    def _project_changed(self):
        self._alerted = False
        self.refresh_banner()
        if not self.show_stored():
            self.run(store=False)

    def _changed(self, kinds=None):
        """Something in the drawing moved: say the check is out of date, do not re-run by itself."""
        if self.result is None or self._stale:
            return
        self._stale = True
        self.btn_run.setText("Run the Check *")
        self.btn_run.setToolTip("The drawing has changed since this check was run")

    def run(self, alert: bool = False, store: bool = True):
        """Run the field-data checks and show the findings.

        *alert* is set from the Run button: with no vocabulary loaded the check can only do half
        its job, and that is the moment to say so in a box rather than in a strip.  *store* is
        False for a run nobody asked for (the one that fills the dock when a project is opened),
        because a window that dirties a project on sight is a window that loses trust.
        """
        from ..fieldwork import bridge as FB

        self.refresh_banner()
        if alert:
            self.alert_if_no_fieldbook()
        book = self.fieldbook()
        v = getattr(self, "_vocabulary", None) or self.vocabulary()
        try:
            self.result = FB.check_project(self.state.project, f2f=self.code_set,
                                           fieldbook_path=book or (v.get("path") or None))
        except Exception as ex:                          # a check must never break the window
            self.banner.set(f"The check could not run: {ex}", "bad")
            self.state.log(f"Check fieldwork could not run: {ex}", "warn")
            return
        # The run is written into the project (item 13): reopen the project and the check is
        # there, with what it found, when it ran and which vocabulary it used.  It goes inside an
        # edit so it is undoable and so the project knows it has changed.
        if store:
            self._store(v)
        self._stale = False
        self.btn_run.setText("Run the Check")
        self.btn_run.setToolTip("")
        self._fill_table()
        findings = self.result["findings"]
        stats = self.result["stats"] or {}
        points = stats.get("rows", 0)
        crews = stats.get("crews") or []
        line_count = len(self.result.get("line_issues") or [])
        self.lbl_when.setText(f"{points:,} point(s) in the check"
                              + (f", crews {', '.join(str(c) for c in crews)}" if crews else "")
                              + (f", {line_count} line issue(s)" if line_count else ""))
        errors = sum(1 for f in findings if f["level"] == "error")
        warns = sum(1 for f in findings if f["level"] == "warn")
        self.state.log(f"Check fieldwork: {points:,} field point(s), {len(findings)} finding(s)"
                       + (f" ({errors} error, {warns} warning)" if errors or warns else "")
                       + ".  " + PROV.summary(self.state.project), "warn" if errors else "ok")

    # --------------------------------------------------------------------- the audit trail
    def _store(self, vocabulary: dict):
        """Save this run on the project, and write the same run beside the job when there is one."""
        from ..fieldwork import bridge as FB
        try:
            with self.state.edit("Run the Check"):
                payload = FB.store_report(self.state.project, self.result, vocabulary=vocabulary,
                                          job_root=self.job_root())
                path = None
                root = self.job_root()
                if root:
                    reports = Path(root) / "Reports"
                    reports.mkdir(parents=True, exist_ok=True)
                    stamp = payload["when"].replace(":", "").replace("-", "").replace(" ", "-")
                    path = reports / f"Check Fieldwork {stamp}.fwc"
                    rows = FB.report_rows(self.state.project, self.result)
                    if not FB.write_report(path, rows):
                        path = None
                payload["file"] = str(path) if path else ""
        except Exception as ex:                          # never let the trail break the check
            self.state.log(f"The check ran, but its report could not be saved: {ex}", "warn")
            return
        self._last_report_file = payload.get("file") or ""
        self.state.log(f"Check written to the project ({payload['points']:,} point(s), "
                       f"{len(payload['findings'])} finding(s), vocabulary: {payload['vocabulary']}"
                       + (f", {Path(self._last_report_file).name}" if self._last_report_file else "")
                       + ").", "info")

    def stored(self) -> dict | None:
        from ..fieldwork import bridge as FB
        return FB.stored_report(self.state.project)

    def show_stored(self) -> bool:
        """Show the check the project is carrying, if any.  True when something was shown.

        This is what makes a check auditable after the project is closed and reopened: the last run
        comes back with the project, in the same table, with its point numbers, and the strip says
        when it ran and what it ran against - so nobody has to take "I ran it" on trust.
        """
        payload = self.stored()
        if not payload:
            return False
        from ..fieldwork import bridge as FB
        rows, ids = FB.working_rows_from_project(self.state.project)
        id_to_row = {pid: i for i, pid in enumerate(ids)}
        findings = []
        for f in payload.get("findings") or []:
            idxs = [id_to_row[i] for i in (f.get("points") or []) if i in id_to_row]
            findings.append({"level": f.get("level", "info"), "check": f.get("check", ""),
                             "message": f.get("message", ""), "rows": idxs,
                             "stored": True})
        self.result = {"rows": rows, "ids": ids, "findings": findings, "stats": {}, "flags": {},
                       "code_checks": payload.get("vocabulary") not in ("none", "", None),
                       "line_issues": [], "stored": payload}
        self._stale = False
        self.btn_run.setText("Run the Check")
        self.btn_run.setToolTip("")
        self._fill_table()
        when = payload.get("when", "")
        vocab = payload.get("vocabulary_label") or payload.get("vocabulary", "")
        extra = (f", {payload.get('errors', 0)} error, {payload.get('warnings', 0)} warning"
                 if payload.get("errors") or payload.get("warnings") else "")
        self.lbl_when.setText(f"Last run {when} - {payload.get('points', 0):,} point(s), "
                              f"{len(findings)} finding(s){extra}"
                              + (f", vocabulary {vocab}" if vocab else "")
                              + (f"  |  {Path(payload['file']).name}" if payload.get("file") else ""))
        if self.state.dirty:
            self.lbl_when.setText(self.lbl_when.text() + "  (the drawing has changed since)")
        return True

    def _fill_table(self):
        findings = self.result["findings"]
        self.tbl.setRowCount(len(findings))
        for r, f in enumerate(findings):
            vals = [f["level"].upper(), f["check"], f["message"],
                    f"{len(f['rows']):,}" if f["rows"] else (f"{f.get('count'):,}"
                                                             if f.get("count") else "")]
            for c, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if c == 0:
                    item.setForeground(QColor(COLORS.get(f["level"], COLORS["info"])))
                item.setToolTip(f["message"])
                self.tbl.setItem(r, c, item)
        self.tbl.resizeRowsToContents()

    # --------------------------------------------------------------------- acting on a finding
    def _ids(self) -> list:
        if self.result is None:
            return []
        row = self.tbl.currentRow()
        if row < 0 or row >= len(self.result["findings"]):
            return []
        ids = self.result["ids"]
        return [ids[i] for i in self.result["findings"][row]["rows"] if 0 <= i < len(ids)]

    def _select(self):
        ids = self._ids()
        if ids:
            self.state.select(points=ids)

    def _zoom(self, r, c):
        ids = self._ids()
        pr = self.state.project
        pts = [pr.points[i] for i in ids if i in pr.points]
        if pts:
            xs = [p.x for p in pts]
            ys = [p.y for p in pts]
            pad = 15.0
            self.state.zoom_to_bbox((min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad))

