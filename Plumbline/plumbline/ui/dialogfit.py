"""Keep dialogs on the screen.

A dialog that is taller than the monitor is a dialog whose OK button nobody can reach.  It
happens the moment a form grows (a new group box, a longer hint, a bigger table), and it is
invisible on a developer's 1440p display and obvious on a survey laptop at 1366x768.

Two things fix it, and this module does both automatically for **every** dialog in the
program, so a dialog has to try hard to escape:

1. **Clamp**: never taller or wider than the screen it will appear on (minus the desktop's
   own furniture), and never taller than 92% of it.
2. **Scroll**: if the dialog's own content needs more room than that, its content goes
   inside a QScrollArea with the OK/Cancel row left outside it, so the buttons are always
   reachable and the middle scrolls.

The scroll area is added *around the existing layout*, not by rebuilding the dialog, so a
dialog does not have to be written with this in mind.  A dialog that wants to opt out (a
canvas-sized viewer, say) sets ``_no_autofit = True``.

Only the program's *own* dialogs are touched.  Qt's own (QMessageBox, QFileDialog, the colour
picker) size themselves sensibly and constrain themselves to the desktop; wrapping those would
be more likely to break them than to help them.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLayout, QScrollArea,
                               QSizePolicy, QVBoxLayout)

#: Never use more than this fraction of the available screen height.
MAX_SCREEN_FRACTION = 0.92
#: Leave this much room for the desktop's own furniture (taskbar, window title bar).
MARGIN_PX = 24


def available_size(widget):
    """The room a widget may occupy on the screen it is on (or the primary screen)."""
    screen = None
    try:
        screen = widget.screen() or (widget.windowHandle().screen() if widget.windowHandle() else None)
    except Exception:
        screen = None
    if screen is None:
        screen = QApplication.primaryScreen()
    if screen is None:                                    # headless with no platform screens
        return 1600, 900
    g = screen.availableGeometry()
    return max(640, g.width() - MARGIN_PX), max(420, int(g.height() * MAX_SCREEN_FRACTION) - MARGIN_PX)


def _wrap_in_scroll(dlg: QDialog, keep: list) -> None:
    """Move everything except *keep* (the button row) into a scroll area, in place."""
    lay: QLayout = dlg.layout()
    if lay is None or isinstance(lay, QScrollArea):
        return
    scroll = QScrollArea(dlg)
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QScrollArea.NoFrame)
    scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    inner = QDialog(dlg)                                  # a plain container, not a dialog
    inner.setWindowFlags(Qt.Widget)
    inner_layout = QVBoxLayout(inner)
    inner_layout.setContentsMargins(0, 0, 0, 0)
    moved = 0
    for i in reversed(range(lay.count())):
        item = lay.itemAt(i)
        w = item.widget()
        if w is None or w in keep:
            continue
        if isinstance(w, QDialogButtonBox) and not keep:
            continue
        lay.takeAt(i)
        inner_layout.insertWidget(0, w)
        moved += 1
    if not moved:                                         # nothing worth scrolling
        scroll.deleteLater()
        inner.deleteLater()
        return
    inner_layout.addStretch(1)
    scroll.setWidget(inner)
    lay.insertWidget(0, scroll, 1)


def is_ours(dlg) -> bool:
    """True for a dialog built out of this program's own code, false for one of Qt's own.

    Qt's dialogs (QMessageBox, QFileDialog, the colour picker) arrive with their class defined
    inside PySide6; anything else - including a dialog defined in a test or a small script -
    is fair game.
    """
    return not (type(dlg).__module__ or "").startswith("PySide6")


def fit_dialog(dlg: QDialog) -> None:
    """Clamp a dialog to the screen, and make it scroll if its content still needs more."""
    if getattr(dlg, "_no_autofit", False) or getattr(dlg, "_fit_done", False):
        return
    if not is_ours(dlg):
        return
    dlg._fit_done = True
    max_w, max_h = available_size(dlg)
    hint = dlg.sizeHint()
    too_tall = hint.height() > max_h or dlg.height() > max_h
    too_wide = hint.width() > max_w or dlg.width() > max_w
    if too_tall:
        buttons = [b for b in dlg.findChildren(QDialogButtonBox)]
        _wrap_in_scroll(dlg, buttons)
    if too_tall or too_wide:
        dlg.setMaximumSize(max_w, max_h)
        w = min(max(dlg.width(), 480), max_w)
        h = min(max(dlg.height(), 400), max_h)
        dlg.resize(w, h)


class _Fitter(QObject):
    """Application-wide: fit every dialog as it is shown.

    Installed once from ``theme.apply_theme`` (which every entry point calls), so no dialog
    has to remember, including dialogs written later.
    """

    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.Show, QEvent.ShowToParent) and isinstance(obj, QDialog):
            try:
                fit_dialog(obj)
            except Exception:
                pass
        return False


_fitter: _Fitter | None = None


def install(app) -> None:
    """Idempotent - calling it twice does not install two filters."""
    global _fitter
    if _fitter is None:
        _fitter = _Fitter()
    try:
        app.removeEventFilter(_fitter)
    except Exception:
        pass
    app.installEventFilter(_fitter)
