# renumber_tool.py — Single-point and Range renumber dialogs with master protection
"""
Master protection rule (selected: all master points protected):
  - Any PtNum already in master file CSV cannot be used for new data.
  - Conflicts force renumber of new data (single or range).
  - Validated against: current working file used PtNums + master_set + Dup_Renumber + Global_Renumber + external Carlson ranges.

Offers:
  - Single: pick OID/old PtNum → enter new number → validates hole / available / protected.
  - Range: pick start-end (e.g., 1000-1100) → map to new start (e.g., 5000) → validates contiguous block free.
"""

import re
from pathlib import Path
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLabel, QLineEdit, QPushButton,
    QMessageBox, QTableWidget, QTableWidgetItem, QHeaderView, QGroupBox, QSpinBox, QComboBox
)
from PySide6.QtCore import Qt

try:
    from .config import read_master_ptnums, CONTROL_RANGE, BOUNDARY_RANGE, GENERAL_START, crew_blocks
except:
    read_master_ptnums = lambda x: set()
    CONTROL_RANGE = (1,999); BOUNDARY_RANGE=(1000,9999); GENERAL_START=10000
    def crew_blocks(c): return []

def _parse_int(s):
    try:
        return int(str(s).strip())
    except:
        return None

def _collect_used(main_window):
    used = set()
    # Working file edit_table
    try:
        if main_window and hasattr(main_window, "edit_table") and main_window.edit_table:
            for r in range(main_window.edit_table.rowCount()):
                it = main_window.edit_table.item(r, 1)
                if it:
                    txt = it.text().strip()
                    m = re.search(r'-?\d+', txt)
                    if m:
                        try:
                            used.add(int(m.group(0)))
                        except: pass
        # Also from check_all_rows? Already in edit
    except: pass
    # Add external Carlson used if present
    try:
        ext = getattr(main_window, "_external_used", set())
        if ext:
            used.update(ext)
    except: pass
    # Add dup/global renumbered numbers that are already assigned
    try:
        if main_window and hasattr(main_window, "edit_table") and main_window.edit_table and main_window.edit_table.columnCount()>12:
            for r in range(main_window.edit_table.rowCount()):
                for col in (12, 13):  # Dup_Renumber, Global_Renumber (if present; actual indices may vary)
                    if col < main_window.edit_table.columnCount():
                        it = main_window.edit_table.item(r, col)
                        if it and it.text().strip().isdigit():
                            used.add(int(it.text().strip()))
    except: pass
    # Add master protected set separately (caller merges)
    return used

def _master_set(main_window):
    try:
        mp = getattr(main_window, "master_file_path", "") or ""
        if mp:
            return read_master_ptnums(mp)
    except: pass
    return set()

def _is_protected(num: int, master_set: set):
    return num in master_set

def _validate_single(new_num: int, used: set, master_set: set, original_num: int = None):
    if new_num is None:
        return False, "Enter a numeric point number"
    if new_num <= 0:
        return False, "Point number must be >0"
    if original_num is not None and new_num == original_num:
        return False, "New number same as original — no change"
    if _is_protected(new_num, master_set):
        return False, f"{new_num} is PROTECTED (already in master file) — cannot overwrite, choose another"
    if new_num in used:
        # Check if it's the same point's own current number? Allow if it's own original and we are moving away? But new_num in used means conflict
        # If new_num equals original, we already handled; else conflict
        return False, f"{new_num} already used in current file — choose hole or next free"
    return True, "Available"

class SingleRenumberDialog(QDialog):
    """Pick a point (OID + old PtNum) and assign a new PtNum, with live validation against master."""
    def __init__(self, main_window, oid="", old_pt="", parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("Renumber Single Point — Master Protected")
        self.resize(520, 260)
        self.oid = oid
        self.old_pt = old_pt
        self.result_new = None
        lay = QVBoxLayout(self)

        # Master info
        mpath = getattr(main_window, "master_file_path", "") or "(no master set)"
        mset = _master_set(main_window)
        info = QLabel(f"Master: {Path(mpath).name if mpath!='(no master set)' else mpath} — {len(mset)} protected points. All master PtNums cannot be overwritten.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#1a237e; font-size:11px;")
        lay.addWidget(info)

        form = QFormLayout()
        self.oid_edit = QLineEdit(oid)
        self.oid_edit.setReadOnly(True)
        self.old_edit = QLineEdit(old_pt)
        self.old_edit.setReadOnly(True)
        self.new_edit = QLineEdit("")
        self.new_edit.setPlaceholderText("e.g., 315 or 10015 — must be free and not in master")
        form.addRow("OID:", self.oid_edit)
        form.addRow("Current PtNum:", self.old_edit)
        form.addRow("New PtNum*:", self.new_edit)
        lay.addLayout(form)

        # Suggestion row: hole / at-end
        sugg_row = QHBoxLayout()
        self.suggest_hole_btn = QPushButton("Suggest Hole")
        self.suggest_end_btn = QPushButton("Suggest At End")
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#555; font-size:11px;")
        sugg_row.addWidget(self.suggest_hole_btn)
        sugg_row.addWidget(self.suggest_end_btn)
        sugg_row.addStretch()
        lay.addLayout(sugg_row)
        lay.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        ok = QPushButton("Apply"); cancel = QPushButton("Cancel")
        btn_row.addWidget(cancel); btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)
        self.suggest_hole_btn.clicked.connect(self._suggest_hole)
        self.suggest_end_btn.clicked.connect(self._suggest_end)
        self.new_edit.textChanged.connect(self._validate_live)

        self._validate_live()

    def _validate_live(self):
        txt = self.new_edit.text().strip()
        n = _parse_int(txt) if txt else None
        used = _collect_used(self.main_window)
        mset = _master_set(self.main_window)
        # If editing same point, allow its own old number to be considered not conflicting for check? But new must differ
        # Remove original from used for check so that suggesting same number not flagged as conflict? Actually we want to flag same as invalid anyway
        # Keep used as is — but if new == old, we show same error
        if not txt:
            self.status_label.setText("Enter new number")
            self.status_label.setStyleSheet("color:#555")
            return
        if n is None:
            self.status_label.setText("Not a number")
            self.status_label.setStyleSheet("color:#c62828")
            return
        ok, msg = _validate_single(n, used, mset, _parse_int(self.old_pt))
        self.status_label.setText(msg)
        self.status_label.setStyleSheet("color:#2e7d32" if ok else "color:#c62828")

    def _suggest_hole(self):
        try:
            from .config import find_holes_in_ranges, parse_carlson_ranges
            used = _collect_used(self.main_window)
            mset = _master_set(self.main_window)
            used_all = used | mset
            # Use crew/type logic? For single, just find next gap in general
            # Try to parse old as int to decide block
            old_n = _parse_int(self.old_edit.text())
            # Find holes: iterate 1..100000 for first free not in used_all
            cand = None
            for n in range(1, 100000):
                if n not in used_all:
                    # Prefer same magnitude type? Check crew block? For now first hole
                    cand = n
                    break
            if cand is not None:
                self.new_edit.setText(str(cand))
        except Exception as e:
            QMessageBox.warning(self, "Suggest Hole", str(e))

    def _suggest_end(self):
        try:
            used = _collect_used(self.main_window)
            mset = _master_set(self.main_window)
            used_all = used | mset
            if not used_all:
                self.new_edit.setText("1")
                return
            nxt = max(used_all) + 1
            # Avoid protected? Already max+1 not in master
            self.new_edit.setText(str(nxt))
        except Exception as e:
            QMessageBox.warning(self, "Suggest At End", str(e))

    def _on_ok(self):
        txt = self.new_edit.text().strip()
        n = _parse_int(txt)
        used = _collect_used(self.main_window)
        mset = _master_set(self.main_window)
        ok, msg = _validate_single(n, used, mset, _parse_int(self.old_pt))
        if not ok:
            QMessageBox.warning(self, "Invalid", msg)
            return
        self.result_new = str(n)
        self.accept()

class RangeRenumberDialog(QDialog):
    """Map a contiguous old range [A-B] to new start C, validates entire block free and not protected."""
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("Renumber Range — Master Protected")
        self.resize(560, 320)
        self.result_mapping = None  # dict old->new or None
        lay = QVBoxLayout(self)

        mpath = getattr(main_window, "master_file_path", "") or "(no master set)"
        mset = _master_set(main_window)
        info = QLabel(f"Master: {Path(mpath).name if mpath!='(no master set)' else mpath} — {len(mset)} protected. Range must not overlap protected or used numbers.")
        info.setWordWrap(True)
        info.setStyleSheet("color:#1a237e; font-size:11px;")
        lay.addWidget(info)

        form = QFormLayout()
        self.start_edit = QLineEdit("")
        self.start_edit.setPlaceholderText("e.g., 1000")
        self.end_edit = QLineEdit("")
        self.end_edit.setPlaceholderText("e.g., 1100 (inclusive)")
        self.new_start_edit = QLineEdit("")
        self.new_start_edit.setPlaceholderText("e.g., 5000 — new start for range")
        form.addRow("Old Range Start:", self.start_edit)
        form.addRow("Old Range End:", self.end_edit)
        form.addRow("New Start*:", self.new_start_edit)
        lay.addLayout(form)

        # Preview table
        self.preview = QTableWidget(0, 3)
        self.preview.setHorizontalHeaderLabels(["Old PtNum", "New PtNum", "Status"])
        self.preview.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.preview.setMaximumHeight(160)
        lay.addWidget(self.preview)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color:#555; font-size:11px;")
        self.status_label.setWordWrap(True)
        lay.addWidget(self.status_label)

        btn_row = QHBoxLayout()
        self.validate_btn = QPushButton("Validate")
        self.suggest_btn = QPushButton("Suggest Next Free Block")
        btn_row.addWidget(self.validate_btn)
        btn_row.addWidget(self.suggest_btn)
        btn_row.addStretch()
        ok = QPushButton("Apply Range"); cancel = QPushButton("Cancel")
        btn_row.addWidget(cancel); btn_row.addWidget(ok)
        lay.addLayout(btn_row)

        self.validate_btn.clicked.connect(self._validate)
        self.suggest_btn.clicked.connect(self._suggest_block)
        ok.clicked.connect(self._on_ok)
        cancel.clicked.connect(self.reject)
        for w in (self.start_edit, self.end_edit, self.new_start_edit):
            w.textChanged.connect(self._validate)

    def _validate(self):
        s = _parse_int(self.start_edit.text())
        e = _parse_int(self.end_edit.text())
        ns = _parse_int(self.new_start_edit.text())
        if s is None or e is None or ns is None:
            self.status_label.setText("Enter all three numbers")
            self.preview.setRowCount(0)
            return
        if s > e:
            s, e = e, s
        count = e - s + 1
        if count > 5000:
            self.status_label.setText("Range too large (max 5000)")
            self.preview.setRowCount(0)
            return
        used = _collect_used(self.main_window)
        mset = _master_set(self.main_window)
        used_all = used | mset
        # Build mapping
        mapping = {}
        conflicts = []
        for i in range(count):
            old = s + i
            new = ns + i
            mapping[old] = new
            if _is_protected(new, mset):
                conflicts.append(f"{new} protected (master)")
            elif new in used:
                conflicts.append(f"{new} already used")
        # Preview first 20
        self.preview.setRowCount(min(count, 50))
        for i in range(min(count, 50)):
            old = s + i
            new = ns + i
            self.preview.setItem(i, 0, QTableWidgetItem(str(old)))
            self.preview.setItem(i, 1, QTableWidgetItem(str(new)))
            is_conf = (new in used_all)
            self.preview.setItem(i, 2, QTableWidgetItem("CONFLICT" if is_conf else "OK"))
            for c in range(3):
                it = self.preview.item(i, c)
                if it:
                    from PySide6.QtGui import QColor, QBrush
                    it.setBackground(QBrush(QColor("#FFCDD2" if is_conf else "#E8F5E9")))
        if conflicts:
            self.status_label.setText(f"Conflicts ({len(conflicts)}): " + ", ".join(conflicts[:5]) + (" …" if len(conflicts)>5 else "") + " — choose different New Start or use Suggest")
            self.status_label.setStyleSheet("color:#c62828; font-size:11px;")
        else:
            self.status_label.setText(f"Range {s}-{e} ({count} pts) → {ns}-{ns+count-1} — all free, validated against master ({len(mset)} protected) + current used ({len(used)})")
            self.status_label.setStyleSheet("color:#2e7d32; font-size:11px;")

    def _suggest_block(self):
        s = _parse_int(self.start_edit.text())
        e = _parse_int(self.end_edit.text())
        if s is None or e is None:
            QMessageBox.information(self, "Suggest", "Enter Old Range Start/End first")
            return
        if s > e: s,e = e,s
        count = e - s + 1
        used = _collect_used(self.main_window)
        mset = _master_set(self.main_window)
        used_all = used | mset
        # Find next free contiguous block of size count, starting after max(used_all)+1 or from GENERAL_START
        start_search = max(used_all) + 1 if used_all else GENERAL_START
        # Also try holes: scan from 10000 upward in steps
        cand = None
        for attempt in range(start_search, start_search+100000):
            block_ok = True
            for i in range(count):
                if (attempt+i) in used_all:
                    block_ok=False
                    break
            if block_ok:
                cand = attempt
                break
        if cand is not None:
            self.new_start_edit.setText(str(cand))
        else:
            QMessageBox.warning(self, "Suggest", "No free contiguous block found in next 100k")

    def _on_ok(self):
        s = _parse_int(self.start_edit.text())
        e = _parse_int(self.end_edit.text())
        ns = _parse_int(self.new_start_edit.text())
        if s is None or e is None or ns is None:
            QMessageBox.warning(self, "Invalid", "Enter all numbers")
            return
        if s > e: s,e = e,s
        count = e - s + 1
        used = _collect_used(self.main_window)
        mset = _master_set(self.main_window)
        for i in range(count):
            new = ns + i
            if _is_protected(new, mset):
                QMessageBox.warning(self, "Protected", f"{new} is in master — cannot use. Choose another block.")
                return
            if new in used:
                QMessageBox.warning(self, "Used", f"{new} already used in current file.")
                return
        # Build mapping dict
        mapping = {s+i: ns+i for i in range(count)}
        self.result_mapping = mapping
        self.accept()

# Helper to apply renumber to edit_table columns (Dup_Renumber / Global_Renumber)
# Callers should decide which column to write to; for Master step we write to Global_Renumber.

def apply_single_to_table(main_window, oid: str, new_pt: str, target_col_name="Dup_Renumber"):
    """Write single renumber into edit_table's target column (Dup_Renumber or Global_Renumber). Returns True."""
    try:
        # Find column index by header
        col_idx = -1
        if hasattr(main_window, "CORR_HEADERS"):
            try:
                col_idx = main_window.CORR_HEADERS.index(target_col_name)
            except:
                # Fallback: try Dup_Renumber col 12 etc
                pass
        # Fallback indices: Dup_Renumber=?? In ui_main CORR_HEADERS = [..., Dup_Renumber, Global_Renumber, Final_PtNum]
        # That list is 7 cols? Actually CORR_HEADERS = 7? Let's search
        if col_idx == -1:
            # Guess by counting: edit_table has 8 base + corr cols
            # Safer to find by header text in table
            if main_window.edit_table:
                for c in range(main_window.edit_table.columnCount()):
                    hdr = main_window.edit_table.horizontalHeaderItem(c)
                    if hdr and hdr.text().strip() == target_col_name:
                        col_idx = c
                        break
        if col_idx == -1:
            QMessageBox.warning(main_window, "Renumber", f"Column {target_col_name} not found")
            return False
        # Find row by OID col 0
        found = False
        for r in range(main_window.edit_table.rowCount()):
            it = main_window.edit_table.item(r, 0)
            if it and it.text().strip() == str(oid):
                item = main_window.edit_table.item(r, col_idx)
                if item is None:
                    from PySide6.QtWidgets import QTableWidgetItem
                    item = QTableWidgetItem(new_pt)
                    main_window.edit_table.setItem(r, col_idx, item)
                else:
                    item.setText(new_pt)
                # Visual cue
                try:
                    from PySide6.QtGui import QColor, QBrush
                    item.setBackground(QBrush(QColor("#E3F2FD")))
                except: pass
                found = True
                break
        if not found:
            QMessageBox.warning(main_window, "Renumber", f"OID {oid} not found in Consolidated table")
            return False
        # Mark dirty and autosave
        try:
            main_window.edit_dirty = True
            main_window._update_title()
            main_window._autosave_fwk()
        except: pass
        return True
    except Exception as ex:
        QMessageBox.warning(main_window, "Renumber", str(ex))
        return False

def apply_range_to_table(main_window, mapping: dict, target_col_name="Dup_Renumber"):
    """mapping old->new, apply to any rows where PtNum matches old. Returns count applied."""
    count = 0
    try:
        # Find col
        col_idx = -1
        if main_window.edit_table:
            for c in range(main_window.edit_table.columnCount()):
                hdr = main_window.edit_table.horizontalHeaderItem(c)
                if hdr and hdr.text().strip() == target_col_name:
                    col_idx = c
                    break
        if col_idx==-1:
            # try by CORR_HEADERS index
            try:
                col_idx = main_window.CORR_HEADERS.index(target_col_name) + (main_window.edit_table.columnCount() - len(main_window.CORR_HEADERS) ) # rough
            except:
                QMessageBox.warning(main_window, "Renumber", f"Column {target_col_name} not found")
                return 0
        # Range maps old PtNum -> new PtNum; apply to ALL rows sharing that old PtNum (handles duplicates)
        for old, new in mapping.items():
            old_s = str(old)
            for r in range(main_window.edit_table.rowCount()):
                pt_it = main_window.edit_table.item(r, 1)
                if pt_it and pt_it.text().strip() == old_s:
                    item = main_window.edit_table.item(r, col_idx)
                    if item is None:
                        from PySide6.QtWidgets import QTableWidgetItem
                        item = QTableWidgetItem(str(new))
                        main_window.edit_table.setItem(r, col_idx, item)
                    else:
                        item.setText(str(new))
                    try:
                        from PySide6.QtGui import QColor, QBrush
                        item.setBackground(QBrush(QColor("#E3F2FD")))
                    except: pass
                    count+=1
    except Exception as ex:
        print(f"apply_range failed {ex}")
    return count

