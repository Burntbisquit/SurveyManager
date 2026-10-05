"""Survey > File Coordinate Systems... - what each file's numbers were in, and how to change it.

The three things this answers, in the user's words (change order, item 6):

* **what was assumed** - every import writes down the system its numbers were taken to be in,
  whether that was the project's own (`assumed`), the file's own answer, or a choice made at
  import time.  The list here is built from the points themselves, so a file imported before this
  existed still appears with a blank to fill in rather than being invisible;
* **reprojection only when it differs** - nothing has moved these points since they landed, which
  is exactly why the record matters: the coordinates are still in whatever system they arrived in,
  and this is the screen that says so;
* **"assumed TXNC grid, was TXC ground"** - the case that started it.  Two operations, and they are
  opposite, so the dialog makes the choice explicit and counts the points before doing anything:

  ==================  =========================================================
  **Relabel**         the numbers are right; the record was wrong.  Nothing moves.
  **Reproject**       the numbers are in another system.  The points move.
  **Ground / grid**   the same system, scaled: ground = grid x SAF (or back).
  ==================  =========================================================

Every operation goes through one undo step with a label that says what it did, and it says how
many points it touched in the log, so an accidental click is both visible and reversible.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core import filecrs as FCRC
from .crs_dialog import CRSPicker
from .crs_extra import VerticalAndGroundPanel
from .widgets import Hint, error_box, info_box


class _PickCRS(QDialog):
    """Pick the system a file is actually in - coordinate, vertical datum and ground scale."""

    def __init__(self, parent, record: dict | None = None, title="What System Is This File In?"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(900, 640)
        lay = QVBoxLayout(self)
        lay.addWidget(Hint("Pick the system the file's numbers are actually in.  Vertical datum and "
                           "ground scale are part of the answer: the same EPSG code with a SAF is "
                           "ground, without one is grid."))
        self.picker = CRSPicker(kinds=("projected", "geographic"))
        lay.addWidget(self.picker, 1)
        self.extra = VerticalAndGroundPanel(self)
        lay.addWidget(self.extra)
        row = QHBoxLayout()
        row.addStretch(1)
        b_ok = QPushButton("Use This System")
        b_ok.setProperty("accent", True)
        b_no = QPushButton("Cancel")
        row.addWidget(b_ok)
        row.addWidget(b_no)
        lay.addLayout(row)
        b_ok.clicked.connect(self.accept)
        b_no.clicked.connect(self.reject)
        if record:
            key = record.get("key") or ""
            if key:
                try:
                    self.picker.select_key(key)
                except Exception:
                    pass
            self.extra.cmb_datum.setCurrentIndex(max(0, self.extra.cmb_datum.findData(record.get("vertical") or "")))
            self.extra.cmb_geoid.setCurrentIndex(max(0, self.extra.cmb_geoid.findData(record.get("geoid") or "")))
            self.extra.chk_ground.setChecked(bool(record.get("ground")))
            self.extra.sp_cf.setValue(float(record.get("saf") or 1.0))
            self.extra.sp_by.setValue(float(record.get("base_n") or 0.0))
            self.extra.sp_bx.setValue(float(record.get("base_e") or 0.0))

    def record(self) -> dict:
        from ..core import crs as C
        key = self.picker.current_key() or ""
        try:
            crs = C.ProjectCRS.from_key(key)
            label, unit, vunit = crs.label, crs.unit, crs.vunit
        except Exception:
            label, unit, vunit = key, "", ""
        return {**FCRC.make(key=key, label=label, unit=unit, vunit=vunit, method="edited"),
                **{k: v for k, v in self.extra.record().items()}}


class FileCoordinateSystemsDialog(QDialog):
    """The files that brought data in, and what has to be true about their coordinates."""

    COLS = ["File", "Points", "Coordinate system", "Vertical", "SAF", "How it got that way"]

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("File Coordinate Systems")
        self.resize(1000, 620)
        lay = QVBoxLayout(self)
        lay.addWidget(Hint(
            "Every file that has put points into this job, with the coordinate system those numbers "
            "were taken to be in.  A CSV does not carry a coordinate system, so the project's own is "
            "assumed unless you chose another at import - nothing was reprojected to get here.  "
            "Change a file's system below: **Relabel** if the numbers are right and the record was "
            "wrong, **Reproject** if the numbers themselves are in another system, and "
            "**Ground / grid** for the TXDOT scale factor (grid x SAF = ground)."))
        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        lay.addWidget(self.tbl, 1)

        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)

        row = QHBoxLayout()
        self.b_set = QPushButton("Set / change the system...")
        self.b_relabel = QPushButton("Relabel (nothing moves)")
        self.b_repro = QPushButton("Reproject (the points move)")
        self.b_ground = QPushButton("Ground / grid (SAF)...")
        for b in (self.b_set, self.b_relabel, self.b_repro, self.b_ground):
            row.addWidget(b)
        row.addStretch(1)
        b_close = QPushButton("Close")
        b_close.clicked.connect(self.accept)
        row.addWidget(b_close)
        lay.addLayout(row)
        lay.addWidget(Hint("Project system, for comparison: " + state.project.crs.label.replace("\n", "  ·  ")))

        self.tbl.itemSelectionChanged.connect(self._picked)
        self.b_set.clicked.connect(self.set_system)
        self.b_relabel.clicked.connect(self.relabel)
        self.b_repro.clicked.connect(self.reproject)
        self.b_ground.clicked.connect(self.ground_grid)
        self.reload()

    # ------------------------------------------------------------------ table
    def reload(self):
        self.rows = FCRC.files(self.state.project)
        self.tbl.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            crs = row.get("crs") or {}
            label = crs.get("label") or ""
            label = label.splitlines()[0] if label else "(not recorded)"
            vals = [row["file"], f"{row['points']:,}", label,
                    crs.get("vertical") or "", f"{float(crs.get('saf') or 1.0):.9f}"
                    if crs.get("ground") else "grid",
                    FCRC.METHODS.get(row.get("method") or "", row.get("method") or "")]
            for c, v in enumerate(vals):
                it = QTableWidgetItem(str(v))
                if c == 2 and not crs:
                    it.setToolTip("No system recorded for this file - set one.")
                self.tbl.setItem(r, c, it)
        self.tbl.resizeColumnsToContents()
        self._picked()

    def _current(self) -> dict | None:
        r = self.tbl.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def _picked(self):
        row = self._current()
        have = row is not None
        for b in (self.b_set, self.b_relabel, self.b_repro, self.b_ground):
            b.setEnabled(have)
        if not have:
            self.lbl.setText("")
            return
        crs = row.get("crs") or {}
        self.lbl.setText(
            f"<b>{row['file']}</b> - {row['points']:,} point(s)"
            + (f" from {row['folder']}" if row.get("folder") else "")
            + (f".  Recorded as: {crs.get('label', '').replace(chr(10), '  ·  ')}"
               + (f" (SAF {float(crs.get('saf') or 1):.9f}, "
                  f"base N {float(crs.get('base_n') or 0):,.3f} E {float(crs.get('base_e') or 0):,.3f})"
                  if crs.get("ground") else " (grid)")
               + (f".  {crs.get('when')}" if crs.get("when") else "")
               if crs else ".  No coordinate system recorded - the numbers are wherever they landed."))

    # ------------------------------------------------------------------ operations
    def _apply(self, label: str, fn):
        try:
            with self.state.edit(label):
                out = fn()
        except Exception as ex:
            error_box(self, "File Coordinate Systems", str(ex))
            return None
        self.state.refresh({"all"})
        self.reload()
        return out

    def set_system(self):
        row = self._current()
        if row is None:
            return
        dlg = _PickCRS(self, row.get("crs"), title=f"What system is {row['file']} in?")
        if not dlg.exec():
            return
        rec = dlg.record()
        if not rec.get("key"):
            error_box(self, "File Coordinate Systems", "Pick a coordinate system from the list.")
            return
        self.lbl.setText(f"{row['file']}: recorded as {rec['label'].splitlines()[0]}")
        self._apply(f"Record the coordinate system of {row['file']}",
                    lambda: FCRC.relabel(self.state.project, row["file"], rec))
        self.lbl.setText(f"{row['file']} is now recorded as {rec['label'].splitlines()[0]}.  "
                         f"Nothing moved - use Reproject if the numbers are in another system.")

    def relabel(self):
        row = self._current()
        if row is None:
            return
        if not self._pick_and("Relabel", row, "The numbers are right and the record was wrong: "
                                              "nothing will move."):
            return

    def reproject(self):
        row = self._current()
        if row is None:
            return
        rec = self._pick_and("Reproject", row,
                             "The numbers are in that system: the points will move.", apply=False)
        if rec is None:
            return
        n = len(FCRC.points_of(self.state.project, row["file"]))
        if QMessageBox.question(self, "Reproject File",
                                f"Move the {n:,} point(s) from {row['file']} into "
                                f"{rec['label'].splitlines()[0]}?\n\nNothing else in the project is "
                                f"touched.  This is one undo step.") != QMessageBox.Yes:
            return
        out = self._apply(f"Reproject {row['file']}",
                          lambda: FCRC.reproject(self.state.project, row["file"], rec))
        if out:
            self.state.log(f"{row['file']}: {out['points']:,} point(s) reprojected from "
                           f"{out['from'].splitlines()[0]} to {out['to'].splitlines()[0]}.", "ok")

    def _pick_and(self, verb: str, row: dict, why: str, apply: bool = True):
        dlg = _PickCRS(self, row.get("crs"), title=f"{verb} - {row['file']}")
        if not dlg.exec():
            return None
        rec = dlg.record()
        if not rec.get("key"):
            error_box(self, "File Coordinate Systems", "Pick a coordinate system from the list.")
            return None
        if not apply:
            return rec
        self._apply(f"{verb} {row['file']}",
                    lambda: FCRC.relabel(self.state.project, row["file"], rec))
        self.state.log(f"{row['file']}: relabelled to {rec['label'].splitlines()[0]} - no coordinates "
                       f"were changed.", "info")
        self.lbl.setText(f"{row['file']}: {why}  Nothing moved.")
        return rec

    def ground_grid(self):
        row = self._current()
        if row is None:
            return
        from PySide6.QtWidgets import QInputDialog
        crs = row.get("crs") or {}
        saf0 = float(crs.get("saf") or 1.0) or 1.0
        text, ok = QInputDialog.getText(self, "Ground / Grid",
                                       f"SAF for {row['file']} (ground = grid x SAF).\n\n"
                                       f"Enter the whole factor: 1.000136506 is not 1.00013650.",
                                       text=f"{saf0:.9f}".rstrip("0").rstrip(".") or "1.0")
        if not ok or not text.strip():
            return
        try:
            saf = float(text.strip())
        except ValueError:
            error_box(self, "Ground / Grid", f"'{text.strip()}' is not a number.")
            return
        if not (0.9 < saf < 1.1):
            error_box(self, "Ground / Grid", "That is more than 10% away from 1.0 - a SAF is a few "
                                             "parts per million.  Check the decimal point.")
            return
        direction = QMessageBox.question(
            self, "Ground / Grid",
            f"Treat the {row['points']:,} point(s) from {row['file']} as:\n\n"
            f"  Yes  - GROUND, and convert to grid (divide by {saf:.9f})\n"
            f"  No   - GRID, and convert to ground (multiply by {saf:.9f})\n\n"
            f"Either way it is one undo step.")
        to_ground = direction != QMessageBox.Yes
        out = self._apply(f"{'Ground' if to_ground else 'Grid'} rescale of {row['file']}",
                          lambda: FCRC.rescale_ground(self.state.project, row["file"], saf=saf,
                                                      to_ground=to_ground))
        if out:
            self.state.log(f"{row['file']}: {out['points']:,} point(s) rescaled with SAF {saf:.9f} "
                           f"({'grid -> ground' if to_ground else 'ground -> grid'}).", "ok")


__all__ = ["FileCoordinateSystemsDialog"]
