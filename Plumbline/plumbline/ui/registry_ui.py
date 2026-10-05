"""Settings > External Data Sources: the registry on screen, where every URL can be fixed.

The table is read-only by design - the URLs are edited one at a time in the panel underneath,
because a table cell is where a template URL gets truncated by a careless click.  What the user
asked for (item 3) is that a source that moves can be pointed somewhere else *and that the list
exists at all*: "Add source" and "Remove" cover sources that were never shipped, "Restore" covers
the shipped ones, and the accepted-formats line comes from :mod:`plumbline.core.registry` so what
this dialog says a source takes is what the loader actually accepts.

Settings save/load lives in the same dialog, because the two belong together: a settings file is
mostly a list of where things are pulled from.  ``Save settings...`` writes what differs from the
shipped defaults; ``Load settings...`` merges a file over the current settings and reports what
changed, so an imported machine's setup can be reviewed rather than silently applied.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QDialog, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QLineEdit, QMessageBox, QPushButton,
                               QTableWidget, QTableWidgetItem, QVBoxLayout)

from ..core import registry as REG
from ..core.settings import settings
from .widgets import Hint, error_box, info_box


class RegistryDialog(QDialog):
    """Every pull site, listed and editable; plus settings save / load."""

    COLS = ["Source", "Kind", "Where", "State", "URL / value"]

    def __init__(self, parent=None, state=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("External Data Sources - Settings and Pull Sites")
        self.resize(1080, 700)
        lay = QVBoxLayout(self)

        lay.addWidget(Hint(
            "Everywhere this program pulls data from, or looks for it, is on this list: imagery tiles, "
            "coordinate-system grids, geoid and vertical-datum models, the update check and plugin folders. "
            "Point a row somewhere else when a service moves, switch one off, or add your own - "
            "Restore puts a shipped source back the way it came.  Accepted formats are shown under the "
            "editor.  Some of these sources may not be used commercially (Part 1 of the licence)."))
        lay.addLayout(self._settings_row())

        self.tbl = QTableWidget(0, len(self.COLS))
        self.tbl.setHorizontalHeaderLabels(self.COLS)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl.horizontalHeader().setStretchLastSection(True)
        lay.addWidget(self.tbl, 1)

        # -- the editor for the selected row
        ed = QHBoxLayout()
        self.lbl_sel = QLabel("(pick a row)")
        self.lbl_sel.setMinimumWidth(260)
        self.ed = QLineEdit()
        self.ed.setPlaceholderText("the URL, template or path this source is read from")
        self.chk_on = QCheckBox("On")
        self.b_apply = QPushButton("Apply")
        ed.addWidget(self.lbl_sel)
        ed.addWidget(self.ed, 1)
        ed.addWidget(self.chk_on)
        ed.addWidget(self.b_apply)
        lay.addLayout(ed)
        self.lbl_formats = Hint("")
        lay.addWidget(self.lbl_formats)
        self.lbl_terms = Hint("")
        lay.addWidget(self.lbl_terms)

        row = QHBoxLayout()
        for text, slot in (("Add source...", self.add_source), ("Restore shipped value", self.restore),
                           ("Remove", self.remove), ("Print this list", self.print_list)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        self.b_close = QPushButton("Close")
        self.b_close.clicked.connect(self.accept)
        row.addWidget(self.b_close)
        lay.addLayout(row)

        self.tbl.itemSelectionChanged.connect(self._picked)
        self.b_apply.clicked.connect(self.apply_row)
        self.reload()

    # ------------------------------------------------------------------ settings save / load
    def _settings_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel("Settings:"))
        for text, slot, tip in (
                ("Save settings...", self.save_settings,
                 "Write the settings that differ from the shipped defaults - imagery sources, grid "
                 "endpoints, folders, the cache, the licence version accepted."),
                ("Load settings...", self.load_settings,
                 "Read a settings file over the current settings.  What changed is listed, so an "
                 "imported setup can be reviewed."),
                ("Reset to defaults", self.reset_settings, "Back to the shipped settings.")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch(1)
        return row

    def save_settings(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save settings", "plumbline-settings.json",
                                          "JSON (*.json);;All files (*)")
        if not p:
            return
        try:
            settings().export_to(p)
        except OSError as ex:
            error_box(self, "Save Settings", f"Could not write {p}", str(ex))
            return
        info_box(self, "Save Settings", f"Saved to {p}\n\n(Only the settings that differ from the "
                                        "shipped defaults are in the file.)")

    def load_settings(self):
        p, _ = QFileDialog.getOpenFileName(self, "Load settings", "", "JSON (*.json);;All files (*)")
        if not p:
            return
        try:
            changed = settings().load_from(p)
        except Exception as ex:
            error_box(self, "Load Settings", f"Could not read {p}", str(ex))
            return
        msg = (f"Read {p}.\n\nChanged: {', '.join(changed) if changed else 'nothing - the file matches'}")
        info_box(self, "Load Settings", msg)
        self.reload()

    def reset_settings(self):
        if QMessageBox.question(self, "Reset Settings", "Put every setting back to the shipped default?\\n\\n"
                                 "Your projects, caches and downloads are not touched.") != QMessageBox.Yes:
            return
        st = settings()
        for k in list(st._data.keys()):
            st._data.pop(k, None)
        st.save()
        self.reload()

    # ------------------------------------------------------------------ table
    def reload(self):
        self.rows = REG.as_rows()
        self.tbl.setRowCount(len(self.rows))
        for r, row in enumerate(self.rows):
            for c, key in enumerate(("name", "kind", "where", "state", "value")):
                it = QTableWidgetItem(str(row.get(key, "")))
                if c == 4:
                    it.setToolTip(str(row.get("note", "")))
                self.tbl.setItem(r, c, it)
        self.tbl.resizeColumnToContents(0)
        self.tbl.resizeColumnToContents(1)
        self.tbl.resizeColumnToContents(2)
        self.tbl.resizeColumnToContents(3)
        if self.rows:
            self.tbl.selectRow(0)

    def _current(self) -> dict | None:
        r = self.tbl.currentRow()
        return self.rows[r] if 0 <= r < len(self.rows) else None

    def _picked(self):
        row = self._current()
        if row is None:
            return
        self.lbl_sel.setText(f"<b>{row['name']}</b>")
        self.ed.setText(row["value"])
        self.ed.setReadOnly(not self._editable(row))
        self.chk_on.setChecked(row["state"] == "on")
        self.chk_on.setEnabled(self._editable(row))
        self.b_apply.setEnabled(self._editable(row))
        self.lbl_formats.setText(f"Accepts: {row['formats']}")
        t = row.get("terms") or ""
        self.lbl_terms.setText(f"Terms: {t}" if t else "")
        self.ed.setToolTip(row.get("note", ""))

    @staticmethod
    def _editable(row: dict) -> bool:
        s = REG.site(row.get("key", ""))
        return bool(s and s.editable)

    def apply_row(self):
        row = self._current()
        if row is None:
            return
        value = self.ed.text().strip()
        if not value:
            error_box(self, "External Data Sources", "Enter the URL or path this source is read from.")
            return
        REG.apply_edit(row["key"], value, self.chk_on.isChecked())
        if self.state is not None:
            self.state.log(f"External source '{row['name']}' -> {value}"
                           f"{'' if self.chk_on.isChecked() else '  (switched off)'}", "info")
        self.reload()

    def add_source(self):
        name, ok = QInputDialog.getText(self, "Add Source", "Name for this source:")
        if not ok or not name.strip():
            return
        url, ok = QInputDialog.getText(self, "Add Source", f"URL for '{name.strip()}'\\n\\n"
                                                           f"Accepts: {REG.FORMATS[REG.KIND_IMAGERY]}")
        if not ok or not url.strip():
            return
        REG.apply_edit(f"imagery:{name.strip()}", url.strip(), True)
        self.reload()

    def restore(self):
        row = self._current()
        if row is None:
            return
        REG.restore_builtin(row["key"])
        self.reload()

    def remove(self):
        row = self._current()
        if row is None:
            return
        s = REG.site(row["key"])
        if s is not None and s.builtin and not row["key"].startswith("imagery:"):
            error_box(self, "External Data Sources",
                      "This source ships with the program - switch it off instead of removing it.")
            return
        REG.remove(row["key"])
        self.reload()

    def print_list(self):
        """The list as a report: the same rows, with the accepted formats, on a page to keep."""
        from .dialogs import ReportViewer
        from ..io import reports
        tbl = reports.Table("Pull sites", self.COLS,
                            [[r["name"], r["kind"], r["where"], r["state"], r["value"]] for r in self.rows],
                            align=["l", "l", "c", "c", "l"], note="Restore puts a shipped source back.")
        sec = reports.Section(
            "Where this program pulls data from", tables=[tbl],
            paragraphs=[f"{r['name']}  ({r['where']}): accepts {r['formats']}"
                        + (f"  Terms: {r['terms']}" if r["terms"] else "")
                        for r in self.rows])
        rep = reports.Report("External Data Sources", sections=[sec],
                             footer="Some of these sources may not be used commercially - see the "
                                    "licence, Part 1.")
        ReportViewer(self, rep).exec()


__all__ = ["RegistryDialog"]
