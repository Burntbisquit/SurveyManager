"""The licence and the end-user agreement, on screen: first run, and from Help at any time.

Two jobs, one dialog:

* **Accept** - shown the first time this build is started (and again if the agreement's version
  changes).  The two parts are on two tabs, in the order they are written, with the commercial-use
  limitation on the first tab and the general agreement on the second.  The Accept button stays
  disabled until the box is ticked, because "I agree" that can be pressed without reading is not
  agreement; Declining closes the program rather than hiding the question.
* **Read** - the same dialog without the accept machinery, from **Help > Licence Agreement...**.
  A user who accepted it eight months ago must be able to read what they accepted.

The text is not duplicated here: it comes from :mod:`plumbline.core.licence`, the same module the
shipped ``LICENSE.md`` and ``EULA.md`` are generated from, so the words on screen and the words on
disk cannot drift apart.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QPushButton, QTabWidget, QTextBrowser, QVBoxLayout)

from ..core import licence as LIC
from ..core.settings import settings


def _markdown_html(text: str) -> str:
    """Enough Markdown for these documents: headings, bold, rules and paragraphs.

    Deliberately not a Markdown library: the licence must render identically everywhere, with no
    dependency that could be missing on a locked-down machine.
    """
    out = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if block.startswith("#"):
            level = len(block) - len(block.lstrip("#"))
            body = block[level:].strip()
            out.append(f"<h{min(level + 1, 6)}>{_inline(body)}</h{min(level + 1, 6)}>")
        elif set(block) <= {"-"} and len(block) >= 3:
            out.append("<hr>")
        else:
            out.append(f"<p style='margin:6px 0'>{_inline(block).replace(chr(10), '<br>')}</p>")
    return "".join(out)


def _inline(text: str) -> str:
    import re
    text = (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"<i>\1</i>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


class LicenceDialog(QDialog):
    """The agreement, read-only, with (in accept mode) the box that says you read it."""

    def __init__(self, parent=None, accept_mode: bool = False):
        super().__init__(parent)
        self.accept_mode = accept_mode
        self.setWindowTitle("Licence Agreement" if not accept_mode else "Licence Agreement - Please Read")
        self.resize(860, 680)
        lay = QVBoxLayout(self)

        head = QLabel(
            f"<b>Plumbline is licensed for testing and private use only.</b>  "
            f"Commercial use is not granted.  Version {LIC.VERSION}.")
        head.setWordWrap(True)
        lay.addWidget(head)
        if accept_mode:
            note = QLabel("Read both parts. Part 1 governs commercial use; Part 2 is the general "
                          "end-user agreement and applies in full.")
            note.setWordWrap(True)
            note.setStyleSheet("color:#8a94a1;")
            lay.addWidget(note)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._page(f"# {LIC.COMMERCIAL_TERMS_TITLE}\n\n{LIC.COMMERCIAL_TERMS}"),
                         "1 - Licence (no commercial use)")
        self.tabs.addTab(self._page(f"# {LIC.EULA_TITLE}\n\n{LIC.EULA}"),
                         "2 - General EULA")
        lay.addWidget(self.tabs, 1)

        self.chk = QCheckBox("I have read both parts and I agree to them.  I will not use this "
                             "software commercially.")
        self.chk.setVisible(accept_mode)
        lay.addWidget(self.chk)

        if accept_mode:
            bb = QDialogButtonBox()
            self.b_ok = bb.addButton("I Agree", QDialogButtonBox.AcceptRole)
            self.b_no = bb.addButton("Decline and Close", QDialogButtonBox.RejectRole)
            self.b_ok.setEnabled(False)
            self.chk.toggled.connect(self.b_ok.setEnabled)
            bb.accepted.connect(self.accept)
            bb.rejected.connect(self.reject)
            lay.addWidget(bb)
        else:
            row = QHBoxLayout()
            row.addStretch(1)
            b = QPushButton("Close")
            b.clicked.connect(self.accept)
            row.addWidget(b)
            lay.addLayout(row)

    def _page(self, markdown: str) -> QTextBrowser:
        t = QTextBrowser()
        t.setOpenExternalLinks(True)
        t.setHtml(_markdown_html(markdown))
        t.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        return t


def accepted_version() -> int:
    try:
        return int(settings().get("licence_accepted_version") or 0)
    except Exception:
        return 0


def needs_acceptance() -> bool:
    """Has *this* version of the agreement been accepted in this installation?"""
    return accepted_version() < LIC.VERSION


def record_acceptance() -> None:
    settings().set("licence_accepted_version", LIC.VERSION)


def ensure_accepted(parent=None) -> bool:
    """Show the agreement when it has not been accepted; True when the program may continue.

    Called once, before the main window is built: a user who declines should never reach a window
    that has already opened their files.
    """
    if not needs_acceptance():
        return True
    dlg = LicenceDialog(parent, accept_mode=True)
    if dlg.exec() and dlg.chk.isChecked():
        record_acceptance()
        return True
    return False


def show_licence(parent=None) -> None:
    LicenceDialog(parent, accept_mode=False).exec()


__all__ = ["LicenceDialog", "accepted_version", "needs_acceptance", "record_acceptance",
           "ensure_accepted", "show_licence"]
