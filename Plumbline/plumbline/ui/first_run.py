"""First run: what the program would like to fetch, offered once, ticked by default.

The change order asked for the external data (coordinate-system grids, geoids, vertical datums and
every other external reference) to be **flags that ship with the program** rather than files
inside it, and for the download to be **the default on first run** (item 9).  This dialog is that
first run: every item with what it is for, what stops working without it, and its size, all
ticked.

The offer is made once and remembered (``settings["external_prompt_done"]``).  "Later" is a real
answer - it records that the question was asked and not answered, and everything that needs a grid
says so at the moment it is needed (``core.vdatum`` never invents a separation).  The same list,
with the URLs editable, is behind Settings > External data sources, so a source that moves can be
fixed there rather than in this dialog.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QProgressBar, QPushButton,
                               QVBoxLayout)

from ..core import firstrun as FR
from .widgets import Hint, info_box


class _FetchWorker(QObject):
    step = Signal(float, str)
    finished = Signal(dict)
    failed = Signal(str)

    def __init__(self, keys):
        super().__init__()
        self.keys = list(keys)
        self.cancel_requested = False

    def run(self):
        try:
            items = [i for i in FR.plan() if i.key in set(self.keys)]
            out = FR.download(items, progress=lambda f, m: self.step.emit(f, m),
                              is_cancelled=lambda: self.cancel_requested)
        except Exception as ex:
            self.failed.emit(f"{type(ex).__name__}: {ex}")
        else:
            self.finished.emit(out)


class FirstRunDialog(QDialog):
    """The one-time offer.  Ticked by default; the reason for each item is on the row."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Plumbline - External Data")
        self.resize(760, 560)
        self.result: dict | None = None
        self.checked: list[str] = []

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("<b>Where Plumbline would like to fetch from - offered once, ticked by default</b>"))
        lay.addWidget(Hint(
            "None of this is inside the program: grids and models are downloaded the first time "
            "they are needed, or now, so the download is small and the data is current.  Untick "
            "anything you do not want today - nothing is fetched behind your back, and every item "
            "can be fetched later (Settings > External data sources) or left alone, in which case "
            "the program says it cannot do that particular conversion rather than guessing."))

        self.rows: list[tuple[QCheckBox, FR.Item, QLabel]] = []
        for item in FR.plan():
            box = QCheckBox(f"{item.title}   ({item.size})")
            box.setChecked(True)
            box.setEnabled(item.mb > 0)          # imagery has no size: it is a cache, always on
            box.setToolTip(item.why)
            why = QLabel(item.why)
            why.setWordWrap(True)
            why.setStyleSheet("color:#8a94a1; margin-left:24px;")
            need = QLabel("Needed for: " + ", ".join(item.needed_by) if item.needed_by else "")
            need.setWordWrap(True)
            need.setStyleSheet("color:#8a94a1; margin-left:24px;")
            lay.addWidget(box)
            lay.addWidget(why)
            if item.needed_by:
                lay.addWidget(need)
            self.rows.append((box, item, why))

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setVisible(False)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        lay.addWidget(self.bar)
        lay.addStretch(1)

        row = QHBoxLayout()
        self.b_all = QPushButton("Tick all")
        self.b_none = QPushButton("Tick none")
        row.addWidget(self.b_all)
        row.addWidget(self.b_none)
        row.addStretch(1)
        self.b_go = QPushButton("Download now")
        self.b_go.setProperty("accent", True)
        self.b_later = QPushButton("Later")
        row.addWidget(self.b_go)
        row.addWidget(self.b_later)
        lay.addLayout(row)

        self.b_all.clicked.connect(lambda: [b.setChecked(True) for b, i, _ in self.rows if i.mb > 0])
        self.b_none.clicked.connect(lambda: [b.setChecked(b not in [r[0] for r in self.rows]) for b, i, _ in self.rows if i.mb > 0])
        self.b_go.clicked.connect(self.fetch)
        self.b_later.clicked.connect(self.reject)

    def keys(self) -> list[str]:
        return [i.key for b, i, _ in self.rows if b.isChecked()]

    def fetch(self):
        keys = self.keys()
        if not keys:
            FR.mark_asked("declined")
            self.reject()
            return

        self.checked = keys
        self.b_go.setEnabled(False)
        self.b_later.setText("Cancel")
        self.bar.setVisible(True)
        self._thread = QThread(self)
        self._worker = _FetchWorker(keys)
        self._worker.moveToThread(self._thread)
        self._worker.step.connect(self._on_step)
        self._worker.finished.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._thread.started.connect(self._worker.run)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    def _on_step(self, fraction: float, message: str):
        self.bar.setValue(int(fraction * 100))
        self.lbl.setText(message + "...")

    def _on_done(self, out: dict):
        self.result = out
        if hasattr(self, "_thread"):
            self._thread.quit()
        FR.mark_asked("downloaded" if not out["failed"] else "partly")
        done, skipped, failed = len(out["done"]), len(out["skipped"]), len(out["failed"])
        word = (f"{done} downloaded, {skipped} already present")
        if failed:
            word += (f", {failed} could not be fetched:\n"
                     + "\n".join(f"  {k}: {why}" for k, why in out["failed"][:4])
                     + "\n\nEverything else works; a missing grid is reported when a conversion "
                       "needs it.")
        info_box(self, "External Data", word + "\n\nEvery source stays visible and editable under "
                                               "Settings > External data sources.")
        self.accept()

    def _on_failed(self, message: str):
        if hasattr(self, "_thread"):
            self._thread.quit()
        self.lbl.setText(f"The download could not be made: {message}")
        self.b_go.setEnabled(True)
        self.b_later.setText("Later")
        FR.mark_asked("offered")

    def closeEvent(self, event):
        thread = getattr(self, "_thread", None)
        if thread is not None and thread.isRunning():
            self._worker.cancel_requested = True
            self.lbl.setText("Stopping after the current item...")
            event.ignore()
            return
        super().closeEvent(event)


def offer_on_first_run(parent=None) -> bool:
    """Show the offer once per installation.  True when the dialog was shown."""
    if FR.already_asked():
        return False
    dlg = FirstRunDialog(parent)
    dlg.exec()
    if not FR.already_asked():
        # Whatever was answered - download, untick, Later - the question has been asked.  Nothing
        # is fetched behind the user's back and nothing is asked twice.
        FR.mark_asked("later" if not dlg.checked else "offered")
    return True


__all__ = ["FirstRunDialog", "offer_on_first_run"]
