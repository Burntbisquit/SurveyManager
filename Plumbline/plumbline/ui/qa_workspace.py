"""Full-Featured QA & Error Resolution Workbenches for Plumbline.

Provides dedicated, non-modal workbenches for fixing field errors:
1. FixPointErrorsDialog: Point & code errors (Duplicates, Proximity, Unrecognized Codes, Letter Cases)
2. FixLineworkDialog: Linework errors & sequence cleanup (Missing ST/END, Bowties, Inverted Codes, Gaps)

Features:
- Split Layout: Left pane = 2D Plan View + 3D Elevation/Terrain View; Right pane = Issues & Inline Tools
- Top Plan & 3D synchronized views with visual error flags and filtering
- Traceback local undo/redo and autosave transaction staging
- Deep inline point/linework resolution tools (with point selection highlighting in 2D/3D)
- Closeness tolerance configuration shown only when editing close points
- Stacked close points with per-point action dropdowns dialog
- Smart Description Merging: combines code groups and note descriptions (e.g. 'ec1 st - sw / new' + 'toc1 / broken' -> 'ec1 st - sw - toc1 / new broken')
- Export Check Report to CSV
- Clean exit prompts on unsaved changes
"""
from __future__ import annotations

import csv
import math
import re
from typing import Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                               QFormLayout, QFrame, QGridLayout, QGroupBox,
                               QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSplitter,
                               QStackedWidget, QTableWidget, QTableWidgetItem,
                               QToolButton, QVBoxLayout, QWidget)

from ..core import point_linework_coder as PLC
from ..core.model import Polyline, SurveyPoint
from . import icons, theme
from .canvas import CanvasView
from .view3d import PRESETS, SceneProvider, View3D
from .widgets import Banner, Hint


# ------------------------------------------------------------------ Helper Functions
def merge_point_descriptions(descs: Sequence[str]) -> str:
    """Merge multiple point descriptions by stacking code groups and note descriptions.

    Example:
    'ec1 st - sw / new' + 'toc1 / broken' -> 'ec1 st - sw - toc1 / new broken'
    """
    code_segments = []
    notes = []

    for d in descs:
        if not d or not str(d).strip():
            continue
        d_str = str(d).strip()
        if "/" in d_str:
            c_part, _, n_part = d_str.partition("/")
            c_part = c_part.strip()
            n_part = n_part.strip()
        else:
            c_part = d_str.strip()
            n_part = ""

        if c_part:
            for sub_c in [s.strip() for s in c_part.split(" - ") if s.strip()]:
                if sub_c not in code_segments:
                    code_segments.append(sub_c)
        if n_part:
            for word in n_part.split():
                if word not in notes:
                    notes.append(word)

    merged_code = " - ".join(code_segments) if code_segments else ""
    merged_note = " ".join(notes) if notes else ""

    if merged_code and merged_note:
        return f"{merged_code} / {merged_note}"
    elif merged_code:
        return merged_code
    elif merged_note:
        return f"/ {merged_note}"
    return ""


def unit_name_for(project) -> str:
    """Get the friendly display name of the horizontal unit of the project."""
    u = getattr(project, "h_unit", "ftUS")
    labels = {
        "ftUS": "US survey foot",
        "ft": "International foot",
        "m": "Metre",
    }
    return labels.get(u, str(u))


def _average_finite(values: Sequence[float]) -> float:
    """Average known elevations without letting a missing value erase the rest."""
    finite = []
    for value in values:
        if value is None:
            continue
        elevation = float(value)
        if math.isfinite(elevation):
            finite.append(elevation)
    return sum(finite) / len(finite) if finite else float("nan")


# ------------------------------------------------------------------ Stack Resolution Popup Dialog
class ClosePointsResolveDialog(QDialog):
    """Modal popup dialog for resolving a single stack of close or duplicate points."""

    def __init__(self, state, points: Sequence[SurveyPoint], is_duplicate: bool = False, parent=None):
        super().__init__(parent)
        self.state = state
        self.points = list(points)
        self.is_duplicate = is_duplicate
        self.setWindowTitle("Resolve Point Stack")
        self.resize(780, 480)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        lay.addWidget(QLabel("<b>Point Stack Resolution:</b>"))
        lay.addWidget(Hint(
            "Choose an action for each point in this stack. "
            + ("Points have distinct numbers — no renumbering needed." if not is_duplicate else "Duplicate numbers can be renumbered, merged, or deleted.")
        ))

        # Table of points in group with per-point Action dropdown
        self.tbl = QTableWidget(len(self.points), 6)
        self.tbl.setHorizontalHeaderLabels(["Pt #", "Northing", "Easting", "Elevation", "Description", "Action"])
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setAlternatingRowColors(True)
        hh = self.tbl.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        self.tbl.setColumnWidth(0, 65)
        self.tbl.setColumnWidth(1, 105)
        self.tbl.setColumnWidth(2, 105)
        self.tbl.setColumnWidth(3, 90)
        self.tbl.setColumnWidth(4, 220)
        self.tbl.setColumnWidth(5, 170)
        hh.setStretchLastSection(True)

        self.combos: list[QComboBox] = []
        for r, p in enumerate(self.points):
            self.tbl.setItem(r, 0, QTableWidgetItem(str(p.number)))
            self.tbl.setItem(r, 1, QTableWidgetItem(f"{p.y:,.3f}"))
            self.tbl.setItem(r, 2, QTableWidgetItem(f"{p.x:,.3f}"))
            self.tbl.setItem(r, 3, QTableWidgetItem(f"{p.z:,.3f}"))
            self.tbl.setItem(r, 4, QTableWidgetItem(str(p.desc or "")))

            cmb = QComboBox()
            actions = ["Merge (Target)", "Merge (Into Target)", "Delete Point", "Keep Point", "Ignore"]
            if self.is_duplicate:
                actions.insert(2, "Renumber Point")
            cmb.addItems(actions)

            if r == 0:
                cmb.setCurrentIndex(0)  # Merge (Target)
            else:
                cmb.setCurrentIndex(1)  # Merge (Into Target)
            cmb.currentIndexChanged.connect(self._on_row_action_changed)
            self.combos.append(cmb)
            self.tbl.setCellWidget(r, 5, cmb)

        self.tbl.selectRow(0)
        lay.addWidget(self.tbl, 1)

        # Merge Options / Description Preview
        box_opt = QGroupBox("Merged Description & Coordinates")
        lay_opt = QFormLayout(box_opt)

        self.ed_preview_desc = QLineEdit()
        self.ed_preview_desc.setText(merge_point_descriptions([p.desc for p in self.points]))
        lay_opt.addRow("Merged Description:", self.ed_preview_desc)

        self.chk_avg_coords = QCheckBox("Average coordinates of merged points")
        self.chk_avg_coords.setChecked(True)
        lay_opt.addRow("", self.chk_avg_coords)

        lay.addWidget(box_opt)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        b_apply = QPushButton("Apply")
        b_apply.setProperty("accent", True)
        b_apply.clicked.connect(self.accept)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        btn_row.addWidget(b_apply)
        btn_row.addWidget(b_cancel)
        lay.addLayout(btn_row)

        self._update_preview()

    def _on_row_action_changed(self):
        self._update_preview()

    def _update_preview(self):
        merge_points = [p for r, p in enumerate(self.points)
                        if "Merge" in self.combos[r].currentText()]

        if len(merge_points) > 1:
            self.ed_preview_desc.setEnabled(True)
            self.chk_avg_coords.setEnabled(True)
            self.ed_preview_desc.setText(merge_point_descriptions([p.desc or "" for p in merge_points]))
        else:
            # A single target is not a merge. Clear any stale preview so Keep/Ignore/Delete
            # choices cannot accidentally apply a description left over from an earlier choice.
            self.ed_preview_desc.setEnabled(False)
            self.chk_avg_coords.setEnabled(False)
            preview_desc = (merge_points[0].desc or "") if merge_points else ""
            self.ed_preview_desc.setText(preview_desc)

    def get_result(self) -> dict:
        target_p = None
        pts_merge = []
        pts_delete = []
        pts_renumber = []
        pts_keep = []
        pts_ignore = []

        for r, p in enumerate(self.points):
            cmb = self.combos[r]
            act = cmb.currentText()
            if act == "Merge (Target)":
                target_p = p
                pts_merge.append(p)
            elif act == "Merge (Into Target)":
                pts_merge.append(p)
            elif act == "Delete Point":
                pts_delete.append(p)
            elif act == "Renumber Point":
                pts_renumber.append(p)
            elif act == "Keep Point":
                pts_keep.append(p)
            else:
                pts_ignore.append(p)

        if not target_p and pts_merge:
            target_p = pts_merge[0]
        elif not target_p and self.points:
            target_p = self.points[0]

        return {
            "target_point": target_p,
            "merge_points": pts_merge,
            "delete_points": pts_delete,
            "renumber_points": pts_renumber,
            "keep_points": pts_keep,
            "ignore_points": pts_ignore,
            "merged_desc": self.ed_preview_desc.text().strip() if len(pts_merge) > 1 else "",
            "average_coords": self.chk_avg_coords.isChecked() and len(pts_merge) > 1,
            "action": 0 if len(pts_merge) > 1 else (2 if pts_delete else 3),
        }


# ------------------------------------------------------------------ Base Workbench Dialog
class BaseQAWorkbenchDialog(QDialog):
    """Base class for full-screen QA Workbenches with 2D/3D split views and inline resolution."""

    workbench_title = "QA Workbench"

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle(self.workbench_title)
        self.setMinimumSize(1100, 720)
        self.resize(1350, 850)

        # Baseline snapshot for Discard on Exit
        self.baseline_snapshot = self._take_snapshot()

        # Local undo/redo history stacks
        self.history_undo: list[tuple[str, dict[int, tuple]]] = []
        self.history_redo: list[tuple[str, dict[int, tuple]]] = []
        self.dirty = False

        # Active findings & resolved tracking
        self.tracked_findings: list[dict] = []
        self.tracked_findings_by_key: dict[str, dict] = {}
        self.active_findings: list[dict] = []
        self.resolved_findings: list[dict] = []
        self.ignored_keys: set[str] = set()
        self.error_point_ids: set[int] = set()
        self.current_edit_finding: dict | None = None
        self.current_selected_stack: list[int] = []
        self.issue_snapshot: dict[int, tuple] | None = None
        self.issue_metadata_snapshot: dict | None = None
        self.issue_dirty = False
        self.fieldbook_path = ""

        self._build_ui()

    def _build_ui(self):
        root_lay = QVBoxLayout(self)
        root_lay.setContentsMargins(6, 6, 6, 6)
        root_lay.setSpacing(4)

        # Top Banner
        self.banner = Banner()
        root_lay.addWidget(self.banner)

        # Main Splitter: Left Pane (2D/3D Views) | Right Pane (Issues List & Deep Editor)
        self.splitter = QSplitter(Qt.Horizontal)
        root_lay.addWidget(self.splitter, 1)

        # ==================== LEFT PANE: 2D & 3D Split Views ====================
        self.w_left = QWidget()
        lay_left = QVBoxLayout(self.w_left)
        lay_left.setContentsMargins(0, 0, 0, 0)
        lay_left.setSpacing(4)

        # Top View Controls Bar (compact 2-row layout for responsive left panel sizing)
        w_view_bar = QWidget()
        lay_vb = QVBoxLayout(w_view_bar)
        lay_vb.setContentsMargins(0, 0, 0, 0)
        lay_vb.setSpacing(2)

        row1 = QHBoxLayout()
        row1.setContentsMargins(0, 0, 0, 0)
        row1.setSpacing(4)
        row1.addWidget(QLabel("<b>View:</b>"))

        self.chk_show_only_err = QCheckBox("Errors Only")
        self.chk_show_only_err.setToolTip("Hides non-error points in both 2D and 3D views")
        self.chk_show_only_err.toggled.connect(self._sync_view_flags)
        row1.addWidget(self.chk_show_only_err)

        self.chk_dim_non_err = QCheckBox("Dim")
        self.chk_dim_non_err.setToolTip("Dims non-error points in 2D and 3D views to make error flags stand out")
        self.chk_dim_non_err.toggled.connect(self._sync_view_flags)
        row1.addWidget(self.chk_dim_non_err)

        self.chk_imagery = QCheckBox("Imagery")
        self.chk_imagery.setChecked(True)
        self.chk_imagery.setToolTip("Toggle aerial imagery in 2D plan view")
        self.chk_imagery.toggled.connect(self._sync_view_flags)
        row1.addWidget(self.chk_imagery)
        row1.addStretch(1)

        lay_vb.addLayout(row1)

        row2 = QHBoxLayout()
        row2.setContentsMargins(0, 0, 0, 0)
        row2.setSpacing(4)
        row2.addWidget(QLabel("<b>3D:</b>"))

        self.sp_vexag = QDoubleSpinBox()
        self.sp_vexag.setRange(0.1, 50.0)
        self.sp_vexag.setSingleStep(0.5)
        self.sp_vexag.setDecimals(1)
        self.sp_vexag.setValue(1.0)
        self.sp_vexag.setSuffix("x")
        self.sp_vexag.setToolTip("Change vertical exaggeration on the fly in 3D view")
        self.sp_vexag.valueChanged.connect(self._on_vexag_changed)
        row2.addWidget(self.sp_vexag)

        self.cb_preset = QComboBox()
        self.cb_preset.addItems(["Iso 3D", "Top (Plan)", "Front (South)", "Right (East)", "Back (North)", "Left (West)"])
        self.cb_preset.setToolTip("Set 3D camera angle preset")
        self.cb_preset.currentIndexChanged.connect(self._on_preset_changed)
        row2.addWidget(self.cb_preset)

        self.chk_persp = QCheckBox("Persp")
        self.chk_persp.setChecked(True)
        self.chk_persp.setToolTip("Toggle perspective / orthographic projection in 3D")
        self.chk_persp.toggled.connect(self._on_persp_toggled)
        row2.addWidget(self.chk_persp)
        row2.addStretch(1)

        btn_zoom_point = QToolButton()
        btn_zoom_point.setText("Point")
        btn_zoom_point.setIcon(icons.icon("zoom_selected"))
        btn_zoom_point.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_zoom_point.setToolTip("Center highlighted point in both 2D and 3D views (orbit centroid fixes to point in 3D)")
        btn_zoom_point.clicked.connect(self._zoom_to_highlighted_point)
        row2.addWidget(btn_zoom_point)

        btn_zoom_ext = QToolButton()
        btn_zoom_ext.setText("All")
        btn_zoom_ext.setIcon(icons.icon("zoom_extents"))
        btn_zoom_ext.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_zoom_ext.setToolTip("Zoom to extents in 2D and reset 3D orbit to scene centroid")
        btn_zoom_ext.clicked.connect(self._zoom_extents)
        row2.addWidget(btn_zoom_ext)

        lay_vb.addLayout(row2)

        lay_left.addWidget(w_view_bar)

        # Vertical Splitter: Top = 2D Canvas, Bottom = 3D View
        self.split_views = QSplitter(Qt.Vertical)

        # 2D Canvas
        self.canvas = CanvasView(self.state, parent=self)
        self.canvas.opts.show_grid = True
        self.canvas.opts.show_imagery = True
        self.split_views.addWidget(self.canvas)

        # 3D Elevation / Terrain Canvas
        self.scene_provider = SceneProvider(self.state)
        self.view3d = View3D(self.state, self.scene_provider, parent=self)
        self.split_views.addWidget(self.view3d)
        self.split_views.setSizes([450, 300])

        lay_left.addWidget(self.split_views, 1)
        self.splitter.addWidget(self.w_left)

        # ==================== RIGHT PANE: Stacked Pages ====================
        self.w_right = QWidget()
        lay_right = QVBoxLayout(self.w_right)
        lay_right.setContentsMargins(0, 0, 0, 0)
        lay_right.setSpacing(4)

        # Top Action Bar: Undo, Redo, Export
        self.w_top_actions = QWidget()
        self.lay_top_actions = QHBoxLayout(self.w_top_actions)
        self.lay_top_actions.setContentsMargins(0, 0, 0, 0)
        self.lay_top_actions.setSpacing(6)

        self.btn_undo = QPushButton("Undo")
        self.btn_undo.setIcon(icons.icon("undo"))
        self.btn_undo.setEnabled(False)
        self.btn_undo.clicked.connect(self._undo)
        self.lay_top_actions.addWidget(self.btn_undo)

        self.btn_redo = QPushButton("Redo")
        self.btn_redo.setIcon(icons.icon("redo"))
        self.btn_redo.setEnabled(False)
        self.btn_redo.clicked.connect(self._redo)
        self.lay_top_actions.addWidget(self.btn_redo)

        self.lay_top_actions.addStretch(1)

        self.btn_export = QPushButton("Export Check Report...")
        self.btn_export.setIcon(icons.icon("export"))
        self.btn_export.setToolTip("Export all active and resolved findings to CSV")
        self.btn_export.clicked.connect(self.export_report_csv)
        self.lay_top_actions.addWidget(self.btn_export)

        lay_right.addWidget(self.w_top_actions)

        # Center Stacked Widget: Page 0 = Summary List (Staging & Final Review), Page 1 = Deep Inline Edit
        self.stack = QStackedWidget()

        # ---------- PAGE 0: Summary List (Staging & Final Review) ----------
        self.page_summary = QWidget()
        lay_sum = QVBoxLayout(self.page_summary)
        lay_sum.setContentsMargins(0, 0, 0, 0)
        lay_sum.setSpacing(4)

        lay_sum.addWidget(QLabel("<b>Active Issues Requiring Attention (Staging & Final Review):</b>"))
        lbl_sum_hint = QLabel("Select an issue and click 'Edit' to resolve. Staged changes appear in green for final review before saving.")
        lbl_sum_hint.setProperty("hint", "true")
        lay_sum.addWidget(lbl_sum_hint)

        self.tbl_active = QTableWidget(0, 5)
        self.tbl_active.setHorizontalHeaderLabels(["Edit", "Status", "Check", "Resolution Summary / Details", "Points"])
        self.tbl_active.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_active.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_active.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_active.setAlternatingRowColors(True)
        self.tbl_active.verticalHeader().setVisible(False)
        hh = self.tbl_active.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_active.setColumnWidth(0, 60)
        self.tbl_active.setColumnWidth(1, 85)
        self.tbl_active.setColumnWidth(2, 180)
        self.tbl_active.setColumnWidth(3, 350)
        self.tbl_active.setColumnWidth(4, 90)
        hh.setStretchLastSection(True)
        self.tbl_active.itemSelectionChanged.connect(self._on_active_row_selected)
        lay_sum.addWidget(self.tbl_active, 2)

        # Resolved Issues Section (Historical / Reference)
        self.lbl_resolved_title = QLabel("<b>Resolved Issues (This Session):</b>")
        lay_sum.addWidget(self.lbl_resolved_title)

        self.tbl_resolved = QTableWidget(0, 4)
        self.tbl_resolved.setHorizontalHeaderLabels(["Level", "Check", "Resolution Summary", "Points"])
        self.tbl_resolved.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_resolved.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_resolved.setAlternatingRowColors(True)
        self.tbl_resolved.verticalHeader().setVisible(False)
        hh_r = self.tbl_resolved.horizontalHeader()
        hh_r.setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_resolved.setColumnWidth(0, 75)
        self.tbl_resolved.setColumnWidth(1, 180)
        self.tbl_resolved.setColumnWidth(2, 380)
        self.tbl_resolved.setColumnWidth(3, 90)
        hh_r.setStretchLastSection(True)
        lay_sum.addWidget(self.tbl_resolved, 1)

        self.scroll_summary = QScrollArea()
        self.scroll_summary.setWidgetResizable(True)
        self.scroll_summary.setFrameShape(QFrame.NoFrame)
        self.scroll_summary.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_summary.setWidget(self.page_summary)
        self.stack.addWidget(self.scroll_summary)

        # ---------- PAGE 1: Deep Inline Edit Panel ----------
        self.page_edit = QWidget()
        self.lay_edit = QVBoxLayout(self.page_edit)
        self.lay_edit.setContentsMargins(0, 0, 0, 0)
        self.lay_edit.setSpacing(6)

        # Back bar & Issue-Scoped Undo/Redo
        w_back_bar = QWidget()
        lay_bb = QHBoxLayout(w_back_bar)
        lay_bb.setContentsMargins(0, 0, 0, 0)
        lay_bb.setSpacing(6)
        self.btn_back = QPushButton("← Back to All Issues")
        self.btn_back.clicked.connect(self._on_back_clicked)
        lay_bb.addWidget(self.btn_back)

        self.lbl_edit_title = QLabel("<b>Fix Issue</b>")
        self.lbl_edit_title.setStyleSheet("font-size: 13px;")
        lay_bb.addWidget(self.lbl_edit_title)

        self.lbl_issue_status = QLabel("")
        lay_bb.addWidget(self.lbl_issue_status)

        lay_bb.addStretch(1)

        self.btn_issue_undo = QPushButton("Undo")
        self.btn_issue_undo.setIcon(icons.icon("undo"))
        self.btn_issue_undo.setToolTip("Undo last correction on this issue")
        self.btn_issue_undo.setEnabled(False)
        self.btn_issue_undo.clicked.connect(self._undo_issue)
        lay_bb.addWidget(self.btn_issue_undo)

        self.btn_issue_redo = QPushButton("Redo")
        self.btn_issue_redo.setIcon(icons.icon("redo"))
        self.btn_issue_redo.setToolTip("Redo last undone correction on this issue")
        self.btn_issue_redo.setEnabled(False)
        self.btn_issue_redo.clicked.connect(self._redo_issue)
        lay_bb.addWidget(self.btn_issue_redo)

        self.lay_edit.addWidget(w_back_bar)

        self.lbl_edit_detail = QLabel("")
        self.lbl_edit_detail.setWordWrap(True)
        self.lbl_edit_detail.setProperty("hint", "true")
        self.lay_edit.addWidget(self.lbl_edit_detail)

        # Table of Affected Points
        self.lay_edit.addWidget(QLabel("<b>Affected Points (Click on point / stack to highlight):</b>"))
        self.tbl_edit_pts = QTableWidget(0, 6)
        self.tbl_edit_pts.setHorizontalHeaderLabels(["Edit", "Pt #", "Northing", "Easting", "Elevation", "Description"])
        self.tbl_edit_pts.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_edit_pts.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl_edit_pts.verticalHeader().setVisible(False)
        hh_e = self.tbl_edit_pts.horizontalHeader()
        hh_e.setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_edit_pts.setColumnWidth(0, 55)
        self.tbl_edit_pts.setColumnWidth(1, 65)
        self.tbl_edit_pts.setColumnWidth(2, 105)
        self.tbl_edit_pts.setColumnWidth(3, 105)
        self.tbl_edit_pts.setColumnWidth(4, 90)
        self.tbl_edit_pts.setColumnWidth(5, 260)
        hh_e.setStretchLastSection(True)
        self.tbl_edit_pts.itemSelectionChanged.connect(self._on_edit_point_selected)
        self.tbl_edit_pts.cellDoubleClicked.connect(self._on_edit_pts_double_clicked)
        self.lay_edit.addWidget(self.tbl_edit_pts, 1)

        # Container for specific inline tool controls
        self.w_edit_tools = QWidget()
        self.lay_edit_tools = QVBoxLayout(self.w_edit_tools)
        self.lay_edit_tools.setContentsMargins(0, 0, 0, 0)
        self.lay_edit.addWidget(self.w_edit_tools)

        # Staged Resolutions for this Finding
        self.lbl_edit_resolved_title = QLabel("<b>Staged Resolutions for this Issue:</b>")
        self.lay_edit.addWidget(self.lbl_edit_resolved_title)

        self.tbl_edit_resolved = QTableWidget(0, 3)
        self.tbl_edit_resolved.setHorizontalHeaderLabels(["Check", "Resolution Summary", "Points"])
        self.tbl_edit_resolved.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_edit_resolved.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_edit_resolved.setAlternatingRowColors(True)
        self.tbl_edit_resolved.verticalHeader().setVisible(False)
        hh_er = self.tbl_edit_resolved.horizontalHeader()
        hh_er.setSectionResizeMode(QHeaderView.Interactive)
        self.tbl_edit_resolved.setColumnWidth(0, 180)
        self.tbl_edit_resolved.setColumnWidth(1, 380)
        self.tbl_edit_resolved.setColumnWidth(2, 90)
        hh_er.setStretchLastSection(True)
        self.lay_edit.addWidget(self.tbl_edit_resolved, 1)

        # Bottom Action Bar on Active Issue Page: Save & Return, Discard, Back
        w_issue_bottom = QWidget()
        lay_ib = QHBoxLayout(w_issue_bottom)
        lay_ib.setContentsMargins(0, 4, 0, 0)
        lay_ib.setSpacing(8)

        self.btn_issue_save = QPushButton("Save & Return to All Issues")
        self.btn_issue_save.setProperty("accent", True)
        self.btn_issue_save.setToolTip("Save staged fixes for this issue and return to the issues list")
        self.btn_issue_save.clicked.connect(self._action_save_issue)
        lay_ib.addWidget(self.btn_issue_save)

        self.btn_issue_discard = QPushButton("Discard Issue Changes")
        self.btn_issue_discard.setToolTip("Revert any changes made on this issue in this session and return")
        self.btn_issue_discard.clicked.connect(self._action_discard_issue)
        lay_ib.addWidget(self.btn_issue_discard)

        lay_ib.addStretch(1)

        self.btn_issue_back_bottom = QPushButton("← Back to All Issues")
        self.btn_issue_back_bottom.clicked.connect(self._on_back_clicked)
        lay_ib.addWidget(self.btn_issue_back_bottom)

        self.lay_edit.addWidget(w_issue_bottom)

        self.scroll_edit = QScrollArea()
        self.scroll_edit.setWidgetResizable(True)
        self.scroll_edit.setFrameShape(QFrame.NoFrame)
        self.scroll_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_edit.setWidget(self.page_edit)
        self.stack.addWidget(self.scroll_edit)
        lay_right.addWidget(self.stack, 1)

        # Bottom Action Bar: Status, Save & Exit, Discard, Cancel
        w_bottom_bar = QWidget()
        lay_bot = QHBoxLayout(w_bottom_bar)
        lay_bot.setContentsMargins(4, 4, 4, 4)
        lay_bot.setSpacing(8)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay_bot.addWidget(self.lbl_status, 1)

        self.btn_save_exit = QPushButton("Save & Exit")
        self.btn_save_exit.setProperty("accent", True)
        self.btn_save_exit.setToolTip("Apply and commit all workbench changes to the project")
        self.btn_save_exit.clicked.connect(self._save_and_exit)
        lay_bot.addWidget(self.btn_save_exit)

        self.btn_discard_exit = QPushButton("Discard & Exit")
        self.btn_discard_exit.setToolTip("Discard all changes made in this session and restore original points")
        self.btn_discard_exit.clicked.connect(self._discard_and_exit)
        lay_bot.addWidget(self.btn_discard_exit)

        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.clicked.connect(self.close)
        lay_bot.addWidget(self.btn_cancel)

        lay_right.addWidget(w_bottom_bar)
        self.stack.currentChanged.connect(self._on_stack_page_changed)
        self._on_stack_page_changed(self.stack.currentIndex())
        self.splitter.addWidget(self.w_right)
        self.splitter.setChildrenCollapsible(False)
        self.split_views.setChildrenCollapsible(False)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setSizes([650, 650])

        # Initial run
        self._refresh_vocabulary()
        self.run_check()
        self._sync_view_flags()

    def _on_stack_page_changed(self, index: int):
        """Keep workbench-level exit actions on the summary page only."""
        show_exit_actions = index == 0
        self.btn_save_exit.setVisible(show_exit_actions)
        self.btn_discard_exit.setVisible(show_exit_actions)
        self.btn_cancel.setVisible(show_exit_actions)

    # ------------------------------------------------------------------ Subclass Extension Hooks
    def _filter_finding(self, finding: dict) -> bool:
        """Override to filter findings by category (point vs linework)."""
        return True

    def _build_inline_tools(self, finding: dict):
        """Override to populate specific correction tools on Page 1."""
        pass

    def _on_stack_clicked(self):
        """Override to handle click on stack table."""
        pass

    def _on_edit_pts_double_clicked(self, row: int, col: int):
        it = self.tbl_edit_pts.item(row, 1)
        if it:
            data = it.data(Qt.UserRole)
            if data and isinstance(data, tuple) and len(data) >= 2:
                stack = data[1]
                chk = self.current_edit_finding.get("check", "") if self.current_edit_finding else ""
                is_dup = "duplicate" in chk.lower() or "look-alike" in chk.lower()
                if hasattr(self, "_action_resolve_stack_dialog"):
                    self._action_resolve_stack_dialog(stack, is_duplicate=is_dup)
                return
        self._on_stack_clicked()

    # ------------------------------------------------------------------ Check & State Management
    def _refresh_vocabulary(self):
        pr = self.state.project
        from ..fieldwork import bridge as FB
        v = FB.vocabulary_for(pr)
        self.code_set = {str(code).casefold() for code in v.get("codes", [])}
        self.fieldbook_path = str(v.get("path") or "")

        n = len(self.code_set)
        if v["source"] == "none" and not self.code_set:
            self.banner.set(f"No field book or code table loaded ({v.get('why', '')}). "
                            "Geometry checks run; vocabulary checks paused.", "warn")
        else:
            label = v.get("label") or "Project Feature Codes"
            self.banner.set(f"Vocabulary: {label} ({n:,} codes active) — All checks active.", "info")

    def run_check(self):
        pr = self.state.project
        if not pr.points:
            self.tbl_active.setRowCount(0)
            self.error_point_ids.clear()
            self._sync_view_flags()
            self.lbl_status.setText("No points in project.")
            return

        from ..fieldwork import bridge as FB
        ne_tol = getattr(self, "close_tol", 0.05)
        self.result = FB.check_project(pr, f2f=self.code_set,
                                       fieldbook_path=self.fieldbook_path or None,
                                       ne_tol=ne_tol)
        self._populate_findings()
        self._sync_view_flags()

    def _populate_findings(self):
        if not hasattr(self, "result") or not self.result:
            return
        pr = self.state.project
        all_findings = self.result.get("findings", [])
        ids = self.result.get("ids") or list(pr.points.keys())

        # Map fresh findings by key/check
        fresh_matched_tracked: list[dict] = []
        err_pids: set[int] = set()

        for f in all_findings:
            rows = f.get("rows")
            if rows is not None:
                raw_pids = [ids[i] for i in rows if 0 <= i < len(ids)]
            else:
                source_pids = f.get("pids") or f.get("points") or []
                raw_pids = []
                for pid in source_pids:
                    if pid in pr.points:
                        raw_pids.append(pid)
                    else:
                        matching = [p.id for p in pr.points.values() if p.number == str(pid)]
                        raw_pids.extend(matching)

            raw_groups = f.get("groups")
            if raw_groups is not None:
                raw_stack_groups = [
                    [ids[i] for i in group if 0 <= i < len(ids)]
                    for group in raw_groups
                ]
            else:
                raw_stack_groups = [raw_pids] if raw_pids else []

            # Keep the finding key based on the detector's complete result. Per-point
            # ignores then remain attached to the same tracked issue as its active
            # point list shrinks.
            key = f.get("key", f"{f.get('check')}:{','.join(str(pid) for pid in raw_pids)}")
            f["key"] = key

            if key in self.ignored_keys:
                continue
            if not self._filter_finding(f):
                continue

            # Match before removing ignored points so a stable tracked finding can
            # carry its per-point ignore state across detector refreshes.
            existing = self.tracked_findings_by_key.get(key)
            if not existing:
                chk = f.get("check")
                existing = next((t for t in self.tracked_findings
                                 if t.get("check") == chk and t not in fresh_matched_tracked), None)

            ignored_pids = set((existing or f).get("ignored_pids") or ())
            resolved_pids = [pid for pid in raw_pids if pid not in ignored_pids]
            if raw_groups is not None:
                stack_groups = [
                    [pid for pid in group if pid not in ignored_pids]
                    for group in raw_stack_groups
                ]
                stack_groups = [group for group in stack_groups if group]
            else:
                stack_groups = [resolved_pids] if resolved_pids else []

            if raw_pids:
                p_nums = [str(pr.points[pid].number) for pid in resolved_pids if pid in pr.points]
            else:
                p_nums = [str(number) for number in (f.get("numbers") or [])]
            f["pids"] = resolved_pids
            f["stack_groups"] = stack_groups
            f["points"] = p_nums
            f["ignored_pids"] = ignored_pids

            for pid in resolved_pids:
                err_pids.add(pid)

            if existing:
                old_key = existing.get("key")
                if old_key and old_key != key and old_key in self.tracked_findings_by_key:
                    del self.tracked_findings_by_key[old_key]
                existing["key"] = key
                self.tracked_findings_by_key[key] = existing
                existing["pids"] = resolved_pids
                existing["stack_groups"] = stack_groups
                existing["points"] = p_nums
                existing["ignored_pids"] = ignored_pids
                if resolved_pids:
                    existing["status"] = "partial" if existing.get("resolutions") else "active"
                else:
                    existing["status"] = "resolved"
                fresh_matched_tracked.append(existing)
            else:
                f["status"] = "resolved" if raw_pids and not resolved_pids else "active"
                f["resolutions"] = []
                f["resolved_history"] = []
                f["resolved_pids"] = set()
                f["history_undo"] = []
                f["history_redo"] = []
                detail = f.get("detail") or f.get("message") or ""
                f["detail"] = detail
                self.tracked_findings_by_key[key] = f
                self.tracked_findings.append(f)
                fresh_matched_tracked.append(f)

        # Mark any tracked findings that were not matched as resolved
        for t in self.tracked_findings:
            if t not in fresh_matched_tracked and t.get("status") != "resolved":
                t["pids"] = []
                t["stack_groups"] = []
                t["status"] = "resolved"

        # Filter tracked findings for current workbench category
        visible_tracked = [
            f for f in self.tracked_findings
            if self._filter_finding(f) and f.get("key") not in self.ignored_keys
        ]
        self.active_findings = visible_tracked
        self.error_point_ids = err_pids

        # Populate Master Active Issues Table (Page 0)
        self.tbl_active.setRowCount(len(visible_tracked))
        dark = theme.current() == "dark"
        c_resolved_bg = QColor(24, 48, 32, 180) if dark else QColor(235, 247, 238)
        brush_resolved = QBrush(c_resolved_bg)

        for r, item in enumerate(visible_tracked):
            st = item.get("status", "active")
            is_res = (st == "resolved")
            is_part = (st == "partial")

            # Col 0: Edit Button
            btn_edit = QPushButton("Review" if is_res else "Edit")
            btn_edit.setProperty("accent", not is_res)
            btn_edit.setToolTip("Review resolutions for this issue" if is_res else "Open issue resolution screen")
            btn_edit.clicked.connect(lambda _, it=item: self._open_inline_editor(it))
            self.tbl_active.setCellWidget(r, 0, btn_edit)

            # Col 1: Status / Level
            if is_res:
                item_lvl = QTableWidgetItem("RESOLVED")
                item_lvl.setForeground(QColor("#27ae60"))
                fnt = item_lvl.font()
                fnt.setBold(True)
                item_lvl.setFont(fnt)
            elif is_part:
                item_lvl = QTableWidgetItem("PARTIAL")
                item_lvl.setForeground(QColor("#f39c12"))
                fnt = item_lvl.font()
                fnt.setBold(True)
                item_lvl.setFont(fnt)
            else:
                lvl = item.get("level", "warn")
                item_lvl = QTableWidgetItem(lvl.upper())
                if lvl == "error":
                    item_lvl.setForeground(QColor("#e74c3c"))
                elif lvl == "warn":
                    item_lvl.setForeground(QColor("#f39c12"))
                else:
                    item_lvl.setForeground(QColor("#3498db"))
                fnt = item_lvl.font()
                fnt.setBold(True)
                item_lvl.setFont(fnt)
            if is_res:
                item_lvl.setBackground(brush_resolved)
            self.tbl_active.setItem(r, 1, item_lvl)

            # Col 2: Check Name
            it_chk = QTableWidgetItem(item.get("check", ""))
            if is_res:
                it_chk.setBackground(brush_resolved)
            self.tbl_active.setItem(r, 2, it_chk)

            # Col 3: Resolution Summary / Details
            if is_res:
                res_texts = item.get("resolutions") or ["Resolved"]
                it_det = QTableWidgetItem("✓ " + " | ".join(res_texts))
                it_det.setForeground(QColor("#27ae60"))
                it_det.setBackground(brush_resolved)
            elif is_part:
                res_texts = item.get("resolutions") or ["Partial"]
                rem_cnt = len(item.get("pids", []))
                it_det = QTableWidgetItem("✓ " + " | ".join(res_texts) + f" ({rem_cnt} remaining)")
                it_det.setForeground(QColor("#f39c12"))
            else:
                detail = item.get("detail") or item.get("message") or ""
                it_det = QTableWidgetItem(detail)
            self.tbl_active.setItem(r, 3, it_det)

            # Col 4: Points
            p_nums = item.get("points") or [str(pr.points[pid].number) for pid in item.get("pids", []) if pid in pr.points]
            it_pts = QTableWidgetItem(", ".join(str(p) for p in p_nums))
            if is_res:
                it_pts.setBackground(brush_resolved)
            self.tbl_active.setItem(r, 4, it_pts)

        # Populate Resolved Table (History / Reference)
        self.tbl_resolved.setRowCount(len(self.resolved_findings))
        for r, item in enumerate(self.resolved_findings):
            item_lvl = QTableWidgetItem("RESOLVED")
            item_lvl.setForeground(QColor("#52c41a"))
            self.tbl_resolved.setItem(r, 0, item_lvl)
            self.tbl_resolved.setItem(r, 1, QTableWidgetItem(item.get("check", "")))
            self.tbl_resolved.setItem(r, 2, QTableWidgetItem(item.get("resolution", "Resolved")))
            self.tbl_resolved.setItem(r, 3, QTableWidgetItem(", ".join(str(p) for p in item.get("points", []))))

        resolved_count = sum(1 for f in visible_tracked if f.get("status") == "resolved")
        active_count = len(visible_tracked) - resolved_count
        self.lbl_status.setText(
            f"Active Issues: {active_count} | Resolved (Staged): {resolved_count} of {len(visible_tracked)} | Flagged Points: {len(err_pids)}"
        )

    # ------------------------------------------------------------------ Inline Detail View (Page 1)
    def _capture_issue_session(self, finding: dict):
        """Remember the state at issue entry so Discard can undo applied fixes too."""
        self.issue_snapshot = self._take_snapshot()
        self.issue_metadata_snapshot = {
            "finding": {
                "status": finding.get("status", "active"),
                "resolutions": list(finding.get("resolutions", [])),
                "resolved_history": list(finding.get("resolved_history", [])),
                "resolved_pids": set(finding.get("resolved_pids", set())),
                "ignored_pids": set(finding.get("ignored_pids", set())),
                "history_undo": list(finding.get("history_undo", [])),
                "history_redo": list(finding.get("history_redo", [])),
                "redo_resolved_history": list(finding.get("redo_resolved_history", [])),
            },
            "resolved_findings": list(self.resolved_findings),
            "history_undo": list(self.history_undo),
            "history_redo": list(self.history_redo),
            "dirty": self.dirty,
            "app_dirty": self.state.dirty,
        }
        self.issue_dirty = False

    def _open_inline_editor(self, finding: dict, *, start_session: bool | None = None):
        # These lists contain wrappers for editor widgets. Drop old wrappers before
        # clearing the layout, otherwise Qt may delete their C++ objects while a
        # later save/back check still calls text() or currentText() on them.
        self.desc_edits = []
        self.sep_corrections = []
        self.current_focused_ed = None
        self.btn_autofix_descriptions = None

        if start_session is None:
            start_session = (self.stack.currentIndex() != 1 or self.current_edit_finding is not finding)
        if start_session:
            self._capture_issue_session(finding)
        self.current_edit_finding = finding
        chk = finding.get("check", "Issue")
        self.lbl_edit_title.setText(f"<b>Fix {chk}</b>")

        st = finding.get("status", "active")
        if st == "resolved":
            self.lbl_issue_status.setText("<span style='color: #27ae60; font-weight: bold;'>[✓ Resolved]</span>")
        elif st == "partial":
            self.lbl_issue_status.setText("<span style='color: #f39c12; font-weight: bold;'>[Partial]</span>")
        else:
            lvl = finding.get("level", "warn")
            col = "#e74c3c" if lvl == "error" else "#f39c12"
            self.lbl_issue_status.setText(f"<span style='color: {col}; font-weight: bold;'>[{lvl.upper()}]</span>")

        # Update Scoped Undo/Redo button states
        h_undo = finding.get("history_undo", [])
        h_redo = finding.get("history_redo", [])
        self.btn_issue_undo.setEnabled(len(h_undo) > 0)
        self.btn_issue_redo.setEnabled(len(h_redo) > 0)
        self.btn_undo.setEnabled(len(h_undo) > 0)
        self.btn_redo.setEnabled(len(h_redo) > 0)

        pr = self.state.project
        is_close = "close" in chk.lower()
        is_dup = "duplicate" in chk.lower() or "look-alike" in chk.lower()

        # Stacks: list of point ID lists
        stacks = finding.get("stack_groups") or []
        if not stacks:
            pids = finding.get("pids", [])
            if pids:
                stacks = [pids]

        # Update detail text above closeness tolerance with just number of groups
        if is_close or is_dup:
            num_groups = len(stacks)
            group_word = "close point group" if is_close else "duplicate number group"
            if num_groups == 0 and st == "resolved":
                self.lbl_edit_detail.setText("<b>✓ All close point groups have been resolved.</b>")
            else:
                self.lbl_edit_detail.setText(f"{num_groups} {group_word}{'s' if num_groups != 1 else ''} detected.")
        else:
            if not stacks and st == "resolved":
                self.lbl_edit_detail.setText("<b>✓ All items in this issue have been resolved.</b>")
            else:
                self.lbl_edit_detail.setText(finding.get("detail", ""))

        flag = str(finding.get("flag", ""))
        is_sep = "MisplacedAfterSeparator" in flag or "potential code in descriptor" in chk.lower() or "text before" in chk.lower() or "separator" in chk.lower()

        # Populate Affected Points Table
        if is_sep:
            self.tbl_edit_pts.setRowCount(0)
            self.tbl_edit_pts.setColumnCount(5)
            self.tbl_edit_pts.setHorizontalHeaderLabels(["Pt #", "Northing", "Easting", "Elevation", "Description"])
            hh_e = self.tbl_edit_pts.horizontalHeader()
            hh_e.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(3, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(4, QHeaderView.Stretch)

            pids = finding.get("pids", [])
            for pid in pids:
                p = pr.points.get(pid)
                if not p:
                    continue
                r = self.tbl_edit_pts.rowCount()
                self.tbl_edit_pts.insertRow(r)

                it_num = QTableWidgetItem(str(p.number))
                it_num.setData(Qt.UserRole, pid)
                self.tbl_edit_pts.setItem(r, 0, it_num)

                it_y = QTableWidgetItem(f"{p.y:,.3f}")
                it_y.setData(Qt.UserRole, pid)
                self.tbl_edit_pts.setItem(r, 1, it_y)

                it_x = QTableWidgetItem(f"{p.x:,.3f}")
                it_x.setData(Qt.UserRole, pid)
                self.tbl_edit_pts.setItem(r, 2, it_x)

                it_z = QTableWidgetItem(f"{p.z:,.3f}")
                it_z.setData(Qt.UserRole, pid)
                self.tbl_edit_pts.setItem(r, 3, it_z)

                it_desc = QTableWidgetItem(str(p.desc or ""))
                it_desc.setData(Qt.UserRole, pid)
                self.tbl_edit_pts.setItem(r, 4, it_desc)
        else:
            self.tbl_edit_pts.setRowCount(0)
            self.tbl_edit_pts.setColumnCount(6)
            self.tbl_edit_pts.setHorizontalHeaderLabels(["Edit", "Pt #", "Northing", "Easting", "Elevation", "Description"])
            hh_e = self.tbl_edit_pts.horizontalHeader()
            hh_e.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(1, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(2, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(3, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(4, QHeaderView.ResizeToContents)
            hh_e.setSectionResizeMode(5, QHeaderView.Stretch)

            dark = theme.current() == "dark"
            c_even = QColor(36, 59, 83, 110) if dark else QColor(245, 248, 252)
            c_odd = QColor(20, 36, 52, 110) if dark else QColor(228, 235, 244)

            for s_idx, stack in enumerate(stacks):
                bg = QBrush(c_even if (s_idx % 2 == 0) else c_odd)
                for p_idx, pid in enumerate(stack):
                    p = pr.points.get(pid)
                    if not p:
                        continue
                    r = self.tbl_edit_pts.rowCount()
                    self.tbl_edit_pts.insertRow(r)

                    # Col 0: Edit Button
                    btn_edit = QPushButton("Edit")
                    btn_edit.setProperty("accent", True)
                    btn_edit.setToolTip(f"Resolve Stack {s_idx + 1}")
                    btn_edit.clicked.connect(lambda _, stk=stack: self._action_resolve_stack_dialog(stk, is_duplicate=is_dup)
                                             if hasattr(self, "_action_resolve_stack_dialog") else None)
                    self.tbl_edit_pts.setCellWidget(r, 0, btn_edit)

                    it_num = QTableWidgetItem(str(p.number))
                    it_num.setData(Qt.UserRole, (s_idx, stack, pid))
                    it_num.setBackground(bg)
                    self.tbl_edit_pts.setItem(r, 1, it_num)

                    it_y = QTableWidgetItem(f"{p.y:,.3f}")
                    it_y.setData(Qt.UserRole, (s_idx, stack, pid))
                    it_y.setBackground(bg)
                    self.tbl_edit_pts.setItem(r, 2, it_y)

                    it_x = QTableWidgetItem(f"{p.x:,.3f}")
                    it_x.setData(Qt.UserRole, (s_idx, stack, pid))
                    it_x.setBackground(bg)
                    self.tbl_edit_pts.setItem(r, 3, it_x)

                    it_z = QTableWidgetItem(f"{p.z:,.3f}")
                    it_z.setData(Qt.UserRole, (s_idx, stack, pid))
                    it_z.setBackground(bg)
                    self.tbl_edit_pts.setItem(r, 4, it_z)

                    it_desc = QTableWidgetItem(str(p.desc or ""))
                    it_desc.setData(Qt.UserRole, (s_idx, stack, pid))
                    it_desc.setBackground(bg)
                    self.tbl_edit_pts.setItem(r, 5, it_desc)

        # Clear and build inline tools
        while self.lay_edit_tools.count():
            item = self.lay_edit_tools.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            l = item.layout()
            if l:
                while l.count():
                    sub = l.takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

        self._build_inline_tools(finding)
        self._update_resolved_tables()
        self.stack.setCurrentIndex(1)
        if hasattr(self, "scroll_edit"):
            self.scroll_edit.verticalScrollBar().setValue(0)

        # Select first point / stack and center view
        if is_sep:
            pids = finding.get("pids", [])
            if pids and self.tbl_edit_pts.rowCount() > 0:
                self.tbl_edit_pts.selectRow(0)
                self._select_and_focus_points(pids[:1])
        elif stacks and self.tbl_edit_pts.rowCount() > 0:
            self.current_selected_stack = stacks[0]
            self.tbl_edit_pts.selectRow(0)
            self._select_stack_points(stacks[0])

    def _show_summary_page(self):
        self.current_edit_finding = None
        self.issue_snapshot = None
        self.issue_metadata_snapshot = None
        self.issue_dirty = False
        if hasattr(self, "w_close_tol_bar"):
            self.w_close_tol_bar.hide()
        self.stack.setCurrentIndex(0)
        self.run_check()

    def _action_save_issue(self):
        if self._has_unapplied_issue_edits():
            self._apply_pending_issue_edits()
        f = self.current_edit_finding
        if f:
            if not f.get("pids") or len(f.get("pids", [])) == 0:
                f["status"] = "resolved"
            elif f.get("resolutions"):
                f["status"] = "partial"
        self.issue_dirty = False
        self._show_summary_page()

    def _action_discard_issue(self):
        if self.issue_snapshot is not None:
            self._restore_snapshot(self.issue_snapshot)

        finding = self.current_edit_finding
        session = self.issue_metadata_snapshot
        if session is not None:
            if finding is not None:
                for key, value in session["finding"].items():
                    if isinstance(value, set):
                        value = set(value)
                    elif isinstance(value, list):
                        value = list(value)
                    finding[key] = value
            self.resolved_findings[:] = session["resolved_findings"]
            self.history_undo[:] = session["history_undo"]
            self.history_redo[:] = session["history_redo"]
            self.dirty = session["dirty"]
            self.state.set_dirty(session["app_dirty"])
        elif finding is not None:
            finding.setdefault("history_undo", []).clear()
            finding.setdefault("history_redo", []).clear()
            finding.setdefault("resolutions", []).clear()
            finding["status"] = "active"

        if finding is not None:
            self.btn_issue_undo.setEnabled(bool(finding.get("history_undo")))
            self.btn_issue_redo.setEnabled(bool(finding.get("history_redo")))
        self.btn_undo.setEnabled(bool(self.history_undo))
        self.btn_redo.setEnabled(bool(self.history_redo))
        self.issue_dirty = False
        self._show_summary_page()

    def _on_back_clicked(self):
        if self._has_unapplied_issue_edits():
            mb = QMessageBox(self)
            mb.setWindowTitle("Unsaved Changes")
            mb.setText("You have unsaved changes in this issue.\n\nDo you want to save them to the initial view before returning?")
            b_save = mb.addButton("Save & Return", QMessageBox.AcceptRole)
            b_discard = mb.addButton("Discard & Return", QMessageBox.DestructiveRole)
            b_cancel = mb.addButton("Cancel", QMessageBox.RejectRole)
            mb.setDefaultButton(b_save)
            mb.exec()

            clicked = mb.clickedButton()
            if clicked == b_save:
                self._action_save_issue()
            elif clicked == b_discard:
                self._action_discard_issue()
            else:
                return
        else:
            self._show_summary_page()

    @staticmethod
    def _safe_widget_text(widget, getter: str) -> str | None:
        """Read text from a Qt widget, returning None if its C++ object was deleted."""
        if widget is None:
            return None
        try:
            return getattr(widget, getter)()
        except (AttributeError, RuntimeError):
            return None

    def _has_unapplied_issue_edits(self) -> bool:
        for item in getattr(self, "desc_edits", []):
            if len(item) < 2:
                continue
            p, ed = item[0], item[1]
            text = self._safe_widget_text(ed, "text")
            if text is not None and text.strip() != (p.desc or ""):
                return True

        for item in getattr(self, "sep_corrections", []):
            cb_action = item[3] if len(item) >= 4 else (item[1] if len(item) >= 2 else None)
            action = self._safe_widget_text(cb_action, "currentText")
            if action in ("Correct", "Correct (Leave # in Descriptor)", "Ignore"):
                return True
        return bool(getattr(self, "issue_dirty", False))

    def _apply_pending_issue_edits(self):
        # A stale wrapper is ignored rather than dereferenced. Normally the editor
        # lists are cleared during rebuild; this is a final guard for queued Qt
        # deferred-delete events on Back and Save Issue paths.
        desc_edits = [
            item for item in getattr(self, "desc_edits", [])
            if len(item) >= 2 and self._safe_widget_text(item[1], "text") is not None
        ]
        if desc_edits:
            self.desc_edits = desc_edits
            self._action_apply_descriptions()
            return

        sep_corrections = []
        for item in getattr(self, "sep_corrections", []):
            cb_action = item[3] if len(item) >= 4 else (item[1] if len(item) >= 2 else None)
            if self._safe_widget_text(cb_action, "currentText") is None:
                continue
            if len(item) >= 3 and self._safe_widget_text(item[2], "text") is None:
                continue
            sep_corrections.append(item)
        if sep_corrections:
            self.sep_corrections = sep_corrections
            self._action_apply_separator_corrections()

    def _discard_issue_edits(self):
        self._action_discard_issue()

    def _on_vexag_changed(self, val: float):
        self.view3d.set_vexag(val)

    def _on_preset_changed(self, idx: int):
        names = ["iso", "top", "front", "right", "back", "left"]
        if 0 <= idx < len(names):
            self.view3d.set_preset(names[idx])

    def _on_persp_toggled(self, checked: bool):
        self.view3d.set_perspective(checked)

    def _zoom_extents(self):
        self.state.zoom_extents()
        sc = self.scene_provider.scene()
        if sc.bounds is not None:
            self.view3d.cam.fit(sc.bounds, max(self.view3d.width(), 50), max(self.view3d.height(), 50))
            self.view3d.invalidate()
            self.view3d.update()

    def _on_active_row_selected(self):
        row = self.tbl_active.currentRow()
        if 0 <= row < len(self.active_findings):
            item = self.active_findings[row]
            pids = item.get("pids", [])
            self._select_and_focus_points(pids)

    def _on_edit_point_selected(self):
        row = self.tbl_edit_pts.currentRow()
        if row >= 0:
            it = self.tbl_edit_pts.item(row, 0)
            if not it or it.data(Qt.UserRole) is None:
                it = self.tbl_edit_pts.item(row, 1)
            if it:
                data = it.data(Qt.UserRole)
                if data and isinstance(data, tuple) and len(data) >= 2:
                    s_idx, stack = data[0], data[1]
                    self.current_selected_stack = stack
                    self._select_stack_points(stack)
                elif data is not None:
                    pid_list = [data] if isinstance(data, int) else list(data)
                    self._select_and_focus_points(pid_list)

    def _select_stack_points(self, stack_pids: list[int]):
        pr = self.state.project
        pts = [pr.points[pid] for pid in stack_pids if pid in pr.points]
        if not pts:
            return
        self.state.select(points=[p.id for p in pts])
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        zs = [p.z for p in pts]
        pad = 20.0
        self.state.zoom_to_bbox((min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad))
        self.view3d.center_on_point(sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        self._sync_view_flags()

    def _select_and_focus_points(self, pids: list[int]):
        pr = self.state.project
        pts = [pr.points[pid] for pid in pids if pid in pr.points]
        if not pts:
            return
        self.state.select(points=[p.id for p in pts])
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        zs = [p.z for p in pts]
        pad = 20.0
        self.state.zoom_to_bbox((min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad))
        self.view3d.center_on_point(sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        self._sync_view_flags()

    def _zoom_to_highlighted_point(self):
        pr = self.state.project
        stk = getattr(self, "current_selected_stack", None)
        pids = stk or list(self.state.sel_points)
        pts = [pr.points[pid] for pid in pids if pid in pr.points]
        if not pts and self.error_point_ids:
            pts = [pr.points[pid] for pid in self.error_point_ids if pid in pr.points][:1]
        if not pts:
            return
        xs = [p.x for p in pts]
        ys = [p.y for p in pts]
        zs = [p.z for p in pts]
        pad = 20.0
        self.state.zoom_to_bbox((min(xs) - pad, min(ys) - pad, max(xs) + pad, max(ys) + pad))
        self.view3d.center_on_point(sum(xs) / len(xs), sum(ys) / len(ys), sum(zs) / len(zs))
        self._sync_view_flags()

    def _sync_view_flags(self):
        opts = self.canvas.opts
        opts.error_point_ids = set(self.error_point_ids)
        opts.hide_non_error_points = self.chk_show_only_err.isChecked()
        opts.dim_non_error_points = self.chk_dim_non_err.isChecked()
        opts.show_imagery = self.chk_imagery.isChecked()
        self.canvas.invalidate()
        self.canvas.update()

        # Sync 3D View flags
        self.view3d.error_point_ids = set(self.error_point_ids)
        self.view3d.hide_non_error_points = self.chk_show_only_err.isChecked()
        self.view3d.dim_non_error_points = self.chk_dim_non_err.isChecked()
        self.scene_provider.invalidate()
        self.view3d.invalidate()
        self.view3d.update()

    def _update_resolved_tables(self):
        # Update main summary page table
        self.tbl_resolved.setRowCount(len(self.resolved_findings))
        for r, item in enumerate(self.resolved_findings):
            item_lvl = QTableWidgetItem("RESOLVED")
            item_lvl.setForeground(QColor("#52c41a"))
            self.tbl_resolved.setItem(r, 0, item_lvl)
            self.tbl_resolved.setItem(r, 1, QTableWidgetItem(item.get("check", "")))
            self.tbl_resolved.setItem(r, 2, QTableWidgetItem(item.get("resolution", "Resolved")))
            self.tbl_resolved.setItem(r, 3, QTableWidgetItem(", ".join(str(p) for p in item.get("points", []))))

        # Update nested editor page table: tied specifically to current edit finding!
        cur_f = self.current_edit_finding
        if cur_f:
            hist = cur_f.get("resolved_history", [])
            self.tbl_edit_resolved.setRowCount(len(hist))
            for r, h in enumerate(hist):
                self.tbl_edit_resolved.setItem(r, 0, QTableWidgetItem(h.get("check", "")))
                self.tbl_edit_resolved.setItem(r, 1, QTableWidgetItem(h.get("resolution", "Resolved")))
                self.tbl_edit_resolved.setItem(r, 2, QTableWidgetItem(", ".join(str(p) for p in h.get("points", []))))
        else:
            self.tbl_edit_resolved.setRowCount(0)

    # ------------------------------------------------------------------ Transaction & Undo/Redo
    def _take_snapshot(self) -> dict[int, tuple]:
        pr = self.state.project
        return {
            pid: (p.number, p.x, p.y, p.z, p.desc, p.layer, dict(p.attrs))
            for pid, p in pr.points.items()
        }

    def _restore_snapshot(self, snap: dict[int, tuple]):
        pr = self.state.project
        # Remove points not in snapshot
        current_ids = list(pr.points.keys())
        for pid in current_ids:
            if pid not in snap:
                pr.points.pop(pid, None)

        # Restore / add points from snapshot
        for pid, data in snap.items():
            num, x, y, z, desc, layer, attrs = data
            if pid in pr.points:
                p = pr.points[pid]
                p.number = num
                p.x = x
                p.y = y
                p.z = z
                p.desc = desc
                p.layer = layer
                p.attrs = dict(attrs)
            else:
                p = SurveyPoint(id=pid, number=num, x=x, y=y, z=z, desc=desc, layer=layer, attrs=dict(attrs))
                pr.points[pid] = p

        pr.process_linework()
        pr.touch()
        self.state.set_dirty(True)
        self.state.refresh(("points", "entities"))

    def _push_undo(self, desc: str):
        snap = self._take_snapshot()
        self.history_undo.append((desc, snap))
        self.history_redo.clear()
        self.btn_undo.setEnabled(True)
        self.btn_redo.setEnabled(False)
        self.dirty = True
        self.issue_dirty = True
        if self.current_edit_finding:
            self.current_edit_finding.setdefault("history_undo", []).append((desc, snap))
            self.current_edit_finding.setdefault("history_redo", []).clear()
            self.btn_issue_undo.setEnabled(True)
            self.btn_issue_redo.setEnabled(False)

    def _undo_issue(self):
        f = self.current_edit_finding
        if not f:
            return
        h_undo = f.setdefault("history_undo", [])
        h_redo = f.setdefault("history_redo", [])
        if not h_undo:
            return
        desc, snap = h_undo.pop()
        h_redo.append((desc, self._take_snapshot()))
        self._restore_snapshot(snap)
        if f.get("resolutions"):
            f["resolutions"].pop()
        if f.get("resolved_history"):
            last_item = f["resolved_history"].pop()
            f.setdefault("redo_resolved_history", []).append(last_item)
            f.setdefault("ignored_pids", set()).difference_update(last_item.get("ignored_pids", []))
        self.btn_issue_undo.setEnabled(len(h_undo) > 0)
        self.btn_issue_redo.setEnabled(True)
        self.btn_undo.setEnabled(len(h_undo) > 0)
        self.btn_redo.setEnabled(True)
        if self.resolved_findings:
            self.resolved_findings.pop()
        self.run_check()
        self.lbl_status.setText(f"Undo: {desc}")
        self._open_inline_editor(f, start_session=False)

    def _redo_issue(self):
        f = self.current_edit_finding
        if not f:
            return
        h_undo = f.setdefault("history_undo", [])
        h_redo = f.setdefault("history_redo", [])
        if not h_redo:
            return
        desc, snap = h_redo.pop()
        h_undo.append((desc, self._take_snapshot()))
        self._restore_snapshot(snap)
        f.setdefault("resolutions", []).append(desc)
        if f.get("redo_resolved_history"):
            last_item = f["redo_resolved_history"].pop()
            f.setdefault("resolved_history", []).append(last_item)
            f.setdefault("ignored_pids", set()).update(last_item.get("ignored_pids", []))
        else:
            res_item = {
                "level": f.get("level", "warn"),
                "check": f.get("check", "Issue"),
                "resolution": desc,
                "points": list(f.get("points", [])),
            }
            f.setdefault("resolved_history", []).append(res_item)
        self.btn_issue_redo.setEnabled(len(h_redo) > 0)
        self.btn_issue_undo.setEnabled(True)
        self.btn_redo.setEnabled(len(h_redo) > 0)
        self.btn_undo.setEnabled(True)
        self.run_check()
        self.lbl_status.setText(f"Redo: {desc}")
        self._open_inline_editor(f, start_session=False)

    def _undo(self):
        if self.stack.currentIndex() == 1 and self.current_edit_finding:
            self._undo_issue()
            return
        if not self.history_undo:
            return
        desc, snap = self.history_undo.pop()
        self.history_redo.append((desc, self._take_snapshot()))
        self._restore_snapshot(snap)
        self.btn_undo.setEnabled(len(self.history_undo) > 0)
        self.btn_redo.setEnabled(True)
        if self.resolved_findings:
            self.resolved_findings.pop()
            self._update_resolved_tables()
        self.run_check()
        self.lbl_status.setText(f"Undo: {desc}")

    def _redo(self):
        if self.stack.currentIndex() == 1 and self.current_edit_finding:
            self._redo_issue()
            return
        if not self.history_redo:
            return
        desc, snap = self.history_redo.pop()
        self.history_undo.append((desc, self._take_snapshot()))
        self._restore_snapshot(snap)
        self.btn_redo.setEnabled(len(self.history_redo) > 0)
        self.btn_undo.setEnabled(True)
        self.run_check()
        self.lbl_status.setText(f"Redo: {desc}")

    def _apply_fix(
        self,
        resolution_desc: str,
        fix_fn,
        resolved_points: list[int] | None = None,
        stay_on_edit_page: bool = True,
        ignored_points: list[int] | None = None,
    ):
        pr = self.state.project
        cur_finding = self.current_edit_finding
        p_nums = []
        if resolved_points is not None:
            p_nums = [str(pr.points[pid].number) if pid in pr.points else str(pid)
                      for pid in resolved_points]
        elif cur_finding:
            p_nums = list(cur_finding.get("points", []))

        self._push_undo(resolution_desc)
        ignored_pids = list(dict.fromkeys(ignored_points or []))
        if cur_finding and ignored_pids:
            cur_finding.setdefault("ignored_pids", set()).update(ignored_pids)
        fix_fn()
        pr.process_linework()
        self.state.project.touch()
        self.state.set_dirty(True)
        self.state.refresh(("points", "entities"))

        res_item = {
            "level": cur_finding.get("level", "warn") if cur_finding else "warn",
            "check": cur_finding.get("check", "Issue") if cur_finding else "Issue",
            "resolution": resolution_desc,
            "points": p_nums,
            "ignored_pids": ignored_pids,
        }
        self.resolved_findings.append(res_item)
        if cur_finding:
            cur_finding.setdefault("resolutions", []).append(resolution_desc)
            cur_finding.setdefault("resolved_history", []).append(res_item)
            if resolved_points:
                cur_finding.setdefault("resolved_pids", set()).update(resolved_points)

        self.run_check()

        if stay_on_edit_page and cur_finding:
            self._open_inline_editor(cur_finding, start_session=False)
        else:
            self._show_summary_page()

    def _action_ignore(self, key: str):
        if not key and self.current_edit_finding:
            key = self.current_edit_finding.get("key", "")
        if key:
            self.ignored_keys.add(key)
        self._show_summary_page()
        self.run_check()

    # ------------------------------------------------------------------ Save & Discard Exits
    def export_report_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Export Check Report", "Check_Report.csv", "CSV Files (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Status", "Level", "Check", "Details", "Points"])
                for item in self.active_findings:
                    writer.writerow(["ACTIVE", item.get("level", "warn"), item.get("check", ""),
                                     item.get("detail", ""), ", ".join(str(p) for p in item.get("points", []))])
                for item in self.resolved_findings:
                    writer.writerow(["RESOLVED", item.get("level", "warn"), item.get("check", ""),
                                     item.get("resolution", ""), ", ".join(str(p) for p in item.get("points", []))])
            QMessageBox.information(self, "Export Successful", f"Report saved to:\n{path}")
        except Exception as ex:
            QMessageBox.critical(self, "Export Error", f"Failed to save CSV report:\n{ex}")

    def _save_and_exit(self):
        self.dirty = False
        self.accept()

    def _discard_and_exit(self):
        self._restore_snapshot(self.baseline_snapshot)
        self.dirty = False
        self.reject()

    def closeEvent(self, event):
        if self.dirty:
            mb = QMessageBox(self)
            mb.setWindowTitle("Unsaved Changes")
            mb.setText("You have unsaved changes in this workbench.\nDo you want to save them before exiting?")
            b_save = mb.addButton("Save & Exit", QMessageBox.AcceptRole)
            b_discard = mb.addButton("Discard & Exit", QMessageBox.DestructiveRole)
            b_cancel = mb.addButton("Cancel", QMessageBox.RejectRole)
            mb.setDefaultButton(b_save)
            mb.exec()

            clicked = mb.clickedButton()
            if clicked == b_save:
                self._save_and_exit()
                event.accept()
            elif clicked == b_discard:
                self._discard_and_exit()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# ============================================================================
# 1. FIX POINT ERRORS WORKBENCH
# ============================================================================
class FixPointErrorsDialog(BaseQAWorkbenchDialog):
    """Workbench dedicated to Category 1: Point & Code Errors."""

    workbench_title = "Fix Point Errors"

    def __init__(self, state, parent=None):
        self.close_tol = 0.05
        super().__init__(state, parent)
        self._init_close_tol_bar()

    def _init_close_tol_bar(self):
        self.w_close_tol_bar = QWidget()
        lay_tol = QHBoxLayout(self.w_close_tol_bar)
        lay_tol.setContentsMargins(0, 0, 0, 0)
        lay_tol.setSpacing(6)

        lay_tol.addWidget(QLabel("<b>Closeness Tolerance:</b>"))
        self.sp_close_tol = QDoubleSpinBox()
        self.sp_close_tol.setRange(0.001, 50.0)
        self.sp_close_tol.setDecimals(3)
        self.sp_close_tol.setSingleStep(0.01)
        self.sp_close_tol.setValue(self.close_tol)
        self.sp_close_tol.setToolTip("Key in closeness tolerance for detecting duplicate proximity collisions")
        self.sp_close_tol.valueChanged.connect(self._on_tolerance_changed)
        lay_tol.addWidget(self.sp_close_tol)

        self.lbl_units = QLabel(unit_name_for(self.state.project))
        self.lbl_units.setStyleSheet(
            "padding: 2px 6px; background: rgba(53, 126, 221, 0.15); "
            "border: 1px solid #357edd; border-radius: 4px; font-weight: bold; color: #5dade2;"
        )
        self.lbl_units.setToolTip(f"Active project horizontal units: {self.lbl_units.text()}")
        lay_tol.addWidget(self.lbl_units)
        lay_tol.addStretch(1)

        # Insert at top of page_edit (index 2 after back bar and description label)
        self.lay_edit.insertWidget(2, self.w_close_tol_bar)
        self.w_close_tol_bar.hide()

    def _on_tolerance_changed(self):
        self.close_tol = self.sp_close_tol.value()
        self.run_check()
        if self.current_edit_finding:
            key = self.current_edit_finding.get("key", "")
            match = next((f for f in self.active_findings if f.get("key", "") == key), None)
            if match:
                self._open_inline_editor(match, start_session=False)

    def _filter_finding(self, finding: dict) -> bool:
        chk = finding.get("check", "").lower()
        flag = str(finding.get("flag", ""))
        # Filter out line issues (they belong in Fix Linework)
        if "line:" in chk or flag.startswith("Missing") or any(w in chk for w in ("line", "curve", "string", "closed")):
            return False
        return True

    def _on_stack_clicked(self):
        stk = getattr(self, "current_selected_stack", None)
        if not stk and self.current_edit_finding:
            stacks = self.current_edit_finding.get("stack_groups") or [self.current_edit_finding.get("pids", [])]
            if stacks:
                stk = stacks[0]
        if stk:
            chk = self.current_edit_finding.get("check", "") if self.current_edit_finding else ""
            is_dup = "duplicate" in chk.lower() or "look-alike" in chk.lower()
            self._action_resolve_stack_dialog(stk, is_duplicate=is_dup)

    def _build_inline_tools(self, finding: dict):
        pr = self.state.project
        chk = finding.get("check", "").lower()
        flag = str(finding.get("flag", ""))
        is_close = "close" in chk or "top of each other" in chk
        is_exact_dup = "duplicate" in chk or ("number" in chk and "used" in finding.get("detail", "").lower())
        is_lookalike = "look-alike" in chk
        is_sep = "MisplacedAfterSeparator" in flag or "potential code in descriptor" in chk or "text before" in chk or "separator" in chk

        if is_sep:
            self.w_close_tol_bar.hide()
            grp = QGroupBox("Corrections")
            lay_g = QVBoxLayout(grp)
            lay_g.setSpacing(8)

            pids = finding.get("pids", [])
            pts = [pr.points[pid] for pid in pids if pid in pr.points]

            f2f_set = set(self.code_set) if self.code_set else set()
            fb_path = None
            try:
                from ..fieldwork.bridge import vocabulary_for
                voc = vocabulary_for(pr, getattr(self.state, "job_folder", None))
                if voc.get("codes"):
                    f2f_set.update(voc.get("codes"))
                fb_path = voc.get("path")
            except Exception:
                pass

            self.tbl_corrections = QTableWidget(len(pts), 4)
            self.tbl_corrections.setHorizontalHeaderLabels(["Pt #", "Original Code", "Fixed Code", "Action"])
            self.tbl_corrections.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.tbl_corrections.verticalHeader().setVisible(False)
            self.tbl_corrections.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed | QAbstractItemView.SelectedClicked)
            hh_c = self.tbl_corrections.horizontalHeader()
            hh_c.setSectionResizeMode(QHeaderView.Interactive)
            self.tbl_corrections.setColumnWidth(0, 60)
            self.tbl_corrections.setColumnWidth(1, 200)
            self.tbl_corrections.setColumnWidth(2, 240)
            self.tbl_corrections.setColumnWidth(3, 240)
            hh_c.setStretchLastSection(True)

            self.sep_corrections = []
            _updating_from_combo = False
            for r, p in enumerate(pts):
                orig_desc = str(p.desc or "")
                sugg = ""
                sugg_num = ""
                try:
                    from ..fieldwork.clean import _autocorrect_desc, _autocorrect_desc_leave_number
                    sugg = _autocorrect_desc(orig_desc, f2f_set, fieldbook_path=fb_path) or ""
                    sugg_num = _autocorrect_desc_leave_number(orig_desc, f2f_set, fieldbook_path=fb_path) or ""
                except Exception:
                    pass
                if not sugg:
                    raw_desc = orig_desc
                    if "/" in raw_desc:
                        parts = raw_desc.split("/", 1)
                        c_part, f_part = parts[0].strip(), parts[1].strip()
                        sugg = f"{f_part} / {c_part}" if c_part else f_part
                    else:
                        sugg = raw_desc
                if not sugg_num:
                    sugg_num = sugg

                it_pt = QTableWidgetItem(str(p.number))
                it_pt.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tbl_corrections.setItem(r, 0, it_pt)

                it_orig = QTableWidgetItem(orig_desc)
                it_orig.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                self.tbl_corrections.setItem(r, 1, it_orig)

                it_fixed = QTableWidgetItem(sugg)
                it_fixed.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsEditable)
                self.tbl_corrections.setItem(r, 2, it_fixed)

                cb_action = QComboBox()
                cb_action.addItems(["Skip", "Correct", "Correct (Leave # in Descriptor)", "Ignore"])
                cb_action.setCurrentIndex(0)  # default all dropdowns to skip

                # Connect dropdown change to update the Fixed Code column preview in real time
                def _make_on_action_changed(it_f=it_fixed, s=sugg, sn=sugg_num, od=orig_desc):
                    def _on_act_changed(text):
                        nonlocal _updating_from_combo
                        _updating_from_combo = True
                        try:
                            if "leave" in text.lower() or "keep" in text.lower() or "number" in text.lower():
                                it_f.setText(sn)
                            elif text == "Correct":
                                if it_f.text().strip() in (sn, od, ""):
                                    it_f.setText(s)
                            elif text == "Ignore":
                                it_f.setText(od)
                        finally:
                            _updating_from_combo = False
                    return _on_act_changed

                cb_action.currentTextChanged.connect(_make_on_action_changed())
                self.tbl_corrections.setCellWidget(r, 3, cb_action)

                self.sep_corrections.append((p, orig_desc, it_fixed, cb_action, sugg, sugg_num))

            def _on_corr_cell_changed(row: int, col: int):
                if _updating_from_combo:
                    return
                if col == 2 and hasattr(self, "sep_corrections") and 0 <= row < len(self.sep_corrections):
                    entry = self.sep_corrections[row]
                    cb = entry[3]
                    cb.blockSignals(True)
                    cb.setCurrentText("Correct")
                    cb.blockSignals(False)

            self.tbl_corrections.cellChanged.connect(_on_corr_cell_changed)

            lay_g.addWidget(Hint("Double-click 'Fixed Code' to overwrite and set action to Correct."))
            lay_g.addWidget(self.tbl_corrections)

            # Bottom buttons: Apply and Correct All
            row_btns = QHBoxLayout()
            row_btns.setSpacing(8)

            btn_apply = QPushButton("Apply")
            btn_apply.setProperty("accent", True)
            btn_apply.setToolTip("Process selections (Correct / Ignore / Skip) for points")
            btn_apply.clicked.connect(self._action_apply_separator_corrections)
            row_btns.addWidget(btn_apply)

            btn_correct_all = QPushButton("Correct All")
            btn_correct_all.setToolTip("Set all points to Correct and apply fixed codes immediately")
            btn_correct_all.clicked.connect(self._action_correct_all_separator_corrections)
            row_btns.addWidget(btn_correct_all)

            row_btns.addStretch(1)
            lay_g.addLayout(row_btns)
            self.lay_edit_tools.addWidget(grp)

        elif is_close or is_exact_dup or is_lookalike:
            if is_close:
                self.w_close_tol_bar.show()
            else:
                self.w_close_tol_bar.hide()

            # Compact toolbar for stack resolution mirroring the dialog
            row_c_btns = QHBoxLayout()
            row_c_btns.setSpacing(6)

            btn_resolve_stack = QPushButton("Resolve Stack...")
            btn_resolve_stack.setProperty("accent", True)
            btn_resolve_stack.setToolTip("Open popup dialog with per-point action dropdowns for the selected stack")
            btn_resolve_stack.clicked.connect(lambda: self._action_resolve_selected_stack(is_duplicate=not is_close))
            row_c_btns.addWidget(btn_resolve_stack)

            btn_merge = QPushButton("Merge Stack")
            btn_merge.setToolTip("Combines code groups & notes into primary point and averages coordinates")
            btn_merge.clicked.connect(lambda: self._action_merge_selected_stack(average=True))
            row_c_btns.addWidget(btn_merge)

            btn_del_others = QPushButton("Delete Others")
            btn_del_others.setToolTip("Keep first point and delete other points in selected stack")
            btn_del_others.clicked.connect(self._action_delete_others_selected_stack)
            row_c_btns.addWidget(btn_del_others)

            if is_exact_dup or is_lookalike:
                btn_ren = QPushButton("Renumber Second")
                btn_ren.setToolTip("Assign next free point number to second point in stack")
                btn_ren.clicked.connect(self._action_renumber_selected_stack)
                row_c_btns.addWidget(btn_ren)

            row_c_btns.addStretch(1)

            btn_skip = QPushButton("Skip Finding")
            btn_skip.clicked.connect(lambda: self._action_ignore(finding.get("key", "")))
            row_c_btns.addWidget(btn_skip)

            self.lay_edit_tools.addLayout(row_c_btns)

        else:
            self.w_close_tol_bar.hide()

            pids = finding.get("pids", [])
            pts = [pr.points[pid] for pid in pids if pid in pr.points]

            # Split layout: Left = Point Corrections & Validation; Right = Fieldbook Lookup & Filter
            sp_desc = QSplitter(Qt.Horizontal)
            sp_desc.setChildrenCollapsible(False)

            # ===== LEFT: Key-In Descriptions =====
            grp_keyin = QGroupBox("Key-In Description Corrections")
            lay_keyin = QVBoxLayout(grp_keyin)
            lay_keyin.setSpacing(6)

            lay_keyin.addWidget(Hint(
                "Key in corrected descriptions. Unrecognized codes are underlined in red. "
                "All entered codes are checked against the Field Book in real time."
            ))

            scroll_pts = QScrollArea()
            scroll_pts.setWidgetResizable(True)
            scroll_pts.setFrameShape(QFrame.NoFrame)
            w_pts_inner = QWidget()
            lay_pts_inner = QVBoxLayout(w_pts_inner)
            lay_pts_inner.setContentsMargins(0, 0, 0, 0)
            lay_pts_inner.setSpacing(8)

            self.desc_edits: list[tuple[SurveyPoint, QLineEdit, QLabel]] = []
            self.current_focused_ed: QLineEdit | None = None

            for p in pts:
                w_pt_box = QFrame()
                w_pt_box.setFrameShape(QFrame.StyledPanel)
                lay_p = QVBoxLayout(w_pt_box)
                lay_p.setContentsMargins(6, 6, 6, 6)
                lay_p.setSpacing(3)

                # Header row: Pt # and original description with highlighted red error tokens
                row_h = QHBoxLayout()
                lbl_pt_num = QLabel(f"<b>Pt #{p.number}</b>")
                row_h.addWidget(lbl_pt_num)

                lbl_orig = QLabel(f"<b>Original:</b> {self._highlight_unknown_tokens(p.desc)}")
                lbl_orig.setTextFormat(Qt.RichText)
                row_h.addWidget(lbl_orig, 1)
                lay_p.addLayout(row_h)

                # Key-in box and status feedback
                row_ed = QHBoxLayout()
                row_ed.addWidget(QLabel("<b>Fixed:</b>"))
                ed = QLineEdit(str(p.desc or ""))
                row_ed.addWidget(ed, 1)
                lay_p.addLayout(row_ed)

                lbl_status = QLabel("")
                lbl_status.setTextFormat(Qt.RichText)
                lay_p.addWidget(lbl_status)

                # Focus tracking
                def _make_focus_handler(e=ed):
                    orig_focus = e.focusInEvent
                    def _on_focus_in(event):
                        self.current_focused_ed = e
                        orig_focus(event)
                    return _on_focus_in
                ed.focusInEvent = _make_focus_handler()

                # Validation callback
                def _make_validate_handler(e=ed, lbl=lbl_status):
                    def _on_txt_changed(txt):
                        is_val, msg = self._validate_desc_text(txt)
                        if not is_val:
                            e.setStyleSheet("QLineEdit { color: #1f2933; selection-color: #ffffff; selection-background-color: #357edd; border: 1.5px solid #e74c3c; background-color: #fdf2f2; border-radius: 3px; }")
                            lbl.setText(f"<span style='color: #e74c3c; font-size: 11px; font-weight: bold;'>⚠ {msg}</span>")
                        else:
                            e.setStyleSheet("QLineEdit { color: #1f2933; selection-color: #ffffff; selection-background-color: #357edd; border: 1.5px solid #27ae60; background-color: #f4faf6; border-radius: 3px; }")
                            lbl.setText(f"<span style='color: #27ae60; font-size: 11px; font-weight: bold;'>✓ {msg}</span>")
                    return _on_txt_changed

                val_fn = _make_validate_handler()
                ed.textChanged.connect(val_fn)
                val_fn(ed.text())  # Run initial validation

                self.desc_edits.append((p, ed, lbl_status))
                lay_pts_inner.addWidget(w_pt_box)

            if self.desc_edits:
                self.current_focused_ed = self.desc_edits[0][1]

            lay_pts_inner.addStretch(1)
            scroll_pts.setWidget(w_pts_inner)
            lay_keyin.addWidget(scroll_pts, 1)

            # Bottom buttons for Key-in
            row_d_btns = QHBoxLayout()
            row_d_btns.setSpacing(6)

            btn_apply_desc = QPushButton("Apply")
            btn_apply_desc.setProperty("accent", True)
            btn_apply_desc.setToolTip("Validate and apply corrected point descriptions")
            btn_apply_desc.clicked.connect(self._action_apply_descriptions)
            row_d_btns.addWidget(btn_apply_desc)

            btn_autofix = QPushButton("Auto Fix All")
            btn_autofix.setEnabled(False)
            btn_autofix.setToolTip("Auto Fix is temporarily disabled. Edit descriptions manually or use Fieldbook Lookup.")
            btn_autofix.clicked.connect(self._action_autofix_descriptions)
            self.btn_autofix_descriptions = btn_autofix
            row_d_btns.addWidget(btn_autofix)

            row_d_btns.addStretch(1)
            btn_skip = QPushButton("Skip Finding")
            btn_skip.clicked.connect(lambda: self._action_ignore(finding.get("key", "")))
            row_d_btns.addWidget(btn_skip)
            lay_keyin.addLayout(row_d_btns)

            sp_desc.addWidget(grp_keyin)

            # ===== RIGHT: Fieldbook Lookup & Filter =====
            grp_fb = QGroupBox("Fieldbook Lookup")
            lay_fb = QVBoxLayout(grp_fb)
            lay_fb.setSpacing(6)

            # Filter bar: Search + Category
            row_fb_filter = QHBoxLayout()
            row_fb_filter.setSpacing(6)

            self.fb_search = QLineEdit()
            self.fb_search.setPlaceholderText("Search code or description (*contains*)...")
            self.fb_search.setClearButtonEnabled(True)
            row_fb_filter.addWidget(self.fb_search, 1)

            row_fb_filter.addWidget(QLabel("<b>Category:</b>"))
            self.fb_category = QComboBox()
            self.fb_category.addItem("All Categories")

            self.fb_all_rows = self._load_fieldbook_lookup_rows()
            categories = sorted({cat for _, _, cat in self.fb_all_rows if cat})
            for cat in categories:
                self.fb_category.addItem(cat)
            row_fb_filter.addWidget(self.fb_category)
            lay_fb.addLayout(row_fb_filter)

            # Fieldbook Table
            self.fb_table = QTableWidget(0, 3)
            self.fb_table.setHorizontalHeaderLabels(["Code", "Description", "Category"])
            self.fb_table.setSelectionBehavior(QAbstractItemView.SelectRows)
            self.fb_table.setSelectionMode(QAbstractItemView.SingleSelection)
            self.fb_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
            self.fb_table.setAlternatingRowColors(True)
            self.fb_table.verticalHeader().setVisible(False)
            hh_fb = self.fb_table.horizontalHeader()
            hh_fb.setSectionResizeMode(QHeaderView.Interactive)
            self.fb_table.setColumnWidth(0, 80)
            self.fb_table.setColumnWidth(1, 160)
            self.fb_table.setColumnWidth(2, 120)
            hh_fb.setStretchLastSection(True)
            self.fb_table.cellDoubleClicked.connect(lambda r, c: self._fb_use_code())
            lay_fb.addWidget(self.fb_table, 1)

            # Bottom row of Fieldbook Lookup: Count + Use Button
            row_fb_bot = QHBoxLayout()
            self.fb_count_lbl = QLabel("")
            self.fb_count_lbl.setStyleSheet("color: #7f8c8d; font-size: 11px;")
            row_fb_bot.addWidget(self.fb_count_lbl)
            row_fb_bot.addStretch(1)

            btn_use_code = QPushButton("→ Use Selected Code")
            btn_use_code.setToolTip("Insert selected Field Book code into active point's fixed description")
            btn_use_code.clicked.connect(self._fb_use_code)
            row_fb_bot.addWidget(btn_use_code)
            lay_fb.addLayout(row_fb_bot)

            # Wire search & category changes
            self.fb_search.textChanged.connect(self._fb_apply_filter)
            self.fb_category.currentTextChanged.connect(self._fb_apply_filter)
            self._fb_apply_filter()

            sp_desc.addWidget(grp_fb)
            sp_desc.setSizes([340, 340])
            self.lay_edit_tools.addWidget(sp_desc)

    # ------------------------------------------------------------------ Fieldbook & Validation Helpers
    def _highlight_unknown_tokens(self, orig_desc: str | None) -> str:
        """Format original description with unrecognized code tokens underlined and colored in red."""
        import html
        from ..fieldwork.parse import parse_desc_field
        if not orig_desc or not str(orig_desc).strip():
            return "<i style='color: #888;'>No description</i>"
        raw_s = str(orig_desc)
        f2f_set = self.code_set or set()
        parsed = parse_desc_field(raw_s, f2f_set)
        bad_tokens = set()
        for item in parsed.get("code_classified", []):
            if item.get("error") == "UnknownCode" or item.get("status") == "unknown":
                bad_tokens.add(item.get("raw", ""))
        for f in parsed.get("flags", []):
            if f.startswith("UnknownCode:"):
                bad_tokens.add(f.split(":", 1)[1].strip())

        escaped = html.escape(raw_s)
        for tok in sorted(bad_tokens, key=len, reverse=True):
            if not tok:
                continue
            tok_esc = html.escape(tok)
            pat = re.compile(rf"\b{re.escape(tok_esc)}\b", re.IGNORECASE)
            escaped = pat.sub(f"<span style='color: #e74c3c; text-decoration: underline; font-weight: bold;'>{tok_esc}</span>", escaped)
        return escaped

    def _validate_desc_text(self, txt: str, f2f_set: set | None = None) -> tuple[bool, str]:
        """Check if keyed-in description parses cleanly against Field Book vocabulary."""
        from ..fieldwork.parse import parse_desc_field
        s = txt.strip()
        if not s:
            return False, "Empty description"
        f_set = f2f_set if f2f_set is not None else (self.code_set or set())
        parsed = parse_desc_field(s, f_set)
        bad_tokens = []
        for item in parsed.get("code_classified", []):
            if item.get("error") == "UnknownCode" or item.get("status") == "unknown":
                bad_tokens.append(item.get("raw", ""))
        for f in parsed.get("flags", []):
            if f.startswith("UnknownCode:"):
                bad_tokens.append(f.split(":", 1)[1].strip())
        if bad_tokens:
            return False, f"Unknown code '{bad_tokens[0]}' not in Field Book"
        return True, "Valid Field Book Code"

    def _load_fieldbook_lookup_rows(self) -> list[tuple[str, str, str]]:
        """Return list of (code, description, category) tuples for Fieldbook lookup."""
        pr = self.state.project
        rows: list[tuple[str, str, str]] = []
        seen = set()

        # 1. Try reading the fieldbook .fwb file if available
        fb_path = None
        try:
            from ..fieldwork.bridge import vocabulary_for
            voc = vocabulary_for(pr, getattr(self.state, "job_folder", None))
            fb_path = voc.get("path")
        except Exception:
            pass
        if not fb_path and (pr.settings or {}).get("fieldbook_file"):
            fb_path = pr.settings.get("fieldbook_file")

        if fb_path:
            try:
                from ..fieldwork.io_carlson import read_fwb_file
                from pathlib import Path
                _, fwb_rows = read_fwb_file(Path(fb_path))
                for r in (fwb_rows or []):
                    c = str(r[0]).strip() if len(r) > 0 else ""
                    if not c or c.casefold() in seen:
                        continue
                    d = str(r[1]).strip() if len(r) > 1 else ""
                    cat = str(r[5]).strip() if len(r) > 5 and str(r[5]).strip() else "General"
                    rows.append((c, d, cat))
                    seen.add(c.casefold())
            except Exception:
                pass

        # 2. Add codes from project.codes
        if hasattr(pr, "codes") and pr.codes:
            codes_dict = getattr(pr.codes, "codes", {})
            if isinstance(codes_dict, dict):
                for c, code_obj in codes_dict.items():
                    c_str = str(c).strip()
                    if c_str and c_str.casefold() not in seen:
                        d_str = str(getattr(code_obj, "name", code_obj) or "").strip()
                        layer_str = str(getattr(code_obj, "layer", "") or "").strip()
                        prefix = layer_str.split("-")[0].strip().upper() if layer_str else ""
                        cat_map = {
                            "ROAD": "Road / Paving",
                            "TOPO": "Topography",
                            "CONTROL": "Control / Monuments",
                            "UTIL": "Utilities",
                            "HYDRO": "Hydrology",
                            "GRADE": "Grading / Slopes",
                            "STRUCT": "Structures",
                            "SITE": "Site / Features",
                            "VEG": "Vegetation",
                            "BNDY": "Boundary / Easements",
                        }
                        cat_str = cat_map.get(prefix, prefix.capitalize() or "Project Codes")
                        rows.append((c_str, d_str, cat_str))
                        seen.add(c_str.casefold())
            elif isinstance(pr.codes, (list, tuple, set)):
                for c in pr.codes:
                    c_str = str(getattr(c, "code", c)).strip()
                    if c_str and c_str.casefold() not in seen:
                        d_str = str(getattr(c, "name", getattr(c, "desc", "")) or "").strip()
                        cat_str = str(getattr(c, "category", "Project Codes")).strip() or "Project Codes"
                        rows.append((c_str, d_str, cat_str))
                        seen.add(c_str.casefold())

        # 3. Add any leftover codes from code_set
        for c in sorted(self.code_set):
            c_str = str(c).strip()
            if c_str and c_str.casefold() not in seen:
                rows.append((c_str.upper(), "", "General"))
                seen.add(c_str.casefold())

        return sorted(rows, key=lambda x: (x[2].casefold(), x[0].casefold()))

    def _fb_apply_filter(self):
        if not hasattr(self, "fb_table") or not hasattr(self, "fb_all_rows"):
            return
        query = self.fb_search.text().strip().casefold()
        cat = self.fb_category.currentText().strip()

        filtered = []
        for c, d, k in self.fb_all_rows:
            if cat != "All Categories" and k != cat:
                continue
            if query and (query not in c.casefold() and query not in d.casefold()):
                continue
            filtered.append((c, d, k))

        self.fb_table.setRowCount(len(filtered))
        for r, (c, d, k) in enumerate(filtered):
            it_c = QTableWidgetItem(c)
            it_c.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_d = QTableWidgetItem(d)
            it_d.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            it_k = QTableWidgetItem(k)
            it_k.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
            self.fb_table.setItem(r, 0, it_c)
            self.fb_table.setItem(r, 1, it_d)
            self.fb_table.setItem(r, 2, it_k)

        total = len(self.fb_all_rows)
        self.fb_count_lbl.setText(f"Showing {len(filtered)} of {total} codes")

    def _fb_use_code(self):
        sel_rows = self.fb_table.selectionModel().selectedRows()
        if not sel_rows:
            return
        r = sel_rows[0].row()
        it_c = self.fb_table.item(r, 0)
        if not it_c:
            return
        code_to_insert = it_c.text().strip()

        target_ed = getattr(self, "current_focused_ed", None)
        if not target_ed and hasattr(self, "desc_edits") and self.desc_edits:
            target_ed = self.desc_edits[0][1]

        if target_ed:
            cur_txt = target_ed.text().strip()
            if not cur_txt:
                target_ed.setText(code_to_insert)
            else:
                from ..fieldwork.parse import parse_desc_field
                parsed = parse_desc_field(cur_txt, self.code_set or set())
                bad_tokens = []
                for item in parsed.get("code_classified", []):
                    if item.get("error") == "UnknownCode" or item.get("status") == "unknown":
                        bad_tokens.append(item.get("raw", ""))
                if bad_tokens:
                    pat = r'\b' + re.escape(bad_tokens[0]) + r'\b'
                    new_txt = re.sub(pat, code_to_insert, cur_txt, count=1, flags=re.I)
                    target_ed.setText(new_txt)
                else:
                    target_ed.setText(code_to_insert)
            target_ed.setFocus()

    # Specific Fix Actions
    def _action_resolve_stack_dialog(self, stack_pids: list[int], is_duplicate: bool = False):
        pr = self.state.project
        pts = [pr.points[pid] for pid in stack_pids if pid in pr.points]
        if not pts:
            return
        dlg = ClosePointsResolveDialog(self.state, pts, is_duplicate=is_duplicate, parent=self)
        if dlg.exec() != QDialog.Accepted:
            return
        res = dlg.get_result()
        target_p = res["target_point"]
        merge_pts = res["merge_points"]
        delete_pts = res["delete_points"]
        renumber_pts = res.get("renumber_points", [])
        ignore_pts = res.get("ignore_points", [])
        merged_desc = res["merged_desc"]
        avg_coords = res["average_coords"]

        pts_to_remove = [p for p in merge_pts if p.id != target_p.id] + delete_pts

        def do_it():
            if avg_coords and len(merge_pts) > 1:
                target_p.x = sum(p.x for p in merge_pts) / len(merge_pts)
                target_p.y = sum(p.y for p in merge_pts) / len(merge_pts)
                target_p.z = _average_finite([p.z for p in merge_pts])
            if len(merge_pts) > 1 and merged_desc:
                target_p.desc = merged_desc
            for p in renumber_pts:
                all_nums = [int(pt.number) for pt in pr.points.values() if pt.number.isdigit()]
                next_num = str(max(all_nums) + 1) if all_nums else "1"
                p.number = next_num
            remove_ids = [p.id for p in pts_to_remove if p.id in pr.points]
            if remove_ids:
                pr.remove_points(remove_ids)

        summary = f"Resolved stack into Pt #{target_p.number}"
        if merged_desc:
            summary += f" ({merged_desc})"
        if ignore_pts:
            summary += f"; ignored {len(ignore_pts)} point(s)"
        self._apply_fix(
            summary,
            do_it,
            resolved_points=stack_pids,
            stay_on_edit_page=True,
            ignored_points=[p.id for p in ignore_pts],
        )

    def _action_resolve_selected_stack(self, is_duplicate: bool = False):
        stk = getattr(self, "current_selected_stack", None)
        if not stk and self.current_edit_finding:
            stacks = self.current_edit_finding.get("stack_groups") or [self.current_edit_finding.get("pids", [])]
            if stacks:
                stk = stacks[0]
        if stk:
            self._action_resolve_stack_dialog(stk, is_duplicate=is_duplicate)

    def _action_merge_selected_stack(self, average: bool = True):
        stk = getattr(self, "current_selected_stack", None)
        if not stk and self.current_edit_finding:
            stacks = self.current_edit_finding.get("stack_groups") or [self.current_edit_finding.get("pids", [])]
            if stacks:
                stk = stacks[0]
        if not stk:
            return
        pr = self.state.project
        pts = [pr.points[pid] for pid in stk if pid in pr.points]
        if not pts:
            return
        self._action_merge_close(pts, average=average)

    def _action_delete_others_selected_stack(self):
        stk = getattr(self, "current_selected_stack", None)
        if not stk and self.current_edit_finding:
            stacks = self.current_edit_finding.get("stack_groups") or [self.current_edit_finding.get("pids", [])]
            if stacks:
                stk = stacks[0]
        if not stk:
            return
        pr = self.state.project
        pts = [pr.points[pid] for pid in stk if pid in pr.points]
        if not pts:
            return
        self._action_delete_close_others(pts)

    def _action_renumber_selected_stack(self):
        stk = getattr(self, "current_selected_stack", None)
        if not stk and self.current_edit_finding:
            stacks = self.current_edit_finding.get("stack_groups") or [self.current_edit_finding.get("pids", [])]
            if stacks:
                stk = stacks[0]
        if not stk:
            return
        pr = self.state.project
        pts = [pr.points[pid] for pid in stk if pid in pr.points]
        if len(pts) >= 2:
            self.ed_new_num = QLineEdit()
            all_nums = [int(p.number) for p in pr.points.values() if p.number.isdigit()]
            self.ed_new_num.setText(str(max(all_nums) + 1) if all_nums else "1")
            self._action_renumber(pts)

    def _action_merge_close(self, pts: list[SurveyPoint], average: bool = True):
        if not pts:
            return
        p_primary = pts[0]
        pts_del = pts[1:]
        stack_pids = [p.id for p in pts]
        merged_desc = merge_point_descriptions([p.desc for p in pts])

        def do_it():
            if average and pts:
                p_primary.x = sum(p.x for p in pts) / len(pts)
                p_primary.y = sum(p.y for p in pts) / len(pts)
                p_primary.z = _average_finite([p.z for p in pts])
            p_primary.desc = merged_desc
            if pts_del:
                self.state.project.remove_points([p.id for p in pts_del if p.id in self.state.project.points])

        self._apply_fix(f"Merged {len(pts)} close points into Pt #{p_primary.number} ({merged_desc})", do_it,
                        resolved_points=stack_pids, stay_on_edit_page=True)

    def _action_delete_close_others(self, pts: list[SurveyPoint]):
        if not pts:
            return
        p_primary = pts[0]
        pts_del = pts[1:]
        stack_pids = [p.id for p in pts]

        def do_it():
            if pts_del:
                self.state.project.remove_points([p.id for p in pts_del if p.id in self.state.project.points])

        self._apply_fix(f"Kept Pt #{p_primary.number}, deleted {len(pts_del)} other point(s)", do_it,
                        resolved_points=stack_pids, stay_on_edit_page=True)

    def _action_renumber(self, pts: list[SurveyPoint]):
        if len(pts) < 2:
            return
        new_num = self.ed_new_num.text().strip() if hasattr(self, "ed_new_num") and self.ed_new_num.text().strip() else ""
        if not new_num:
            pr = self.state.project
            all_nums = [int(p.number) for p in pr.points.values() if p.number.isdigit()]
            new_num = str(max(all_nums) + 1) if all_nums else "1"
        p_target = pts[1]
        stack_pids = [p.id for p in pts]

        def do_it():
            p_target.number = new_num

        self._apply_fix(f"Renumbered point {p_target.id} to {new_num}", do_it,
                        resolved_points=stack_pids, stay_on_edit_page=True)

    def _action_average(self, pts: list[SurveyPoint]):
        if len(pts) < 2:
            return
        p_keep = pts[0]
        pts_del = pts[1:]
        stack_pids = [p.id for p in pts]

        def do_it():
            p_keep.x = sum(p.x for p in pts) / len(pts)
            p_keep.y = sum(p.y for p in pts) / len(pts)
            p_keep.z = _average_finite([p.z for p in pts])
            if pts_del:
                self.state.project.remove_points([p.id for p in pts_del if p.id in self.state.project.points])

        self._apply_fix(f"Averaged {len(pts)} points onto Pt #{p_keep.number}", do_it,
                        resolved_points=stack_pids, stay_on_edit_page=True)

    def _action_keep_first(self, pts: list[SurveyPoint]):
        if len(pts) < 2:
            return
        p_keep = pts[0]
        pts_del = pts[1:]
        stack_pids = [p.id for p in pts]

        def do_it():
            if pts_del:
                self.state.project.remove_points([p.id for p in pts_del if p.id in self.state.project.points])

        self._apply_fix(f"Kept Pt #{p_keep.number}, removed {len(pts_del)} duplicate(s)", do_it,
                        resolved_points=stack_pids, stay_on_edit_page=True)

    def _action_apply_descriptions(self):
        if not hasattr(self, "desc_edits") or not self.desc_edits:
            return

        f2f_set = self.code_set or set()
        changes: list[tuple[SurveyPoint, str, QLineEdit]] = []
        for item in self.desc_edits:
            p = item[0]
            ed = item[1]
            txt = ed.text().strip()
            if txt != (p.desc or ""):
                changes.append((p, txt, ed))

        if not changes:
            return

        # Pre-validate only changed descriptions: if any contains unknown codes, self-flag and show error
        invalid_entries = []
        for p, txt, ed in changes:
            is_valid, err_msg = self._validate_desc_text(txt, f2f_set)
            if not is_valid:
                invalid_entries.append((p, txt, err_msg, ed))

        if invalid_entries:
            first_p, first_txt, first_err, first_ed = invalid_entries[0]
            first_ed.setFocus()
            QMessageBox.critical(
                self,
                "Invalid Field Book Code",
                f"Point #{first_p.number} has an invalid description:\n\n"
                f"'{first_txt}'\n\n"
                f"Error: {first_err}\n\n"
                f"Keyed-in codes must exist in the Field Book so linework and point processing do not fail. "
                f"Please correct the error or select a valid code from Fieldbook Lookup before applying.",
            )
            return

        pids = [p.id for p, _, _ in changes]

        def do_it():
            for p, txt, _ in changes:
                p.desc = txt

        descs_str = ", ".join(f"Pt #{p.number} -> '{txt}'" for p, txt, _ in changes)
        self._apply_fix(f"Updated description(s): {descs_str}", do_it,
                        resolved_points=pids, stay_on_edit_page=True)

    def _action_apply_separator_corrections(self):
        if not hasattr(self, "sep_corrections") or not self.sep_corrections:
            return

        to_correct: list[tuple[SurveyPoint, str]] = []
        to_ignore: list[SurveyPoint] = []
        to_skip: list[SurveyPoint] = []

        for item in self.sep_corrections:
            p = item[0]
            orig_desc = item[1]
            it_fixed = item[2]
            cb_action = item[3]
            sugg = item[4] if len(item) > 4 else ""
            sugg_num = item[5] if len(item) > 5 else ""

            act = cb_action.currentText().strip()
            if act == "Correct":
                txt = it_fixed.text().strip() or sugg
                to_correct.append((p, txt))
            elif "leave" in act.lower() or "keep" in act.lower() or "number" in act.lower():
                txt = it_fixed.text().strip() or sugg_num
                to_correct.append((p, txt))
            elif act == "Ignore":
                to_ignore.append(p)
            else:
                to_skip.append(p)

        resolved_pts = [p for p, _ in to_correct] + to_ignore
        if not resolved_pts:
            return

        resolved_pids = [p.id for p in resolved_pts]

        def do_it():
            for p, txt in to_correct:
                p.desc = txt

        descs_str = ", ".join(f"Pt #{p.number} -> '{txt}'" for p, txt in to_correct)
        if to_ignore:
            ign_str = f"Ignored {len(to_ignore)} point(s)"
            summary = f"Corrected potential code in descriptor: {descs_str}; {ign_str}" if descs_str else f"Potential code in descriptor: {ign_str}"
        else:
            summary = f"Corrected potential code in descriptor: {descs_str}"

        self._apply_fix(
            summary,
            do_it,
            resolved_points=resolved_pids,
            stay_on_edit_page=True,
            ignored_points=[p.id for p in to_ignore],
        )

        finding = self.current_edit_finding
        if not to_skip:
            self.tbl_edit_pts.setRowCount(0)
            self.sep_corrections = []
            while self.lay_edit_tools.count():
                it = self.lay_edit_tools.takeAt(0)
                if it.widget():
                    it.widget().deleteLater()
                elif it.layout():
                    while it.layout().count():
                        sub = it.layout().takeAt(0)
                        if sub.widget():
                            sub.widget().deleteLater()
        else:
            if finding:
                finding["pids"] = [p.id for p in to_skip]
                finding["numbers"] = [str(p.number) for p in to_skip]
                self._open_inline_editor(finding, start_session=False)

    def _action_correct_all_separator_corrections(self):
        if hasattr(self, "sep_corrections") and self.sep_corrections:
            for item in self.sep_corrections:
                item[3].setCurrentText("Correct")
            self._action_apply_separator_corrections()

    def _action_ignore_separator_finding(self, finding: dict):
        pids = finding.get("pids", [])
        self._action_ignore(finding.get("key", ""))
        self.tbl_edit_pts.setRowCount(0)
        self.sep_corrections = []
        while self.lay_edit_tools.count():
            it = self.lay_edit_tools.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
            elif it.layout():
                while it.layout().count():
                    sub = it.layout().takeAt(0)
                    if sub.widget():
                        sub.widget().deleteLater()

    def _action_uppercase_descriptions(self):
        for item in getattr(self, "desc_edits", []):
            p, ed = item[0], item[1]
            ed.setText(ed.text().upper())
        self._action_apply_descriptions()

    def _action_autofix_descriptions(self):
        """Auto Fix is temporarily disabled; use manual edits or Fieldbook Lookup."""
        return



# ============================================================================
# 2. FIX LINEWORK WORKBENCH
# ============================================================================
class FixLineworkDialog(BaseQAWorkbenchDialog):
    """Workbench dedicated to Category 2: Linework Errors & Cleanup."""

    workbench_title = "Fix Linework"

    def _filter_finding(self, finding: dict) -> bool:
        chk = finding.get("check", "").lower()
        flag = str(finding.get("flag", ""))
        # Only linework issues
        if "line:" in chk or flag.startswith("Missing") or any(w in chk for w in ("line", "curve", "string", "closed")):
            return True
        return False

    def _build_inline_tools(self, finding: dict):
        pr = self.state.project
        pids = finding.get("pids", [])
        pts = [pr.points[pid] for pid in pids if pid in pr.points]

        grp = QGroupBox("Linework Sequence & Cleanup Tools")
        lay_g = QVBoxLayout(grp)
        lay_g.setSpacing(6)

        # 1. Quick Start / End additions
        row_se = QHBoxLayout()
        btn_add_st = QPushButton("Add ST")
        btn_add_st.clicked.connect(lambda: self._action_add_st(pts))
        row_se.addWidget(btn_add_st)

        btn_add_end = QPushButton("Add END")
        btn_add_end.clicked.connect(lambda: self._action_add_end(pts))
        row_se.addWidget(btn_add_end)

        btn_add_cls = QPushButton("Close Figure")
        btn_add_cls.clicked.connect(lambda: self._action_add_cls(pts))
        row_se.addWidget(btn_add_cls)
        row_se.addStretch(1)
        lay_g.addLayout(row_se)

        # 2. Bowtie Rod Code Swap
        box_bt = QGroupBox("Fix Bowtie (Swap Parallel Rod Codes)")
        lay_bt = QHBoxLayout(box_bt)
        self.ed_c1 = QLineEdit("EC1")
        self.ed_c1.setMaximumWidth(80)
        self.ed_c2 = QLineEdit("EC2")
        self.ed_c2.setMaximumWidth(80)
        lay_bt.addWidget(QLabel("Swap Line 1:"))
        lay_bt.addWidget(self.ed_c1)
        lay_bt.addWidget(QLabel("with Line 2:"))
        lay_bt.addWidget(self.ed_c2)
        btn_swap = QPushButton("Swap Codes")
        btn_swap.setProperty("accent", True)
        btn_swap.clicked.connect(lambda: self._action_swap_bowtie(pts))
        lay_bt.addWidget(btn_swap)
        lay_bt.addStretch(1)
        lay_g.addWidget(box_bt)

        # 3. Reclass & Merge String
        box_rc = QGroupBox("Reclass & Merge String Range")
        lay_rc = QHBoxLayout(box_rc)
        self.ed_rc_code = QLineEdit("EC")
        self.ed_rc_code.setMaximumWidth(80)
        free_id = PLC.find_free_string_id(pr, "EC")
        self.ed_rc_id = QLineEdit(free_id)
        self.ed_rc_id.setMaximumWidth(60)
        lay_rc.addWidget(QLabel("Base Code:"))
        lay_rc.addWidget(self.ed_rc_code)
        lay_rc.addWidget(QLabel("New String ID:"))
        lay_rc.addWidget(self.ed_rc_id)
        btn_rc = QPushButton("Merge & Reclass")
        btn_rc.clicked.connect(lambda: self._action_reclass_merge(pts))
        lay_rc.addWidget(btn_rc)
        lay_rc.addStretch(1)
        lay_g.addWidget(box_rc)

        # 4. Reorder Figure & Command Order
        row_extra = QHBoxLayout()
        btn_cmd_order = QPushButton("Fix Command Order")
        btn_cmd_order.clicked.connect(lambda: self._action_fix_cmd_order(pts))
        row_extra.addWidget(btn_cmd_order)

        btn_reverse = QPushButton("Reverse Figure")
        btn_reverse.clicked.connect(lambda: self._action_reverse(pts))
        row_extra.addWidget(btn_reverse)
        row_extra.addStretch(1)
        lay_g.addLayout(row_extra)

        # Skip / Ignore Button
        row_skip = QHBoxLayout()
        row_skip.addStretch(1)
        btn_skip = QPushButton("Skip Issue")
        btn_skip.clicked.connect(lambda: self._action_ignore(finding.get("key", "")))
        row_skip.addWidget(btn_skip)
        lay_g.addLayout(row_skip)

        self.lay_edit_tools.addWidget(grp)

    # Linework Actions
    def _action_add_st(self, pts: list[SurveyPoint]):
        if not pts:
            return
        p = pts[0]

        def do_it():
            tokens = (p.desc or "").split()
            code = tokens[0] if tokens else "EP"
            p.desc = PLC.update_point_token(p.desc or "", code, f"{code} ST")

        self._apply_fix(f"Added ST to Pt #{p.number}", do_it, resolved_points=[p.id], stay_on_edit_page=True)

    def _action_add_end(self, pts: list[SurveyPoint]):
        if not pts:
            return
        p = pts[-1]

        def do_it():
            tokens = (p.desc or "").split()
            code = tokens[0] if tokens else "EP"
            p.desc = PLC.update_point_token(p.desc or "", code, f"{code} END")

        self._apply_fix(f"Added END to Pt #{p.number}", do_it, resolved_points=[p.id], stay_on_edit_page=True)

    def _action_add_cls(self, pts: list[SurveyPoint]):
        if not pts:
            return
        p = pts[-1]

        def do_it():
            tokens = (p.desc or "").split()
            code = tokens[0] if tokens else "BLDG"
            p.desc = PLC.update_point_token(p.desc or "", code, f"{code} CLS")

        self._apply_fix(f"Closed figure on Pt #{p.number}", do_it, resolved_points=[p.id], stay_on_edit_page=True)

    def _action_swap_bowtie(self, pts: list[SurveyPoint]):
        c1 = self.ed_c1.text().strip().upper()
        c2 = self.ed_c2.text().strip().upper()
        if not c1 or not c2:
            return
        pids = [p.id for p in pts]

        def do_it():
            PLC.swap_parallel_line_codes(pts, c1, c2)

        self._apply_fix(f"Swapped parallel line codes {c1} <-> {c2}", do_it, resolved_points=pids, stay_on_edit_page=True)

    def _action_reclass_merge(self, pts: list[SurveyPoint]):
        t_code = self.ed_rc_code.text().strip().upper()
        t_id = self.ed_rc_id.text().strip()
        if not t_code or not t_id:
            return
        pids = [p.id for p in pts]

        def do_it():
            mid = len(pts) // 2
            s1 = pts[:mid]
            s2 = pts[mid:]
            PLC.merge_and_reclass_strings(self.state.project, s1, s2, target_code=t_code, new_string_id=t_id)

        self._apply_fix(f"Reclassed and merged to {t_code}{t_id}", do_it, resolved_points=pids, stay_on_edit_page=True)

    def _action_fix_cmd_order(self, pts: list[SurveyPoint]):
        pids = [p.id for p in pts]

        def do_it():
            for p in pts:
                p.desc = PLC.fix_line_command_order(p.desc or "")

        self._apply_fix(f"Standardized line command order on {len(pts)} point(s)", do_it, resolved_points=pids, stay_on_edit_page=True)

    def _action_reverse(self, pts: list[SurveyPoint]):
        pids = [p.id for p in pts]

        def do_it():
            PLC.reverse_string_coding(pts)

        self._apply_fix(f"Reversed line direction on {len(pts)} point(s)", do_it, resolved_points=pids, stay_on_edit_page=True)


# Backward compatibility alias
class QAWorkspaceDialog(FixPointErrorsDialog):
    """Backwards-compatible alias for FixPointErrorsDialog."""
    pass


# ------------------------------------------------------------------ Dedicated Repair Dialogs
class BowtieRepairDialog(QDialog):
    """Interactive Bowtie Line Repair Dialog."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Repair Bowtie (Crossing Parallel Strings)")
        self.setMinimumSize(450, 260)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        lay.addWidget(Hint(
            "Select the crossing/swapped rod points. Plumbline will swap their string codes "
            "(e.g. EC1 <-> EC2) so the two lines uncross cleanly."
        ))

        form = QFormLayout()
        self.le_code1 = QLineEdit("EC1")
        self.le_code2 = QLineEdit("EC2")
        form.addRow("Line 1 Code (e.g. EC1):", self.le_code1)
        form.addRow("Line 2 Code (e.g. EC2):", self.le_code2)
        lay.addLayout(form)

        pids = list(state.sel_points)
        pts = [state.project.points[i] for i in pids if i in state.project.points]
        lay.addWidget(QLabel(f"Selected Points to Swap: <b>{len(pts)} point(s)</b> ({', '.join(p.number for p in pts[:6])})"))

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        b_apply = QPushButton("Apply Swap")
        b_apply.setProperty("accent", True)
        b_apply.clicked.connect(self._apply)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        btn_row.addWidget(b_apply)
        btn_row.addWidget(b_cancel)
        lay.addLayout(btn_row)

    def _apply(self):
        c1 = self.le_code1.text().strip().upper()
        c2 = self.le_code2.text().strip().upper()
        pids = list(self.state.sel_points)
        pts = [self.state.project.points[i] for i in pids if i in self.state.project.points]
        if not pts or not c1 or not c2:
            return
        with self.state.edit(f"Repair bowtie {c1} <-> {c2}"):
            PLC.swap_parallel_line_codes(pts, c1, c2)
            self.state.project.process_linework()
            self.state.set_dirty(True)
            self.state.refresh(("points", "entities"))
        self.accept()


class ReclassMergeLinesDialog(QDialog):
    """Merge and Reclassify Line Strings Dialog."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        self.setWindowTitle("Merge & Reclassify Line Strings")
        self.setMinimumSize(480, 300)
        lay = QVBoxLayout(self)
        lay.setSpacing(8)

        lay.addWidget(Hint(
            "Merge two broken string segments into a single continuous polyline with a fresh string ID."
        ))

        form = QFormLayout()
        self.le_str1 = QLineEdit("EP1")
        self.le_str2 = QLineEdit("EP2")
        self.le_target_code = QLineEdit("EP")
        free_id = PLC.find_free_string_id(state.project, "EP")
        self.le_target_id = QLineEdit(free_id)

        form.addRow("First String (e.g. EP1):", self.le_str1)
        form.addRow("Second String (e.g. EP2):", self.le_str2)
        form.addRow("Target Feature Code:", self.le_target_code)
        form.addRow("New String ID:", self.le_target_id)
        lay.addLayout(form)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        b_apply = QPushButton("Apply Merge")
        b_apply.setProperty("accent", True)
        b_apply.clicked.connect(self._apply)
        b_cancel = QPushButton("Cancel")
        b_cancel.clicked.connect(self.reject)
        btn_row.addWidget(b_apply)
        btn_row.addWidget(b_cancel)
        lay.addLayout(btn_row)

    def _apply(self):
        s1_name = self.le_str1.text().strip().upper()
        s2_name = self.le_str2.text().strip().upper()
        t_code = self.le_target_code.text().strip().upper()
        t_id = self.le_target_id.text().strip()
        if not s1_name or not s2_name or not t_code or not t_id:
            return

        pr = self.state.project
        pts1 = [p for p in pr.points.values() if s1_name in (p.desc or "").upper().split()]
        pts2 = [p for p in pr.points.values() if s2_name in (p.desc or "").upper().split()]

        if not pts1 or not pts2:
            QMessageBox.warning(self, "Points Not Found", "Could not find points matching both strings in project.")
            return

        with self.state.edit(f"Merge {s1_name} + {s2_name} -> {t_code}{t_id}"):
            PLC.merge_and_reclass_strings(pr, pts1, pts2, target_code=t_code, new_string_id=t_id)
            pr.process_linework()
            self.state.set_dirty(True)
            self.state.refresh(("points", "entities"))
        self.accept()
