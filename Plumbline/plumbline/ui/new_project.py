"""New-project dialog.

Three decisions, in the order a surveyor actually makes them:

1. **What is the job called?**  (also the project file name and the job folder name)
2. **Where does it live, and does the job folder get built?**
3. **What coordinate system?**  - and the default answer is *none yet*.

Why "unassigned" is the default
-------------------------------
Plumbline used to open a new project on a coordinate system whether or not the user
had one in mind, and the failure mode was silent: work drew fine, then the KML export
landed in the wrong hemisphere. Now a new project starts **UNASSIGNED** - a flag that
reads *NO CRS* in the status bar - and the moment a tool genuinely needs to know where
on the earth the job is (imagery, KML, GIS, reprojection, datum work), it says so:

    "Grid convergence needs a coordinate system - this project's CRS is UNASSIGNED.
     Select CRS first (Survey > Project Coordinate System...)."

Drawing, surfaces, volumes, DXF and point handling never need a CRS and never nag.

What the coordinate-system list contains
----------------------------------------
The ten Texas State Plane NAD83(2011) zone definitions - five zones, each in metres and
in US survey feet - plus WGS 84.  Not the whole EPSG register: a picker that opens on
nine thousand entries is a picker nobody reads.  Anything else can still be typed in by
EPSG code or searched, and legacy codes (2275-2279) are translated forward to their
2011 equivalents rather than handed back as a deprecated zone.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QRadioButton, QScrollArea, QVBoxLayout, QWidget)

from ..core import crs as C
from ..core import units as U
from .crs_dialog import CRSPicker
from .crs_extra import VerticalAndGroundPanel
from .job_setup import JobSetupPanel
from .widgets import Hint, error_box

#: The zones offered as one click.  Each row is (epsg, label) and both unit variants
#: of every zone are present, because picking the metre code by mistake is a 3.28x
#: error rather than a rounding error.
def _texas_rows() -> list[tuple[object, str]]:
    """Texas State Plane NAD83(2011) in US survey feet, per zone.

    Other eras and units can be searched via the EPSG register.
    """
    zones = ["North Central", "North", "Central", "South Central", "South"]
    rows = []
    for key, info in C.TEXAS_ZONES.items():
        if info.get("state") == "TX" and info.get("era") == "2011" and info.get("units") == "USft":
            rows.append((key, f"{info['name']}  -  US survey feet"))
    rows.sort(key=lambda t: (zones.index(C.TEXAS_ZONES[t[0]]["zone"])
                             if C.TEXAS_ZONES[t[0]]["zone"] in zones else 9))
    return rows


class NewProjectDialog(QDialog):
    _no_autofit = True

    def __init__(self, parent=None, name: str = "Untitled", job_hint: str = ""):
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.resize(780, 640)
        self.setMinimumSize(720, 500)
        self.crs: C.ProjectCRS | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 12, 14, 12)
        outer.setSpacing(8)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        inner = QWidget()
        root = QVBoxLayout(inner)
        root.setSpacing(10)
        root.setContentsMargins(4, 4, 10, 4)

        # ---- 1. name
        form = QFormLayout()
        self.ed_name = QLineEdit(name)
        self.ed_name.setPlaceholderText("e.g. 23-036.03 Murchison")
        form.addRow("Job name:", self.ed_name)
        root.addLayout(form)

        # ---- 2. job folder  (one folder choice: the job folder is named after the job)
        self.setup = JobSetupPanel(self, job_hint)
        self.ed_name.textChanged.connect(lambda t: self.setup.set_job_name(t))
        self.setup.set_job_name(self.ed_name.text())
        root.addWidget(self.setup)

        # ---- 3. coordinate system
        root.addWidget(QLabel("<b>Coordinate system</b>"))
        self.r_unassigned = QRadioButton(
            "Unassigned  -  draw now, choose a coordinate system when you need one")
        self.r_unassigned.setToolTip(
            "Drawing, surfaces, volumes and DXF do not need a coordinate system.\n"
            "Imagery, KML, GIS and datum work do - they will ask you to select CRS first.")
        self.r_crs = QRadioButton(
            "Use a coordinate system  (needed for imagery, KML, GIS and datum work)")
        self.r_other = QRadioButton("Search the full EPSG register:")
        self.r_unassigned.setChecked(True)
        for r in (self.r_unassigned, self.r_crs, self.r_other):
            root.addWidget(r)

        # -- Texas quick list
        self.texas = QWidget()
        tf = QFormLayout(self.texas)
        tf.setContentsMargins(24, 0, 0, 0)
        self.cmb_texas = QComboBox()
        for key, label in _texas_rows():
            prefix = "EPSG:" if not str(key).endswith("-ft") else ""
            self.cmb_texas.addItem(f"{prefix}{key}   {label}", key)
        self.cmb_texas.setCurrentIndex(max(0, self.cmb_texas.findData(C.TEXAS_DEFAULT_EPSG)))
        tf.addRow("Texas State Plane:", self.cmb_texas)
        root.addWidget(self.texas)

        # -- unit for an unassigned project
        self.unit_row = QWidget()
        uh = QHBoxLayout(self.unit_row)
        uh.setContentsMargins(24, 0, 0, 0)
        self.cmb_unit = QComboBox()
        for u in U.LINEAR_CHOICES:
            self.cmb_unit.addItem(U.LABEL[u], u)
        self.cmb_unit.setCurrentIndex(max(0, self.cmb_unit.findData("ftUS")))
        uh.addWidget(QLabel("Units for this job:"))
        uh.addWidget(self.cmb_unit)
        uh.addStretch(1)
        root.addWidget(self.unit_row)

        # -- full search
        self.picker_holder = QWidget()
        ph = QVBoxLayout(self.picker_holder)
        ph.setContentsMargins(24, 0, 0, 0)
        self.picker = CRSPicker(kinds=("projected",))
        self.picker.setMinimumHeight(220)
        ph.addWidget(self.picker)
        self.picker_holder.setVisible(False)
        root.addWidget(self.picker_holder)

        # ---- 3b. vertical datum and ground scale - the other two parts of the same decision
        self.lbl_heights = QLabel("<b>Heights and ground scale</b>")
        root.addWidget(self.lbl_heights)
        self.extra = VerticalAndGroundPanel(self)
        root.addWidget(self.extra)

        root.addStretch(1)

        scroll.setWidget(inner)
        outer.addWidget(scroll, 1)

        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.buttons.button(QDialogButtonBox.Ok).setText("Create")
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

        self.r_unassigned.toggled.connect(self._sync)
        self.r_crs.toggled.connect(self._sync)
        self.r_other.toggled.connect(self._sync)
        self.extra.chk_ground.setChecked(False)       # a new job starts as grid until told otherwise
        self._sync()

    # ------------------------------------------------------------------ state
    def _sync(self):
        unassigned = self.r_unassigned.isChecked()
        self.unit_row.setVisible(unassigned)
        self.texas.setVisible(self.r_crs.isChecked())
        self.picker_holder.setVisible(self.r_other.isChecked())
        if self.r_other.isChecked():
            self.picker.setFocus()
        self.lbl_heights.setVisible(not unassigned)
        self.extra.setVisible(not unassigned)
        self.extra.set_unassigned(unassigned)

    def _accept(self):
        if self.r_unassigned.isChecked():
            self.crs = C.ProjectCRS.unassigned(self.cmb_unit.currentData())
        elif self.r_crs.isChecked():
            key = self.cmb_texas.currentData()
            try:
                self.crs = C.ProjectCRS.from_key(key)
            except Exception as ex:
                error_box(self, "New Project", f"{key} could not be loaded:\n{ex}")
                return
        else:
            key = self.picker.current_key()
            if not key:
                error_box(self, "New Project",
                          "Pick a coordinate system from the list, or choose Unassigned.")
                return
            try:
                # The full-register search keeps its own key shape (EPSG:6584, ESRI:...).
                self.crs = C.ProjectCRS.from_key(key)
            except Exception as ex:
                error_box(self, "New Project", f"{key} could not be loaded:\n{ex}")
                return

        if not self.r_unassigned.isChecked():
            reason = self.extra.validate()
            if reason:
                error_box(self, "New Project", reason)
                return
            if self.crs is not None:
                self.extra.apply_to(self.crs)
        reason = self.setup.validate() if self.setup.enabled else None
        if reason:
            error_box(self, "New Project", reason)
            return
        self.accept()

    # ------------------------------------------------------------------ results
    @property
    def project_name(self) -> str:
        return self.ed_name.text().strip() or "Untitled"

    @property
    def setup_job(self) -> bool:
        return self.setup.enabled

    @property
    def job_folder(self) -> str:
        """The job folder this dialog will create (parent + the job's name)."""
        return str(self.setup.folder_path(self.project_name))

    @property
    def setup_parent_folder(self) -> str:
        return self.setup.parent_folder

    @property
    def setup_template(self):
        return self.setup.template

    @property
    def setup_weeks(self) -> int | None:
        return self.setup.weeks       # always None - Field Data/ is created empty
