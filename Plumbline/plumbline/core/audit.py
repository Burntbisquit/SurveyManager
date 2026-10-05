"""The point audit: what the imported points were, against what they are now.

The change list asked for a *"Point(s) Audit" report*, and settled the one question that decides
everything about it: **the audit reads against the imported state.**  Not a baseline somebody
marks by hand - that version was offered and not taken - and not "compare against yesterday",
which would say something different tomorrow.  The imported state is fixed the moment the data
lands, so the same report says the same thing a month later, whether or not anybody thought to
press a button at the right time.

That decision has one consequence nothing else in the program had to face: **nothing recorded
what a point was when it arrived.**  :mod:`plumbline.core.provenance` records where and when -
the file, the folder, the import, the time - but not the coordinates or the description, and it
travels *with* the point, so a point that is deleted takes its own evidence with it and no one
can tell it was ever there.  Two of the four questions an audit is asked - *which imported points
are gone* and *which ones moved* - cannot be answered from the live point set at all.

So this module keeps a second record: one row per imported point, written at the moment the
import lands, holding the point as it arrived.  It lives in the project
(``Project.settings["point_audit"]``), which means it survives a save, a load and an undo exactly
like everything else, and a project written before this change simply has none - the report says
so rather than inventing a baseline nobody recorded.

The rows are **field data only**.  Reference points (stake-out / control / other) are somebody
else's coordinates on loan, the data-quality checks already set them aside by name, and an audit
of *this job's* field work is what the item asked for.

Three details worth knowing before reading the code:

* **A reprojection is not every point moving.**  A change of coordinate system moves every number
  on the job without changing a single fact about the ground, so the record is converted with it -
  eagerly, by :func:`reprojected`, which :meth:`Project.reproject` calls while the move is
  happening.  That timing is the point: an **assignment** (which changes the name and keeps every
  number, what the CRS dialog's *assign* does) and a **reprojection** (which changes both) look
  identical from the outside, and guessing wrong reports every point on the job as having moved a
  million feet.  Caught at the moment it happens, the two cannot be confused.
* **A tolerance.**  Coordinates are floats: they are compared with a tolerance far below anything
  a person can survey (``DEFAULT_TOLERANCE``, a millionth of a unit), and the actual deltas are
  reported, so nothing hides inside it.
* **The record is not free.**  It roughly doubles the point data in a project file, because it
  holds every imported point twice, once as it arrived and once as it is.  That is the price of
  the decision in the first paragraph, and it is paid once per import, not once per report.
"""
from __future__ import annotations

import copy as _copy
import math
from dataclasses import dataclass, field

from . import cogo
from . import provenance as PROV
from . import reference as REF
from . import units as U

#: The key in ``Project.settings`` holding the baseline.
KEY = "point_audit"

#: How far a coordinate has to move before it counts as a move.  A millionth of a unit is float
#: noise, not a survey: an operation that *should* not move a point (a save, a load, a redraw)
#: leaves it exactly where it was, and anything a person did by hand is orders of magnitude larger.
DEFAULT_TOLERANCE = 1e-6

#: Where the one-line "the ruler changed" note is kept inside the baseline.
NOTE = "crs_note"


def _finite(v) -> bool:
    try:
        return v is not None and math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _row_of(point) -> dict:
    """One point as the baseline keeps it: what it was, and where it came from.

    The provenance is copied in rather than looked up on demand because the point it was copied
    from is exactly the thing that may be gone by the time the audit runs.
    """
    rec = PROV.of(point)
    z = float(point.z)
    return {"id": int(point.id), "number": str(point.number),
            "x": float(point.x), "y": float(point.y),
            "z": (None if not math.isfinite(z) else z),
            "desc": str(point.desc), "layer": str(point.layer),
            "set": rec["set"], "file": rec["file"], "folder": rec["folder"], "when": rec["when"]}


# ----------------------------------------------------------------------------- the baseline
def store(project) -> dict:
    """The baseline itself: the rows, and the coordinate system their numbers are in."""
    return project.settings.setdefault(KEY, {})


def rows(project) -> list[dict]:
    """The imported points as they arrived, in the order they were recorded."""
    return list(store(project).get("rows") or [])


def has_baseline(project) -> bool:
    """True when this project has an imported state to audit against."""
    return bool(store(project).get("rows"))


def recorded_when(project) -> str:
    """When the baseline was last written - "" for a project that has none."""
    return str(store(project).get("recorded", ""))


def crs_note(project) -> str:
    """What the report should say about the ruler the record is kept in, if anything."""
    return str(store(project).get(NOTE, ""))


def record(project, points) -> int:
    """Write these points into the baseline *as they are now*, and say how many were new.

    Called by every door an import can come through, with the points that import just landed.
    A point the import landed on top of (the overwrite duplicate policy) keeps its id, so its row
    is replaced rather than added: what arrived is the imported state, and the audit must not
    report an import's own work as somebody's edit.

    Reference points are not recorded at all; they are not this job's field data.
    """
    pts = [p for p in points if p is not None and not REF.is_reference(p) and getattr(p, "id", 0)]
    if not pts:
        return 0
    st = store(project)
    rebase(project, st)                                  # never mix two rulers in one baseline
    stored = st.setdefault("rows", [])
    index = {int(r["id"]): i for i, r in enumerate(stored)}
    fresh = 0
    for p in pts:
        row = _row_of(p)
        at = index.get(row["id"])
        if at is None:
            index[row["id"]] = len(stored)
            stored.append(row)
            fresh += 1
        else:
            stored[at] = row
    st["crs"] = project.crs.to_dict()
    st["recorded"] = PROV.now()
    return fresh


def clear(project) -> None:
    """Forget the baseline - the audit then has nothing to read against, and says so."""
    project.settings.pop(KEY, None)


# ----------------------------------------------------------------------------- staying on one ruler
def _convert(project, st: dict, old: dict) -> tuple[bool, str]:
    """Move the stored rows from the coordinate system in *old* into the project's current one."""
    from .crs import ProjectCRS

    stored = st.get("rows") or []
    try:
        old_crs = ProjectCRS.from_dict(old)
        fn = project.crs.transform_from(old_crs)
        zs = U.M_PER_UNIT[old_crs.vunit] / U.M_PER_UNIT[project.crs.vunit]
        xs, ys = fn([float(r["x"]) for r in stored], [float(r["y"]) for r in stored])
    except Exception as exc:                             # a local system, a missing grid, bad maths
        return False, (f"the record is in {old.get('name', 'an older system')} and could not be "
                       f"converted into {project.crs.name} ({exc}).")
    for r, x, y in zip(stored, xs, ys):
        r["x"], r["y"] = float(x), float(y)
        if _finite(r.get("z")):
            r["z"] = float(r["z"]) * zs
    st["crs"] = project.crs.to_dict()
    return True, ""


def reprojected(project, old_crs) -> str:
    """The job's data has just been reprojected: move the record with it.

    Called by :meth:`Project.reproject` *while* the move is happening, because that is the only
    moment at which the two facts are both known - that the system changed **and** that every
    number moved.  Worked out later from the two CRS descriptions alone, a reprojection and an
    assignment look the same, and the wrong guess is an audit that reports every point on the job
    as having moved.  Returns a one-line note for the report ("" when there is nothing to say).
    """
    st = store(project)
    if not st.get("rows"):
        return ""
    before = old_crs.to_dict()
    if st.get("crs") != before:
        # The record's label had already drifted from the project's (an assignment since the last
        # import).  Assigning never moves a number, so catch the label up first - then the
        # conversion below is the reprojection's alone.
        st["crs"] = before
    ok, why = _convert(project, st, before)
    if not ok:
        # A record that cannot follow the data is not a record of it any more.  Clearing it is
        # the honest end: the report then says the job has no imported state rather than
        # comparing numbers in two different systems and calling the difference movement.
        st.clear()
        st[NOTE] = f"{why} The record was cleared; the next import into this job starts it again."
        return st[NOTE]
    st[NOTE] = (f"the project was reprojected since the import ({before.get('name', 'older system')} "
                f"to {project.crs.name}); the record was converted into the current system with it.")
    return st[NOTE]


def rebase(project, st: dict | None = None) -> tuple[bool, str]:
    """Catch the record's ruler up with the project's, when only the *name* changed.

    An assignment (the CRS dialog's *assign*, and the import that states a file's system) keeps
    every coordinate exactly where it is and only changes what the numbers are called.  So when
    the stored ruler and the project's disagree and no reprojection has converted them - a
    reprojection does that as it happens, see :func:`reprojected` - the record is **relabelled,
    not transformed**, and the report says which kind of change it was.  Transforming it here
    would move a baseline that never moved and report the whole job as shifted.
    """
    st = store(project) if st is None else st
    stored = st.get("rows") or []
    old = st.get("crs")
    if not stored or not old:
        return True, ""
    now = project.crs.to_dict()
    if old == now:
        return True, ""
    st["crs"] = now
    st[NOTE] = (f"the project's coordinate system was changed from {old.get('name', 'an older system')} "
                f"to {project.crs.name} without the points moving (assigned, not reprojected), so the "
                f"record was relabelled and the coordinates are compared as they stand.")
    return True, st[NOTE]


# ----------------------------------------------------------------------------- the comparison
@dataclass
class Audit:
    """What the audit found.  Lists of plain rows, so a report and a test read the same thing."""

    baseline: int = 0                    # imported points the baseline holds
    now: int = 0                         # field points in the job now
    unchanged: int = 0
    missing: list = field(default_factory=list)      # rows: imported, no longer in the drawing
    added: list = field(default_factory=list)        # rows: no import behind them
    moved: list = field(default_factory=list)        # rows: N/E changed since the import
    changed: list = field(default_factory=list)      # rows: description / number / layer / elevation
    notes: list = field(default_factory=list)        # one-line things the report should say
    tolerance: float = DEFAULT_TOLERANCE

    @property
    def clean(self) -> bool:
        """True when the job is exactly as it arrived (which is worth being able to say)."""
        return not (self.missing or self.added or self.moved or self.changed)

    def summary_line(self) -> str:
        if not self.baseline:
            return "This project has no imported state recorded, so there is nothing to audit."
        if self.clean:
            return f"All {self.now:,} field point(s) are exactly as imported."
        bits = []
        if self.missing:
            bits.append(f"{len(self.missing):,} missing")
        if self.added:
            bits.append(f"{len(self.added):,} added")
        if self.moved:
            bits.append(f"{len(self.moved):,} moved")
        if self.changed:
            bits.append(f"{len(self.changed):,} changed")
        return f"{self.now:,} field point(s) audited: " + ", ".join(bits) + "."


def _kinds_of(row: dict, p, tolerance: float = DEFAULT_TOLERANCE) -> list[str]:
    """What is different about a point, in the words the report prints, in a fixed order."""
    out = []
    if str(p.number) != row["number"]:
        out.append("number")
    if str(p.desc) != row["desc"]:
        out.append("description")
    if str(p.layer) != row["layer"]:
        out.append("layer")
    z0, z1 = row.get("z"), float(p.z)
    if _finite(z0) and _finite(z1):
        if abs(z1 - float(z0)) > tolerance:
            out.append("elevation")
    elif _finite(z0) != _finite(z1):
        out.append("elevation")                          # one of them has none and the other has one
    return out


def compare(project, tolerance: float = DEFAULT_TOLERANCE) -> Audit:
    """Compare the job's field points against the imported state.

    The baseline is read through a *copy* - a report must never write to the thing it is reporting
    on - so running the audit twice, or on a job that has not changed, changes nothing.  The read
    through ``rebase`` is the one exception, and it only relabels: an assignment that leaves every
    number where it is has to be noticed by whichever call comes first, and saying so on the next
    report is the point of it.
    """
    st = _copy.deepcopy(store(project))
    stored = list(st.get("rows") or [])
    if stored:
        rebase(project, st)
        stored = list(st.get("rows") or [])
    live = REF.survey_points(project)
    a = Audit(baseline=len(stored), now=len(live), tolerance=float(tolerance))
    if st.get(NOTE):
        a.notes.append(str(st[NOTE]))
    if not stored:
        a.notes.append("No import has recorded what the points were, so nothing can be compared. "
                       "The next import into this job starts the record.")
        return a
    base = {int(r["id"]): r for r in stored}
    seen = set()
    for p in live:
        pid = int(p.id)
        seen.add(pid)
        row = base.get(pid)
        if row is None:
            a.added.append(_added_row(p))
            continue
        dn, de = float(p.y) - float(row["y"]), float(p.x) - float(row["x"])
        dist = math.hypot(dn, de)
        if dist > tolerance:
            dz = None
            if _finite(row.get("z")) and _finite(p.z):
                dz = float(p.z) - float(row["z"])
            a.moved.append({"id": pid, "number": str(p.number), "before_number": row["number"],
                            "dn": dn, "de": de, "dz": dz, "dist": dist,
                            "azimuth": cogo.azimuth_deg(de, dn),
                            "file": row["file"], "set": row["set"], "when": row["when"],
                            "x": float(p.x), "y": float(p.y),
                            "x0": float(row["x"]), "y0": float(row["y"]),
                            "z0": (float(row["z"]) if _finite(row.get("z")) else None)})
        kinds = _kinds_of(row, p, tolerance)
        if kinds:
            a.changed.append({"id": pid, "number": str(p.number), "kinds": kinds,
                              "before_number": row["number"], "before_desc": row["desc"],
                              "after_desc": str(p.desc), "before_layer": row["layer"],
                              "after_layer": str(p.layer),
                              "z0": (float(row["z"]) if _finite(row.get("z")) else None),
                              "z": float(p.z), "file": row["file"], "set": row["set"],
                              "when": row["when"]})
    a.missing = [dict(r) for r in stored if int(r["id"]) not in seen]
    a.unchanged = max(0, len(live) - len(a.added)
                      - len({m["id"] for m in a.moved} | {c["id"] for c in a.changed}))
    return a


def _added_row(p) -> dict:
    """A point that is here now and was not imported - where it is, and anything it does say."""
    rec = PROV.of(p)
    return {"id": int(p.id), "number": str(p.number), "x": float(p.x), "y": float(p.y),
            "z": float(p.z), "desc": str(p.desc), "layer": str(p.layer), "role": REF.role_of(p),
            "set": rec["set"], "file": rec["file"], "when": rec["when"]}


def describe(project) -> str:
    """One line for the status bar or a dock: what there is to audit against."""
    if not has_baseline(project):
        return "No imported state recorded yet."
    n = len(rows(project))
    when = recorded_when(project)
    return f"{n:,} imported point(s) on record" + (f", last written {when[:10]}." if when else ".")


__all__ = ["KEY", "NOTE", "DEFAULT_TOLERANCE", "Audit", "store", "rows", "has_baseline",
           "recorded_when", "crs_note", "record", "clear", "reprojected", "rebase", "compare",
           "describe"]
