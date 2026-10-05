"""KML / KMZ import and export (Google Earth checks).

Import returns lon/lat in x/y with batch.info["geographic"] = True and any GroundOverlays found.
Export writes survey geometry as WGS84 lon/lat; the datum strategy is chosen by the caller (see core.crs).
"""
from __future__ import annotations

import html
import io
import math
import re
import time
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from ..core import geometry as G
from ..core.model import ImportBatch, Polyline, SurveyPoint

NAN = math.nan


def _tag(e):
    return e.tag.rsplit("}", 1)[-1]


def _find(e, name):
    for c in e.iter():
        if _tag(c) == name:
            return c
    return None


def _coords(text: str):
    out = []
    for tok in (text or "").replace("\n", " ").split():
        p = tok.split(",")
        if len(p) >= 2:
            try:
                out.append((float(p[0]), float(p[1]), float(p[2]) if len(p) > 2 and p[2] != "" else NAN))
            except ValueError:
                pass
    return out


_TAGS = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(_TAGS.sub(" ", text))).strip()


def read_kml(path, cache_dir=None) -> ImportBatch:
    path = Path(path)
    batch = ImportBatch()
    batch.info["geographic"] = True
    batch.info["overlays"] = []
    zf = None
    if path.suffix.lower() == ".kmz":
        zf = zipfile.ZipFile(path)
        names = [n for n in zf.namelist() if n.lower().endswith(".kml")]
        if not names:
            raise ValueError("This KMZ does not contain a KML document.")
        main = "doc.kml" if "doc.kml" in names else names[0]
        root = ET.fromstring(zf.read(main))
    else:
        root = ET.parse(path).getroot()

    def walk(elem, folder=""):
        for ch in elem:
            t = _tag(ch)
            if t in ("Folder", "Document"):
                nm = next((_clean(c.text) for c in ch if _tag(c) == "name"), "")
                walk(ch, nm or folder)
            elif t == "Placemark":
                _placemark(ch, folder)
            elif t == "GroundOverlay":
                _overlay(ch)

    def _placemark(pm, folder):
        name = next((_clean(c.text) for c in pm if _tag(c) == "name"), "")
        desc = next((_clean(c.text) for c in pm if _tag(c) == "description"), "")
        attrs = {}
        ed = next((c for c in pm if _tag(c) == "ExtendedData"), None)
        if ed is not None:
            for d in ed.iter():
                if _tag(d) == "Data" and d.get("name"):
                    v = next((c.text for c in d if _tag(c) == "value"), "")
                    attrs[d.get("name")] = (v or "").strip()
                elif _tag(d) == "SimpleData" and d.get("name"):
                    attrs[d.get("name")] = (d.text or "").strip()
        layer = (folder or "KML")[:40]
        for g in pm.iter():
            gt = _tag(g)
            if gt == "Point":
                c = _coords(next((x.text for x in g.iter() if _tag(x) == "coordinates"), ""))
                if c:
                    batch.points.append(SurveyPoint(0, name or str(len(batch.points) + 1), c[0][0], c[0][1], c[0][2],
                                                    desc[:120], layer, attrs))
            elif gt == "LineString":
                c = _coords(next((x.text for x in g.iter() if _tag(x) == "coordinates"), ""))
                if len(c) >= 2:
                    batch.polylines.append(Polyline(0, layer, np.array(c), False, None, "line", None, None,
                                                    {"name": name, **attrs}))
            elif gt == "LinearRing":
                if g is pm:
                    continue
                c = _coords(next((x.text for x in g.iter() if _tag(x) == "coordinates"), ""))
                if len(c) >= 4:
                    batch.polylines.append(Polyline(0, layer, np.array(c[:-1]), True, None, "parcel", None, None,
                                                    {"name": name, **attrs}))

    def _overlay(go):
        href = None
        ic = next((c for c in go if _tag(c) == "Icon"), None)
        if ic is not None:
            href = next((c.text.strip() for c in ic if _tag(c) == "href" and c.text), None)
        box = next((c for c in go if _tag(c) == "LatLonBox"), None)
        if not href or box is None:
            return
        v = {_tag(c): float(c.text) for c in box if c.text and _tag(c) in ("north", "south", "east", "west", "rotation")}
        if not {"north", "south", "east", "west"} <= v.keys():
            return
        name = next((_clean(c.text) for c in go if _tag(c) == "name"), "Overlay")
        local = None
        if zf is not None and href in zf.namelist():
            d = Path(cache_dir or path.parent) / "kml_overlays"
            d.mkdir(parents=True, exist_ok=True)
            local = d / f"{path.stem}_{Path(href).name}"
            local.write_bytes(zf.read(href))
        elif not href.startswith(("http://", "https://")):
            cand = path.parent / href
            if cand.exists():
                local = cand
        batch.info["overlays"].append({"name": name, "href": href, "file": str(local) if local else None, **v})

    walk(root)
    if batch.is_empty() and not batch.info["overlays"]:
        batch.messages.append("No placemarks or overlays were found in this KML/KMZ.")
    return batch


# ------------------------------------------------------------------------------ export
def _kml_color(rgb, alpha=255):
    r, g, b = (int(c) for c in rgb)
    return f"{alpha:02x}{b:02x}{g:02x}{r:02x}"


def write_kml(path, project, lonlat_fn, point_ids=None, entity_ids=None, include_points=True,
              include_lines=True, include_contours=False, label_points=True, kmz: bool | None = None,
              max_line_vertices: int = 2_000_000, note: str = "") -> dict:
    """lonlat_fn(x_array, y_array) -> (lon, lat)  (project coords -> WGS84 degrees)."""
    path = Path(path)
    if kmz is None:
        kmz = path.suffix.lower() == ".kmz"
    used_layers = set()
    hidden = project.hidden_ids()
    pts = [p for p in project.points.values() if include_points and p.id not in hidden
           and (point_ids is None or p.id in point_ids)
           and (project.layers.get(p.layer).visible if p.layer in project.layers else True)]
    lines = [e for e in project.polylines()
             if include_lines and e.id not in hidden and (entity_ids is None or e.id in entity_ids)
             and (include_contours or e.kind != "contour")
             and (project.layers[e.layer].visible if e.layer in project.layers else True)]
    for p in pts:
        used_layers.add(p.layer)
    for e in lines:
        used_layers.add(e.layer)
    out = ['<?xml version="1.0" encoding="UTF-8"?>',
           '<kml xmlns="http://www.opengis.net/kml/2.2"><Document>',
           f'<name>{escape(project.name)}</name>',
           f'<description>{escape("Exported from Plumbline " + time.strftime("%Y-%m-%d %H:%M") + ". CRS: " + project.crs.name + ". " + note)}</description>']
    for ln in sorted(used_layers):
        c = project.layer_color(ln)
        sid = "s_" + re.sub(r"\W", "_", ln)
        out.append(f'<Style id="{sid}"><IconStyle><color>{_kml_color(c)}</color><scale>0.55</scale>'
                   f'<Icon><href>http://maps.google.com/mapfiles/kml/shapes/placemark_circle.png</href></Icon></IconStyle>'
                   f'<LabelStyle><color>{_kml_color(c)}</color><scale>0.7</scale></LabelStyle>'
                   f'<LineStyle><color>{_kml_color(c)}</color><width>2</width></LineStyle>'
                   f'<PolyStyle><fill>0</fill><outline>1</outline></PolyStyle></Style>')
    stats = {"points": 0, "lines": 0}
    if pts:
        arr = np.array([[p.x, p.y] for p in pts])
        lon, lat = lonlat_fn(arr[:, 0], arr[:, 1])
        out.append('<Folder><name>Survey points</name>')
        for p, lo, la in zip(pts, lon, lat):
            if not (math.isfinite(lo) and math.isfinite(la)):
                continue
            z = "" if math.isnan(p.z) else f"Elevation: {p.z:.3f}<br/>"
            body = f"<![CDATA[Point {escape(p.number)}<br/>{z}{escape(p.desc)}<br/>Layer: {escape(p.layer)}]]>"
            sid = "s_" + re.sub(r"\W", "_", p.layer)
            nm = f"<name>{escape(p.number)}</name>" if label_points else "<name></name>"
            out.append(f'<Placemark>{nm}<description>{body}</description><styleUrl>#{sid}</styleUrl>'
                       f'<Point><altitudeMode>clampToGround</altitudeMode><coordinates>{lo:.9f},{la:.9f},0</coordinates></Point></Placemark>')
            stats["points"] += 1
        out.append('</Folder>')
    if lines:
        out.append('<Folder><name>Linework</name>')
        budget = max_line_vertices
        for e in lines:
            v = G.flatten_polyline(e.verts, e.bulges, e.closed, max_dev=0.02)
            if e.closed and len(v):
                v = np.vstack([v, v[:1]])
            if len(v) < 2 or budget < len(v):
                continue
            budget -= len(v)
            lon, lat = lonlat_fn(v[:, 0], v[:, 1])
            ok = np.isfinite(lon) & np.isfinite(lat)
            coords = " ".join(f"{a:.9f},{b:.9f},0" for a, b in zip(lon[ok], lat[ok]))
            sid = "s_" + re.sub(r"\W", "_", e.layer)
            out.append(f'<Placemark><name>{escape(e.layer)}</name><styleUrl>#{sid}</styleUrl><LineString><tessellate>1</tessellate>'
                       f'<altitudeMode>clampToGround</altitudeMode><coordinates>{coords}</coordinates></LineString></Placemark>')
            stats["lines"] += 1
        out.append('</Folder>')
    out.append('</Document></kml>')
    data = "\n".join(out)
    if kmz:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("doc.kml", data)
    else:
        path.write_text(data, encoding="utf-8")
    return stats
