"""What coordinate system each file's numbers were in - recorded, and changeable afterwards.

Item 6 of the change order, in the user's words:

    "any csv import assumes the project crs. repro only happens when it is a different crs.
     need a way to change the crs of a file after the fact.  (assumed TXNC grid, was TXC ground)"

Three statements, three jobs for this module.

**Assumed, not asked.**  A CSV is a column of numbers; it does not say where they are.  So the
importer assumes the project's own system - the safe assumption, and the one that makes a plain
points file import with no boxes to fill in (``ui/import_export.py``).  Nothing is reprojected when
the assumption holds, because nothing needs to move.

**Recorded.**  The assumption is written down against the file, together with which of the parts
were assumed and which came from the file itself: the horizontal system, the elevation unit and
vertical datum, and the ground/grid state (SAF from a base point).  Without this record the
assumption is invisible, and an invisible assumption is the one that gets discovered in the
checking stage.

**Changeable.**  "Assumed TXNC grid, was TXC ground" is the exact failure this is about: the
numbers are right and the *label* is wrong, or the numbers are wrong and the label is right.
Those need opposite operations, so the dialog that edits a file's CRS offers both, in the
program's own words - **relabel** (nothing moves) and **reproject** (the data moves) - and says
which one it is about to do, with how many points it will touch.  A ground/grid correction is the
third case and is offered as its own operation, because dividing by a SAF of 1.000136506 is not a
reprojection: no datum changes, the distances do.

The record lives on the **project**, not on the points: it is one fact about one file, and the
points already carry the file name they came from (:mod:`plumbline.core.provenance`).  Projects
saved before this existed simply have no records, and the dialog shows the files it can see
points from with the CRS left blank rather than guessing one.
"""
from __future__ import annotations

from datetime import datetime

import numpy as np

from . import units as U

#: Where the records live: ``project.settings[KEY]`` is ``{file name: record}``.
KEY = "file_crs"

#: How the file's system was arrived at, in the words the dialog shows.
METHODS = {
    "project": "assumed to be the project's system (the default for a CSV)",
    "file": "read from the file itself",
    "chosen": "chosen at import time",
    "edited": "changed afterwards on this screen",
    "field-book": "the job's field book / fieldwork import",
}


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def make(*, key: str = "", label: str = "", unit: str = "", vunit: str = "", vertical: str = "",
         geoid: str = "", saf: float = 1.0, ground: bool = False, base_n: float = 0.0,
         base_e: float = 0.0, method: str = "project", folder: str = "", when: str = "") -> dict:
    """One file's coordinate-system record.  Everything is a plain value so it survives save/load."""
    return {"key": str(key or ""), "label": str(label or ""), "unit": str(unit or ""),
            "vunit": str(vunit or ""), "vertical": str(vertical or ""), "geoid": str(geoid or ""),
            "saf": float(saf or 1.0), "ground": bool(ground), "base_n": float(base_n or 0.0),
            "base_e": float(base_e or 0.0), "method": str(method or "project"),
            "folder": str(folder or ""), "when": str(when or _stamp())}


def make_from_project(project, method: str = "project", **kw) -> dict:
    """The record that describes "in the project's system, as the project stands now"."""
    c = project.crs
    g = c.ground
    return make(key=c.authority or "", label=c.label or c.name or "", unit=c.unit, vunit=c.vunit,
                vertical=getattr(c, "vdatum", "") or "", geoid=getattr(c, "geoid", "") or "",
                saf=float(getattr(g, "saf", 1.0) or 1.0), ground=bool(getattr(g, "enabled", False)),
                base_n=float(getattr(g, "base_y", 0.0) or 0.0),
                base_e=float(getattr(g, "base_x", 0.0) or 0.0), method=method, **kw)


# --------------------------------------------------------------------------------------------- store
def record(project, file: str, rec: dict) -> dict:
    """Write one file's record (replacing any earlier one for the same name)."""
    table = dict(project.settings.get(KEY) or {})
    table[str(file)] = dict(rec)
    project.settings[KEY] = table
    return table[str(file)]


def forget(project, file: str) -> None:
    table = dict(project.settings.get(KEY) or {})
    table.pop(str(file), None)
    project.settings[KEY] = table


def for_file(project, file: str) -> dict | None:
    return (project.settings.get(KEY) or {}).get(str(file))


def files(project) -> list[dict]:
    """Every file that brought data into this project, with its record (or an empty one).

    The list of files comes from the points themselves, so a file imported before this feature
    existed still appears - with a blank CRS to fill in - and a file whose points were all deleted
    disappears with them.
    """
    from . import provenance as PROV
    seen: dict[str, dict] = {}
    for p in project.points.values():
        rec = PROV.of(p)
        name = rec.get("file") or ""
        if not name:
            continue
        row = seen.setdefault(name, {"file": name, "folder": rec.get("folder", ""), "points": 0})
        row["points"] += 1
    table = project.settings.get(KEY) or {}
    for name in list(seen) + [k for k in table if k not in seen]:
        seen.setdefault(name, {"file": name, "folder": "", "points": 0})
    out = []
    for name, row in seen.items():
        rec = table.get(name)
        out.append({**row, "crs": rec or None,
                    "key": (rec or {}).get("key", ""), "label": (rec or {}).get("label", ""),
                    "vertical": (rec or {}).get("vertical", ""), "saf": (rec or {}).get("saf", 1.0),
                    "ground": (rec or {}).get("ground", False),
                    "method": (rec or {}).get("method", ""), "when": (rec or {}).get("when", "")})
    return sorted(out, key=lambda r: (-r["points"], r["file"].lower()))


def points_of(project, file: str) -> list:
    from . import provenance as PROV
    return [p for p in project.points.values() if (PROV.of(p).get("file") or "") == str(file)]


# --------------------------------------------------------------------------------------------- the two operations
def relabel(project, file: str, rec: dict) -> dict:
    """Say the file was in *rec*'s system all along.  **Nothing moves.**

    The right answer to "assumed TXNC grid, and it really was TXNC grid - it was the record that
    was wrong".  No coordinates are touched, so this is safe on a job that has already been worked
    on, and it is undoable like any other edit.
    """
    rec = dict(rec)
    rec["method"] = "edited"
    rec["when"] = _stamp()
    return record(project, file, rec)


def reproject(project, file: str, rec: dict, *, convert_z: bool = True) -> dict:
    """Move the coordinates of one file's points into *rec*'s system.  **The data moves.**

    Only the points from that file are touched - everything else in the project stays where it is -
    which is what makes this different from Project > Reproject.  Heights are converted only when
    the vertical unit changes, exactly as the project-wide operation does.
    """
    from .crs import ProjectCRS
    from . import audit as AUD

    old_rec = for_file(project, file) or make_from_project(project)
    target = to_projectcrs(rec)
    if target is None:
        raise ValueError("Pick the coordinate system this file is actually in.")
    pts = points_of(project, file)
    old_crs = to_projectcrs(old_rec) or project.crs
    fn = old_crs.transform_to(target)
    zs = (U.M_PER_UNIT.get(old_crs.vunit, 1.0) / U.M_PER_UNIT.get(target.vunit, 1.0)
          if convert_z else 1.0)
    xs = np.array([p.x for p in pts], float)
    ys = np.array([p.y for p in pts], float)
    nx, ny = fn(xs, ys)
    for p, a, b in zip(pts, nx, ny):
        p.x, p.y = float(a), float(b)
        if convert_z and np.isfinite(p.z):
            p.z *= zs
    AUD.record(project, pts)          # the audit trail is the same one the reprojection tool uses
    out = dict(rec)
    out["method"] = "edited"
    out["when"] = _stamp()
    out["reprojected_from"] = old_rec.get("label") or old_rec.get("key") or "the previous record"
    out["label"] = target.label or out.get("label", "")   # the label follows the system
    out["unit"] = target.unit
    out["vunit"] = target.vunit
    record(project, file, out)
    return {"points": len(pts), "from": old_rec.get("label") or old_rec.get("key") or "",
            "to": out.get("label") or out.get("key") or "", "record": out}


def rescale_ground(project, file: str, *, saf: float, to_ground: bool, base_n: float = 0.0,
                   base_e: float = 0.0) -> dict:
    """Fix the ground/grid state of one file's points: "assumed grid, was ground".

    The TXDOT operation, applied to one file's points only: ``grid = ground / SAF`` when the
    numbers arrived as ground and the project is storing grid, and the multiplication the other
    way.  No datum changes and no scale factor is taken from anywhere but this argument, so what
    the dialog showed is what the coordinates got.
    """
    from .crs import GroundScale
    if not (saf and saf > 0):
        raise ValueError("a SAF is needed: ground = grid x SAF")
    if abs(saf - 1.0) < 1e-12:
        return {"points": 0, "note": "SAF 1.000000000 is grid; nothing to do."}
    pts = points_of(project, file)
    # A scale that is switched off is not a scale: build the one asked for here rather than
    # reading the project's (which is off whenever the job is grid - the case this fixes).
    gr = GroundScale(enabled=True, base_x=float(base_e), base_y=float(base_n), saf=float(saf))
    fn = gr.from_grid if to_ground else gr.to_grid
    for p in pts:
        nx, ny = fn(p.x, p.y)
        p.x, p.y = float(nx), float(ny)
    from . import audit as AUD
    AUD.record(project, pts)
    rec = dict(for_file(project, file) or make_from_project(project))
    rec.update({"saf": float(saf), "ground": bool(to_ground), "base_n": float(base_n),
                "base_e": float(base_e), "method": "edited", "when": _stamp()})
    if to_ground:
        rec["note"] = f"ground = grid x {saf:.9f} from N {base_n:,.3f}, E {base_e:,.3f}"
    else:
        rec["note"] = f"grid = ground / {saf:.9f} from N {base_n:,.3f}, E {base_e:,.3f}"
    record(project, file, rec)
    return {"points": len(pts), "saf": float(saf), "to_ground": bool(to_ground), "record": rec}


def record_from_crs(crs, *, method: str = "chosen", **kw) -> dict:
    """The record that describes a particular ProjectCRS (the one an import converted from)."""
    g = getattr(crs, "ground", None)
    return make(key=getattr(crs, "key", "") or (crs.authority if crs.authority != "custom" else ""),
                label=crs.label or crs.name or "", unit=getattr(crs, "unit", ""),
                vunit=getattr(crs, "vunit", ""), vertical=getattr(crs, "vdatum", "") or "",
                geoid=getattr(crs, "geoid", "") or "",
                saf=float(getattr(g, "saf", 1.0) or 1.0),
                ground=bool(getattr(g, "enabled", False)),
                base_n=float(getattr(g, "base_y", 0.0) or 0.0),
                base_e=float(getattr(g, "base_x", 0.0) or 0.0), method=method, **kw)


def to_projectcrs(rec: dict):
    """A record -> a :class:`~plumbline.core.crs.ProjectCRS`, for a transform.  None if it cannot.

    The ground part matters here: two records with the same EPSG code and different SAF are the
    difference between grid and ground coordinates, and ``ProjectCRS.transform_to`` applies that
    step when both sides are ProjectCRS objects - which is how "assumed grid, was ground" is
    fixed by the same code path that fixes a wrong zone.
    """
    from .crs import GroundScale, ProjectCRS
    rec = rec or {}
    key = str(rec.get("key") or "").strip()
    if not key:
        return None
    try:
        pc = ProjectCRS.from_key(key)
    except Exception:
        try:
            pc = ProjectCRS.from_epsg(int(key.split(":")[-1]))
        except Exception:
            return None
    if rec.get("vunit"):
        pc.vunit = rec["vunit"]
    pc.vdatum = rec.get("vertical") or pc.vdatum
    pc.geoid = rec.get("geoid") or pc.geoid
    pc.ground = GroundScale(enabled=bool(rec.get("ground")),
                            base_x=float(rec.get("base_e") or 0.0),
                            base_y=float(rec.get("base_n") or 0.0),
                            saf=float(rec.get("saf") or 1.0))
    return pc


__all__ = ["KEY", "METHODS", "make", "make_from_project", "record_from_crs", "to_projectcrs",
           "record", "forget", "for_file", "files", "points_of", "relabel", "reproject",
           "rescale_ground"]
