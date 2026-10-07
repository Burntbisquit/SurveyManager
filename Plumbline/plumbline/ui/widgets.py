"""Small reusable widgets and helpers."""
from __future__ import annotations

import math
import threading
import traceback

from PySide6.QtCore import QEventLoop, QObject, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressDialog, QPushButton, QSizePolicy, QSpinBox, QToolButton, QVBoxLayout, QWidget, QAbstractSpinBox)

from . import icons


# ----------------------------------------------------------------------------- background work
class _Result(QObject):
    done = Signal(object, object)       # (result, error_traceback)


def run_blocking(parent, text: str, fn, *args, cancellable: bool = False, **kw):
    """Run fn(*args) on a worker thread while showing a busy dialog; the UI keeps repainting.

    Returns fn's result, or raises RuntimeError(traceback text) if it failed.
    """
    holder = {}
    res = _Result()
    loop = QEventLoop()

    def target():
        try:
            holder["r"] = fn(*args, **kw)
            err = None
        except BaseException:
            err = traceback.format_exc()
        res.done.emit(holder.get("r"), err)

    res.done.connect(lambda r, e: (holder.update(err=e), loop.quit()), Qt.QueuedConnection)
    dlg = QProgressDialog(text, None, 0, 0, parent)
    dlg.setWindowTitle("Working...")
    dlg.setWindowModality(Qt.WindowModal)
    dlg.setMinimumDuration(400)
    dlg.setCancelButton(None)
    t = threading.Thread(target=target, daemon=True)
    t.start()
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        loop.exec()
    finally:
        QApplication.restoreOverrideCursor()
        dlg.close()
    t.join()
    if holder.get("err"):
        raise RuntimeError(holder["err"])
    return holder.get("r")


def error_box(parent, title: str, text: str, detail: str | None = None):
    m = QMessageBox(parent)
    m.setIcon(QMessageBox.Warning)
    m.setWindowTitle(title)
    m.setText(text)
    if detail:
        m.setDetailedText(detail)
    m.exec()


def info_box(parent, title: str, text: str):
    m = QMessageBox(parent)
    m.setIcon(QMessageBox.Information)
    m.setWindowTitle(title)
    m.setText(text)
    m.exec()


def confirm(parent, title: str, text: str, yes: str = "Yes") -> bool:
    m = QMessageBox(parent)
    m.setIcon(QMessageBox.Question)
    m.setWindowTitle(title)
    m.setText(text)
    b = m.addButton(yes, QMessageBox.AcceptRole)
    m.addButton("Cancel", QMessageBox.RejectRole)
    m.exec()
    return m.clickedButton() is b


def destructive_confirm(parent, title: str, steps: list[tuple[str, str]],
                        final: str = "Last chance to cancel. Continue?") -> bool:
    """Ask every warning in *steps*, then ask a separate last-chance question.

    Keeping the final question separate matters: combining "are you sure?" and "last
    chance" in one box reduced the promised three-stage overwrite warning to two clicks.
    Returns True only when every warning and the final confirmation are accepted.
    """
    for text, yes in steps:
        m = QMessageBox(parent)
        m.setIcon(QMessageBox.Warning)
        m.setWindowTitle(title)
        m.setText(text)
        b = m.addButton(yes, QMessageBox.AcceptRole)
        m.addButton("Cancel", QMessageBox.RejectRole)
        m.setDefaultButton(QMessageBox.Cancel)
        m.exec()
        if m.clickedButton() is not b:
            return False

    m = QMessageBox(parent)
    m.setIcon(QMessageBox.Warning)
    m.setWindowTitle(title)
    m.setText(final)
    m.setInformativeText("Continuing will delete the prior contents of the project folder.")
    b = m.addButton("Continue - delete prior data", QMessageBox.AcceptRole)
    m.addButton("Cancel - keep everything", QMessageBox.RejectRole)
    m.setDefaultButton(QMessageBox.Cancel)
    m.exec()
    return m.clickedButton() is b


# ----------------------------------------------------------------------------- widgets
class ColorButton(QPushButton):
    colorChanged = Signal(tuple)

    def __init__(self, rgb=(255, 255, 255), parent=None):
        super().__init__(parent)
        self._rgb = tuple(rgb)
        self.setFixedSize(34, 22)
        self.clicked.connect(self._pick)
        self._paint()

    def rgb(self):
        return self._rgb

    def setRgb(self, rgb):
        self._rgb = tuple(int(c) for c in rgb)
        self._paint()

    def _paint(self):
        r, g, b = self._rgb
        self.setStyleSheet(f"QPushButton {{ background: rgb({r},{g},{b}); border: 1px solid #667; border-radius: 4px; padding:0; }}")

    def _pick(self):
        c = QColorDialog.getColor(QColor(*self._rgb), self, "Layer colour")
        if c.isValid():
            self.setRgb((c.red(), c.green(), c.blue()))
            self.colorChanged.emit(self._rgb)


class Hint(QLabel):
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setProperty("hint", True)


class Banner(QLabel):
    """Coloured message strip: kind = info | warn | bad."""

    def __init__(self, text: str = "", kind: str = "info", parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setProperty("banner", kind)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)

    def set(self, text: str, kind: str = "info"):
        self.setText(text)
        self.setProperty("banner", kind)
        self.style().unpolish(self)
        self.style().polish(self)
        self.setVisible(bool(text))


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def tool_button(icon_name: str, tip: str, checkable: bool = False, parent=None) -> QToolButton:
    b = QToolButton(parent)
    b.setIcon(icons.icon(icon_name))
    b.setToolTip(tip)
    b.setCheckable(checkable)
    b.setAutoRaise(True)
    b.setIconSize(QSize(20, 20))
    return b


def widen_chars(widget, chars: int, extra_px: int = 0):
    """Make a spin box / line edit wide enough to show *chars* characters.

    Qt sizes an input from the widest value it thinks it can hold, which is consistently
    narrower than what a user types into it ("1.00017" is fine; "1.00017000" is not).  A
    figure that has to be read exactly - a scale factor, a northing - gets its own width.
    Use the widget's own font, so it still works on the 125% DPI laptops.
    """
    from PySide6.QtGui import QFontMetrics
    fm = QFontMetrics(widget.font())
    width = fm.horizontalAdvance("0" * int(chars)) + extra_px
    widget.setMinimumWidth(max(width, widget.minimumWidth()))
    return widget


def dspin(value=0.0, lo=-1e12, hi=1e12, dec=3, step=0, suffix="") -> QDoubleSpinBox:
    s = QDoubleSpinBox()
    s.setDecimals(dec)
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setValue(value)
    s.setGroupSeparatorShown(False)
    s.setKeyboardTracking(False)
    s.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    if suffix:
        s.setSuffix(suffix)
    s.setAlignment(Qt.AlignRight)
    return s


def ispin(value=0, lo=-10 ** 9, hi=10 ** 9) -> QSpinBox:
    s = QSpinBox()
    s.setRange(lo, hi)
    s.setValue(value)
    s.setKeyboardTracking(False)
    return s


class Collapsible(QWidget):
    """A titled section that is closed until the user opens it.

    For detail that is worth having and not worth showing: the arithmetic behind a factor,
    a raw parameter list, the fine print.  Closed by default means the dialog fits on a
    laptop screen; opened means the information is exactly where it belongs rather than
    hidden in a tooltip nobody reads.
    """

    def __init__(self, title: str, parent=None, expanded: bool = False, tooltip: str = ""):
        super().__init__(parent)
        from PySide6.QtWidgets import QToolButton
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(4)
        self.button = QToolButton(self)
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setChecked(bool(expanded))
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.button.setStyleSheet("QToolButton{border:none;font-weight:bold;}")
        if tooltip:
            self.button.setToolTip(tooltip)
        self.body = QWidget(self)
        self.body.setVisible(bool(expanded))
        self._root.addWidget(self.button)
        self._root.addWidget(self.body)
        self.button.toggled.connect(self._on_toggle)

    def _on_toggle(self, on: bool):
        self.button.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.body.setVisible(on)

    def body_layout(self, kind="v"):
        """A layout on the collapsible's body, indented under the arrow."""
        from PySide6.QtWidgets import QGridLayout
        cls = {"v": QVBoxLayout, "h": QHBoxLayout, "form": QFormLayout, "grid": QGridLayout}[kind]
        lay = cls(self.body)
        lay.setContentsMargins(18, 0, 0, 0)
        return lay


class FormDialog(QDialog):
    """Base dialog: title, optional intro, a QFormLayout body and OK/Cancel."""

    def __init__(self, parent=None, title: str = "", intro: str = "", ok_text: str = "OK", min_width: int = 460):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(min_width)
        self.root = QVBoxLayout(self)
        self.root.setSpacing(10)
        if intro:
            self.root.addWidget(Hint(intro))
        self.form = QFormLayout()
        self.form.setLabelAlignment(Qt.AlignRight)
        self.form.setSpacing(8)
        self.root.addLayout(self.form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText(ok_text)
        self.buttons.accepted.connect(self._try_accept)
        self.buttons.rejected.connect(self.reject)
        self.root.addWidget(self.buttons)

    def _try_accept(self):
        err = self.validate()
        if err:
            error_box(self, self.windowTitle(), err)
            return
        self.accept()

    def validate(self) -> str | None:
        return None


def fmt_coord(v: float, decimals: int = 3) -> str:
    return "" if (v is None or (isinstance(v, float) and not math.isfinite(v))) else f"{v:,.{decimals}f}"
