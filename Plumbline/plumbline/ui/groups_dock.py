"""The Groups dock: name a set of objects, tick it on and off.

The four things the change order asks for are the four buttons - **New**, **Rename**, **Remove**
on the left; **Add selection** and **Take out** under the table - and the tick in the first
column is the switch.  A tick that is *off* hides the group's objects **everywhere**: out of the
drawing, out of the exports (DXF, LandXML, GIS, KML, reports) and out of surfaces built after it
(``core/groups.py`` has the whole rule).  Surfaces that already exist are not rebuilt by a tick -
that is a surface rebuild, not a display change - so a note appears under the table when a
switched-off group is feeding an existing surface.

A hidden object can still be picked in the drawing: that is deliberate, because the way to get
something *back* is usually to find it where it was drawn.  Hidden geometry is drawn in the
selection overlay if it is selected, so a mistake is visible rather than silent.
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
                               QMenu, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.groups import GroupSet
from .widgets import Hint, error_box


class GroupsDock(QWidget):
    """Groups of objects, with a tick each."""

    def __init__(self, state, parent=None):
        super().__init__(parent)
        self.state = state
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["On", "Group", "Objects"])
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setShowGrid(False)
        self.tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        h = self.tbl.horizontalHeader()
        h.setSectionResizeMode(0, QHeaderView.Fixed)
        h.setSectionResizeMode(1, QHeaderView.Stretch)
        h.setSectionResizeMode(2, QHeaderView.Fixed)
        self.tbl.setColumnWidth(0, 34)
        self.tbl.setColumnWidth(2, 70)
        lay.addWidget(self.tbl, 1)

        row = QHBoxLayout()
        self.b_new = QPushButton("New")
        self.b_ren = QPushButton("Rename")
        self.b_del = QPushButton("Remove")
        for b in (self.b_new, self.b_ren, self.b_del):
            row.addWidget(b)
        lay.addLayout(row)
        row2 = QHBoxLayout()
        self.b_add = QPushButton("Add selection")
        self.b_out = QPushButton("Take out")
        self.b_all = QPushButton("Show all")
        for b in (self.b_add, self.b_out, self.b_all):
            row2.addWidget(b)
        lay.addLayout(row2)
        self.lbl = QLabel("")
        self.lbl.setWordWrap(True)
        lay.addWidget(self.lbl)
        lay.addWidget(Hint("A group switched off is hidden everywhere: the drawing, the exports "
                           "(DXF, LandXML, GIS, KML, reports) and surfaces built after it.  "
                           "The same object can be in several groups; a hidden object can still be "
                           "picked, so it can be put back."))

        self.tbl.cellClicked.connect(self._clicked)
        self.tbl.cellDoubleClicked.connect(lambda r, c: self.rename())
        self.b_new.clicked.connect(self.new_group)
        self.b_ren.clicked.connect(self.rename)
        self.b_del.clicked.connect(self.remove)
        self.b_add.clicked.connect(self.add_selection)
        self.b_out.clicked.connect(self.take_out)
        self.b_all.clicked.connect(self.show_all)
        self.tbl.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl.customContextMenuRequested.connect(self._menu)
        state.changed.connect(lambda k: self.refresh())
        state.selection_changed.connect(self._selection_changed)
        state.project_replaced.connect(self.refresh)
        self.refresh()

    # ------------------------------------------------------------------ data
    @property
    def groups(self) -> GroupSet:
        return self.state.project.groups

    def _selected_name(self) -> str | None:
        r = self.tbl.currentRow()
        if 0 <= r < len(self.groups.groups):
            return self.groups.groups[r].name
        return None

    def _selection_ids(self) -> set:
        st = self.state
        return set(st.sel_points) | set(st.sel_entities)

    def _selection_changed(self):
        n = len(self._selection_ids())
        self.b_add.setEnabled(n > 0 and self._selected_name() is not None)
        self.b_out.setEnabled(n > 0 and self._selected_name() is not None)
        self.lbl.setText(f"{n} object(s) selected." if n else "")

    # ------------------------------------------------------------------ view
    def refresh(self):
        pr = self.state.project
        hidden = pr.hidden_ids()
        self.tbl.blockSignals(True)
        self.tbl.setRowCount(len(self.groups.groups))
        for r, g in enumerate(self.groups.groups):
            it = QTableWidgetItem("")
            it.setCheckState(Qt.Checked if g.visible else Qt.Unchecked)
            it.setToolTip("Tick on to show this group; clear to hide its objects everywhere.")
            self.tbl.setItem(r, 0, it)
            name = QTableWidgetItem(g.name)
            missing = [i for i in g.oids if i not in pr.points and i not in pr.entities and i not in pr.surfaces]
            if missing:
                name.setToolTip(f"{len(missing)} object(s) in this group are no longer in the project.")
                name.setForeground(QColor(200, 160, 100))
            self.tbl.setItem(r, 1, name)
            cnt = QTableWidgetItem(str(g.count))
            cnt.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if g.count == 0:
                cnt.setToolTip("Empty - select objects in the drawing, then Add selection.")
            self.tbl.setItem(r, 2, cnt)
        self.tbl.blockSignals(False)
        self._selection_changed()
        self._surface_note()

    def _surface_note(self):
        """Say when a switched-off group is feeding a surface that already exists."""
        pr = self.state.project
        hidden = pr.hidden_ids()
        if not hidden or not pr.surfaces:
            return
        stale = [s.name for s in pr.surfaces.values()
                 if s.id not in hidden and (s.report or {}).get("sig")]
        if stale:
            self.lbl.setText(self.lbl.text() + f"  Surfaces {', '.join(stale[:3])} were built before this "
                                               f"group was switched off - rebuild them to take it out.")

    def _clicked(self, row: int, col: int):
        if col != 0:
            return
        g = self.groups.groups[row]
        self._set_visible(g.name, not g.visible)

    def _menu(self, pos):
        r = self.tbl.rowAt(pos.y())
        if r < 0:
            return
        self.tbl.selectRow(r)
        m = QMenu(self)
        m.addAction("Rename...", self.rename)
        m.addAction("Switch on" if not self.groups.groups[r].visible else "Switch off",
                    lambda: self._set_visible(self.groups.groups[r].name,
                                              not self.groups.groups[r].visible))
        m.addSeparator()
        m.addAction("Add selection", self.add_selection)
        m.addAction("Take selection out", self.take_out)
        m.addSeparator()
        m.addAction("Select this group's objects", lambda: self.select_group(self.groups.groups[r].name))
        m.addAction("Remove group", self.remove)
        m.exec(self.tbl.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ edit operations
    def _edit(self, label: str, fn):
        """Run a group change inside an undo step, so Ctrl+Z puts a group back."""
        try:
            with self.state.edit(label):
                fn()
        except (ValueError, KeyError) as ex:
            error_box(self, "Groups", str(ex))
            return
        self.state.project.touch()
        self.state.refresh({"all"})
        self.refresh()

    def new_group(self):
        ids = self._selection_ids()
        hint = f"{len(ids)} selected object(s) will go in it." if ids else "It will start empty."
        name, ok = QInputDialog.getText(self, "New Group", f"Name for the new group?\n\n{hint}")
        if not ok or not name.strip():
            return
        self._edit(f"New group '{name.strip()}'",
                   lambda: self.groups.create(name, sorted(ids)))

    def rename(self):
        old = self._selected_name()
        if old is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Group", "New name:", text=old)
        if not ok or not name.strip() or name.strip() == old:
            return
        self._edit(f"Rename group to '{name.strip()}'", lambda: self.groups.rename(old, name))

    def remove(self):
        name = self._selected_name()
        if name is None:
            return
        g = self.groups.get(name)
        n = g.count if g else 0
        msg = (f"Remove the group '{name}'?\n\nThe {n} object(s) in it are not deleted - only the "
               f"group goes." if n else f"Remove the empty group '{name}'?")
        if QMessageBox.question(self, "Remove Group", msg) != QMessageBox.Yes:
            return
        self._edit(f"Remove group '{name}'", lambda: self.groups.remove(name))

    def add_selection(self):
        name = self._selected_name()
        ids = self._selection_ids()
        if name is None or not ids:
            return
        self._edit(f"Add selection to '{name}'", lambda: self.groups.add(name, sorted(ids)))

    def take_out(self):
        name = self._selected_name()
        ids = self._selection_ids()
        if name is None or not ids:
            return
        self._edit(f"Take selection out of '{name}'", lambda: self.groups.discard(name, sorted(ids)))

    def show_all(self):
        if not self.groups.groups:
            return
        self._edit("Show all groups", self.groups.show_all)

    def _set_visible(self, name: str, on: bool):
        self._edit(f"{'Show' if on else 'Hide'} group '{name}'",
                   lambda: self.groups.set_visible(name, on))

    def select_group(self, name: str):
        g = self.groups.get(name)
        if g is None:
            return
        pr = self.state.project
        pts = [i for i in g.oids if i in pr.points]
        ents = [i for i in g.oids if i in pr.entities]
        self.state.select(points=pts, entities=ents)
        self.state.log(f"Selected {len(pts)} point(s) and {len(ents)} object(s) in group '{name}'.", "info")


__all__ = ["GroupsDock"]
