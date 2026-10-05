"""Reference points: stake-out, control and other coordinates that arrive in a CSV.

A CSV of stake-out shots, published control coordinates, or a point file from another agency is
*reference* data.  It belongs on the drawing - you want to see it, stake from it and check the
field against it - but it is not field data: this job's crews did not shoot it, it is not part of
the fieldwork list, and it must not be counted, checked or renumbered beside the points that were.

So it gets its own list:

======================  ==================  ==================================================
role                    layer               what goes there
======================  ==================  ==================================================
``stakeout``            ``STAKE-OUT``       points to be set out from the design
``control``             ``CONTROL``         published control, other agencies' coordinates
``other``               ``OTHER``           anything else that is reference only
======================  ==================  ==================================================

The points themselves live in the project's own point store - so they draw, snap, select, move
and export with everything else - tagged in ``attrs["reference"]``.  :func:`is_reference` is then
the one question every field-data path asks before it treats a point as its own, and
:func:`survey_points` is the answer to "which points are this job's field data?".

Each role has its own numbering space: a stake-out list numbered from 1 does not collide with
field points numbered from 1, and importing one role never renumbers another.
"""
from __future__ import annotations

import math

from .model import Layer, SurveyPoint

#: The roles, in the order they are offered in the interface.
ROLES = ("stakeout", "control", "other")

ROLE_LABELS = {"stakeout": "Stake-out", "control": "Control", "other": "Other"}

#: One layer per role.  Plain names on purpose - these are the layers a user looks for.
ROLE_LAYER = {"stakeout": "STAKE-OUT", "control": "CONTROL", "other": "OTHER"}

ROLE_COLOR = {"stakeout": (255, 214, 102), "control": (108, 214, 255), "other": (206, 170, 255)}

ROLE_NOTE = {
    "stakeout": "points to be set out - reference, not field data",
    "control": "published or other-agency control - reference, not field data",
    "other": "reference coordinates - not field data",
}

#: The key written into ``SurveyPoint.attrs``.  One key, one meaning, used everywhere.
ATTR = "reference"


def is_role(role) -> bool:
    return role in ROLES


def layer_for(role: str) -> str:
    """The layer a role's points live on."""
    return ROLE_LAYER.get(role, "OTHER")


def label_for(role: str) -> str:
    return ROLE_LABELS.get(role, "Other")


def role_of(point) -> str | None:
    """The role a point was imported as, or None for a point that is not reference data."""
    role = (getattr(point, "attrs", None) or {}).get(ATTR)
    return role if role in ROLES else None


def is_reference(point) -> bool:
    """True for stake-out / control / other points - the ones that are not field data."""
    return role_of(point) is not None


def mark(point, role: str):
    """Tag one point as reference data of *role* and put it on that role's layer."""
    if role not in ROLES:
        raise ValueError(f"Unknown reference role {role!r} - expected one of {', '.join(ROLES)}.")
    point.attrs = dict(point.attrs or {})
    point.attrs[ATTR] = role
    point.layer = layer_for(role)
    return point


def mark_batch(batch, role: str):
    """Tag every point in an import batch and give the batch its layer definition."""
    for p in batch.points:
        mark(p, role)
    if batch.points:
        name = layer_for(role)
        batch.layers.setdefault(name, Layer(name, ROLE_COLOR[role]))
    return batch


def ensure_layers(project):
    """Make sure the three reference layers exist, with their own colours."""
    for role in ROLES:
        project.ensure_layer(layer_for(role), ROLE_COLOR[role])
    return project


def reference_points(project, role: str | None = None) -> list:
    """The reference points of a project (all of them, or one role), newest last."""
    return [p for p in project.points.values() if is_reference(p) and (role is None or role_of(p) == role)]


def survey_points(project) -> list:
    """The project's field data: every point that is *not* reference data.

    This is "the fieldwork list" as far as the rest of the program is concerned.  Anything that
    counts, checks, renumbers or reports field points asks for this, not ``project.points``.
    """
    return [p for p in project.points.values() if not is_reference(p)]


def select(project, source, only_ids=None) -> list:
    """The point list a source name asks for.

    *source* is None (the fieldwork list), a role name, or ``"all"`` (everything, reference
    included).  *only_ids* narrows it to a selection, when one is being used.
    """
    if source == "all":
        pts = list(project.points.values())
    elif is_role(source):
        pts = reference_points(project, source)
    else:
        pts = survey_points(project)
    if only_ids is not None:
        pts = [p for p in pts if p.id in only_ids]
    return pts


def counts(project) -> dict:
    """How many points each list holds - used to word the menus and dialogs honestly."""
    out = {role: 0 for role in ROLES}
    n_survey = 0
    for p in project.points.values():
        role = role_of(p)
        if role:
            out[role] += 1
        else:
            n_survey += 1
    out["survey"] = n_survey
    return out


def add_one(project, x, y, z=math.nan, number: str | None = None, desc: str = "", role: str = "stakeout"):
    """Add a single reference point by hand (the point tool, with a reference role chosen)."""
    ensure_layers(project)
    p = project.add_point(x, y, z, number=number, desc=desc, layer=layer_for(role))
    return mark(p, role)


def next_number(project, role: str) -> str:
    """The first free number in a role's own list (its numbering space, not the field's)."""
    used = set()
    for p in reference_points(project, role):
        try:
            used.add(int(float(p.number)))
        except (TypeError, ValueError):
            continue
    n = 1
    while n in used:
        n += 1
    return str(n)


def describe(project) -> str:
    """One line for the status bar: what reference data this drawing carries."""
    cnt = counts(project)
    bits = [f"{cnt[r]:,} {ROLE_LABELS[r].lower()}" for r in ROLES if cnt[r]]
    return ("Reference: " + ", ".join(bits)) if bits else "No reference points."


def remove_all(project, role: str | None = None) -> int:
    """Delete reference points (one role, or all of them).  Field data is never touched."""
    doomed = [p.id for p in reference_points(project, role)]
    project.remove_points(doomed)
    return len(doomed)


__all__ = ["ROLES", "ROLE_LABELS", "ROLE_LAYER", "ROLE_COLOR", "ROLE_NOTE", "ATTR", "is_role",
           "layer_for", "label_for", "role_of", "is_reference", "mark", "mark_batch",
           "ensure_layers", "reference_points", "survey_points", "select", "counts", "add_one",
           "next_number", "describe", "remove_all"]
