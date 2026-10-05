"""GIS vector import / export via pyogrio (Shapefile, GeoPackage, GeoJSON, ...) - raw WKB, no geopandas."""
from __future__ import annotations

import datetime as _dt
import math
import os
from pathlib import Path

import numpy as np
import shapely
from pyogrio import list_layers, raw

from ..core import geometry as G
from ..core.model import ImportBatch, Polyline, SurveyPoint

NAN = math.nan

EXTENSIONS = {".shp": "ESRI Shapefile", ".gpkg": "GPKG", ".geojson": "GeoJSON", ".json": "GeoJSON"}

_FIELD_SYN = {
    "number": {"number", "pointnumber", "pointno", "ptno", "pt", "point", "id", "name", "pointid", "num", "no"},
    "description": {"description", "desc", "code", "descr", "feature", "fc", "featurecode", "note", "notes"},
    "elevation": {"elevation", "elev", "z", "height", "ele", "el"},
}


def list_gis_layers(path) -> list[tuple[str, str]]:
    return [(str(n), str(g) if g else "") for n, g in list_layers(path)]


def guess_fields(names) -> dict:
    out = {}
    for role, syn in _FIELD_SYN.items():
        for n in names:
            if "".join(c for c in str(n).lower() if c.isalnum()) in syn:
                out[role] = str(n)
                break
    return out


def _py(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, (np.datetime64, _dt.date, _dt.datetime)):
        return str(v)
    if isinstance(v, bytes):
        return v.decode("utf-8", "replace")
    return v


def read_gis(path, layer: str | None = None, fields: dict | None = None, keep_attrs: bool = True,
             max_features: int = 2_000_000) -> ImportBatch:
    """Read a vector layer. `fields` maps roles (number/description/elevation) to attribute names.

    The batch coordinates are in the file's CRS; `batch.info['crs']` holds it as a string (WKT / EPSG) or None.
    """
    meta, fids, geoms, data = raw.read(str(path), layer=layer)
    names = [str(n) for n in meta["fields"]]
    fields = fields or guess_fields(names)
    batch = ImportBatch()
    batch.info["crs"] = meta.get("crs")
    batch.info["layer"] = layer
    batch.info["geometry_type"] = meta.get("geometry_type")
    batch.info["fields"] = names
    n = len(geoms)
    if n > max_features:
        batch.messages.append(f"File has {n:,} features - only the first {max_features:,} were read.")
        n = max_features
    gs = shapely.from_wkb(geoms[:n])
    col = {nm: data[i] for i, nm in enumerate(names)}
    stem = Path(path).stem
    layer_name = (layer or stem)[:40]
    cnt = 0
    skipped = 0
    for i in range(n):
        g = gs[i]
        if g is None or g.is_empty:
            skipped += 1
            continue
        attrs = {}
        if keep_attrs:
            for nm in names:
                v = _py(col[nm][i])
                if v not in (None, ""):
                    attrs[nm] = v
        _emit(batch, g, layer_name, attrs, fields, col, i, cnt)
        cnt += 1
    if skipped:
        batch.messages.append(f"{skipped} feature(s) had no geometry and were skipped.")
    return batch


def _emit(batch, g, layer, attrs, fields, col, i, cnt):
    t = g.geom_type
    if t == "Point":
        number = str(_py(col[fields["number"]][i])) if fields.get("number") in col else str(len(batch.points) + 1)
        desc = str(_py(col[fields["description"]][i]) or "") if fields.get("description") in col else ""
        z = g.z if g.has_z else NAN
        if fields.get("elevation") in col:
            try:
                zv = float(col[fields["elevation"]][i])
                z = zv if math.isfinite(zv) else z
            except (TypeError, ValueError):
                pass
        batch.points.append(SurveyPoint(0, number, g.x, g.y, z, desc, layer, attrs))
    elif t in ("MultiPoint", "GeometryCollection", "MultiLineString", "MultiPolygon"):
        for part in g.geoms:
            _emit(batch, part, layer, attrs, fields, col, i, cnt)
    elif t in ("LineString", "LinearRing"):
        c = np.asarray(g.coords)
        if len(c) >= 2:
            closed = bool(g.is_closed and len(c) > 3)
            if closed:
                c = c[:-1]
            batch.polylines.append(Polyline(0, layer, c, closed, None, "line", None, None, attrs))
    elif t == "Polygon":
        rings = [g.exterior] + list(g.interiors)
        for k, r in enumerate(rings):
            c = np.asarray(r.coords)[:-1]
            if len(c) >= 3:
                a = dict(attrs)
                if k:
                    a["hole"] = True
                batch.polylines.append(Polyline(0, layer, c, True, None, "parcel", None, None, a))


def _tess(e: Polyline, max_dev=0.01):
    v = G.flatten_polyline(e.verts, e.bulges, e.closed, max_dev=max_dev)
    if e.closed and len(v) and not np.allclose(v[0], v[-1]):
        v = np.vstack([v, v[:1]])
    return v


def write_gis(path, project, driver: str | None = None, xy_fn=None, crs=None,
              point_ids=None, entity_ids=None, include_points=True, include_lines=True,
              include_polygons=True, z_scale: float = 1.0) -> dict:
    """Write points / lines / polygons.  GeoPackage -> one file with 3 layers; others -> *_points/_lines/_polygons files.

    xy_fn(x, y) converts project coords to the output CRS; `crs` is the output CRS (anything pyogrio accepts).
    """
    path = Path(path)
    driver = driver or EXTENSIONS.get(path.suffix.lower(), "GPKG")

    def conv(a):
        a = np.asarray(a, float)
        if xy_fn is None or not len(a):
            return a
        x, y = xy_fn(a[:, 0], a[:, 1])
        return np.column_stack([x, y, a[:, 2] * z_scale if a.shape[1] > 2 else np.zeros(len(a))])

    out_files = []
    stats = {"points": 0, "lines": 0, "polygons": 0}
    first = True

    def target(kind):
        nonlocal first
        if driver == "GPKG":
            return path, kind
        stem = path.with_suffix("")
        ext = path.suffix or ".shp"
        return Path(f"{stem}_{kind}{ext}"), kind

    # ---- points
    hidden = project.hidden_ids()
    pts = [p for p in project.points.values() if p.id not in hidden
           and (point_ids is None or p.id in point_ids)]
    if include_points and pts:
        a = conv(np.array([[p.x, p.y, 0.0 if math.isnan(p.z) else p.z * 1.0] for p in pts]))
        if xy_fn is None:
            a[:, 2] *= z_scale
        zs = np.array([p.z * z_scale for p in pts])
        geom = shapely.to_wkb(shapely.points(a[:, 0], a[:, 1], np.where(np.isfinite(zs), zs, 0.0)), flavor="iso")
        fp, ln = target("points")
        raw.write(str(fp), geometry=geom, field_data=[
            np.array([p.number for p in pts], dtype=object), np.array([p.desc for p in pts], dtype=object),
            zs, np.array([p.layer for p in pts], dtype=object)],
            fields=["number", "descr", "elev", "layer"], crs=crs, geometry_type="Point Z", driver=driver,
            layer=ln if driver == "GPKG" else None, append=(driver == "GPKG" and not first))
        first = False
        out_files.append(str(fp))
        stats["points"] = len(pts)
    # ---- lines / polygons
    lines, polys = [], []
    for e in project.polylines():
        if entity_ids is not None and e.id not in entity_ids:
            continue
        if e.closed and e.kind not in ("contour", "breakline") and len(e.verts) >= 3:
            polys.append(e)
        else:
            lines.append(e)
    if include_lines and lines:
        arrs = [conv(_tess(e)) for e in lines]
        geom = shapely.to_wkb(np.array([shapely.linestrings(a[:, 0], a[:, 1], np.where(np.isfinite(a[:, 2]), a[:, 2], 0.0))
                                        for a in arrs], dtype=object), flavor="iso")
        fp, ln = target("lines")
        raw.write(str(fp), geometry=geom, field_data=[
            np.array([e.layer for e in lines], dtype=object), np.array([e.kind for e in lines], dtype=object),
            np.array([e.elevation * z_scale for e in lines]),
            np.array([G.polyline_length(e.verts, e.bulges, e.closed) for e in lines])],
            fields=["layer", "kind", "elev", "length"], crs=crs, geometry_type="LineString Z", driver=driver,
            layer=ln if driver == "GPKG" else None, append=(driver == "GPKG" and not first))
        first = False
        out_files.append(str(fp))
        stats["lines"] = len(lines)
    if include_polygons and polys:
        arrs = [conv(_tess(e)) for e in polys]
        geoms = [shapely.polygons(shapely.linearrings(a[:, 0], a[:, 1], np.where(np.isfinite(a[:, 2]), a[:, 2], 0.0)))
                 for a in arrs]
        geom = shapely.to_wkb(np.array(geoms, dtype=object), flavor="iso")
        fp, ln = target("polygons")
        raw.write(str(fp), geometry=geom, field_data=[
            np.array([e.layer for e in polys], dtype=object), np.array([e.kind for e in polys], dtype=object),
            np.array([G.polygon_area(e.verts, e.bulges) for e in polys])],
            fields=["layer", "kind", "area"], crs=crs, geometry_type="Polygon Z", driver=driver,
            layer=ln if driver == "GPKG" else None, append=(driver == "GPKG" and not first))
        first = False
        out_files.append(str(fp))
        stats["polygons"] = len(polys)
    stats["files"] = sorted(set(out_files))
    return stats
