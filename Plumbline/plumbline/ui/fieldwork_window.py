"""Survey > Fieldwork Manager - the field-data half of Plumbline, in its own window.

Fieldwork Manager was a separate program with a large, much-used UI: five tabs over
raw field data, a duplicate checker, a description parser, a renumbering tool and a
field-book viewer.  Rather than rebuild that window inside Plumbline's main window
(and risk breaking tools that already work), Plumbline opens it beside itself and the
two share the job folder.

Why a window and not a dock
---------------------------
The field-data workflow and the drawing workflow use different data at different
times - you reduce a download in the morning and draw in the afternoon.  A window can
be moved to a second monitor, maximised over the drawing, or simply closed.  Nothing
here is load-bearing for Plumbline: if the fieldwork package fails to import, the
Tools menu item is disabled and says why, and every other tool still works.

What "shares the project" means
-------------------------------
* The field window opens pointed at the *same job folder* as the open project, so its
  Field Data folder is already filled in.
* **Send Cleaned Points to Plumbline** pushes the rows from the Consolidated tab into
  the open project through :mod:`plumbline.fieldwork.bridge` - one import, using the
  job's own feature code table, with the duplicate policy the user picks.
* Nothing is written back over the field data.  The download is the record.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
                               QLabel, QMessageBox, QRadioButton, QVBoxLayout)

from ..fieldwork import bridge as FB


# --------------------------------------------------------------------------------------------- state
def rows_from_window(win) -> tuple[list[list[str]], str]:
    """The best working rows a live Fieldwork Manager window currently holds.

    Preference order, most authoritative first:

    1. the Consolidated (Edit Fieldwork) tab - it holds whatever the user has been
       editing, including renumbering that has not been saved to disk yet;
    2. the consolidated .fwk file it was loaded from;
    3. whatever .fwk files sit in the Field Data folder.

    Returns ``(rows, where_it_came_from)`` so the caller can tell the user honestly
    what it just read.
    """
    table = getattr(win, "edit_table", None)
    if table is not None and table.rowCount():
        rows = []
        for r in range(table.rowCount()):
            row = []
            for c in range(table.columnCount()):
                item = table.item(r, c)
                row.append(item.text() if item is not None else "")
            if any(row):
                rows.append(FB.pad_row(row))
        if rows:
            return rows, "the Edit Fieldwork tab"

    path = getattr(win, "edit_file_path", None)
    if path and Path(path).exists():
        return FB.read_working_file(path) or [], Path(path).name

    folder = getattr(win, "fieldwork_path", "") or ""
    if folder and Path(folder).is_dir():
        files = sorted(Path(folder).rglob("*.fwk"))
        # A consolidated file is the joined-up download - the crew books inside it are the
        # same points in pieces, so reading both would double-count every shot.
        files.sort(key=lambda f: (0 if "consolidat" in f.name.lower() else 1,
                                  len(f.parts), f.name.lower()))
        if files and "consolidat" in files[0].name.lower():
            rows = FB.read_working_file(files[0])
            if rows:
                return rows, files[0].name
        else:
            # No consolidated file: take every crew's book, in crew order, as one download.
            rows: list[list[str]] = []
            for f in files:
                rows.extend(FB.read_working_file(f) or [])
            if rows:
                where = (files[0].name if len(files) == 1
                         else f"{len(files)} crew files in {Path(folder).name}")
                return [FB.pad_row(r) for r in rows], where
    return [], ""


# --------------------------------------------------------------------------------------------- dialog
class SendToPlumblineDialog(QDialog):
    """Choose what happens to point numbers that already exist in the project."""

    POLICIES = (
        ("renumber", "Renumber the incoming point", "Keep both. The arriving point gets the next free number."),
        ("overwrite", "Overwrite the existing point", "The incoming coordinates win - use when re-importing corrected data."),
        ("skip", "Skip it", "Keep what is already in the project and drop the arriving point."),
    )

    def __init__(self, parent=None, n_points=0, n_dupes=0, source="", job_name="", has_codes=False):
        super().__init__(parent)
        self.setWindowTitle("Send Field Data to Plumbline")
        self.resize(560, 300)
        root = QVBoxLayout(self)
        head = QLabel(f"<b>{n_points:,} points</b> from {source or 'the field data'} "
                      f"will be added to <b>{job_name or 'the open project'}</b>.")
        head.setWordWrap(True)
        root.addWidget(head)
        if n_dupes:
            warn = QLabel(f"{n_dupes} of them share a number with a point already in the project.")
            warn.setWordWrap(True)
            root.addWidget(warn)
            form = QFormLayout()
            self.radios = {}
            for key, label, tip in self.POLICIES:
                rb = QRadioButton(label)
                rb.setToolTip(tip)
                rb.setChecked(key == "renumber")
                self.radios[key] = rb
                form.addRow(rb, QLabel(tip))
            root.addLayout(form)
        else:
            self.radios = {}
        if has_codes:
            root.addWidget(QLabel("The job's feature code table will be applied, so points land on "
                                  "the office's own layers."))
        root.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Send")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @property
    def policy(self) -> str:
        for key, rb in self.radios.items():
            if rb.isChecked():
                return key
        return "renumber"


# --------------------------------------------------------------------------------------------- controller
class FieldworkBridge(QObject):
    """Owns the Fieldwork Manager window for one Plumbline main window.

    Kept as an object rather than a free function so the field window survives garbage
    collection (a Qt window with no Python reference is destroyed silently) and so the
    same window is raised rather than a second copy being opened.
    """

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.window = None
        self._job_root: Path | None = None
        self.last_result: dict | None = None

    # -- lifecycle ----------------------------------------------------------------------
    def open(self):
        """Open (or raise) the Fieldwork Manager window.  Returns it, or None on failure."""
        from ..fieldwork.ui_main import MainWindow as FieldworkMainWindow

        if self.window is None:
            self.window = FieldworkMainWindow()
            self.window.setWindowFlag(Qt.WindowType.Window, True)
            self._add_plumbline_menu()
        self._point_at_open_project()
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()
        return self.window

    def _point_at_open_project(self):
        """Fill in the field window's paths from the open project, without clobbering
        anything the user has already set in the field window."""
        if self.window is None:
            return
        job = self.job_root()
        if job is None:
            return
        self._job_root = job
        if not getattr(self.window, "project_path", ""):
            self.window.project_path = str(job)
        field = job / "Field Data"
        if not getattr(self.window, "fieldwork_path", "") and field.is_dir():
            self.window.fieldwork_path = str(field)
        book_dir = job / "Field Book"
        if not getattr(self.window, "fieldbook_path", "") and book_dir.is_dir():
            books = sorted(book_dir.glob("*.fwb"))
            if books:
                self.window.fieldbook_path = str(books[0])
        try:
            self.window.setWindowTitle(f"Fieldwork Manager — {job.name}")
            label = getattr(self.window, "status_label", None)
            if label is not None and not getattr(self.window, "current_file", ""):
                # the header line above the tabs: say which job this window is working on,
                # so the two windows visibly agree instead of one saying "Untitled".
                label.setText(f"{job.name} - field data in Field Data/")
        except Exception:
            pass

    def job_root(self) -> Path | None:
        """The job folder, or None if there is not one yet.

        Normally the folder the open project lives in; if the user has pointed the program at a
        job folder with File > Select Job Folder (a job with a download but no project yet), that
        choice wins - it is the whole reason the menu item exists.
        """
        chooser = getattr(self.main, "_job_folder", None)
        if callable(chooser):
            try:
                chosen = chooser()
            except Exception:
                chosen = None
            if chosen is not None:
                return Path(chosen)
        pr = self._project()
        path = getattr(pr, "path", None) if pr else None
        if not path:
            return None
        root = Path(path).parent
        return root if root.is_dir() else None

    def _project(self):
        state = getattr(self.main, "state", None)
        return getattr(state, "project", None) if state else None

    # -- the menu the field window grows -------------------------------------------------
    def _add_plumbline_menu(self):
        bar = self.window.menuBar()
        menu = bar.addMenu("&Plumbline")
        act_send = QAction("Send Cleaned Points to Plumbline...", self.window)
        act_send.setToolTip("Import the points on the Edit Fieldwork tab into the open Plumbline project")
        act_send.triggered.connect(self.send_to_plumbline)
        menu.addAction(act_send)
        menu.addSeparator()
        act_checks = QAction("Run the Field-Data Checks", self.window)
        act_checks.triggered.connect(self.run_checks)
        menu.addAction(act_checks)
        act_codes = QAction("Load the Job's Feature Code Table", self.window)
        act_codes.triggered.connect(self.load_feature_codes)
        menu.addAction(act_codes)
        menu.addSeparator()
        act_back = QAction("Bring Plumbline Forward", self.window)
        act_back.triggered.connect(lambda: (self.main.raise_(), self.main.activateWindow()))
        menu.addAction(act_back)

    # -- actions -------------------------------------------------------------------------
    def code_table(self):
        """The job's feature code table from Field Book/, or None."""
        job = self._job_root or self.job_root()
        if not job:
            return None
        book = job / "Field Book"
        if not book.is_dir():
            return None
        for f in sorted(book.glob("*.fwb")):
            try:
                from ..fieldwork.bridge import f2f_code_set
                return f2f_code_set(f)
            except Exception:
                continue
        for f in sorted(book.glob("*.csv")):
            if "f2f" in f.name.lower() or "code" in f.name.lower():
                try:
                    table, _stats = FB.feature_codes_from_f2f(f)
                    return table
                except Exception:
                    continue
        return None

    def load_feature_codes(self):
        pr = self._project()
        table = self.code_table()
        if pr is None or table is None:
            QMessageBox.information(self.window, "Feature Codes",
                                    "No feature code table found in the job's Field Book folder.")
            return
        n = len(table) if not isinstance(table, set) else len(table)
        pr.codes = table
        pr.touch()
        QMessageBox.information(self.window, "Feature Codes",
                                f"{n:,} feature codes loaded into the project. "
                                f"Points will draw on the office's own layers.")

    def run_checks(self):
        rows, where = rows_from_window(self.window)
        if not rows:
            QMessageBox.information(self.window, "Checks",
                                    "No field data loaded. Open a consolidated .fwk first.")
            return
        found = FB.run_checks(rows)
        s = FB.summarise(rows)
        summary = (f"{s['rows']:,} rows from {where}\n\n"
                   f"  exact duplicate numbers .... {len(found['exact'])} groups\n"
                   f"  look-alike numbers ......... {len(found['similar'])} groups\n"
                   f"  points on top of each other  {len(found['close'])} groups")
        if s["crews"]:
            summary += f"\n\ncrews by point range: {', '.join(str(c) for c in s['crews'])}"
        QMessageBox.information(self.window, "Field-Data Checks", summary)

    def send_to_plumbline(self):
        pr = self._project()
        if pr is None:
            QMessageBox.warning(self.window, "Send to Plumbline", "No project is open in Plumbline.")
            return
        rows, where = rows_from_window(self.window)
        if not rows:
            QMessageBox.warning(self.window, "Send to Plumbline",
                                "There is no field data to send.\n\n"
                                "Load a consolidated .fwk file on the Edit Fieldwork tab first.")
            return
        table = self.code_table()
        existing = {p.number for p in pr.points.values()}
        incoming = {str(r[FB.PTNUM]).strip() for r in rows if FB.row_is_usable(r)}
        dupes = len(incoming & existing)

        dlg = SendToPlumblineDialog(self.window, n_points=len(incoming), n_dupes=dupes,
                                    source=where, job_name=pr.name, has_codes=table is not None)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            result = FB.apply_rows_to_project(pr, rows, code_table=table, dup_policy=dlg.policy)
        except Exception as exc:
            QMessageBox.critical(self.window, "Send to Plumbline", f"The import failed:\n\n{exc}")
            return
        self.last_result = result
        try:
            pr.touch()
        except Exception:
            pass
        # let the drawing half refresh with the new points
        for name in ("refresh_all", "refresh_layers", "redraw"):
            fn = getattr(self.main, name, None)
            if callable(fn):
                try:
                    fn()
                except TypeError:
                    pass
                break
        lines = [f"{result.get('points', 0):,} points sent to {pr.name}.",
                 f"{result.get('coded', 0):,} placed on a feature-code layer."]
        if result.get("duplicates"):
            lines.append(f"{result['duplicates']} point number(s) already existed "
                         f"({dlg.policy}) - {result.get('renumbered', 0)} renumbered, "
                         f"{result.get('skipped', 0)} skipped.")
        if result.get("unknown_code_points"):
            lines.append(f"{result['unknown_code_points']} point(s) use a code that is not in the "
                         f"job's feature code table - they stay on the POINTS layer.")
        if table is not None:
            lines.append("\nLinework is not built yet - use Survey > Process Linework when you want it.")
        QMessageBox.information(self.window, "Send to Plumbline", "\n".join(lines))


# --------------------------------------------------------------------------------------------- entry point
_bridges: list[FieldworkBridge] = []          # keeps windows alive for the process lifetime


def open_fieldwork_manager(main_window):
    """Survey > Fieldwork Manager.  Returns the window, or None if the field code
    could not be loaded (in which case the user has already been told why)."""
    for b in _bridges:
        if b.main is main_window:
            try:
                return b.open()
            except Exception as exc:                      # pragma: no cover - GUI failure path
                _explain(main_window, exc)
                return None
    bridge = FieldworkBridge(main_window)
    try:
        win = bridge.open()
    except Exception as exc:
        _explain(main_window, exc)
        return None
    _bridges.append(bridge)
    return win


def _explain(parent, exc):
    QMessageBox.critical(
        parent, "Fieldwork Manager",
        f"The field-data window could not be opened:\n\n{type(exc).__name__}: {exc}\n\n"
        "The rest of Plumbline is unaffected - drawing, surfaces, imagery and exports all "
        "still work.")


__all__ = ["open_fieldwork_manager", "FieldworkBridge", "SendToPlumblineDialog", "rows_from_window"]
