"""What goes and gets itself on first run - and what does not ship in the zip at all.

Item 9 of the change order, in the user's words:

    "flags to download shipped when installed / first run, so not packaged but default download
     when first run.  do this for all external references to keep the ship small."

So the rule for this program is:

* **nothing large ships inside the package** - no geoid grids, no datum shift grids, no imagery,
  no coordinate-system grid files.  The package carries *definitions* (EPSG parameters from PROJ,
  the datum and geoid tables in :mod:`plumbline.core.vdatum`) and **flags** saying where the data
  comes from;
* **on first run the flags default to on** - the download is offered, ticked, with the sizes, and
  the answer is remembered.  A surveyor who installs this on a laptop with a metered connection
  unticks the big ones and is asked again never;
* **after that the flags are the registry** (:mod:`plumbline.core.registry`): every source listed,
  editable when it moves, switchable, restorable.  That is the same table, so there is one place
  a URL lives.

What is *not* downloaded here: imagery tiles.  Those are a cache - the first pan of the map fetches
the tiles it needs and nothing else - and pre-downloading a country of satellite imagery would be
gigabytes for no reason.  Their flags are in the registry, not in this plan.

The plan is pure: :func:`plan` computes what *would* be fetched and how big it is, and
:func:`download` does it with a progress callback and a cancel check.  Nothing here touches the
network at import time, so a test can read the plan on a machine with no connection.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .settings import settings

#: One-time question answered (the answer is remembered in settings under this key).
PROMPT_KEY = "external_prompt_done"


@dataclass
class Item:
    """One thing that can be fetched, with what it is for and roughly how big it is."""

    key: str                       # a registry key ("geoid:GEOID18"), so the registry can edit it
    title: str
    why: str
    mb: float = 0.0                # rough size, for the tick boxes
    needed_by: tuple = ()          # what stops working without it
    url: str = ""

    @property
    def size(self) -> str:
        if self.mb >= 1000:
            return f"{self.mb / 1000:.1f} GB"
        if self.mb >= 1:
            return f"{self.mb:.0f} MB"
        return f"{self.mb * 1000:.0f} kB"


#: Rough, published sizes.  Only used to let a user make a decision - the download itself reports
#: what it actually got.
SIZES = {
    "us_noaa_g2018u0.tif": 400.0,       # GEOID18, CONUS, 1' grid
    "us_noaa_g2012bu0.tif": 250.0,
    "us_noaa_g1999u01.tif": 40.0,
    "us_noaa_vertconc.tif": 3.0,        # VERTCON, central
}


def geoid_items() -> list[Item]:
    from . import vdatum as VD
    out = []
    for m in VD.GEOID_MODELS:
        mb = sum(SIZES.get(g, 5.0) for g in m.grids)
        out.append(Item(key=f"geoid:{m.key}", title=f"Geoid {m.name} ({m.region})",
                        why=f"{m.note}  Ties orthometric heights to the ellipsoid; without it a "
                            f"geoid separation cannot be computed and the program says so instead "
                            f"of guessing.",
                        mb=mb, needed_by=("vertical datum conversion", "NAVD88 + ellipsoid heights")))
    out.append(Item(key="geoid:VERTCON", title="VERTCON (NGVD29 <-> NAVD88)",
                    why="Relates the old NGVD29 datum to NAVD88 where a job still carries NGVD29 "
                        "heights.  Small, and used more often than people expect.",
                    mb=sum(SIZES.get(g, 2.0) for g in VD.VERTCON_GRIDS),
                    needed_by=("NGVD29 jobs",)))
    return out


def crs_items() -> list[Item]:
    """The coordinate-system side: the network grid endpoint, and nothing else to fetch."""
    return [Item(key="crs:network-grids", title="Datum shift grids (PROJ CDN)",
                 why="Some coordinate systems need a datum-shift grid (NAD27 to NAD83, for "
                     "example).  PROJ fetches each one the first time it is needed and keeps it.",
                 mb=60.0, needed_by=("legacy datum conversions",),
                 url=str(settings().get("proj_grid_url") or "https://cdn.proj.org"))]


def imagery_items() -> list[Item]:
    """Imagery is a cache, not a download: say what it costs without pretending to fetch it."""
    return [Item(key="imagery:cache", title="Imagery and map tiles on demand",
                 why="Imagery is fetched a tile at a time as you look at the map and cached on "
                     "disk, so there is nothing to download now.  The sources, and what to do when "
                     "one moves, are in the registry.",
                 mb=0.0, needed_by=("imagery",), url="")]


def plan(include_optional: bool = True) -> list[Item]:
    """Everything the first run would fetch, biggest first.  Pure - no network, no writes."""
    items = geoid_items() + crs_items() + imagery_items()
    return sorted(items, key=lambda i: -i.mb) if include_optional else items


def total_mb(items) -> float:
    return float(sum(i.mb for i in items))


def already_asked() -> bool:
    """Has the offer been made in this installation?  "Later" counts as an answer: the list lives
    in Settings > External data sources from then on, which is where a user who wants it later
    will look."""
    return bool(settings().get(PROMPT_KEY))


def mark_asked(what: str = "offered") -> None:
    """Remember that the offer was made and what came of it (offered / later / downloaded / ...)."""
    settings().set(PROMPT_KEY, {"answer": str(what), "when": _now()})


def _now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def grid_present(key: str) -> bool:
    """Is a geoid model's grid usable right now?  (The test the conversion itself uses.)"""
    from . import vdatum as VD
    if key.startswith("geoid:") and key != "geoid:VERTCON":
        st = VD.grid_state(key.split(":", 1)[1])
        return bool(st.get("present"))
    if key == "geoid:VERTCON":
        return VD.vertcon_shift(-96.6, 32.8, allow_download=False) is not None
    if key == "crs:network-grids":
        return True                      # nothing to hold on disk: fetched per conversion
    return True


def download(items, progress=None, is_cancelled=None) -> dict:
    """Fetch what is missing.  Returns ``{"done", "skipped", "failed", "bytes"}``.

    The only real fetching in this program that is a *choice*: geoid and datum grids.  It is done
    through PROJ, which is what will need them at conversion time anyway, so there is one download
    path rather than two that can disagree about where a grid lives.  Each item is attempted on its
    own: a machine with no route to the CDN still gets everything else, and the failure is
    reported with the item that caused it rather than stopping the run.
    """
    from . import vdatum as VD

    out = {"done": [], "skipped": [], "failed": [], "bytes": 0}
    items = list(items)
    for n, item in enumerate(items):
        if is_cancelled is not None and is_cancelled():
            out["cancelled"] = True
            break
        if progress is not None:
            progress(n / max(1, len(items)), f"{item.title}")
        if item.mb <= 0 or grid_present(item.key):
            out["skipped"].append(item.key)
            continue
        try:
            _fetch(item)
            out["done"].append(item.key)
            out["bytes"] += int(item.mb * 1024 * 1024)
        except Exception as ex:                        # no route, no CDN, no permission
            out["failed"].append((item.key, str(ex)))
    if progress is not None:
        progress(1.0, "done")
    return out


def _fetch(item: Item):
    """Fetch one item through PROJ, by asking it for a value only the grid can give.

    ``+proj=vgridshift`` with downloads allowed is exactly what a conversion does, so this fetches
    the real file into the real cache - not a copy in a second location that a later conversion
    would not find.
    """
    from . import vdatum as VD

    if item.key == "geoid:VERTCON":
        if VD.vertcon_shift(-96.6, 32.8, allow_download=True) is None:
            raise RuntimeError("VERTCON could not be fetched (no route to cdn.proj.org?)")
        return
    if item.key.startswith("geoid:"):
        key = item.key.split(":", 1)[1]
        was = VD.allow_downloads(True)
        try:
            if VD.separation(-96.6, 32.8, key) is None:
                raise RuntimeError(f"{key} could not be fetched (no route to cdn.proj.org?)")
        finally:
            VD.allow_downloads(was)
        return
    if item.key == "crs:network-grids":
        # Nothing to fetch up front: PROJ pulls the one grid a conversion needs, when it needs it.
        return
    return


__all__ = ["Item", "plan", "total_mb", "download", "already_asked", "mark_asked", "grid_present",
           "PROMPT_KEY", "geoid_items", "crs_items", "imagery_items"]
