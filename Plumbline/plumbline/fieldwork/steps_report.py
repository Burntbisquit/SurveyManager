# steps_report.py — Workflow steps engine + report file builder (HTML/PDF + CSV)
"""
Steps in required order:

  1. Fix All Description Errors      (DescFlag: UnknownCode, OrphanCommand, etc. — flagged only)
  2. Fix Duplicate Errors            (ExactDuplicate, SimilarNumber, CloseNE)
  3. Fix Line Code Errors            (LineRepair: START/END/PC/PT validation)
  4. Master Check                    (Global Renumber vs master, merge/remove/renumber, master protection)
  5. Final Export / Google Earth     (KML draft + final _VALID.csv)

Report is live in Steps tab + exportable as REPORT.csv + STEPS_REPORT.html (PDF via print).
Master protection: all point numbers already in master file are protected — new data cannot overwrite.
Renumber single/range validated against: current file used numbers + master + Dup_Renumber + Global_Renumber.
"""

import csv, datetime
from pathlib import Path

# Step definitions
STEPS = [
    {"id": 1, "key": "desc", "title": "1. Fix All Description Errors", "desc": "Flagged-only: UnknownCode, OrphanCommand, MisplacedAfterSeparator, LineOrderError, EmptyDescription. Use Clean First / Clean Auto. All must be Corrected / Ignored / Removed before next step."},
    {"id": 2, "key": "duplicate", "title": "2. Fix Duplicate Errors", "desc": "ExactDuplicate, SimilarNumber, CloseNE (NE≤0.1, EL≤0.1). Merge (keep smallest OID), Remove, or Renumber. Renumber single/range offered here."},
    {"id": 3, "key": "line", "title": "3. Fix Line Code Errors", "desc": "Line Repair tab: each line needs START and END/CLOSE, curves PC→PT, reuse after END allowed, field ties ascending. Fix per segment."},
    {"id": 4, "key": "master", "title": "4. Check Against Master — Duplicate Points, Merge / Remove / Renumber", "desc": "Global Renumber vs master file CSV — master points are PROTECTED (cannot be overwritten). New conflicts must renumber single or range. Also checks duplicate points already merged/removed."},
    {"id": 5, "key": "export", "title": "5. Final Export & Google Earth", "desc": "Final Error Report → _VALID.csv + KML (Texas State Plane → WGS84, with/without surface factor). Choose EPSG and factor in Coordinate Settings."},
]

def _master_protected_set(master_file_path):
    try:
        from .config import read_master_ptnums
        return read_master_ptnums(master_file_path) if master_file_path else set()
    except:
        return set()

def _collect_used_numbers(working_rows, desc_rows=None, check_rows=None, master_set=None, extra_used=None):
    """Union of current file PtNums + master + dup/global renumbered + external."""
    used = set()
    # Current
    try:
        for r in working_rows or []:
            pt = str(r[1]).strip() if len(r)>1 else ""
            # numeric core only? keep int parse
            import re
            m = re.search(r'-?\d+', pt)
            if m:
                try:
                    used.add(int(m.group(0)))
                except: pass
    except: pass
    if master_set:
        used.update(master_set)
    if extra_used:
        used.update(extra_used)
    # From Desc/Dup tables? Already in working_rows
    return used

def compute_steps_status(main_window):
    """
    Returns list of dicts per step: {id, title, total, open, fixed, pct, status_str, detail}
    Reads live from main_window tables/rows.
    """
    out = []
    # Helpers to count status
    def count_rows(all_rows):
        total = len(all_rows) if all_rows else 0
        open_cnt = 0
        fixed_cnt = 0
        for ur in (all_rows or []):
            # unified rows: [gid, display, issue, oid, flags, detail, flagdetail, status, comments]
            status = str(ur[7]).strip() if len(ur)>7 else "Open"
            if status == "Open":
                open_cnt += 1
            else:
                fixed_cnt += 1
        pct = int(fixed_cnt * 100 / total) if total else 100
        state = "Complete" if total==0 or open_cnt==0 else ("In Progress" if fixed_cnt>0 else "Not Started")
        return total, open_cnt, fixed_cnt, pct, state

    # Step 1: Description
    desc_rows = getattr(main_window, "_desc_parse_all_rows", []) or []
    # Also check edit table? desc_parse_all_rows is unified desc flagged only
    total1, open1, fixed1, pct1, state1 = count_rows(desc_rows)
    detail1 = f"{fixed1}/{total1} fixed, {open1} Open"
    # If no desc rows at all, it's complete (or Not Started if checks never run)
    if total1==0:
        # Check if checks have been run at all
        has_checks = bool(getattr(main_window, "check_report_path", "")) or bool(desc_rows) or bool(getattr(main_window, "_check_all_rows", []))
        if not has_checks:
            state1 = "Not Started"; detail1 = "Run Checks (Consolidated + Field Book) to populate"
        else:
            state1 = "Complete"; detail1 = "No flagged description errors"
    out.append({"id":1, "key":"desc", "title": STEPS[0]["title"], "desc": STEPS[0]["desc"], "total": total1, "open": open1, "fixed": fixed1, "pct": pct1, "status": state1, "detail": detail1})

    # Step 2: Duplicate
    dup_rows = getattr(main_window, "_check_all_rows", []) or []
    total2, open2, fixed2, pct2, state2 = count_rows(dup_rows)
    detail2 = f"{fixed2}/{total2} fixed, {open2} Open"
    if total2==0:
        has_checks = bool(getattr(main_window, "check_report_path", "")) or bool(dup_rows)
        if not has_checks:
            state2 = "Not Started"; detail2 = "Run Checks to populate"
        else:
            state2 = "Complete"; detail2 = "No duplicate groups"
    out.append({"id":2, "key":"duplicate", "title": STEPS[1]["title"], "desc": STEPS[1]["desc"], "total": total2, "open": open2, "fixed": fixed2, "pct": pct2, "status": state2, "detail": detail2})

    # Step 3: Line
    line_rows = getattr(main_window, "_line_all_rows", []) or []
    # line rows dict or list
    total3 = len(line_rows) if line_rows else 0
    # line status stored in table status col 7; count from table if possible
    open3 = fixed3 = 0
    try:
        if hasattr(main_window, "line_table") and main_window.line_table:
            for r in range(main_window.line_table.rowCount()):
                it = main_window.line_table.item(r, 7)
                status = it.text().strip() if it else "Open"
                if status == "Open":
                    open3+=1
                else:
                    fixed3+=1
            total3 = open3+fixed3 if (open3+fixed3)>0 else total3
        else:
            # fallback: count from line_rows if they have status
            for lr in line_rows:
                if isinstance(lr, dict):
                    s = lr.get("status","Open")
                else:
                    s = str(lr[7]).strip() if len(lr)>7 else "Open"
                if s=="Open": open3+=1
                else: fixed3+=1
    except: pass
    pct3 = int(fixed3*100/total3) if total3 else 100
    if total3==0:
        has_line_checks = bool(line_rows) or (hasattr(main_window,"line_table") and main_window.line_table and main_window.line_table.rowCount()>0)
        if not has_line_checks:
            # If no line data, consider Not Started or Complete? If no line-flagged, it's complete
            # Check if line repair tab has any rows; if none, maybe not needed
            state3 = "Complete"; detail3 = "No line code errors"
        else:
            state3 = "Complete"; detail3 = "No line code errors"
    else:
        state3 = "Complete" if open3==0 else ("In Progress" if fixed3>0 else "Not Started")
        detail3 = f"{fixed3}/{total3} fixed, {open3} Open"
    out.append({"id":3, "key":"line", "title": STEPS[2]["title"], "desc": STEPS[2]["desc"], "total": total3, "open": open3, "fixed": fixed3, "pct": pct3, "status": state3, "detail": detail3})

    # Step 4: Master — check global vs master conflicts
    master_path = getattr(main_window, "master_file_path", "") or ""
    master_set = _master_protected_set(master_path)
    total4 = len(master_set) if master_path and Path(master_path).exists() else 0
    # Count conflicts: duplicate points that are in master and also in current file with same PtNum but different coords? Simplified: count of _check_all_rows where PtNum in master
    conflict_cnt = 0
    global_rows = []
    try:
        # Try to collect current PtNums that collide with master
        working_rows = []
        if hasattr(main_window, "edit_table") and main_window.edit_table:
            for r in range(main_window.edit_table.rowCount()):
                pt_it = main_window.edit_table.item(r,1)
                if pt_it:
                    try:
                        pt_int = int(pt_it.text().strip().split()[0])
                        if pt_int in master_set:
                            conflict_cnt+=1
                    except: pass
        # Also global renumber table if exists
        if hasattr(main_window, "global_table") and main_window.global_table:
            for r in range(main_window.global_table.rowCount()):
                pass
    except: pass
    # Master step status: if no master file set, Not Started; if master set and no conflicts, Complete
    if not master_path or not Path(master_path).exists():
        state4 = "Not Started"; detail4 = "No master file set — set in Project Paths (all master points will be protected)"
        pct4 = 0
    else:
        if conflict_cnt==0:
            state4 = "Complete"; detail4 = f"Master {Path(master_path).name}: {len(master_set)} points protected, 0 conflicts"
            pct4 = 100
        else:
            state4 = "In Progress"; detail4 = f"{conflict_cnt} new points conflict with master — renumber single/range required"
            pct4 = 50
        total4 = conflict_cnt if conflict_cnt else len(master_set)
        open4 = conflict_cnt
        fixed4 = 0 if conflict_cnt else len(master_set)
        # keep totals consistent
        out.append({"id":4, "key":"master", "title": STEPS[3]["title"], "desc": STEPS[3]["desc"], "total": total4 if total4 else 1, "open": open4, "fixed": fixed4 if conflict_cnt==0 else 0, "pct": pct4, "status": state4, "detail": detail4})
        # else we already appended? Need to handle duplicate append
        # We already appended for first three, so for master we need to append once — handle above
        return out  # early return to avoid double append below

    # If master not set, still append step 4 entry
    out.append({"id":4, "key":"master", "title": STEPS[3]["title"], "desc": STEPS[3]["desc"], "total": total4 if total4 else 1, "open": conflict_cnt if 'conflict_cnt' in locals() else 0, "fixed": 0, "pct": pct4 if 'pct4' in locals() else 0, "status": state4, "detail": detail4})

    # Step 5: Export
    # Check final report exists and Google Earth settings
    final_rows = 0
    try:
        if hasattr(main_window, "final_report_table") and main_window.final_report_table:
            final_rows = main_window.final_report_table.rowCount()
    except: pass
    has_final = final_rows>0
    has_kml = False
    try:
        # Check if KML was exported (look for .kml in project dir)
        proj = getattr(main_window, "project_path", "") or ""
        if proj and Path(proj).exists():
            # project_path may be a folder or file? In our app it's folder for fieldwork? Let's check current_file
            # Search for recent kml
            has_kml = any(Path(proj).glob("*.kml")) if Path(proj).is_dir() else False
        if not has_kml:
            cur = getattr(main_window, "current_file", "") or ""
            if cur:
                has_kml = any(Path(cur).parent.glob("*.kml"))
    except: pass
    total5 = 2
    fixed5 = (1 if has_final else 0) + (1 if has_kml else 0)
    open5 = total5 - fixed5
    pct5 = int(fixed5*100/total5)
    if fixed5==total5:
        state5="Complete"; detail5 = f"Final Error Report {final_rows} rows + KML exported"
    elif fixed5>0:
        state5="In Progress"; detail5 = f"{'Final Report done' if has_final else 'Final Report pending'}; {'KML done' if has_kml else 'KML pending'}"
    else:
        state5="Not Started"; detail5 = "Generate Final Error Report → _VALID.csv and Export KML/KMZ (choose 2011 EPSG + TXDOT SAF top-layer from origin 0,0 in Coordinate Settings — clampToGround)"
    out.append({"id":5, "key":"export", "title": STEPS[4]["title"], "desc": STEPS[4]["desc"], "total": total5, "open": open5, "fixed": fixed5, "pct": pct5, "status": state5, "detail": detail5})

    return out

def build_report_rows(main_window):
    """Flat rows for CSV: step, title, total, fixed, open, pct, status, detail"""
    steps = compute_steps_status(main_window)
    rows = []
    for s in steps:
        rows.append([s["id"], s["title"], s["total"], s["fixed"], s["open"], s["pct"], s["status"], s["detail"]])
    return steps, rows

# Exporters

def write_steps_csv(dest: Path, main_window):
    try:
        steps, rows = build_report_rows(main_window)
        with open(dest, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["Step", "Title", "Total", "Fixed", "Open", "Pct", "Status", "Detail"])
            w.writerows(rows)
            # Also write timestamp and project
            w.writerow([])
            w.writerow(["Generated", datetime.datetime.now().isoformat()])
            w.writerow(["Project", getattr(main_window, "current_file", "") or getattr(main_window, "project_path","")])
            w.writerow(["Master", getattr(main_window, "master_file_path","")])
        return True
    except Exception as e:
        print(f"write_steps_csv failed {dest}: {e}")
        return False

def write_steps_html(dest: Path, main_window, title="Steps Report — Fieldwork Manager"):
    try:
        steps, rows = build_report_rows(main_window)
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        proj = getattr(main_window, "current_file", "") or getattr(main_window, "project_path", "") or "(unsaved)"
        master = getattr(main_window, "master_file_path", "") or "(none)"
        # Build HTML with inline CSS (preview-friendly)
        html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>{title}</title>
<style>
 body{{font-family: Segoe UI, Arial, sans-serif; margin:24px; color:#222}}
 h1{{font-size:22px; margin:0 0 8px}}
 .meta{{color:#555; font-size:12px; margin-bottom:16px}}
 table{{border-collapse:collapse; width:100%; margin-top:12px}}
 th{{background:#1a237e; color:#fff; padding:8px 10px; text-align:left; font-size:13px}}
 td{{padding:8px 10px; border-bottom:1px solid #ddd; font-size:13px; vertical-align:top}}
 tr:nth-child(even) td{{background:#f5f7ff}}
 .badge{{display:inline-block; padding:2px 8px; border-radius:10px; font-size:11px; font-weight:700; color:#fff}}
 .Complete{{background:#2e7d32}} .In{{background:#ef6c00}} .Not{{background:#6d6d6d}}
 .bar{{height:8px; background:#e0e0e0; border-radius:4px; overflow:hidden; width:120px; display:inline-block; vertical-align:middle; margin-left:8px}}
 .fill{{height:100%; background:#1a237e}}
 .small{{font-size:11px; color:#444}}
 .foot{{margin-top:18px; font-size:11px; color:#666}}
</style></head><body>
<h1>{title}</h1>
<div class="meta">Project: {proj} &nbsp;|&nbsp; Master (protected): {master} &nbsp;|&nbsp; Generated: {now}</div>
<p class="small">Order: Fix All Description → Duplicate → Line → Master (Merge/Remove/Renumber, master protected) → Final Export &amp; Google Earth (2011 Texas State Plane + TXDOT SAF top-layer (from origin 0,0)). Master points cannot be overwritten; new conflicts must renumber single/range.</p>
<table><tr><th>Step</th><th>Status</th><th>Progress</th><th>Detail</th></tr>
"""
        for s in steps:
            status = s["status"]
            cls = "Complete" if status=="Complete" else ("In" if "Progress" in status else "Not")
            pct = s["pct"]
            html += f"""<tr><td><b>{s['title']}</b><div class="small">{s['desc']}</div></td>
<td><span class="badge {cls}">{status}</span></td>
<td>{s['fixed']}/{s['total']} <div class="bar"><div class="fill" style="width:{pct}%"></div></div> {pct}%</td>
<td>{s['detail']}</td></tr>
"""
        html += f"""</table>
<div class="foot">Fieldwork Manager — Steps report. Re-run Checks before final export. Master protected set = all point numbers in master file. Renumber single/range validated against current + master + renumbered. Export _VALID.csv via Final Error Report → Save _VALID.csv. KML via Coordinate Settings.</div>
</body></html>"""
        dest.write_text(html, encoding="utf-8")
        return True
    except Exception as e:
        print(f"write_steps_html failed {dest}: {e}")
        import traceback; traceback.print_exc()
        return False

# For printing to PDF, user can Print from HTML in browser; we also note PDF placeholder.

