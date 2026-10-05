"""The vertical-datum and ground halves of a coordinate-system choice, as one widget.

The change order (item 7) says the coordinate-system choice has to carry **all three** of its
parts - the horizontal system, the vertical datum and the ground scale - and that it has to be
there *when it matters*: at import, and when a new project is started.  Those two places are where
a job's heights and its grid/ground state are decided, and they are the two places a surveyor is
least likely to go back and visit later.

This widget is those two parts, so the same rows appear wherever they are asked:

* **Vertical datum** - NAVD88 / NGVD29 / ellipsoid / assumed, with the geoid model that ties it to
  the ellipsoid (``core.vdatum``).  This is what says whether a height in this job is comparable
  with anything outside it.
* **Use ground coordinates** - the tick, then the SAF and the base point it scales about.  The
  SAF and the base N/E boxes are **locked until the tick is set** (item 10): a factor typed while
  the job is grid does nothing at all, and a live box says otherwise.  Northing is above easting,
  as it is everywhere else a coordinate is typed here.  The SAF keeps 11 decimals, so
  1.000136506 is that number and not 1.00013650 (item 11).
"""
from __future__ import annotations

from PySide6.QtWidgets import (QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QVBoxLayout,
                               QWidget)

from ..core import crs as C
from ..core import vdatum as VD
from .widgets import Hint, dspin, widen_chars


class VerticalAndGroundPanel(QWidget):
    """Vertical datum + geoid + the ground (SAF) tick, for anywhere a CRS is chosen."""

    def __init__(self, parent=None, show_vertical: bool = True):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self.cmb_datum = QComboBox()
        for d in VD.VERTICAL_DATUMS:
            self.cmb_datum.addItem(d.name, d.key)
        self.cmb_datum.setCurrentIndex(max(0, self.cmb_datum.findData(VD.DEFAULT_DATUM)))
        self.cmb_geoid = QComboBox()
        self.cmb_geoid.addItem("(none - not an orthometric datum)", "")
        for m in VD.GEOID_MODELS:
            self.cmb_geoid.addItem(f"{m.name}  ({m.region}, {m.accuracy_m:g} m)", m.key)
        self.lbl_datum = QLabel("")
        self.lbl_datum.setWordWrap(True)
        if show_vertical:
            form.addRow("Vertical datum:", self.cmb_datum)
            form.addRow("Geoid model:", self.cmb_geoid)
            form.addRow("", self.lbl_datum)
        root.addLayout(form)
        if not show_vertical:
            self.cmb_datum.setVisible(False)
            self.cmb_geoid.setVisible(False)
            self.lbl_datum.setVisible(False)

        self.chk_ground = QCheckBox("Use ground coordinates (TXDOT SAF - stored coordinates are ground)")
        self.chk_ground.setToolTip("With this clear the job is grid: ground = grid, SAF = 1.0, and the\n"
                                   "SAF box below is locked.  Tick it to store scaled coordinates.")
        root.addWidget(self.chk_ground)
        self.ground_form = QFormLayout()
        self.ground_form.setContentsMargins(18, 0, 0, 0)
        self.sp_by = widen_chars(dspin(0.0, -1e12, 1e12, 3), 18)
        self.sp_bx = widen_chars(dspin(0.0, -1e12, 1e12, 3), 18)
        self.sp_cf = widen_chars(dspin(1.0, 0.9, 1.1, 11, 0.000001), 18)
        self.sp_by.setToolTip("Base northing the SAF scales about - the TXDOT convention is the "
                              "projection origin, 0.000.")
        self.sp_bx.setToolTip("Base easting the SAF scales about.")
        self.sp_cf.setToolTip("Ground over grid, entered in full: 1.000136506 is not 1.00013650.")
        self.ground_form.addRow("Base Northing:", self.sp_by)
        self.ground_form.addRow("Base Easting:", self.sp_bx)
        self.ground_form.addRow("Surface Adjustment Factor (ground / grid):", self.sp_cf)
        root.addLayout(self.ground_form)
        self.ground_hint = Hint("Ground coordinates only exist when the tick is set: the base point and the "
                                "SAF are how the two are related, so they are locked until it is.  "
                                "A SAF of 1.000000000 is grid.")
        root.addWidget(self.ground_hint)

        self.chk_ground.toggled.connect(self._sync)
        self.cmb_datum.currentIndexChanged.connect(self._datum_changed)
        self._sync(self.chk_ground.isChecked())
        self._datum_changed()

    # ------------------------------------------------------------------ behaviour
    def _sync(self, on: bool):
        for w in (self.sp_by, self.sp_bx, self.sp_cf):
            w.setEnabled(bool(on))

    def set_unassigned(self, hide: bool):
        """Hide ground scaling when the project has no horizontal CRS.

        A surface adjustment factor is a relationship to a projected grid, so it is
        meaningless for unassigned coordinates.  Keep the vertical-datum choice available,
        but hide the ground checkbox, every form row (including its label), and its hint.
        """
        visible = not hide
        if hide:
            # Do not let a previously selected, now-hidden option leak into an unassigned CRS.
            self.chk_ground.setChecked(False)
        self.chk_ground.setVisible(visible)
        for field in (self.sp_by, self.sp_bx, self.sp_cf):
            self.ground_form.setRowVisible(field, visible)
        self.ground_hint.setVisible(visible)
        self._sync(self.chk_ground.isChecked())

    def _datum_changed(self):
        d = VD.datum(self.cmb_datum.currentData())
        if d is None:
            self.lbl_datum.setText("")
            return
        self.lbl_datum.setText(f"{d.note}  Tied to the ellipsoid by: {d.tied_by}.")
        # An orthometric datum needs a geoid model; ellipsoid / assumed heights do not.
        want = d.kind == "orthometric"
        self.cmb_geoid.setEnabled(want)
        if not want:
            self.cmb_geoid.setCurrentIndex(0)
        elif not self.cmb_geoid.currentData():
            self.cmb_geoid.setCurrentIndex(max(0, self.cmb_geoid.findData(VD.DEFAULT_GEOID)))

    # ------------------------------------------------------------------ data
    def set_from(self, crs: C.ProjectCRS):
        """Load the three parts out of an existing project CRS."""
        i = self.cmb_datum.findData(getattr(crs, "vdatum", "") or VD.DEFAULT_DATUM)
        self.cmb_datum.setCurrentIndex(max(0, i))
        j = self.cmb_geoid.findData(getattr(crs, "geoid", "") or "")
        self.cmb_geoid.setCurrentIndex(max(0, j))
        g = crs.ground
        self.chk_ground.setChecked(bool(g.enabled))
        self.sp_by.setValue(float(g.base_y))
        self.sp_bx.setValue(float(g.base_x))
        self.sp_cf.setValue(float(g.saf) or 1.0)
        self._sync(self.chk_ground.isChecked())

    def apply_to(self, crs: C.ProjectCRS) -> C.ProjectCRS:
        """Write the three parts into a project CRS (in place - the CRS object is the project's)."""
        crs.vdatum = self.cmb_datum.currentData() or ""
        crs.geoid = self.cmb_geoid.currentData() or ""
        g = crs.ground
        g.enabled = bool(self.chk_ground.isChecked())
        g.base_y = float(self.sp_by.value())
        g.base_x = float(self.sp_bx.value())
        g.saf = float(self.sp_cf.value()) or 1.0
        if not g.enabled:
            g.saf = 1.0
            g.base_x = g.base_y = 0.0
        return crs

    def record(self) -> dict:
        """The same three parts as a plain record (``core.filecrs``)."""
        return {"vertical": self.cmb_datum.currentData() or "",
                "geoid": self.cmb_geoid.currentData() or "",
                "ground": bool(self.chk_ground.isChecked()),
                "saf": float(self.sp_cf.value()) or 1.0,
                "base_n": float(self.sp_by.value()),
                "base_e": float(self.sp_bx.value())}

    def validate(self) -> str | None:
        if self.chk_ground.isChecked():
            saf = float(self.sp_cf.value())
            if saf <= 1.0 and abs(saf - 1.0) > 1e-12:
                return ("A SAF below 1.0 makes the ground smaller than the grid.  That is a "
                        "reciprocal typed into the wrong box - check the number.")
        return None


__all__ = ["VerticalAndGroundPanel"]
