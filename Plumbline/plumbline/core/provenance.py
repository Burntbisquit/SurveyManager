"""Where each point came from - the provenance Fieldwork Manager keeps in its working file.

The field-data pipeline has always carried two provenance columns beside the coordinates:
**Parent Folder** and **Source File** (columns 7 and 8 of a ``.fwk`` working file).  They are what
lets a person answer the two questions that come up on every job: *which download is this point
from*, and *which crew shot it*.  Until now Plumbline dropped them at the doorstep - the field
window's import kept the source file on the point (``attrs["fieldwork_source"]``) but nothing else
did, and nothing on screen showed it.

This module gives every imported point a small record of its own:

    point.attrs["import"] = {"file": "crew6.csv", "folder": "Field Data/Week 1/Crew 6",
                             "set":  "Cleaned field data", "when": "2026-10-04T06:20:11"}

* **file** - the file the point was read from, as the user sees it (a name, not a path).
* **folder** - the folder that file was in, relative to the job folder when it can be.
* **set** - the import as a whole, in the words the interface used: "Stake-out list.csv",
  "Control points from Survey/Control", "Google Earth pins", "Cleaned field data (crew 6)".
* **when** - when it landed, to the second.

One key, one meaning, read by everybody: the point list's optional columns, the Properties panel,
the Check Fieldwork dock's header, and (as a fallback) the field window's older
``fieldwork_source`` key.  Nothing here is load-bearing for the drawing: a project whose points
have no record shows empty columns rather than guessing, and a project written before this change
simply has none.

The time is stored as a string on purpose.  It is a label - "when did this arrive" - and a string
survives a save/load round trip, an undo and a file written by another version without any of them
having to agree about a datetime type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

#: The key in ``SurveyPoint.attrs``.
ATTR = "import"

#: The record's fields, in the order the interface shows them.
FIELDS = ("file", "folder", "set", "when")

#: (column key, column heading) for the point list, in the order they are appended.
COLUMNS = (("source_file", "Source File"), ("source_folder", "Parent Folder"),
           ("imported", "Imported"), ("import_set", "Import"))

#: The two the working file has always carried, so they are on until somebody turns them off.
DEFAULT_COLUMNS = ("source_file", "source_folder")


@dataclass(frozen=True)
class Source:
    """One import, as the importer can describe it."""

    file: str = ""
    folder: str = ""
    set: str = ""
    when: str = ""


def now() -> str:
    """The stamp a fresh import gets: local time, seconds, ISO - sorts as text, reads as text."""
    return datetime.now().replace(microsecond=0).isoformat(sep="T")


def file_name(text) -> str:
    """The file's own name, from a path written either way round.

    A field file's Source column is written by a Windows program, so it arrives as
    ``2026-07-19-S1\\2026-07-19GPS S1.csv`` wherever it is read - and on a Linux box ``Path`` does
    not treat a backslash as a separator.  The folder half belongs in the folder column, so the
    name is taken from the last separator of either kind.
    """
    parts = re.split(r"[\\/]+", str(text or "").strip())
    return parts[-1] if parts else ""


def make(file="", folder="", set="", when="") -> Source:
    """A Source with the time filled in, and paths reduced to what a person reads.

    A folder is stored relative to the job folder when it is inside it ("Field Data/Week 1/Crew 6"
    rather than "C:/Jobs/23-036/Field Data/Week 1/Crew 6"): the job travels, and a column that is
    three quarters the same prefix on every row is a column nobody reads.
    """
    return Source(file=file_name(file),
                  folder=short_folder(folder), set=str(set or ""), when=when or now())


def short_folder(folder, job_root=None) -> str:
    """A folder as it should be shown: inside the job folder, relative; otherwise as given."""
    if not folder:
        return ""
    p = Path(str(folder))
    if p.parts in ((), (".",), ("",)):
        return ""                    # a bare file name has no folder worth showing
    if job_root:
        try:
            return str(p.relative_to(Path(job_root)))
        except ValueError:
            pass
    return str(p)


def stamp_one(point, *, file="", folder="", set="", when="") -> None:
    """Record where one point came from."""
    if point is None:
        return
    if point.attrs is None:
        point.attrs = {}
    point.attrs[ATTR] = {"file": file_name(file), "folder": str(folder or ""),
                         "set": str(set or ""), "when": str(when or now())}


def stamp(points, **kw) -> int:
    """Record the same provenance on a batch of points.  Returns how many were stamped."""
    n = 0
    for p in points or ():
        stamp_one(p, **kw)
        n += 1
    return n


def set_label(label: str) -> str:
    """The import's own name, as the interface said it: "points (crew6.csv)" -> "points".

    The file name is already in its own column; repeating it inside the import's name makes a
    column that says the same thing twice and groups nothing.
    """
    text = str(label or "").strip()
    if text.endswith(")") and "(" in text:
        text = text[:text.rindex("(")].strip()
    return text or "Imported points"


def of(point) -> dict:
    """A point's provenance: what was recorded, plus the field window's older key as a fallback."""
    attrs = getattr(point, "attrs", None) or {}
    rec = attrs.get(ATTR) or {}
    out = {k: str(rec.get(k, "") or "") for k in FIELDS}
    if not out["file"]:
        out["file"] = file_name(attrs.get("fieldwork_source", ""))
    if not out["folder"]:
        out["folder"] = str(attrs.get("fieldwork_folder", "") or "")
    return out


def value(point, key: str) -> str:
    """The text a column shows for one point, or "" when there is nothing to say."""
    rec = of(point)
    if key == "source_file":
        return rec["file"]
    if key == "source_folder":
        return rec["folder"]
    if key == "import_set":
        return rec["set"]
    if key == "imported":
        when = rec["when"]
        return f"{when[:10]} {when[11:16]}" if len(when) >= 16 else when
    if key == "modified":
        return "Yes" if getattr(point, "is_modified", False) else "No"
    if key == "orig_coords":
        if getattr(point, "is_modified", False):
            import math
            z_str = "" if math.isnan(point.orig_z) else f", Z {point.orig_z:,.3f}"
            return f"N {point.orig_y:,.3f}, E {point.orig_x:,.3f}{z_str}"
        return ""
    if key == "delta_xy":
        d = getattr(point, "delta_xy", 0.0)
        return f"{d:.3f}" if d > 0.0001 else ""
    return ""


def describe(point) -> str:
    """One line for the Properties panel: file, folder, when - or "" when the point has none."""
    rec = of(point)
    where = rec["file"] or "an unnamed file"
    if rec["folder"]:
        where += f" in {rec['folder']}"
    when = value(point, "imported")
    line = f"{where} - imported {when}" if when else where
    if rec["set"]:
        line += f" ({rec['set']})"
    return line if (rec["file"] or rec["folder"] or rec["when"] or rec["set"]) else ""


def history(project, limit: int = 200) -> list[dict]:
    """Every import the project's points remember, newest first, with a point count.

    Grouped by (set, file, folder, when): one row per file per import, which is how a person
    remembers it - "the three crew files from Tuesday", not 3,773 identical stamps.
    """
    seen: dict[tuple, int] = {}
    for p in project.points.values():
        rec = of(p)
        if not any(rec.values()):
            continue
        key = (rec["set"], rec["file"], rec["folder"], rec["when"])
        seen[key] = seen.get(key, 0) + 1
    rows = [{"set": k[0], "file": k[1], "folder": k[2], "when": k[3], "points": n}
            for k, n in seen.items()]
    rows.sort(key=lambda r: (r["when"], r["set"], r["file"]), reverse=True)
    return rows[:limit]


def column_label(key: str) -> str:
    """The heading for a column key, or the key itself if it is not one of ours."""
    for k, label in COLUMNS:
        if k == key:
            return label
    return key


def summary(project) -> str:
    """One line for a dock or a report: how many points came from how many files and folders."""
    pts = [p for p in project.points.values() if any(of(p).values())]
    if not pts:
        return "No imported points carry provenance yet."
    files = {of(p)["file"] for p in pts if of(p)["file"]}
    folders = {of(p)["folder"] for p in pts if of(p)["folder"]}
    bits = [f"{len(pts):,} point(s)"]
    if files:
        bits.append(f"{len(files):,} source file(s)")
    if folders:
        bits.append(f"{len(folders):,} folder(s)")
    return " from ".join([bits[0], ", ".join(bits[1:])]) + "."
