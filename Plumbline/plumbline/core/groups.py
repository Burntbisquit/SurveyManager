"""Object groups: name a set of objects, then turn the whole set on and off.

Item 2 of the change order.  A *layer* is what an object **is** - points, a fence line, a
building - and it is fixed when the object is drawn.  A *group* is what the object is **for** on
this job: "the 2023 topo", "the client's boundary", "everything west of the creek", "the part the
engineer has not seen yet".  The same point can be in as many groups as it likes, or none, and a
group can hold points, polylines, text and surfaces together - which is what makes it useful.

The rule the user set is that a group that is switched off is **hidden everywhere**: not just off
the drawing, but out of the exports and out of the surfaces.  A fence line you cannot see but
which still exports is a data-integrity problem, not a display setting.  So the hidden ids are
consulted in one place - :meth:`plumbline.core.project.Project.hidden_ids` - and the drawing, the
DXF / LandXML / GIS / KML / report writers and the surface builder all go through it.

Group membership is by **object id**, and ids are unique across points, entities and surfaces in a
project (one counter, ``Project.new_id``), so a group never has to say *what kind* of thing it
holds.  Ids survive save and load, which is what makes a group worth keeping in the project rather
than in the window.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ObjectGroup:
    name: str
    oids: list = field(default_factory=list)     # object ids (points, entities and surfaces)
    visible: bool = True

    @property
    def count(self) -> int:
        return len(self.oids)

    def to_dict(self) -> dict:
        return {"name": self.name, "oids": [int(i) for i in self.oids], "visible": bool(self.visible)}

    @classmethod
    def from_dict(cls, d: dict) -> "ObjectGroup":
        return cls(str(d.get("name", "")), [int(i) for i in d.get("oids", [])], bool(d.get("visible", True)))


class GroupSet:
    """The groups on one project, in the order they were made.

    Names are unique and compared without case, because two groups called "Sequence 3" and
    "sequence 3" in one list is a mistake waiting to happen.  Empty groups are allowed - naming a
    group and then filling it from the selection is a natural order of work - but an empty group
    is called out in the dock so it is not mistaken for a group whose objects have gone.
    """

    def __init__(self, groups: list[ObjectGroup] | None = None):
        self.groups: list[ObjectGroup] = list(groups or [])

    # -- reading
    def __len__(self) -> int:
        return len(self.groups)

    def __iter__(self):
        return iter(self.groups)

    def names(self) -> list[str]:
        return [g.name for g in self.groups]

    def get(self, name: str) -> ObjectGroup | None:
        low = str(name).strip().lower()
        return next((g for g in self.groups if g.name.lower() == low), None)

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def hidden_ids(self) -> set:
        """Every object id in a group that is switched off - the one answer to "is it hidden?"."""
        out: set = set()
        for g in self.groups:
            if not g.visible:
                out.update(g.oids)
        return out

    def groups_of(self, oid) -> list[str]:
        return [g.name for g in self.groups if oid in g.oids]

    def visible_group_names(self) -> list[str]:
        return [g.name for g in self.groups if g.visible]

    # -- writing (each returns the group it touched, or None)
    def create(self, name: str, oids=()) -> ObjectGroup:
        name = str(name).strip()
        if not name:
            raise ValueError("a group needs a name")
        if self.has(name):
            raise ValueError(f"there is already a group called '{name}'")
        g = ObjectGroup(name, _clean(oids))
        self.groups.append(g)
        return g

    def remove(self, name: str) -> bool:
        g = self.get(name)
        if g is None:
            return False
        self.groups.remove(g)
        return True

    def rename(self, old: str, new: str) -> ObjectGroup:
        g = self.get(old)
        if g is None:
            raise KeyError(old)
        new = str(new).strip()
        if not new:
            raise ValueError("a group needs a name")
        other = self.get(new)
        if other is not None and other is not g:
            raise ValueError(f"there is already a group called '{new}'")
        g.name = new
        return g

    def set_visible(self, name: str, on: bool) -> ObjectGroup:
        g = self.get(name)
        if g is None:
            raise KeyError(name)
        g.visible = bool(on)
        return g

    def toggle(self, name: str) -> ObjectGroup:
        g = self.get(name)
        if g is None:
            raise KeyError(name)
        g.visible = not g.visible
        return g

    def show_all(self) -> None:
        for g in self.groups:
            g.visible = True

    def add(self, name: str, oids) -> ObjectGroup:
        g = self.get(name)
        if g is None:
            raise KeyError(name)
        seen = set(g.oids)
        for i in _clean(oids):
            if i not in seen:
                g.oids.append(i)
                seen.add(i)
        return g

    def discard(self, name: str, oids) -> ObjectGroup:
        g = self.get(name)
        if g is None:
            raise KeyError(name)
        drop = _clean(oids)
        g.oids = [i for i in g.oids if i not in drop]
        return g

    def remove_objects(self, oids) -> int:
        """Take these objects out of every group (they were deleted).  Returns how many groups changed."""
        drop = _clean(oids)
        n = 0
        for g in self.groups:
            keep = [i for i in g.oids if i not in drop]
            if len(keep) != len(g.oids):
                g.oids = keep
                n += 1
        return n

    # -- persistence
    def to_list(self) -> list[dict]:
        return [g.to_dict() for g in self.groups]

    @classmethod
    def from_list(cls, rows) -> "GroupSet":
        out: list[ObjectGroup] = []
        seen: set[str] = set()
        for r in (rows or []):
            try:
                g = ObjectGroup.from_dict(r) if isinstance(r, dict) else ObjectGroup(str(r))
            except Exception:
                continue
            if not g.name or g.name.lower() in seen:
                continue
            seen.add(g.name.lower())
            out.append(g)
        return cls(out)


def _clean(oids) -> list[int]:
    out = []
    for i in (oids or ()):
        try:
            out.append(int(i))
        except (TypeError, ValueError):
            continue
    return out


__all__ = ["ObjectGroup", "GroupSet"]
