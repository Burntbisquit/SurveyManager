"""DXF import / export (ezdxf).

Export is designed for hand-off to AutoCAD / Civil 3D: real layers with colours and linetypes, LWPOLYLINEs
with arc bulges, 3D polylines where elevations vary, contours at elevation, points with optional
number / elevation / description labels (or attributed blocks), and TIN faces.
"""
from __future__ import annotations

import math
import os
import re
from dataclasses import dataclass, field

import ezdxf
import numpy as np
from ezdxf import colors as dxfcolors
from ezdxf.enums import TextEntityAlignment

from ..core import geometry as G
from ..core.model import ImportBatch, Layer, NAN, Polyline, SurveyPoint, Surface, TextEntity

INSUNITS = {0: None, 1: "in", 2: "ft", 4: None, 5: None, 6: "m", 21: "ftUS", 10: "yd"}
INSUNITS_OUT = {"ftUS": 21, "ft": 2, "m": 6}

_ACI_RGB = np.array([dxfcolors.int2rgb(c) for c in dxfcolors.DXF_DEFAULT_COLORS[1:256]], float)
_BAD = re.compile(r'[<>/\\":;?*|=`]')


def nearest_aci(rgb) -> int:
    d = ((_ACI_RGB - np.array(rgb, float)) ** 2).sum(axis=1)
    return int(np.argmin(d)) + 1


def safe_layer(name: str) -> str:
    return _BAD.sub("_", name)[:200] or "0"


def _entity_color(e, doc):
    try:
        if e.dxf.hasattr("true_color") and e.dxf.true_color:
            return tuple(int(v) for v in dxfcolors.int2rgb(e.dxf.true_color))
        c = e.dxf.color if e.dxf.hasattr("color") else 256
        if 1 <= c <= 255:
            return tuple(int(v) for v in _ACI_RGB[c - 1])
    except Exception:
        pass
    return None


def _layer_color(lay) -> tuple:
    try:
        if lay.dxf.hasattr("true_color") and lay.dxf.true_color:
            return tuple(int(v) for v in dxfcolors.int2rgb(lay.dxf.true_color))
        c = abs(lay.dxf.color)
        if 1 <= c <= 255:
            return tuple(int(v) for v in _ACI_RGB[c - 1])
    except Exception:
        pass
    return (230, 230, 230)


# ============================================================================ import
def read_dxf(path, explode_blocks: bool = False, tess_dev: float = 0.05, include_paperspace: bool = False) -> ImportBatch:
    try:
        doc = ezdxf.readfile(path)
    except ezdxf.DXFStructureError:
        from ezdxf import recover
        doc, auditor = recover.readfile(path)
    batch = ImportBatch()
    ins = doc.header.get("$INSUNITS", 0)
    batch.info["insunits"] = ins
    batch.info["units"] = INSUNITS.get(ins)
    for lay in doc.layers:
        n = lay.dxf.name
        lt = (lay.dxf.linetype or "CONTINUOUS").upper()
        batch.layers[n] = Layer(n, _layer_color(lay), lt if lt != "CONTINUOUS" else "CONTINUOUS",
                                visible=lay.is_on() and not lay.is_frozen(), locked=lay.is_locked())
    skipped: dict[str, int] = {}
    faces: list = []
    pts_z0 = 0

    def add_poly(layer, verts, bulges=None, closed=False, color=None, lt=None, attrs=None, kind="line"):
        v = np.asarray(verts, float)
        if len(v) >= 2:
            batch.polylines.append(Polyline(0, layer, v, closed, bulges, kind, color, lt, attrs or {}))

    def handle(e, depth=0):
        nonlocal pts_z0
        t = e.dxftype()
        layer = e.dxf.layer if e.dxf.hasattr("layer") else "0"
        color = _entity_color(e, doc)
        lt = e.dxf.linetype if e.dxf.hasattr("linetype") and e.dxf.linetype.upper() not in ("BYLAYER", "BYBLOCK") else None
        if t == "POINT":
            p = e.dxf.location
            batch.points.append(SurveyPoint(0, str(len(batch.points) + 1), p.x, p.y, p.z, "", layer))
            if p.z == 0:
                pts_z0 += 1
        elif t == "INSERT":
            if explode_blocks and depth < 4:
                try:
                    for ve in e.virtual_entities():
                        handle(ve, depth + 1)
                    return
                except Exception:
                    pass
            p = e.dxf.insert
            attrs = {a.dxf.tag: a.dxf.text for a in e.attribs} if hasattr(e, "attribs") else {}
            low = {k.lower(): v for k, v in attrs.items()}
            number = next((low[k] for k in ("number", "point", "pt", "pointnumber", "pt_no", "id") if k in low), None)
            desc = next((low[k] for k in ("description", "desc", "code") if k in low), e.dxf.name)
            z = p.z
            for k in ("elevation", "elev", "z"):
                if k in low:
                    try:
                        z = float(low[k])
                    except ValueError:
                        pass
                    break
            batch.points.append(SurveyPoint(0, str(number or len(batch.points) + 1), p.x, p.y, z, desc, layer,
                                            {"block": e.dxf.name, **attrs}))
        elif t == "LINE":
            s, en = e.dxf.start, e.dxf.end
            add_poly(layer, [[s.x, s.y, s.z], [en.x, en.y, en.z]], None, False, color, lt)
        elif t == "LWPOLYLINE":
            pts = list(e.get_points("xyb"))
            if pts:
                el = e.dxf.elevation if e.dxf.hasattr("elevation") else 0.0
                el = el[2] if hasattr(el, "__len__") else el
                v = [[p[0], p[1], el] for p in pts]
                add_poly(layer, v, [p[2] for p in pts], e.closed, color, lt)
        elif t == "POLYLINE":
            if e.is_poly_face_mesh:
                try:
                    for fc in e.indexed_faces():
                        faces.append([tuple(v.dxf.location) for v in fc.points()] if hasattr(fc, "points") else [])
                except Exception:
                    skipped["POLYFACE"] = skipped.get("POLYFACE", 0) + 1
            elif e.is_polygon_mesh:
                skipped["POLYMESH"] = skipped.get("POLYMESH", 0) + 1
            else:
                vs = list(e.vertices)
                v = [[q.dxf.location.x, q.dxf.location.y, q.dxf.location.z] for q in vs]
                b = [q.dxf.bulge if q.dxf.hasattr("bulge") else 0.0 for q in vs]
                add_poly(layer, v, b if e.is_2d_polyline else None, e.is_closed, color, lt)
        elif t == "3DFACE":
            faces.append([tuple(e.dxf.vtx0), tuple(e.dxf.vtx1), tuple(e.dxf.vtx2), tuple(e.dxf.vtx3)])
        elif t in ("TEXT", "MTEXT"):
            if t == "TEXT":
                p, txt, h, rot = e.dxf.insert, e.dxf.text, e.dxf.height, e.dxf.rotation
            else:
                p, txt, h = e.dxf.insert, e.plain_text(), e.dxf.char_height
                rot = e.dxf.rotation if e.dxf.hasattr("rotation") else 0.0
            if txt and txt.strip():
                batch.texts.append(TextEntity(0, layer, p.x, p.y, txt.replace("\n", " "), h or 1.0, rot or 0.0, color))
        elif t == "CIRCLE":
            c, r = e.dxf.center, e.dxf.radius
            add_poly(layer, [[c.x - r, c.y, c.z], [c.x + r, c.y, c.z]], [1.0, 1.0], True, color, lt)
        elif t == "ARC":
            c, r = e.dxf.center, e.dxf.radius
            a0, a1 = math.radians(e.dxf.start_angle), math.radians(e.dxf.end_angle)
            sweep = (a1 - a0) % (2 * math.pi) or 2 * math.pi
            s = [c.x + r * math.cos(a0), c.y + r * math.sin(a0), c.z]
            en = [c.x + r * math.cos(a1), c.y + r * math.sin(a1), c.z]
            add_poly(layer, [s, en], [math.tan(sweep / 4), 0.0], False, color, lt)
        elif t in ("SPLINE", "ELLIPSE"):
            try:
                from ezdxf import path as dxfpath
                p = dxfpath.make_path(e)
                v = [[q.x, q.y, q.z] for q in p.flattening(tess_dev)]
                add_poly(layer, v, None, getattr(e, "closed", False), color, lt)
            except Exception:
                skipped[t] = skipped.get(t, 0) + 1
        else:
            skipped[t] = skipped.get(t, 0) + 1

    spaces = [doc.modelspace()]
    if include_paperspace:
        spaces += [l.entity_space for l in doc.layouts if l.name != "Model"]
    for sp in spaces:
        for e in sp:
            try:
                handle(e)
            except Exception as ex:                               # one odd entity must not kill the import
                skipped[e.dxftype()] = skipped.get(e.dxftype(), 0) + 1

    if faces:
        sf = _faces_to_surface(faces)
        if sf is not None:
            batch.surfaces.append(sf)
            batch.messages.append(f"{len(faces):,} 3D faces were combined into surface '{sf.name}'.")
    if batch.points and pts_z0 == len(batch.points):
        for p in batch.points:
            p.z = NAN
        batch.messages.append("All DXF POINT elevations were 0 - treated as having no elevation.")
    if skipped:
        batch.messages.append("Skipped (not supported): " + ", ".join(f"{n} x{c}" for n, c in sorted(skipped.items())))
    return batch


def _faces_to_surface(faces) -> Surface | None:
    idx, pts, tris = {}, [], []

    def vid(p):
        k = (round(p[0], 4), round(p[1], 4), round(p[2], 4))
        i = idx.get(k)
        if i is None:
            i = idx[k] = len(pts)
            pts.append(p)
        return i

    for f in faces:
        if len(f) < 3:
            continue
        v = [vid(p) for p in f]
        uniq = []
        for i in v:
            if i not in uniq:
                uniq.append(i)
        if len(uniq) == 3:
            tris.append(tuple(uniq))
        elif len(uniq) == 4:
            tris.append((uniq[0], uniq[1], uniq[2]))
            tris.append((uniq[0], uniq[2], uniq[3]))
    if not tris:
        return None
    return Surface(0, "DXF surface", np.array(pts, float), np.array(tris, np.int64), {"source": "dxf"})


# ============================================================================ export
@dataclass
class DxfOptions:
    version: str = "R2013"
    points_mode: str = "point+text"          # point | point+text | block
    label_number: bool = True
    label_elev: bool = True
    label_desc: bool = True
    text_height: float = 2.0                 # drawing units
    elev_decimals: int = 2
    include_contours: bool = True
    include_contour_labels: bool = True
    include_surface_faces: bool = False      # TIN as 3DFACE
    visible_layers_only: bool = True
    point_ids: set | None = None             # restrict to these points
    entity_ids: set | None = None            # restrict to these entities
    no_elev_as_zero: bool = True
    surfaces: list | None = None             # surface ids for 3DFACE output (None = all)


def write_dxf(path, project, opts: DxfOptions | None = None) -> dict:
    """Write `project` to the DXF file at `path`.

    Argument order is (path, project, opts) to match every other writer in `plumbline.io`
    (write_landxml / write_gis / write_kml / write_points_csv) and every reader.
    """
    if not isinstance(path, (str, os.PathLike)):
        # Guard the pre-0.2 (project, path) order explicitly - a swapped call used to fail
        # deep inside with a confusing AttributeError.
        raise TypeError("write_dxf(path, project, opts) - the file path comes first; "
                        f"got {type(path).__name__} where a path was expected. "
                        "Did you mean write_dxf(path, project)?")
    o = opts or DxfOptions()
    doc = ezdxf.new(o.version, setup=True)
    msp = doc.modelspace()
    doc.header["$INSUNITS"] = INSUNITS_OUT.get(project.h_unit, 0)
    doc.header["$MEASUREMENT"] = 1 if project.h_unit == "m" else 0
    doc.header["$LUNITS"] = 2
    doc.header["$LUPREC"] = 3
    st = {"points": 0, "polylines": 0, "polylines3d": 0, "texts": 0, "faces": 0, "layers": 0, "contours": 0}
    made_layers: set = set()

    label_rgb = {"PT-NUMBER": (255, 255, 255), "PT-ELEV": (0, 255, 255), "PT-DESC": (0, 255, 0)}

    def layer_of(name: str) -> str:
        n = safe_layer(name)
        if n not in made_layers:
            made_layers.add(n)
            if n not in doc.layers:
                src = project.layers.get(name)
                rgb = src.color if src else label_rgb.get(name, (255, 255, 255))
                lt = (src.linetype if src else "CONTINUOUS").upper()
                if lt not in [x.dxf.name.upper() for x in doc.linetypes]:
                    lt = "CONTINUOUS"
                doc.layers.add(n, color=nearest_aci(rgb), true_color=dxfcolors.rgb2int(tuple(int(c) for c in rgb)),
                               linetype=lt)
                st["layers"] += 1
        return n

    def layer_visible(name):
        lay = project.layers.get(name)
        return (lay.visible if lay else True) or not o.visible_layers_only

    def attribs(layer, color=None, linetype=None):
        d = {"layer": layer_of(layer)}
        if color:
            d["true_color"] = dxfcolors.rgb2int(tuple(int(c) for c in color))
        if linetype and linetype.upper() in [x.dxf.name.upper() for x in doc.linetypes]:
            d["linetype"] = linetype
        return d

    th = o.text_height
    # ---------------------------------------------------------------- points
    if o.points_mode == "block":
        blk = doc.blocks.new("PLB_POINT")
        r = 0.5
        blk.add_circle((0, 0), r * 0.5)
        blk.add_line((-r, 0), (r, 0))
        blk.add_line((0, -r), (0, r))
        for i, tag in enumerate(("NUMBER", "ELEVATION", "DESCRIPTION")):
            blk.add_attdef(tag, (r * 1.2, r * (1.0 - 1.4 * i)), height=r * 1.0,
                           dxfattribs={"flags": 1})       # invisible attribute (data only)
    # A group switched off is hidden everywhere, exports included (change order, item 2).
    _hidden = project.hidden_ids()
    for p in project.points.values():
        if p.id in _hidden:
            continue
        if o.point_ids is not None and p.id not in o.point_ids:
            continue
        if not layer_visible(p.layer):
            continue
        z = 0.0 if math.isnan(p.z) and o.no_elev_as_zero else p.z
        zz = 0.0 if math.isnan(z) else z
        lay = layer_of(p.layer)
        if o.points_mode == "block":
            ins = msp.add_blockref("PLB_POINT", (p.x, p.y, zz), dxfattribs={"layer": lay, "xscale": th * 0.6,
                                                                              "yscale": th * 0.6, "zscale": th * 0.6})
            ins.add_auto_attribs({"NUMBER": p.number, "ELEVATION": "" if math.isnan(p.z) else f"{p.z:.{o.elev_decimals}f}",
                                  "DESCRIPTION": p.desc})
        else:
            msp.add_point((p.x, p.y, zz), dxfattribs={"layer": lay})
        st["points"] += 1
        if o.points_mode in ("point+text", "block"):
            lines = []
            if o.label_number:
                lines.append(("PT-NUMBER", p.number))
            if o.label_elev and not math.isnan(p.z):
                lines.append(("PT-ELEV", f"{p.z:.{o.elev_decimals}f}"))
            if o.label_desc and p.desc:
                lines.append(("PT-DESC", p.desc))
            for k, (tl, txt) in enumerate(lines):
                t = msp.add_text(txt, height=th, dxfattribs={"layer": layer_of(tl)})
                t.set_placement((p.x + 0.8 * th, p.y + th * (0.9 - 1.15 * k)), align=TextEntityAlignment.LEFT)
                st["texts"] += 1
    # ---------------------------------------------------------------- polylines & text
    for e in project.entities.values():
        if e.id in _hidden:
            continue
        if o.entity_ids is not None and e.id not in o.entity_ids:
            continue
        if not layer_visible(e.layer):
            continue
        if isinstance(e, Polyline):
            if e.kind == "contour" and not o.include_contours:
                continue
            at = attribs(e.layer, e.color, e.linetype)
            z = e.verts[:, 2]
            zf = np.where(np.isfinite(z), z, 0.0)
            varies = len(zf) > 0 and np.ptp(zf) > 1e-9
            if varies:
                v = G.flatten_polyline(e.verts, e.bulges, e.closed, max_dev=0.01)
                v = np.column_stack([v[:, 0], v[:, 1], np.where(np.isfinite(v[:, 2]), v[:, 2], 0.0)])
                pl = msp.add_polyline3d([tuple(r) for r in v], close=e.closed, dxfattribs=at)
                st["polylines3d"] += 1
            else:
                pts = [(float(r[0]), float(r[1]), 0.0, 0.0, float(b)) for r, b in
                       zip(e.verts, e.bulges if e.bulges is not None else np.zeros(len(e.verts)))]
                if len(pts) >= 2:
                    lw = msp.add_lwpolyline(pts, format="xyseb", close=e.closed, dxfattribs={**at, "elevation": float(zf[0]) if len(zf) else 0.0})
                    st["polylines"] += 1
            if e.kind == "contour":
                st["contours"] += 1
        elif isinstance(e, TextEntity):
            if e.derived.startswith("contours") and not o.include_contour_labels:
                continue
            at = attribs(e.layer, e.color)
            t = msp.add_text(e.text, height=e.height, rotation=e.rotation, dxfattribs=at)
            t.set_placement((e.x, e.y), align=TextEntityAlignment.MIDDLE_CENTER if e.derived.startswith("contours")
                            else TextEntityAlignment.LEFT)
            st["texts"] += 1
    # ---------------------------------------------------------------- surfaces
    if o.include_surface_faces:
        for s in project.surfaces.values():
            if s.id in _hidden:
                continue
            if o.surfaces is not None and s.id not in o.surfaces:
                continue
            lay = layer_of(f"SURFACE-{s.name}".replace(" ", "_"))
            for a, b, c in s.tris:
                pa, pb, pc = s.pts[a], s.pts[b], s.pts[c]
                msp.add_3dface([tuple(pa), tuple(pb), tuple(pc), tuple(pc)], dxfattribs={"layer": lay})
                st["faces"] += 1
    try:
        from ezdxf import zoom
        zoom.extents(msp)
    except Exception:
        pass
    doc.saveas(path)
    return st
