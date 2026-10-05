"""Coordinate systems, vertical datums and geoid models.

The Texas library and the geoid models are *data*, and data is exactly where a mistake is
quiet and expensive: a transposed EPSG code, the wrong foot, or a geoid separation subtracted
instead of added all look fine on screen and are wrong in the ground.  Wherever possible these
tests check the library against an outside reference - PROJ's own EPSG database, NOAA's geoid
grids - instead of against itself.
"""
from __future__ import annotations

import math
import os

import pytest
from pyproj import CRS as ProjCRS
from pyproj import Geod, Transformer

import pyproj
from plumbline.core import crs as C
from plumbline.core import vdatum as VD

pyproj.network.set_network_enabled(False)          # tests never reach out for a grid

NO_GEOID = "Not Used - this datum needs no geoid"   # the single entry an ellipsoid/assumed datum gets


def _proj_crs(key):
    """The pyproj CRS behind a library key."""
    return C.crs_from_key(key)


def _false_origin(key):
    """PROJ's stated false origin and natural origin of a projected system."""
    c = _proj_crs(key)
    op = c.coordinate_operation
    p = {prm.name: prm.value for prm in op.params}
    lon_0 = p["Longitude of false origin"]
    lat_0 = p["Latitude of false origin"]
    return lat_0, lon_0, p["Easting at false origin"], p["Northing at false origin"]


# --------------------------------------------------------------------------------- the library

def test_the_texas_library_has_every_zone_the_state_plane_has():
    """Five zones, three realisations.  Every zone has metres, US survey feet and international
    feet under NAD83 and NAD83(2011); NAD27 exists only in US survey feet, because that is how
    NGS defined it - there is no NAD27 metric Texas zone to offer."""
    tx = {k: v for k, v in C.TEXAS_ZONES.items() if v.get("state") == "TX"}
    assert len(tx) == 35
    zones = {"North", "North Central", "Central", "South Central", "South"}
    assert {v["zone"] for v in tx.values()} == zones
    for datum, units in (("NAD83(2011)", {"m", "USft", "ft"}),
                         ("NAD83", {"m", "USft", "ft"}),
                         ("NAD27", {"USft"})):
        for zone in zones:
            got = {v["units"] for v in tx.values() if v["zone"] == zone and v["datum"] == datum}
            assert got == units, f"{zone} {datum} has {got}"
    # the whole register also carries plain WGS 84 lat/lon, for jobs that have no state plane at all
    assert {v["name"] for k, v in C.TEXAS_ZONES.items() if str(k) == "4326"} == {"WGS 84 (lat/lon)"}


def test_every_code_is_the_code_proj_knows_it_by():
    """A transposed pair of digits (6584 for 6585, 2276 for 2275) would put a whole job in the
    neighbouring zone and every distance would still look reasonable.  Compare against PROJ."""
    checked = 0
    for key, info in C.TEXAS_ZONES.items():
        if info.get("state") != "TX" or C.is_derived_key(key):
            continue
        epsg = int(key)
        proj_name = ProjCRS.from_epsg(epsg).name
        # our display name is the EPSG name with the units spelled out at the end
        stem = info["name"].split("(")[0].strip()
        assert proj_name.startswith(stem), f"{epsg}: {proj_name!r} vs {info['name']!r}"
        assert info["zone"] in proj_name, f"{epsg}: {proj_name!r} is not {info['zone']!r}"
        assert info["zone"] in proj_name
        unit_word = {"m": "metre", "USft": "US survey foot", "ft": "foot"}[info["units"]]
        assert ProjCRS.from_epsg(epsg).axis_info[0].unit_name == unit_word, epsg
        checked += 1
    assert checked == 25          # 5 zones x (2011 m + 2011 USft + 1986 m + 1986 USft + NAD27 USft)


def test_the_projection_puts_the_false_origin_exactly_where_epsg_says_it_is():
    """Project the zone's natural origin and it must land on the declared false easting and
    northing, in the declared unit.  This is what catches a metric parameter list used for a
    feet system - the coordinates come back 3.28 times too small, which still looks plausible."""
    for key, info in C.TEXAS_ZONES.items():
        if info.get("state") != "TX" or C.is_derived_key(key):
            continue
        lat_0, lon_0, e0, n0 = _false_origin(key)
        c = _proj_crs(key)
        # from the zone's OWN geographic datum, so PROJ applies no datum shift: this test is
        # about the projection parameters, not about how NAD27 relates to WGS 84
        to_grid = Transformer.from_crs(c.geodetic_crs, c, always_xy=True)
        e, n = to_grid.transform(lon_0, lat_0)
        assert e == pytest.approx(e0, abs=0.002), key
        assert n == pytest.approx(n0, abs=0.002), key
        # and the declared origin is a state-plane-sized number, not a swapped pair or a zero
        assert 1e5 < e0 < 20e6 and 0 <= n0 < 20e6, key


def test_the_metre_entry_and_the_foot_entry_are_the_same_ground_in_two_rulers():
    """Texas North Central: 600 000 m and 1 968 500 US survey feet are the same point."""
    assert 600000.0 / (1200.0 / 3937.0) == pytest.approx(1968500.0, abs=0.001)
    lat_0, lon_0, e_m, n_m = _false_origin(6583)                 # metres
    _, _, e_ft, n_ft = _false_origin(6584)                       # US survey feet
    assert e_m == pytest.approx(600000.0, abs=0.001)
    assert e_ft == pytest.approx(e_m / (1200.0 / 3937.0), abs=0.01)
    assert n_ft == pytest.approx(n_m / (1200.0 / 3937.0), abs=0.01)


def test_international_feet_change_the_ruler_and_not_the_origin():
    """The derived international-foot systems have no EPSG code; the rule is that the plane
    origin stays where it is and only the unit changes, so every coordinate is 2 ppm larger
    than its US survey foot twin.  At a northing of 7 million feet that is 14 feet of ground."""
    usft = C.crs_from_key(6584)
    intl = C.crs_from_key("6584-ft")
    assert usft.axis_info[0].unit_name == "US survey foot"
    assert intl.axis_info[0].unit_name == "foot"

    ratio = (1200.0 / 3937.0) / 0.3048                            # 1.0000020000...
    assert ratio == pytest.approx(1.000002, abs=1e-9)

    lat_0, lon_0, e_us, n_us = _false_origin(6584)               # metres in PROJ's proj4 syntax
    to_us = Transformer.from_crs(ProjCRS.from_epsg(4326), usft, always_xy=True)
    to_in = Transformer.from_crs(ProjCRS.from_epsg(4326), intl, always_xy=True)
    e_u, n_u = to_us.transform(lon_0, lat_0)
    e_i, n_i = to_in.transform(lon_0, lat_0)
    assert e_i == pytest.approx(e_u * ratio, rel=1e-9)
    assert n_i == pytest.approx(n_u * ratio, rel=1e-9)


def test_a_real_texas_place_lands_in_its_own_zone_and_round_trips():
    """Three known places, checked against the zone they are actually in, then back again with
    the ground distance compared to the grid distance.  A Lambert projection in Texas has a
    scale factor within about 1 part in 10 000 of unity, so a 10 km line on the ground is a
    10 km line on the grid - if it is not, a standard parallel is wrong."""
    places = [("Mesquite", -96.5992, 32.7668, 6584, "North Central"),
              ("El Paso", -106.4851, 31.7590, 6578, "Central"),
              ("Amarillo", -101.8313, 35.2220, 6582, "North"),
              ("Houston", -95.3600, 29.7600, 6588, "South Central")]
    geod = Geod(ellps="GRS80")
    for name, lon, lat, key, zone in places:
        # the zone the library says covers this place is the zone it is published in
        box = _proj_crs(key).area_of_use.bounds
        assert box[0] <= lon <= box[2] and box[1] <= lat <= box[3], f"{name} is outside {zone}"
        assert C.TEXAS_ZONES[key]["zone"] == zone
        c = C.ProjectCRS.from_key(key)
        e, n = c.from_lonlat(lon, lat)
        assert e > 0 and n > 0
        got_lon, got_lat = c.to_lonlat(e, n)
        assert got_lon == pytest.approx(lon, abs=1e-9), name
        assert got_lat == pytest.approx(lat, abs=1e-9), name

        # a second place 10 km east and 5 km north, measured both ways
        _, _, dist = geod.inv(lon, lat, lon + 0.11, lat + 0.045)
        e2, n2 = c.from_lonlat(lon + 0.11, lat + 0.045)
        grid = math.hypot(e2 - e, n2 - n) * c.unit_factor
        assert grid == pytest.approx(dist, rel=2e-4), f"{name}: grid {grid:.1f} m vs ground {dist:.1f} m"


def test_zone_unit_choices_offer_all_three_units_of_one_zone():
    keys = [k for k, _ in C.zone_unit_choices(6584)]
    assert set(keys) == {6584, 6583, "6584-ft"}
    assert all(C.TEXAS_ZONES[k]["zone"] == "North Central" for k in keys)
    assert all(C.TEXAS_ZONES[k]["datum"] == "NAD83(2011)" for k in keys)
    assert [k for k, _ in C.zone_unit_choices("2276-ft")] and C.TEXAS_ZONES["2276-ft"]["units"] == "ft"


def test_a_legacy_zone_offers_its_2011_equivalent_and_keeps_its_own_number():
    legacy = C.ProjectCRS.from_epsg(2276)
    assert legacy.authority == "EPSG:2276" and legacy.is_legacy_zone
    assert legacy.legacy_replacement() == 6584
    assert not C.ProjectCRS.from_epsg(6584).is_legacy_zone
    assert C.ProjectCRS.from_epsg(32138).legacy_replacement() == 6583     # the metre series
    assert C.migrate_epsg(32138) == 6583 and C.migrate_epsg("6584-ft") == "6584-ft"


def test_a_derived_system_survives_a_save_and_load(tmp_path):
    """A system with no EPSG code has to come back as itself and still put coordinates on the
    right patch of ground.  2 552 722.87 / 6 967 192.92 is Mesquite in Texas North Central."""
    from plumbline.core.project import Project
    pr = Project("intl", C.ProjectCRS.from_key("6584-ft"))
    pr.add_point(2552727.9718, 6967206.8524, 100.0, number="1", desc="GS")
    pr.save(tmp_path / "a.plb")
    back = Project.load(tmp_path / "a.plb")
    assert back.crs.key == "6584-ft"
    assert "intl ft" in back.crs.name
    lon, lat = back.crs.to_lonlat(2552727.9718, 6967206.8524)
    assert lat == pytest.approx(32.7668, abs=1e-4) and lon == pytest.approx(-96.5992, abs=1e-4)


def test_texas_records_are_searchable_by_datum_and_unit():
    hits = {r.code for r in C.texas_matches("nad27")}
    assert {"32037", "32038", "32039", "32040", "32041"} <= hits
    intl = {r.code for r in C.texas_matches("international feet")}
    assert {"6584-ft", "2276-ft"} <= intl
    assert {r.code for r in C.texas_matches("mesquite")} == set()          # no invented matches
    assert len(C.texas_zone_records()) == 35
    assert all(r.key.startswith(("EPSG:", "PLUMBLINE:")) for r in C.texas_zone_records())


# ---------------------------------------------------------------------------- vertical datums

def test_the_registry_says_what_each_datum_is_and_needs():
    assert VD.DATUM_KEYS[:2] == ("NAVD88", "NGVD29")
    assert VD.describe("NAVD88", "GEOID18")["label"] == "NAVD88 (GEOID18)"
    assert VD.describe("NAVD88")["needs_geoid"] is True                 # orthometric
    assert VD.describe("HAE")["needs_geoid"] is False                   # it IS the ellipsoid
    assert VD.describe("LOCAL")["needs_geoid"] is False
    assert VD.geoid_choices("HAE") == [("", NO_GEOID)]
    assert len(VD.geoid_choices("NAVD88")) == len(VD.GEOID_KEYS) == 3
    # NGVD29 is not tied to the ellipsoid by a geoid model - it is tied to NAVD88 by VERTCON,
    # so the geoid list is deliberately empty for it and the conversion row offers VERTCON
    ngvd = VD.describe("NGVD29")
    assert ngvd["kind"] == "tidal" and ngvd["needs_geoid"] is False
    assert "VERTCON" in ngvd["tied_by"]
    assert VD.geoid_choices("NGVD29") == [("", NO_GEOID)]
    assert VD.DEFAULT_DATUM == "NAVD88" and VD.DEFAULT_GEOID == "GEOID18"


def test_an_old_free_text_datum_label_is_read_the_way_it_was_written():
    assert VD.resolve_label("NAVD88 (GEOID18)") == ("NAVD88", "GEOID18", "")
    assert VD.resolve_label("NAVD88 (assumed)") == ("NAVD88", "", "assumed")
    assert VD.resolve_label("NGVD29") == ("NGVD29", "", "")
    key, geoid, note = VD.resolve_label("city datum 102.5")
    assert key == "city datum 102.5" and geoid == "" and note == ""     # kept, not filed
    assert VD.resolve_label("")[0] == VD.DEFAULT_DATUM


# -- the geoid arithmetic, against NOAA's own grids (needs the one-off grid download) --------
@pytest.fixture()
def geoid_grid():
    """GEOID18, with downloads allowed for the length of one test.

    PROJ fetches a geoid tile on demand and does not keep it where a second run can read it
    without the switch on, so the switch goes on here and is put back afterwards - a test that
    changes a global setting and walks away is a test that breaks the next one.
    """
    if os.environ.get("PLUMBLINE_NO_NETWORK") == "1":
        pytest.skip("network use is switched off for this run")
    was = VD.allow_downloads(True)
    try:
        n = VD.separation(-96.5992, 32.7668, "GEOID18")                 # Mesquite, Texas
        if n is None:
            pytest.skip("GEOID18 is not available (no network / not downloaded)")
        yield n
    finally:
        VD.allow_downloads(was)


def test_the_geoid_separation_is_the_right_size_and_sign_for_texas(geoid_grid):
    """GEOID18 is about -25.85 m at Mesquite.

    The sign is the whole point: ellipsoid height = orthometric height + N, so at -25.85 m the
    ellipsoid height is LOWER than the published elevation of the same point by 84.8 ft.  Add
    instead of subtract and the number is 170 ft out - and nothing on screen looks wrong.
    """
    n = VD.separation(-96.5992, 32.7668, "GEOID18")
    assert n == pytest.approx(-25.85, abs=0.35)
    # an independent corner of the state (El Paso) is a little different, as it should be
    assert VD.separation(-106.485, 31.759, "GEOID18") == pytest.approx(-24.6, abs=1.5)
    # and it must not be a constant - a grid that failed to load reports a flat number
    assert abs(VD.separation(-94.0, 33.5, "GEOID18") - n) > 0.5


def test_height_conversion_round_trips_in_feet_and_metres(geoid_grid):
    for unit, h in (("ftUS", 500.0), ("m", 152.4)):
        h_ell = VD.convert_height(h, unit, -96.5992, 32.7668, "GEOID18", to="ellipsoid")
        h_orth = VD.convert_height(h_ell, unit, -96.5992, 32.7668, "GEOID18", to="orthometric")
        assert h_orth == pytest.approx(h, rel=1e-9)
        if unit == "ftUS":
            # 500 ft of NAVD88 elevation is about 415 ft of ellipsoid height at Mesquite
            assert h_ell == pytest.approx(415.2, abs=0.6)


def test_ngvd29_and_navd88_are_related_by_vertcon_not_by_the_geoid(geoid_grid):
    d = VD.vertcon_shift(-96.5992, 32.7668)
    assert d is not None and abs(d) < 1.0            # centimetres in north Texas
    up = VD.ngvd29_to_navd88(100.0, -96.5992, 32.7668, "ftUS")
    down = VD.navd88_to_ngvd29(up, -96.5992, 32.7668, "ftUS")
    assert down == pytest.approx(100.0, rel=1e-9)
    assert up != pytest.approx(100.0, abs=1e-12)     # a real shift, not a passthrough


def test_a_geoid_that_is_not_installed_says_so_rather_than_returning_zero():
    """The failure mode this guards against: PROJ skips a missing grid and reports a separation
    of exactly 0.000 m, which is a silent 26 m error in the ground.  Downloads refused and grid
    absent must give None plus a reason."""
    state = VD.grid_state("GEOID99", allow_download=False)
    if state["present"] and state["readable_without_download"]:
        pytest.skip("this machine already has the GEOID99 tiles")
    assert state["present"] is False and state["reason"]
    assert VD.separation(-96.5992, 32.7668, "GEOID99", allow_download=False) is None


def test_vertcon_outside_conus_is_none_not_a_number():
    """The VERTCON tiles return +inf off their edge; a number there would be worse than a gap."""
    assert VD.vertcon_shift(-40.0, 40.0, allow_download=False) is None
