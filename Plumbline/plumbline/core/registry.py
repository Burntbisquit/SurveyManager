"""Every place this program pulls data from, in one list, with a door to fix each of them.

Item 3 of the change order: *"any references to a pull site must be listed, and editable when the
site moves"*.  That is not one dialog per feature - it is one table, because the failure mode this
prevents is the one nobody can find: a template URL buried in a module that 404s two years after
the product ships, or an imagery server that starts answering with somebody else's watermark.

The registry is built **from the code that actually fetches**, not from a hand-written copy:

* imagery tile templates come from :data:`plumbline.core.tiles.PRESETS` and the user's own
  ``custom_tile_sources`` - the same list the Imagery dock offers;
* geoid models, VERTCON grids and the datum definitions come from :mod:`plumbline.core.vdatum`;
* coordinate-system definitions come from PROJ, whose network grid endpoints are here too;
* the software update link and the plugin folders are here for the same reason as the rest.

Each entry knows whether it is **built in** (a copy of the program's own default, restorable with
one button) or **added by the user**, whether it is **on**, what **formats** are accepted where a
format is meaningful (imagery tiles are PNG/JPEG or a WMS/WMTS service; geoid grids are a `.tif`,
`.gtx`, `.bin` set that PROJ reads), and what **terms** apply - the licence in Part 1 exists
because some of these sources may not be used commercially, so the registry says so next to the
source rather than in a separate document.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .settings import settings

KIND_IMAGERY = "imagery"
KIND_CRS = "coordinate system"
KIND_GEOID = "geoid / vertical"
KIND_SOFTWARE = "software"
KIND_FOLDER = "folder"

#: What each kind of source accepts, shown in the editor and in the printed list (item 3: "show
#: accepted formats where possible").  This is the same information the loaders enforce.
FORMATS = {
    KIND_IMAGERY: "Tiles: PNG or JPEG over XYZ  |  services: WMTS 1.0.0, WMS 1.1.1/1.3.0 (GeoTIFF or PNG)",
    KIND_CRS: "AUTHORITY:CODE, a PROJ string, or a WKT file (.wkt / .prj).  Network grids: GeoTIFF, "
              "or PROJ's own GTX/BIN records",
    KIND_GEOID: "Geoid model: GeoTIFF (.tif) or GTX (.gtx)  |  VERTCON: binary .bin  |  "
                "PROJ reads any of them from the download folder",
    KIND_SOFTWARE: "A URL (https), a mapped drive, or a folder on this machine",
    KIND_FOLDER: "Any folder on this machine, or a UNC path (\\\\server\\share)",
}


@dataclass
class Site:
    """One pull site: what it is for, where it is, and whether it is on."""

    key: str
    kind: str
    name: str
    value: str
    builtin: bool = True
    enabled: bool = True
    editable: bool = True
    formats: str = ""
    terms: str = ""
    note: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def where(self) -> str:
        return "built in" if self.builtin else "added by you"

    @property
    def state(self) -> str:
        return "on" if self.enabled else "off"


# --------------------------------------------------------------------------------------------- build
def _geoid_endpoint() -> str:
    return str(settings().get("proj_grid_url") or "https://cdn.proj.org").rstrip("/")


def _imagery_sites() -> list[Site]:
    """Tile templates, straight out of tiles.PRESETS plus whatever the user added."""
    from . import tiles
    st = settings()
    custom = list(st.get("custom_tile_sources") or [])
    replaced = set(st.get("replaced_tile_sources") or [])
    hidden = set(st.get("hidden_tile_sources") or [])
    by_name = {}
    for c in custom:
        by_name[str(c.get("name") or "")] = c
    out = []
    for preset in tiles.PRESETS:
        c = by_name.get(preset.name, {})
        out.append(Site(
            key=f"imagery:{preset.name}", kind=KIND_IMAGERY, name=preset.name,
            value=str(c.get("url") or preset.url),
            builtin=True, enabled=(preset.name not in hidden),
            formats=FORMATS[KIND_IMAGERY], terms=preset.attribution,
            note=("Tile template - {z} {x} {y} are filled in.  Edit it if the service moves or you "
                  "want a different source; Restore puts the shipped one back."
                  + ("  **Replaced** - this name now points at your own URL." if preset.name in replaced else "")),
            extra={"preset_url": preset.url, "min_zoom": preset.min_zoom, "max_zoom": preset.max_zoom,
                   "tile_size": preset.tile_size, "ext": preset.ext, "replaced": preset.name in replaced}))
    for c in custom:
        name = str(c.get("name") or "")
        if any(p.name == name for p in tiles.PRESETS):
            continue
        out.append(Site(key=f"imagery:{name}", kind=KIND_IMAGERY, name=name,
                        value=str(c.get("url") or ""), builtin=False,
                        enabled=True, formats=FORMATS[KIND_IMAGERY],
                        terms=str(c.get("attribution") or ""),
                        note="Added by you.  Remove it and it goes off the Imagery menu.",
                        extra={"custom": True, "min_zoom": c.get("min_zoom"),
                               "max_zoom": c.get("max_zoom")}))
    return out


def _geoid_sites() -> list[Site]:
    """The geoid, VERTCON and datum definitions: what is shipped, what must be fetched.

    Every grid here is fetched from **one** endpoint - the PROJ CDN (or the user's mirror), the
    same one the coordinate-system rows point at - so every row's URL is editable and editing any
    of them moves the endpoint for all of them.  The registry says that out loud rather than
    pretending the rows are independent.
    """
    from . import vdatum
    base = _geoid_endpoint()
    out = []
    for m in vdatum.GEOID_MODELS:
        files = ", ".join(m.grids)
        out.append(Site(key=f"geoid:{m.key}", kind=KIND_GEOID, name=f"Geoid {m.name}",
                        value=f"{base}/{m.grids[0]}",
                        formats=FORMATS[KIND_GEOID],
                        terms="NOAA/NGS - public domain (US Government work)",
                        note=f"Region {m.region}, stated accuracy {m.accuracy_m:g} m.  "
                             f"{len(m.grids)} grid file(s): {files}.  Downloaded on demand, "
                             f"never shipped ({m.note})",
                        extra={"geoid": m.key, "endpoint": base}))
    out.append(Site(key="geoid:VERTCON", kind=KIND_GEOID, name="VERTCON (NGVD29 -> NAVD88)",
                    value=f"{base}/{vdatum.VERTCON_GRIDS[0]}",
                    formats=FORMATS[KIND_GEOID],
                    terms="NOAA/NGS - public domain (US Government work)",
                    note="Relates NGVD29 heights to NAVD88 - not a geoid, a difference between two "
                         "datums.  Three grids: " + ", ".join(vdatum.VERTCON_GRIDS) +
                         ".  Downloaded on demand.",
                    extra={"endpoint": base}))
    for d in vdatum.VERTICAL_DATUMS:
        out.append(Site(key=f"datum:{d.key}", kind=KIND_GEOID, name=f"Vertical datum {d.key}",
                        value=d.tied_by, editable=False, formats=FORMATS[KIND_GEOID],
                        terms="", note=d.note, extra={"datum": d.key, "kind_of_datum": d.kind}))
    return out


def _crs_sites() -> list[Site]:
    """Coordinate-system definitions: PROJ's own register and its network grids."""
    out = [Site(key="crs:proj-register", kind=KIND_CRS, name="EPSG / PROJ register",
                value="(shipped with pyproj)", formats=FORMATS[KIND_CRS],
                terms="EPSG terms of use; the register itself is not redistributable in full",
                note="The parameter file database the Coordinate System picker reads. Nothing to "
                     "download; the grid files some systems need are listed below.",
                editable=False)]
    out.append(Site(key="crs:network-grids", kind=KIND_CRS, name="PROJ network grid endpoint",
                    value=settings().get("proj_grid_url") or "https://cdn.proj.org",
                    editable=True, formats=FORMATS[KIND_CRS],
                    terms="PROJ CDN, each grid under its own terms",
                    note="Where datum-shift and geoid grids come from when a coordinate system "
                         "needs one (proj_network).  Point this at a local mirror to work offline."))
    out.append(Site(key="crs:secondary-readout", kind=KIND_CRS,
                    name="Secondary coordinate readout",
                    value=settings().get("secondary_readout") or "EPSG:4326",
                    formats=FORMATS[KIND_CRS],
                    note="The system shown next to the drawing coordinates in the status bar."))
    return out


def _software_sites() -> list[Site]:
    st = settings()
    out = [Site(key="software:update", kind=KIND_SOFTWARE, name="Software update check",
                value=st.get("update_url") or "", enabled=bool(st.get("update_url")),
                formats=FORMATS[KIND_SOFTWARE],
                note="Blank = never check.  Nothing is sent except the version number.")]
    for d in (st.get("plugin_dirs") or []):
        out.append(Site(key=f"folder:plugin:{d}", kind=KIND_FOLDER, name=f"Plugin folder - {d}",
                        value=str(d), builtin=False, formats=FORMATS[KIND_FOLDER],
                        note="Scanned at start-up for plugin modules."))
    return out


def sites() -> list[Site]:
    """The whole registry, in a stable order: imagery, coordinate systems, geoid, the rest."""
    return _imagery_sites() + _crs_sites() + _geoid_sites() + _software_sites()


def site(key: str) -> Site | None:
    for s in sites():
        if s.key == key:
            return s
    return None


def edited_sites() -> list[Site]:
    """Only the ones the user has changed or added - what a settings export has to carry."""
    return [s for s in sites() if (not s.builtin) or s.value != (s.extra.get("preset_template") or "")]


def _set_imagery(name: str, value: str, enabled: bool, add: bool) -> None:
    """Write one imagery row: either edit a shipped source, or add a new one of your own.

    Editing a shipped source keeps a custom entry of the same name and records the name as
    replaced, so the Imagery menu shows the new URL once, under the familiar name.  Switching a
    shipped source off records it as hidden - it stays listed here so it can be switched back on.
    """
    st = settings()
    from . import tiles
    shipped = any(p.name == name for p in tiles.PRESETS)
    custom = [dict(c) for c in (st.get("custom_tile_sources") or [])]
    custom = [c for c in custom if str(c.get("name") or "") != name]
    replaced = [n for n in (st.get("replaced_tile_sources") or []) if n != name]
    hidden = [n for n in (st.get("hidden_tile_sources") or []) if n != name]
    if add or not shipped:
        src = tiles.TileSource(name=name, url=value, attribution="Added by you - check the source's terms")
        custom.append(src.to_dict())
    else:
        preset = next(p for p in tiles.PRESETS if p.name == name)
        if value.strip() and value.strip() != preset.url:
            custom.append(tiles.TileSource(name=name, url=value, max_zoom=preset.max_zoom,
                                           min_zoom=preset.min_zoom, attribution=preset.attribution,
                                           tile_size=preset.tile_size, ext=preset.ext).to_dict())
            replaced.append(name)
        if not enabled:
            hidden.append(name)
    st.set("custom_tile_sources", custom)
    st.set("replaced_tile_sources", replaced)
    st.set("hidden_tile_sources", hidden)


def apply_edit(key: str, value: str, enabled: bool = True) -> Site | None:
    """Point a site somewhere else, or switch it off.  Returns the site afterwards.

    The Imagery menu, the CRS picker and the datum code all read these settings, so an edit here
    is an edit everywhere - there is no second copy of a URL for anybody to forget.
    """
    st = settings()
    s = site(key)
    if s is None:
        return None
    if key.startswith("imagery:"):
        _set_imagery(key.split(":", 1)[1], value, enabled, add=not s.builtin)
    elif key.startswith("geoid:") and key != "geoid:VERTCON":
        st.set("proj_grid_url", value.rsplit("/", 1)[0] or value)      # the grid endpoint
    elif key == "crs:network-grids":
        st.set("proj_grid_url", value)
    elif key == "crs:secondary-readout":
        st.set("secondary_readout", value)
    elif key == "software:update":
        st.set("update_url", value)
    elif key.startswith("folder:"):
        pass                                                            # folder rows are managed by Plugins
    else:
        st.set(f"site_{key}", {"value": value, "enabled": bool(enabled)})
    return site(key)


def restore_builtin(key: str) -> Site | None:
    """Put a built-in source back the way it shipped (item 3: editable *and* restorable)."""
    st = settings()
    s = site(key)
    if s is None:
        return None
    if key.startswith("imagery:"):
        if not s.builtin:
            remove(key)
            return None
        name = key.split(":", 1)[1]
        _set_imagery(name, s.extra.get("preset_url", s.value), True, add=False)
        return site(key)
    if key.startswith("geoid:"):
        st.set("proj_grid_url", "https://cdn.proj.org")
        return site(key)
    if key == "crs:network-grids":
        st.set("proj_grid_url", "https://cdn.proj.org")
        return site(key)
    return s


def remove(key: str) -> None:
    """Take a source you added off the list.  Shipped sites are switched off instead."""
    st = settings()
    s = site(key)
    if s is None:
        return
    if key.startswith("imagery:"):
        name = key.split(":", 1)[1]
        custom = [c for c in (st.get("custom_tile_sources") or []) if str(c.get("name") or "") != name]
        st.set("custom_tile_sources", custom)
        st.set("hidden_tile_sources", [n for n in (st.get("hidden_tile_sources") or []) if n != name])
    elif key.startswith("folder:"):
        from .settings import settings as _s
        st.set("plugin_dirs", [d for d in (_s().get("plugin_dirs") or []) if f"folder:plugin:{d}" != key])


def as_rows() -> list[dict]:
    from .settings import DEFAULTS  # noqa: F401  (import kept close to use for the reader)
    return [dict(kind=s.kind, name=s.name, where=s.where, state=s.state, value=s.value,
                 formats=s.formats, terms=s.terms, note=s.note, key=s.key) for s in sites()]


def report_lines() -> list[str]:
    """The registry as text: the list that goes into a report or a printed settings summary."""
    lines = ["Pull sites this program uses", "=" * 28]
    for kind in (KIND_IMAGERY, KIND_CRS, KIND_GEOID, KIND_SOFTWARE, KIND_FOLDER):
        group = [s for s in sites() if s.kind == kind]
        if not group:
            continue
        lines.append("")
        lines.append(f"{kind.title()}")
        lines.append("-" * len(kind))
        for s in group:
            lines.append(f"  [{s.state:>3}] {s.name}  ({s.where})")
            lines.append(f"        where : {s.value or '(not set)'}")
            lines.append(f"        takes : {s.formats}")
            if s.terms:
                lines.append(f"        terms : {s.terms}")
            if s.note:
                lines.append(f"        note  : {s.note}")
    return lines


__all__ = ["Site", "sites", "site", "edited_sites", "apply_edit", "restore_builtin", "remove",
           "as_rows",
           "report_lines", "FORMATS", "KIND_IMAGERY", "KIND_CRS", "KIND_GEOID", "KIND_SOFTWARE",
           "KIND_FOLDER"]
