"""Reports and tables: one structured Report -> HTML (Qt-friendly) / CSV / XLSX (PDF is printed by the UI)."""
from __future__ import annotations

import csv
import datetime as _dt
import html
import math
import re
from dataclasses import dataclass, field

import numpy as np

from .. import __version__
from ..core import cogo
from ..core import geometry as G
from ..core import units as U


# ----------------------------------------------------------------------------- structure
@dataclass
class Table:
    title: str
    columns: list
    rows: list
    align: list | None = None                  # per column 'l' | 'r' | 'c'
    footer: list | None = None
    note: str = ""


@dataclass
class Section:
    heading: str = ""
    paragraphs: list = field(default_factory=list)
    kv: list = field(default_factory=list)      # [(label, value)]
    tables: list = field(default_factory=list)
    images: list = field(default_factory=list)  # [(caption, base64 png)]
    warnings: list = field(default_factory=list)


@dataclass
class Report:
    title: str
    subtitle: str = ""
    meta: list = field(default_factory=list)
    sections: list = field(default_factory=list)
    footer: str = ""


def fnum(v, d=3, na="") -> str:
    try:
        if v is None or (isinstance(v, float) and not math.isfinite(v)):
            return na
        return f"{v:,.{d}f}"
    except (TypeError, ValueError):
        return str(v)


def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y-%m-%d %H:%M")


def base_meta(project) -> list:
    c = project.crs
    meta = [("Project", project.name), ("Date", _stamp()),
            ("Coordinate system", f"{c.name} ({c.authority})"),
            ("Horizontal units", U.LABEL.get(project.h_unit, project.h_unit)),
            ("Vertical units / datum", f"{U.LABEL.get(project.v_unit, project.v_unit)}"
                                       + (f" / {c.vdatum}" if getattr(c, "vdatum", "") else ""))]
    if c.ground.enabled:
        where = "origin (0,0)" if c.ground.is_txdot_origin_scale else f"base N {c.ground.base_y:,.3f}, E {c.ground.base_x:,.3f}"
        meta.append(("SAF", f"{c.ground.saf:.8f} (ground / grid) from {where} - coordinates are GROUND values"))
    return meta


# ----------------------------------------------------------------------------- builders
def points_report(project, ids=None, title="Point List") -> Report:
    pts = [p for p in project.visible_points() if ids is None or p.id in ids]
    pts.sort(key=lambda p: (len(p.number), p.number))
    rows = [[p.number, fnum(p.y, 3), fnum(p.x, 3), fnum(p.z, 3), p.desc, p.layer] for p in pts]
    sec = Section("Points", tables=[Table(f"{len(pts):,} point(s)", ["Point", "Northing", "Easting", "Elevation", "Description", "Layer"],
                                          rows, ["l", "r", "r", "r", "l", "l"])])
    if pts:
        z = np.array([p.z for p in pts])
        z = z[np.isfinite(z)]
        if len(z):
            sec.kv = [("Elevation range", f"{z.min():,.3f} to {z.max():,.3f}"), ("Mean elevation", f"{z.mean():,.3f}")]
    return Report(title, meta=base_meta(project), sections=[sec])


def surface_report(project, surface) -> Report:
    tin = surface.tin()
    s = tin.summary()
    u = project.h_unit
    sec = Section("Surface summary")
    sec.kv = [("Name", surface.name), ("Points", f"{tin.n_points:,}"), ("Triangles", f"{tin.n_tris:,}"),
              ("2D area", f"{fnum(s['area2d'], 1)} sq {u}  ({fnum(U.area_to_acres(s['area2d'], u), 3)} acres)"),
              ("3D (surface) area", f"{fnum(s['area3d'], 1)} sq {u}"),
              ("Elevation min / max", f"{fnum(s['zmin'], 3)} / {fnum(s['zmax'], 3)}"),
              ("Slope mean (area-weighted) / max", f"{fnum(s['mean_slope_pct'], 2)}% / {fnum(s['max_slope_pct'], 2)}%"),
              ("Bounds", f"E {fnum(s['xmin'], 2)} to {fnum(s['xmax'], 2)};  N {fnum(s['ymin'], 2)} to {fnum(s['ymax'], 2)}")]
    rep = surface.report or {}
    if rep:
        sec.tables.append(Table("Build report", ["Item", "Value"], [[k.replace("_", " ").capitalize(), str(v)]
                                                                      for k, v in rep.items() if k != "warnings" and not isinstance(v, (list, dict))],
                                ["l", "l"]))
        sec.warnings = list(rep.get("warnings", []))
    # slope distribution
    sl = tin.slopes_pct()
    a = tin.areas2d()
    edges = [0, 2, 5, 10, 15, 25, 33, 50, 1e9]
    labels = ["0-2%", "2-5%", "5-10%", "10-15%", "15-25%", "25-33%", "33-50%", "> 50%"]
    rows = []
    tot = a.sum() or 1.0
    for lo, hi, lb in zip(edges[:-1], edges[1:], labels):
        m = (sl >= lo) & (sl < hi)
        rows.append([lb, fnum(a[m].sum(), 1), fnum(U.area_to_acres(a[m].sum(), u), 3), fnum(100 * a[m].sum() / tot, 1) + "%"])
    sec.tables.append(Table("Slope distribution (by plan area)", ["Slope", f"Area (sq {u})", "Acres", "Share"], rows, ["l", "r", "r", "r"]))
    return Report(f"Surface Report — {surface.name}", meta=base_meta(project), sections=[sec])


def volume_report(project, result, title="Earthwork Volume Report", description: list | None = None) -> Report:
    u = project.h_unit
    vu = project.v_unit
    cy = lambda v: U.volume_to_cubic_yards(v, u, vu)
    cm = lambda v: U.volume_to_cubic_meters(v, u, vu)
    rows = [
        ["Cut", fnum(result.cut, 1), fnum(cy(result.cut), 1), fnum(cm(result.cut), 1), fnum(result.area_cut, 1)],
        ["Fill", fnum(result.fill, 1), fnum(cy(result.fill), 1), fnum(cm(result.fill), 1), fnum(result.area_fill, 1)],
        ["Net (cut - fill)", fnum(result.net, 1), fnum(cy(result.net), 1), fnum(cm(result.net), 1), ""],
    ]
    sec = Section("Results")
    sec.paragraphs = list(description or [])
    sec.tables.append(Table("Volumes", ["", f"Cubic {u}", "Cubic yards", "Cubic metres", f"Area (sq {u})"],
                            rows, ["l", "r", "r", "r", "r"]))
    sec.kv = [("Method", result.method), ("Total area", f"{fnum(result.area_total, 1)} sq {u} ({fnum(U.area_to_acres(result.area_total, u), 3)} acres)"),
              ("Triangles evaluated", f"{result.n_tris:,}")]
    sec.paragraphs.append("Positive net = excess cut (export); negative net = shortage (import). Volumes are un-shrunk, "
                          "in-place (bank) quantities - apply swell/shrink factors separately.")
    return Report(title, meta=base_meta(project), sections=[sec])


def polyline_report(project, ids, title="Line & Curve Table") -> Report:
    sections = []
    n = 0
    for e in project.polylines():
        if ids is not None and e.id not in ids:
            continue
        n += 1
        v = e.verts
        m = len(v)
        segs = []
        total = 0.0
        last = m if e.closed else m - 1
        for i in range(last):
            j = (i + 1) % m
            b = float(e.bulges[i]) if e.bulges is not None else 0.0
            az, d = cogo.inverse(v[i, 0], v[i, 1], v[j, 0], v[j, 1])
            if abs(b) > 1e-12:
                arc = G.bulge_to_arc(v[i, 0], v[i, 1], v[j, 0], v[j, 1], b)
                cx, cy_, r, a0, th = arc
                L = abs(r * th)
                segs.append([f"{i + 1}", "Curve", f"R={fnum(r, 3)}", f"L={fnum(L, 3)}  Δ={cogo.format_azimuth(abs(math.degrees(th)), True, 0)}",
                             cogo.format_bearing(az), fnum(d, 3) + " (chord)", "left" if th > 0 else "right"])
                total += L
            else:
                segs.append([f"{i + 1}", "Line", "", "", cogo.format_bearing(az), fnum(d, 3), ""])
                total += d
        sec = Section(f"Polyline {e.id} - layer {e.layer}")
        sec.kv = [("Vertices", str(m)), ("Closed", "yes" if e.closed else "no"), ("Total length", f"{fnum(total, 3)} {project.h_unit}")]
        if e.closed and m >= 3:
            a = G.polygon_area(e.verts, e.bulges)
            sec.kv.append(("Area", f"{fnum(a, 2)} sq {project.h_unit} = {fnum(U.area_to_acres(a, project.h_unit), 4)} acres"))
        sec.tables.append(Table("Courses", ["#", "Type", "Radius", "Arc", "Bearing", "Distance", "Direction"], segs,
                                ["l", "l", "r", "l", "l", "r", "l"]))
        sec.tables.append(Table("Vertices", ["#", "Northing", "Easting", "Elevation"],
                                [[str(i + 1), fnum(r[1], 3), fnum(r[0], 3), fnum(r[2], 3)] for i, r in enumerate(v)],
                                ["l", "r", "r", "r"]))
        sections.append(sec)
        if n >= 200:
            break
    return Report(title, meta=base_meta(project), sections=sections)


def qa_report(project, issues) -> Report:
    rows = [[i.severity.upper(), i.kind, i.message, len(i.point_ids)] for i in issues]
    sec = Section("Findings", tables=[Table("Data quality checks", ["Level", "Check", "Finding", "Points"], rows, ["l", "l", "l", "r"])])
    for i in issues:
        if i.point_ids:
            nums = [project.points[p].number for p in i.point_ids[:40] if p in project.points]
            sec.paragraphs.append(f"{i.kind}: points {', '.join(nums)}" + (" ..." if len(i.point_ids) > 40 else ""))
    return Report("Data Quality Report", meta=base_meta(project), sections=[sec])


def _point_sort(number) -> tuple:
    """Point numbers the way a person reads them: 2 before 10, letters after numbers."""
    text = str(number)
    digits = text.replace(".", "", 1).isdigit()
    return (1 if digits else 0, float(text) if digits else 0.0, text)


def _blank(sec: Section, text: str):
    """A section with nothing in it says so in a sentence - an empty table reads as a mistake."""
    sec.paragraphs.append(text)


def point_audit_report(project, audit) -> Report:
    """The Point(s) Audit: the job's field points against the state they were imported in.

    One question, asked four ways - what is gone, what is new, what moved, what was edited - so
    the report answers "what has happened to this job since the field data landed".  The decision
    behind it (see :mod:`plumbline.core.audit`) is that the baseline is the *imported* state and
    not a mark of the user's own, so the same report says the same thing tomorrow.
    """
    u = project.h_unit
    label = U.LABEL.get(u, u)
    d = 3
    sections = []

    # ------------------------------------------------------------------ summary
    sec = Section("Summary")
    sec.paragraphs = ["Every point below is this job's field data, as it arrived, compared with what "
                      "the drawing holds now. Reference points - stake-out, control and other - are "
                      "not this job's field work and are not audited."]
    sec.warnings = list(audit.notes)
    if not audit.baseline:
        sec.paragraphs.append("This project has no imported state on record, so there is nothing to "
                              "compare against. The next import into this job starts the record.")
    else:
        sec.kv = [("Points in the job now", f"{audit.now:,} field point(s)"),
                  ("Imported points on record", f"{audit.baseline:,}"),
                  ("Unchanged since the import", f"{audit.unchanged:,}"),
                  ("Missing - imported and no longer here", f"{len(audit.missing):,}"),
                  ("Added - no import behind them", f"{len(audit.added):,}"),
                  ("Moved - northing or easting changed", f"{len(audit.moved):,}"),
                  ("Changed - description, number, layer or elevation", f"{len(audit.changed):,}"),
                  ("Distances in", label),
                  ("A point counts as moved beyond", f"{audit.tolerance:g} {label}")]
        sec.paragraphs.append(audit.summary_line())
    sections.append(sec)

    # ------------------------------------------------------------------ missing
    sec = Section("Missing - imported, no longer in the drawing")
    if not audit.baseline:
        _blank(sec, "Nothing to compare against.")
    elif not audit.missing:
        _blank(sec, "None. Every point that was imported is still here.")
    else:
        rows = [[r.get("number", ""), fnum(r.get("y"), d), fnum(r.get("x"), d),
                 fnum(r.get("z"), d, na="none"), r.get("desc", ""), r.get("file", "") or "-",
                 " ".join(x for x in (r.get("set", ""), r.get("when", "")[:10]) if x)]
                for r in sorted(audit.missing, key=lambda r: _point_sort(r.get("number", "")))]
        sec.tables.append(Table(f"{len(rows):,} point(s) imported and now gone",
                                ["Point", "Northing", "Easting", "Elevation", "Description",
                                 "Source file", "Imported"],
                                rows, ["l", "r", "r", "r", "l", "l", "l"]))
        sec.paragraphs.append("An imported point that is gone was either deleted by hand or never "
                              "drawn: a duplicate policy that skipped or renumbered it, an import "
                              "that landed on top of an existing number, or a point edited away "
                              "afterwards. The source column says which file to look in.")
    sections.append(sec)

    # ------------------------------------------------------------------ added
    sec = Section("Added - points with no import behind them")
    if not audit.baseline:
        _blank(sec, "Nothing to compare against.")
    elif not audit.added:
        _blank(sec, "None. Every field point in the drawing arrived by an import.")
    else:
        rows = [[r["number"], fnum(r["y"], d), fnum(r["x"], d), fnum(r["z"], d, na="none"),
                 r.get("desc", ""), r.get("layer", ""),
                 " ".join(x for x in (r.get("set", ""), r.get("file", "")) if x) or "drawn by hand"]
                for r in sorted(audit.added, key=lambda r: _point_sort(r["number"]))]
        sec.tables.append(Table(f"{len(rows):,} point(s) that no import brought in",
                                ["Point", "Northing", "Easting", "Elevation", "Description", "Layer",
                                 "Where from"],
                                rows, ["l", "r", "r", "r", "l", "l", "l"]))
        sec.paragraphs.append("Points the drawing gained after the import: set out by hand with the "
                              "point tool, added by a plugin or a script, or drawn while editing.")
    sections.append(sec)

    # ------------------------------------------------------------------ moved
    sec = Section("Moved - northing or easting changed since the import")
    if not audit.baseline:
        _blank(sec, "Nothing to compare against.")
    elif not audit.moved:
        _blank(sec, f"None. Every imported point is within {audit.tolerance:g} {label} of where it arrived.")
    else:
        rows = [[m["number"], fnum(m["dn"], d), fnum(m["de"], d),
                 (fnum(m["dz"], d) if m["dz"] is not None else "-"),
                 fnum(m["dist"], d), cogo.format_bearing(m["azimuth"]),
                 fnum(m["y"], d), fnum(m["x"], d), m.get("file", "") or "-"]
                for m in sorted(audit.moved, key=lambda m: _point_sort(m["number"]))]
        sec.tables.append(Table(f"{len(rows):,} point(s) moved",
                                ["Point", "ΔN", "ΔE", "ΔZ", "Distance", "Bearing",
                                 "Northing now", "Easting now", "Source file"],
                                rows, ["l", "r", "r", "r", "r", "l", "r", "r", "l"]))
        worst = max(audit.moved, key=lambda m: m["dist"])
        sec.kv = [("Largest move", f"{fnum(worst['dist'], d)} {label} (point {worst['number']})"),
                  ("Total movement", f"{fnum(sum(m['dist'] for m in audit.moved), d)} {label} "
                                     f"across {len(audit.moved):,} point(s)")]
        sec.paragraphs.append("ΔN and ΔE are positive when the point is now further north and further "
                              "east than it arrived. A transform, a similarity fit, a reprojection or "
                              "a grip drag all show up here.")
    sections.append(sec)

    # ------------------------------------------------------------------ changed
    sec = Section("Changed - description, number, layer or elevation")
    if not audit.baseline:
        _blank(sec, "Nothing to compare against.")
    elif not audit.changed:
        _blank(sec, "None. Every imported point still reads as it did when it arrived.")
    else:
        order = {"number": 0, "description": 1, "layer": 2, "elevation": 3}
        rows = []
        for c in sorted(audit.changed, key=lambda c: _point_sort(c["number"])):
            for kind in sorted(c["kinds"], key=lambda k: order.get(k, 9)):
                if kind == "number":
                    was, now = c["before_number"], c["number"]
                elif kind == "description":
                    was, now = (c["before_desc"] or "(none)"), (c["after_desc"] or "(none)")
                elif kind == "layer":
                    was, now = c["before_layer"], c["after_layer"]
                else:
                    was = fnum(c["z0"], d, na="none")
                    if c["z0"] is not None and c["z"] == c["z"]:
                        where = "above" if c["z"] > c["z0"] else "below"
                        now = f"{fnum(c['z'], d)}  ({fnum(abs(c['z'] - c['z0']), d)} {where})"
                    else:
                        now = fnum(c["z"], d, na="none")
                rows.append([c["number"], kind.capitalize(), was, now, c.get("file", "") or "-"])
        sec.tables.append(Table(f"{len(rows):,} change(s) on {len(audit.changed):,} point(s)",
                                ["Point", "What changed", "Was", "Now", "Source file"],
                                rows, ["l", "l", "l", "l", "l"]))
        sec.paragraphs.append("A point can appear in both this section and the one above it - a point "
                              "can be moved and re-described. An elevation shown as '(none)' means the "
                              "point carries no elevation at all, which is a change of its own when it "
                              "arrived with one.")
    sections.append(sec)

    return Report("Point(s) Audit", meta=base_meta(project), sections=sections)

def crs_report(project, datum_note: str = "") -> Report:
    from ..core import crs as C
    c = project.crs
    sec = Section("Project coordinate system")
    d = C.describe_crs(c.authority) if c.authority else {}
    sec.kv = [("Name", c.name), ("Identifier", c.authority), ("Type", d.get("type", "")), ("Projection", d.get("projection", "")),
              ("Datum", d.get("datum", "")), ("Ellipsoid", d.get("ellipsoid", "")), ("Area of use", d.get("area", "")),
              ("Horizontal unit", f"{c.unit} (1 {c.unit} = {c.unit_factor:.10f} m)"), ("Vertical", f"{c.vunit} {c.vdatum}"),
              ("Datum transformation", c.strategy + (f" - {datum_note}" if datum_note else ""))]
    ext = project.extents()
    if ext:
        cx, cy = (ext[0] + ext[2]) / 2, (ext[1] + ext[3]) / 2
        try:
            lon, lat = c.to_lonlat(cx, cy)
            sec.kv.append(("Centre of data (lon, lat)", f"{lon:.8f}, {lat:.8f}"))
            sec.kv.append(("Grid convergence at centre", f"{c.convergence_at(cx, cy):.5f}°"))
            f = C.combined_factor(c.authority, lon, lat, 0.0)
            sec.kv.append(("Grid scale factor at centre", f"{f['grid_factor']:.8f}"))
        except Exception:
            pass
    if c.ground.enabled:
        where = "origin (0,0)" if c.ground.is_txdot_origin_scale else f"base N {c.ground.base_y:,.3f} E {c.ground.base_x:,.3f}"
        sec.kv.append(("SAF (ground / grid)", f"{c.ground.saf:.8f} from {where}"))
        sec.kv.append(("Equivalent combined factor", f"{c.ground.factor:.8f} (grid / ground)"))
    return Report("Coordinate System Report", meta=base_meta(project), sections=[sec])


# ----------------------------------------------------------------------------- renderers
_CSS = ("body{font-family:'DejaVu Sans',Arial,sans-serif;font-size:9pt;color:#222;}"
        "h1{font-size:17pt;color:#12324f;margin-bottom:0;}h2{font-size:12pt;color:#12324f;margin-top:14px;}"
        "h3{font-size:10pt;color:#333;margin-bottom:2px;}.sub{color:#666;} .warn{color:#9a5b00;} "
        "td,th{font-size:8.5pt;}")


def to_html(rep: Report, thumbs_width: int = 220) -> str:
    e = html.escape
    out = [f"<html><head><meta charset='utf-8'><style>{_CSS}</style></head><body>",
           f"<h1>{e(rep.title)}</h1>"]
    if rep.subtitle:
        out.append(f"<p class='sub'>{e(rep.subtitle)}</p>")
    if rep.meta:
        out.append("<table cellspacing='0' cellpadding='2'>")
        for k, v in rep.meta:
            out.append(f"<tr><td><b>{e(k)}</b>&nbsp;&nbsp;</td><td>{e(str(v))}</td></tr>")
        out.append("</table>")
    for s in rep.sections:
        if s.heading:
            out.append(f"<h2>{e(s.heading)}</h2>")
        for p in s.paragraphs:
            out.append(f"<p>{e(p)}</p>")
        for w in s.warnings:
            out.append(f"<p class='warn'><b>Note:</b> {e(w)}</p>")
        if s.kv:
            out.append("<table cellspacing='0' cellpadding='3' width='100%'>")
            for i, (k, v) in enumerate(s.kv):
                bg = "#f3f6f9" if i % 2 == 0 else "#ffffff"
                out.append(f"<tr bgcolor='{bg}'><td width='42%'><b>{e(str(k))}</b></td><td>{e(str(v))}</td></tr>")
            out.append("</table>")
        for t in s.tables:
            if t.title:
                out.append(f"<h3>{e(t.title)}</h3>")
            out.append("<table cellspacing='0' cellpadding='3' width='100%' border='1' style='border-color:#c8d0d8;'>")
            out.append("<tr bgcolor='#dfe7ee'>" + "".join(f"<th align='left'>{e(str(c))}</th>" for c in t.columns) + "</tr>")
            al = {"l": "left", "r": "right", "c": "center"}
            for i, r in enumerate(t.rows):
                bg = "#ffffff" if i % 2 == 0 else "#f6f8fa"
                cells = []
                for j, v in enumerate(r):
                    a = al.get((t.align or [])[j] if t.align and j < len(t.align) else "l", "left")
                    sv = e(str(v))
                    if str(v) == "OVER":
                        sv = f"<b><font color='#b00020'>{sv}</font></b>"
                    cells.append(f"<td align='{a}'>{sv}</td>")
                out.append(f"<tr bgcolor='{bg}'>" + "".join(cells) + "</tr>")
            if t.footer:
                out.append("<tr bgcolor='#eef2f6'>" + "".join(f"<td><b>{e(str(v))}</b></td>" for v in t.footer) + "</tr>")
            out.append("</table>")
            if t.note:
                out.append(f"<p class='sub'>{e(t.note)}</p>")
        if s.images:
            out.append("<table cellspacing='6'><tr>")
            for i, (cap, b64) in enumerate(s.images):
                if i and i % 3 == 0:
                    out.append("</tr><tr>")
                out.append(f"<td align='center'><img src='data:image/png;base64,{b64}' width='{thumbs_width}'><br/>"
                           f"<span class='sub'>{e(cap)}</span></td>")
            out.append("</tr></table>")
    out.append(f"<p class='sub'><br/>{e(rep.footer)}<br/>Generated by Plumbline {__version__} on {_stamp()}.</p></body></html>")
    return "".join(out)


def to_csv(rep: Report, path) -> int:
    n = 0
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow([rep.title])
        for k, v in rep.meta:
            w.writerow([k, v])
        for s in rep.sections:
            w.writerow([])
            if s.heading:
                w.writerow([s.heading])
            for k, v in s.kv:
                w.writerow([k, v])
            for t in s.tables:
                w.writerow([])
                if t.title:
                    w.writerow([t.title])
                w.writerow(t.columns)
                for r in t.rows:
                    w.writerow(r)
                    n += 1
                if t.footer:
                    w.writerow(t.footer)
    return n


def to_xlsx(rep: Report, path) -> int:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    ws["A1"] = rep.title
    ws["A1"].font = Font(bold=True, size=14)
    r = 3
    for k, v in rep.meta:
        ws.cell(r, 1, k).font = Font(bold=True)
        ws.cell(r, 2, str(v))
        r += 1
    for s in rep.sections:
        if s.kv or s.paragraphs or s.warnings:
            r += 1
            if s.heading:
                ws.cell(r, 1, s.heading).font = Font(bold=True, size=12)
                r += 1
            for k, v in s.kv:
                ws.cell(r, 1, str(k)).font = Font(bold=True)
                ws.cell(r, 2, str(v))
                r += 1
            for p in s.paragraphs + [f"Note: {w}" for w in s.warnings]:
                ws.cell(r, 1, p)
                r += 1
    ws.column_dimensions["A"].width = 44
    ws.column_dimensions["B"].width = 70
    used = {"Summary"}
    n = 0
    hdr_fill = PatternFill("solid", fgColor="DFE7EE")
    for s in rep.sections:
        for t in s.tables:
            base = "".join(c for c in (t.title or s.heading or "Table") if c not in '[]:*?/\\')[:28] or "Table"
            name, k = base, 2
            while name in used:
                name = f"{base[:25]} {k}"
                k += 1
            used.add(name)
            w2 = wb.create_sheet(name)
            w2.append(list(t.columns))
            for c in range(1, len(t.columns) + 1):
                cell = w2.cell(1, c)
                cell.font = Font(bold=True)
                cell.fill = hdr_fill
            for row in t.rows:
                vals, fmts = [], []
                for ci, v in enumerate(row):
                    val, fmt = _xlsx_value(v, ci)
                    vals.append(val)
                    fmts.append(fmt)
                w2.append(vals)
                rr = w2.max_row
                for ci, fmt in enumerate(fmts, start=1):
                    if fmt:
                        w2.cell(rr, ci).number_format = fmt
                n += 1
            for c, col in enumerate(t.columns, start=1):
                width = max(len(str(col)), *(len(str(r[c - 1])) for r in t.rows[:200] if c - 1 < len(r))) if t.rows else len(str(col))
                w2.column_dimensions[get_column_letter(c)].width = min(max(width + 2, 8), 60)
            w2.freeze_panes = "A2"
    wb.save(path)
    return n


_DEC = re.compile(r"^-?[\d,]*\.(\d+)$")
_INT = re.compile(r"^-?[1-9]\d{0,14}$|^0$")


def _xlsx_value(v, col_index: int):
    """Turn formatted report strings back into real numbers (never the first/ID column, never zero-padded IDs)."""
    if not isinstance(v, str):
        return v, None
    t = v.strip().replace(",", "")
    if col_index > 0 or False:
        m = _DEC.match(v.strip()) if "," not in v or "." in v else None
        if m:
            try:
                return float(t), "#,##0." + "0" * len(m.group(1))
            except ValueError:
                pass
        if _INT.match(t) and "." not in t:
            return int(t), "0"
    return v, None
