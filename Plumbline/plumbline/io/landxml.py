"""LandXML 1.x reader / writer: CgPoints, TIN surfaces, parcels, plan features, alignments.

LandXML stores coordinates as  Northing Easting [Elevation]  - we convert to x=Easting, y=Northing.
"""
from __future__ import annotations

import math
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from .. import __version__
from ..core import geometry as G
from ..core.model import ImportBatch, Layer, NAN, Polyline, SurveyPoint, Surface

NS = "http://www.landxml.org/schema/LandXML-1.2"


def _tag(e) -> str:
    return e.tag.rsplit("}", 1)[-1]


def _floats(text: str | None) -> list[float]:
    return [float(t) for t in (text or "").split()]


def _children(e, name):
    return [c for c in e if _tag(c) == name]


def _child(e, name):
    for c in e:
        if _tag(c) == name:
            return c
    return None


_UNIT_MAP = {"ussurveyfoot": "ftUS", "foot": "ft", "meter": "m", "metre": "m", "feet": "ft"}


def _pt(elem) -> tuple[float, float, float] | None:
    if elem is None:
        return None
    v = _floats(elem.text)
    if len(v) < 2:
        return None
    return v[1], v[0], v[2] if len(v) > 2 else NAN       # x=E, y=N


def coordgeom_to_polylines(cg, tol: float = 1e-4):
    """CoordGeom element -> [(verts (n,3), bulges (n,), closed)]."""
    out = []
    verts: list = []
    bulges: list = []

    def flush():
        nonlocal verts, bulges
        if len(verts) >= 2:
            closed = False
            if math.hypot(verts[0][0] - verts[-1][0], verts[0][1] - verts[-1][1]) <= tol and len(verts) > 2:
                verts = verts[:-1]
                bulges = bulges[:-1] if len(bulges) == len(verts) + 1 else bulges
                closed = True
            b = np.array(bulges[:len(verts)] + [0.0] * (len(verts) - len(bulges)))
            out.append((np.array(verts, float), b, closed))
        verts, bulges = [], []

    def add(start, end, bulge=0.0, extra=()):
        nonlocal verts, bulges
        if verts and math.hypot(verts[-1][0] - start[0], verts[-1][1] - start[1]) > tol:
            flush()
        if not verts:
            verts.append(start)
            bulges.append(0.0)
        bulges[-1] = bulge
        for p in extra:
            verts.append(p)
            bulges.append(0.0)
        verts.append(end)
        bulges.append(0.0)

    for el in cg:
        t = _tag(el)
        if t == "Line":
            s, e = _pt(_child(el, "Start")), _pt(_child(el, "End"))
            if s and e:
                add(s, e)
        elif t == "Curve":
            s, e, c = _pt(_child(el, "Start")), _pt(_child(el, "End")), _pt(_child(el, "Center"))
            if s and e:
                if c and math.hypot(s[0] - e[0], s[1] - e[1]) <= tol:
                    # A closed Curve (start == end point) is a full circle.  One DXF bulge
                    # cannot express that, so write it as two antipodal vertices with two
                    # semicircular bulges - exactly how the DXF importer writes a CIRCLE.
                    flush()
                    r = math.hypot(s[0] - c[0], s[1] - c[1])
                    if r > tol:
                        z = s[2] if len(s) > 2 and math.isfinite(s[2]) else NAN
                        v = np.array([[c[0] + r, c[1], z], [c[0] - r, c[1], z]], float)
                        out.append((v, np.array([1.0, 1.0]), True))
                else:
                    b = 0.0
                    if c:
                        b = G.arc_to_bulge(c[0], c[1], s[0], s[1], e[0], e[1],
                                           ccw=el.get("rot", "ccw").lower() == "ccw")
                    add(s, e, b)
        elif t == "Spiral":
            s, e = _pt(_child(el, "Start")), _pt(_child(el, "End"))
            pi = _pt(_child(el, "PI"))
            if s and e:
                add(s, e, 0.0)          # approximated by its chord (clothoid not modelled)
        elif t == "IrregularLine":
            pl = _child(el, "PntList3D") or _child(el, "PntList2D")
            if pl is not None:
                v = _floats(pl.text)
                step = 3 if _tag(pl) == "PntList3D" else 2
                pts = [(v[i + 1], v[i], v[i + 2] if step == 3 else NAN) for i in range(0, len(v) - step + 1, step)]
                if len(pts) >= 2:
                    add(pts[0], pts[-1], 0.0, extra=pts[1:-1])
    flush()
    return out


def read_landxml(path) -> ImportBatch:
    batch = ImportBatch()
    batch.layers = {}
    ctx = ET.iterparse(path, events=("end",))
    n_surf = 0
    for _, el in ctx:
        t = _tag(el)
        if t == "Units":
            u = el[0] if len(el) else None
            if u is not None:
                batch.info["units"] = _UNIT_MAP.get((u.get("linearUnit") or "").lower().replace(" ", ""), None)
        elif t == "CoordinateSystem":
            batch.info["coordsys"] = dict(el.attrib)
            code = (el.get("epsgCode") or "").replace("EPSG:", "").strip()
            if code.isdigit():
                batch.info["epsg"] = int(code)
            wkt = el.get("ogcWktCode")
            if wkt:
                batch.info["wkt"] = wkt
        elif t == "CgPoint":
            v = _floats(el.text)
            if len(v) >= 2:
                desc = el.get("desc") or el.get("code") or ""
                batch.points.append(SurveyPoint(0, el.get("name") or str(len(batch.points) + 1), v[1], v[0],
                                                v[2] if len(v) > 2 else NAN, desc, "POINTS"))
            el.clear()
        elif t == "Surface":
            sf = _surface(el)
            if sf is not None:
                batch.surfaces.append(sf)
                n_surf += 1
            el.clear()
        elif t in ("Parcel", "PlanFeature", "Alignment"):
            layer = {"Parcel": "LANDXML-PARCEL", "PlanFeature": "LANDXML-PLAN", "Alignment": "LANDXML-ALIGN"}[t]
            batch.layers.setdefault(layer, Layer(layer, {"Parcel": (255, 128, 0), "PlanFeature": (0, 255, 255),
                                                          "Alignment": (255, 0, 255)}[t]))
            cg = _child(el, "CoordGeom")
            if cg is not None:
                for verts, bul, closed in coordgeom_to_polylines(cg):
                    batch.polylines.append(Polyline(0, layer, verts, closed, bul,
                                                    "parcel" if t == "Parcel" else "line", None, None,
                                                    {"name": el.get("name", ""), "landxml": t}))
            el.clear()
    if batch.is_empty():
        batch.messages.append("No points, surfaces or linework were found in this LandXML file.")
    return batch


def _surface(el) -> Surface | None:
    d = _child(el, "Definition")
    if d is None:
        return None
    pn = _child(d, "Pnts")
    fc = _child(d, "Faces")
    if pn is None or fc is None:
        return None
    ids, pts = {}, []
    for p in pn:
        if _tag(p) != "P":
            continue
        v = _floats(p.text)
        if len(v) < 3:
            continue
        ids[p.get("id")] = len(pts)
        pts.append((v[1], v[0], v[2]))
    tris = []
    for f in fc:
        if _tag(f) != "F" or f.get("i") in ("1", "true"):
            continue
        ref = (f.text or "").split()
        if len(ref) == 3 and all(r in ids for r in ref):
            tris.append((ids[ref[0]], ids[ref[1]], ids[ref[2]]))
    if not tris:
        return None
    return Surface(0, el.get("name") or "LandXML surface", np.array(pts, float), np.array(tris, np.int64),
                   {"source": "landxml"})


# --------------------------------------------------------------------------- writer
def write_landxml(path, project, surfaces=None, points: bool = True, polylines: bool = True,
                  point_ids=None) -> dict:
    """Write points, TIN surfaces and linework to LandXML 1.2."""
    unit = project.h_unit
    lin = {"ftUS": "USSurveyFoot", "ft": "foot", "m": "meter"}.get(unit, "meter")
    imperial = unit in ("ft", "ftUS")
    out = [f'<?xml version="1.0" encoding="UTF-8"?>\n<LandXML xmlns="{NS}" version="1.2" '
           f'date="{time.strftime("%Y-%m-%d")}" time="{time.strftime("%H:%M:%S")}" language="English" readOnly="false">']
    if imperial:
        out.append(f'<Units><Imperial areaUnit="squareFoot" linearUnit="{lin}" volumeUnit="cubicFeet" '
                   f'temperatureUnit="fahrenheit" pressureUnit="inchHG" diameterUnit="inch" '
                   f'angularUnit="decimal degrees" directionUnit="decimal degrees"/></Units>')
    else:
        out.append('<Units><Metric areaUnit="squareMeter" linearUnit="meter" volumeUnit="cubicMeter" '
                   'temperatureUnit="celsius" pressureUnit="milliBars" diameterUnit="millimeter" '
                   'angularUnit="decimal degrees" directionUnit="decimal degrees"/></Units>')
    epsg = ""
    a = project.crs.authority
    if a.startswith("EPSG:"):
        epsg = f' epsgCode="{a[5:]}"'
    out.append(f'<CoordinateSystem name={quoteattr(project.crs.name)}{epsg} '
               f'horizontalCoordinateSystemName={quoteattr(project.crs.name)} '
               f'desc={quoteattr("Exported by Plumbline; SAF " + (f"{project.crs.ground.saf:.8f} ground/grid applied" if project.crs.ground.enabled else "not applied"))}/>')
    out.append(f'<Project name={quoteattr(project.name)}/>')
    out.append(f'<Application name="Plumbline" desc={quoteattr("Planimetric and topographic CAD")} version="{__version__}"/>')
    stats = {"points": 0, "surfaces": 0, "polylines": 0}
    hidden = project.hidden_ids()
    if points and project.points:
        out.append('<CgPoints>')
        for p in project.points.values():
            if p.id in hidden:
                continue
            if point_ids is not None and p.id not in point_ids:
                continue
            z = "" if math.isnan(p.z) else f" {p.z:.4f}"
            desc = f' desc={quoteattr(p.desc)}' if p.desc else ""
            out.append(f'<CgPoint name={quoteattr(p.number)}{desc}>{p.y:.4f} {p.x:.4f}{z}</CgPoint>')
            stats["points"] += 1
        out.append('</CgPoints>')
    sfs = [s for s in project.surfaces.values() if s.id not in hidden] if surfaces is None else surfaces
    if sfs:
        out.append('<Surfaces>')
        for s in sfs:
            out.append(f'<Surface name={quoteattr(s.name)}><Definition surfType="TIN">')
            out.append('<Pnts>')
            out.extend(f'<P id="{i + 1}">{y:.4f} {x:.4f} {z:.4f}</P>' for i, (x, y, z) in enumerate(s.pts))
            out.append('</Pnts><Faces>')
            out.extend(f'<F>{a + 1} {b + 1} {c + 1}</F>' for a, b, c in s.tris)
            out.append('</Faces></Definition></Surface>')
            stats["surfaces"] += 1
        out.append('</Surfaces>')
    if polylines:
        feats = []
        for e in project.polylines():
            if e.derived.startswith("contours") and False:
                continue
            feats.append(_plan_feature(e))
            stats["polylines"] += 1
        if feats:
            out.append('<PlanFeatures>')
            out.extend(feats)
            out.append('</PlanFeatures>')
    out.append('</LandXML>')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return stats


def _plan_feature(e: Polyline) -> str:
    v = e.verts
    n = len(v)
    items = []
    last = n if e.closed else n - 1
    for i in range(last):
        j = (i + 1) % n
        b = float(e.bulges[i]) if e.bulges is not None else 0.0
        s, t = v[i], v[j]
        if abs(b) > 1e-14:
            arc = G.bulge_to_arc(s[0], s[1], t[0], t[1], b)
            if arc:
                cx, cy, r, a0, th = arc
                items.append(f'<Curve rot="{"ccw" if th > 0 else "cw"}" radius="{r:.4f}" crvType="arc">'
                             f'<Start>{s[1]:.4f} {s[0]:.4f}</Start><Center>{cy:.4f} {cx:.4f}</Center>'
                             f'<End>{t[1]:.4f} {t[0]:.4f}</End></Curve>')
                continue
        items.append(f'<Line><Start>{s[1]:.4f} {s[0]:.4f}</Start><End>{t[1]:.4f} {t[0]:.4f}</End></Line>')
    z = e.elevation
    props = f' desc={quoteattr(e.layer)}'
    elev = f'<Feature code="Elevation"><Property label="elevation" value="{z:.4f}"/></Feature>' if (
        e.kind == "contour" and not math.isnan(z)) else ""
    return (f'<PlanFeature name={quoteattr(e.attrs.get("code") or e.kind)}{props}>'
            f'<CoordGeom>{"".join(items)}</CoordGeom>{elev}</PlanFeature>')
