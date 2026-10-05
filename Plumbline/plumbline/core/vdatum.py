"""Vertical datums and geoid models - CONUS, and honest about what is actually installed.

A horizontal coordinate system says where a point is on the earth's surface.  A **vertical
datum** says what the number in the Z column is measured from, and they are independent: two
jobs can sit on the same State Plane zone and differ by a foot and a half because one is on
NAVD88 and the other is on NGVD29, or because one is *ellipsoid* height and the other is
orthometric.

The three vertical datums a CONUS survey is almost always on:

===============  ==========================================================
``NAVD88``       North American Vertical Datum of 1988 - the current one.
                 Tied to the ellipsoid by a **geoid model** (GEOID18 today).
``NGVD29``       National Geodetic Vertical Datum of 1929 - old surveys, and
                 still on some city/county records.  Related to NAVD88 by
                 VERTCON, not by a geoid.
``HAE``          Ellipsoid height (GPS-native).  No geoid - what the receiver
                 gives you, and what a machine sees as "Z".
===============  ==========================================================

The arithmetic
--------------
    ellipsoid height  h = orthometric height  H  +  geoid separation  N
    orthometric height H = ellipsoid height   h  -  N

``N`` is read from a NOAA geoid grid - about **-25.85 m** at Mesquite, Texas on GEOID18, so
a rooftop at H = 500 ft is at h = 500 ft - 84.8 ft.  Getting that backwards is a 26 m error,
which is the kind that survives to a deliverable.

Grids are downloaded from PROJ's CDN on first use (a few hundred MB for the CONUS geoid) and
cached by PROJ; that download is **opt in** - :func:`allow_downloads` - because a survey
laptop is often offline and a silent 300 MB download on a metered connection is not kind.
Every function here works without the grid and says so by returning ``None`` and a reason,
rather than inventing a separation.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

#: Metres per foot, for the height unit conversions this module needs (heights are
#: converted, never pushed through a horizontal datum shift - see the note in core.crs).
_M_PER_FT_US = 1200.0 / 3937.0          # US survey foot
_M_PER_FT = 0.3048                      # international foot


# ----------------------------------------------------------------------------------- datums
@dataclass(frozen=True)
class VerticalDatum:
    key: str
    name: str
    kind: str            # "orthometric" | "tidal" | "ellipsoid" | "assumed"
    era: str
    tied_by: str         # what relates it to the ellipsoid
    note: str
    region: str = "CONUS"


#: The CONUS vertical datums, current one first.  Anything not in this table is still
#: acceptable as a free-text label (a city's own datum, "assumed 100.00") - the project
#: stores the label either way.
VERTICAL_DATUMS: tuple[VerticalDatum, ...] = (
    VerticalDatum("NAVD88", "NAVD88 (North American Vertical Datum of 1988)", "orthometric", "1988-",
                  "geoid model (GEOID18 / GEOID12B / GEOID99)",
                  "The datum new survey work in the US is on.  Published heights are "
                  "orthometric: they already have the geoid removed."),
    VerticalDatum("NGVD29", "NGVD29 (National Geodetic Vertical Datum of 1929)", "tidal", "1929",
                  "VERTCON (NGVD29 -> NAVD88)",
                  "Old surveys, and the datum on some city and county records.  Relate it to "
                  "NAVD88 with VERTCON; near Texas the two are within a few centimetres, but "
                  "the difference is not zero and it is not constant."),
    VerticalDatum("HAE", "Ellipsoid Height (HAE - no vertical datum)", "ellipsoid", "-",
                  "none - this IS the ellipsoid",
                  "What a GPS receiver reports before any geoid is applied.  Ellipsoid heights "
                  "are not comparable with NAVD88 elevations without the geoid separation."),
    VerticalDatum("LOCAL", "Assumed / Local (job datum)", "assumed", "-", "none - by definition",
                  "A job datum: 100.00 ft on a benchmark, sea level at a named tide gage, or a "
                  "finished-floor elevation.  Nothing outside the job can be compared with it."),
)

DATUM_KEYS = tuple(d.key for d in VERTICAL_DATUMS)
DEFAULT_DATUM = "NAVD88"


def datum(key: str) -> VerticalDatum | None:
    """The registry entry for a datum key (case-insensitive)."""
    k = str(key or "").strip().upper()
    for d in VERTICAL_DATUMS:
        if d.key == k:
            return d
    return None


def resolve_label(label: str) -> tuple[str, str, str]:
    """Split a saved vertical-datum label into ``(datum_key, geoid_key, note)``.

    Projects written before this module existed stored free text.  ``"NAVD88 (GEOID18)"``
    means datum NAVD88 with the GEOID18 model; ``"NAVD88 (assumed)"`` means NAVD88 with a
    note the user typed; ``"city datum 102.5"`` means neither, and is kept as written
    rather than being filed under something it is not.
    """
    text = str(label or "").strip()
    if not text:
        return DEFAULT_DATUM, "", ""
    head, note = text, ""
    if "(" in text and text.endswith(")"):
        head, note = text[:text.index("(")].strip(), text[text.index("(") + 1:-1].strip()
    d = datum(head) or datum(text)
    if d is None:
        return text, "", ""                       # a custom datum: leave it exactly as it is
    geoid = note if model(note) else ""
    return d.key, geoid, ("" if geoid else note)


def datum_label(key: str, geoid_key: str = "") -> str:
    """How a vertical datum is shown in a status bar or a report.

    ``datum_label("NAVD88", "GEOID18")`` -> ``'NAVD88 (GEOID18)'``.  A label that is not in
    the registry is passed through as the user typed it, so an old project or a job-specific
    datum never gets renamed behind the user's back.
    """
    d = datum(key)
    if d is None:
        return str(key or "").strip() or "Not Set"
    if d.kind == "orthometric" and geoid_key:
        m = model(geoid_key)
        return f"{d.key} ({m.key if m else geoid_key})"
    return d.key


# ----------------------------------------------------------------------------------- geoids
@dataclass(frozen=True)
class GeoidModel:
    key: str
    name: str
    epoch: str           # what it is tied to ("2018-01-01" etc.)
    grids: tuple[str, ...]
    region: str
    accuracy_m: float    # the stated difference from GNSS/leveling on the model's own sheet
    note: str = ""

    @property
    def grid_arg(self) -> str:
        """The value for ``+grids=``.

        Deliberately **no** ``@`` prefix.  A ``@`` tells PROJ "download it if it is missing,
        and carry on without it if you cannot" - which fails silently as a separation of
        exactly zero, the worst possible answer for a height.  Without the ``@`` a missing
        grid raises, and :func:`separation` returns None with a reason instead of inventing
        a number.
        """
        return ",".join(g.lstrip("@") for g in self.grids)


#: The CONUS geoid models.  Only the ones NOAA publishes as a single CONUS-wide grid are
#: listed; older models (GEOID12A, GEOID09, GEOID03) were published as regional tiles with
#: different names and are deliberately absent rather than guessed at.
GEOID_MODELS: tuple[GeoidModel, ...] = (
    GeoidModel("GEOID18", "GEOID18", "2018-01-01",
               ("us_noaa_g2018u0.tif",), "CONUS", 0.030,
               "The current CONUS geoid.  1' x 1' grid (~2 km)."),
    GeoidModel("GEOID12B", "GEOID12B", "2012-06-01",
               ("us_noaa_g2012bu0.tif",), "CONUS", 0.050,
               "Still the model some legacy records were reduced with - use it to reproduce "
               "an old job exactly, not for new work."),
    GeoidModel("GEOID99", "GEOID99", "1999-01-01",
               tuple(f"us_noaa_g1999u{i:02d}.tif" for i in range(1, 9)), "CONUS", 0.100,
               "1999 model, published as eight tiles; all eight are required."),
)

GEOID_KEYS = tuple(g.key for g in GEOID_MODELS)
DEFAULT_GEOID = "GEOID18"


def model(key: str) -> GeoidModel | None:
    k = str(key or "").strip().upper()
    for g in GEOID_MODELS:
        if g.key == k:
            return g
    return None


def geoid_choices(for_datum: str = DEFAULT_DATUM) -> list[tuple[str, str]]:
    """(key, label) pairs for a picker, for the datum that is selected.

    A geoid only makes sense for an orthometric datum - on an ellipsoid or assumed datum
    the useful answer is "none", and saying so beats offering three models that will be
    ignored.
    """
    d = datum(for_datum)
    if d is None or d.kind != "orthometric":
        return [("", "Not Used - this datum needs no geoid")]
    return [(g.key, f"{g.name}  ({g.epoch[:4]}, {g.region}, +/-{g.accuracy_m:.3f} m)")
            for g in GEOID_MODELS]


# ----------------------------------------------------------------------------------- network
def allow_downloads(value: bool | None = None) -> bool:
    """Turn PROJ's on-demand grid download on or off, or just read it (the app setting).

    Kept here as well as in the settings dialog because this module is the one that needs
    it, and because a test has to be able to switch it without a settings file.
    """
    from .settings import settings
    if value is not None:
        settings().set("proj_network", bool(value))
        _apply(value)
    return bool(settings().get("proj_network"))


def _apply(enabled: bool):
    """PROJ fetches a missing grid over the network only when this is on."""
    try:
        import pyproj
        pyproj.network.set_network_enabled(bool(enabled))
    except Exception:
        pass


def _pipeline(grids, download: bool):
    """A ``vgridshift`` transformer, with downloads enabled or refused.

    If downloads are refused and the grid is not on disk, this raises - which is the point:
    the caller turns that into "not available", never into a zero separation.
    """
    from pyproj import Transformer
    _apply(bool(download))
    arg = grids if isinstance(grids, str) else ",".join(g.lstrip("@") for g in grids)
    return Transformer.from_pipeline(f"+proj=vgridshift +grids={arg} +multiplier=1")


def grid_state(m: GeoidModel | str, allow_download: bool | None = None) -> dict:
    """Is this model's grid usable right now, and would it have to be downloaded?

    Returns ``{"key", "present", "readable_without_download", "reason"}``.  ``present``
    means a separation was actually computed from the grid - the only test that proves the
    grid is there and usable, rather than merely on disk somewhere.  This is what the
    Vertical Datum tab shows, so it has to be the same code path the conversion uses.
    """
    g = model(m) if not isinstance(m, GeoidModel) else m
    if g is None:
        return {"key": str(m), "present": False, "readable_without_download": False,
                "reason": "unknown geoid model"}
    download = allow_downloads() if allow_download is None else bool(allow_download)

    # 1. already on disk?  Ask with downloads refused, so this cannot fetch anything.
    if separation(-98.5, 32.0, g.key, allow_download=False) is not None:
        return {"key": g.key, "present": True, "readable_without_download": True, "reason": ""}
    # 2. not on disk - is it obtainable?
    if download and separation(-98.5, 32.0, g.key, allow_download=True) is not None:
        return {"key": g.key, "present": True, "readable_without_download": False, "reason": ""}
    return {"key": g.key, "present": False, "readable_without_download": False,
            "reason": ("not downloaded yet - allow downloads in Coordinate System, or copy the "
                       "grid in by hand") if not download else "not available"}


def _tidy(exc) -> str:
    """A PROJ error message a surveyor can read."""
    text = " ".join(str(exc).split())
    if "network" in text.lower() or "download" in text.lower() or "remote" in text.lower():
        return "not downloaded yet - allow downloads in Coordinate System, or copy the grid in by hand"
    return text[:160]


# ------------------------------------------------------------------------------ separations
def separation(lon: float, lat: float, geoid_key: str = DEFAULT_GEOID,
               allow_download: bool | None = None) -> float | None:
    """Geoid separation **N** in metres at a longitude/latitude, or None if unavailable.

    ``h - H``: what to *add* to an orthometric height to get the ellipsoid height.  The
    sign is the one thing people get wrong - in Texas N is about -26 m, so ellipsoid heights
    there are *lower* than NAVD88 elevations.
    """
    g = model(geoid_key)
    if g is None:
        return None
    try:
        download = allow_downloads() if allow_download is None else bool(allow_download)
        _x, _y, n = _pipeline(g.grids, download).transform(float(lon), float(lat), 0.0)
        if n is None or not math.isfinite(n) or abs(n) > 200:
            return None                     # outside the grid's coverage
        return float(n)
    except Exception:
        return None


def orthometric_to_ellipsoid(height: float, lon: float, lat: float,
                             geoid_key: str = DEFAULT_GEOID, unit: str = "m") -> float | None:
    """NAVD88-style orthometric height -> ellipsoid height, in the same unit."""
    n = separation(lon, lat, geoid_key)
    if n is None or height is None:
        return None
    return float(height) + (_to_m(n, unit) if unit != "m" else n) / (_unit_to_m(unit))


def ellipsoid_to_orthometric(height: float, lon: float, lat: float,
                             geoid_key: str = DEFAULT_GEOID, unit: str = "m") -> float | None:
    """Ellipsoid height -> orthometric height, in the same unit."""
    n = separation(lon, lat, geoid_key)
    if n is None or height is None:
        return None
    return float(height) - (_to_m(n, unit) if unit != "m" else n) / (_unit_to_m(unit))


def _unit_to_m(unit: str) -> float:
    u = (unit or "m").strip()
    if u in ("ftUS", "usft", "USft"):
        return _M_PER_FT_US
    if u in ("ft", "foot", "intlft"):
        return _M_PER_FT
    return 1.0


def _to_m(metres: float, unit: str) -> float:
    return metres


def convert_height(height: float, unit: str, lon: float, lat: float, geoid_key: str = DEFAULT_GEOID,
                   to: str = "orthometric") -> float | None:
    """Height between orthometric and ellipsoid in the project's own unit.

    ``to="ellipsoid"`` adds N; ``to="orthometric"`` subtracts it.  Everything is done in
    metres and converted once, so a US-foot project gets the same answer as a metric one.
    """
    n = separation(lon, lat, geoid_key)
    if n is None or height is None:
        return None
    f = _unit_to_m(unit)
    metres = float(height) * f
    metres = metres + n if to == "ellipsoid" else metres - n
    return metres / f


# ---------------------------------------------------------------------------------- VERTCON
#: VERTCON relates NGVD29 to NAVD88 - a different question from the geoid, published as
#: three regional grids.  Outside its region a grid returns an infinite value, which is
#: how "this point is not covered" is detected.
VERTCON_GRIDS = ("us_noaa_vertconc.tif", "us_noaa_vertcone.tif", "us_noaa_vertconw.tif")


def vertcon_shift(lon: float, lat: float, allow_download: bool | None = None) -> float | None:
    """The NGVD29 -> NAVD88 correction in metres at a longitude/latitude (None if outside)."""
    try:
        download = allow_downloads() if allow_download is None else bool(allow_download)
        for grid in VERTCON_GRIDS:
            try:
                _x, _y, d = _pipeline((grid,), download).transform(float(lon), float(lat), 0.0)
                if d is not None and math.isfinite(d) and abs(d) < 5.0:
                    return float(d)
            except Exception:
                continue
        return None
    except Exception:
        return None


def ngvd29_to_navd88(height: float, lon: float, lat: float, unit: str = "m") -> float | None:
    """NGVD29 height -> NAVD88 height (adds the VERTCON correction)."""
    d = vertcon_shift(lon, lat)
    if d is None or height is None:
        return None
    f = _unit_to_m(unit)
    return (float(height) * f + d) / f


def navd88_to_ngvd29(height: float, lon: float, lat: float, unit: str = "m") -> float | None:
    """NAVD88 height -> NGVD29 height (subtracts the VERTCON correction)."""
    d = vertcon_shift(lon, lat)
    if d is None or height is None:
        return None
    f = _unit_to_m(unit)
    return (float(height) * f - d) / f


# ------------------------------------------------------------------------------- reporting
def describe(datum_key: str, geoid_key: str = "") -> dict:
    """Everything the UI and the reports say about a project's vertical datum."""
    d = datum(datum_key)
    g = model(geoid_key) if geoid_key else None
    return {
        "key": d.key if d else (datum_key or ""),
        "label": datum_label(datum_key, geoid_key),
        "name": d.name if d else (datum_key or "not set"),
        "kind": d.kind if d else "custom",
        "tied_by": d.tied_by if d else "unknown",
        "geoid": g.key if g else "",
        "geoid_name": g.name if g else "",
        "geoid_accuracy_m": g.accuracy_m if g else None,
        "needs_geoid": bool(d and d.kind == "orthometric"),
        "note": d.note if d else "A datum this program does not have in its list.",
    }
