# coord_systems.py — 2011 Texas State Plane ONLY (NAD83 2011) + TXDOT SAF (origin 0,0) top-layer scaler + WGS84
"""
2011 Texas State Plane ONLY library. For Google Earth export (KML clampToGround).

Library is SELECTIVE: only 2011 Texas State Plane zones (m + USft per 5 Texas zones) + WGS84 are exposed by default per user request.
library via Settings.

Units: Texas 2011 State Plane uses US Survey Feet (USft) or meters per EPSG; WGS84 lat/lon for KML is degrees.

TOP-LAYER SCALER (TXDOT SAF):
  SAF is the outer affine scaler from origin (0,0): Ground = Grid * SAF, Grid = Ground / SAF.
  TXNC 2011 pre-final grid is approx 6M N by 3M E with origin 0,0; final stored coordinate = grid * SAF (county-wide TXDOT factor, e.g., Bexar 1.00017).
  For KML/WGS84 export: Grid = Ground / SAF (first out last in). No CSF, no base point, only origin 0,0.

Conversion: uses pyproj if available (pip install pyproj). Falls back to pure-python Texas 2011 LCC if not installed (no UTM).
"""

import math

# Curated library - the Texas State Plane zones a Texas crew can actually be handed, in
# every combination of datum and unit that exists:
#
#   NAD27 (US survey feet only - EPSG has no metric NAD27 Texas zone)
#   NAD83 (the original 1986 realisation)      m: 32137-32141   USft: 2275-2279
#   NAD83(2011) (NSRS2011)                     m: 6577-6588     USft: 6582-6586
#
# plus **international feet** variants.  EPSG has no code for those - they are the same
# projection with +units=ft instead of +units=us-ft, which is a 2 ppm difference from US
# survey feet and therefore a real difference at state-plane magnitudes.  They are keyed
# "6584-ft" (the EPSG code they derive from, in international feet); core.crs builds them.
#
# Keys are ints for real EPSG codes and short strings for the derived ones, so that
# nothing has to pretend a derived system has an EPSG number.
EPSG_LIBRARY = {
    # ---- NAD83(2011) - the current realisation, metres .................................
    6581: {"name": "NAD83(2011) / Texas North (m)", "state": "TX", "zone": "North", "epsg": 6581, "units": "m", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    6583: {"name": "NAD83(2011) / Texas North Central (m)", "state": "TX", "zone": "North Central", "epsg": 6583, "units": "m", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    6577: {"name": "NAD83(2011) / Texas Central (m)", "state": "TX", "zone": "Central", "epsg": 6577, "units": "m", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    6587: {"name": "NAD83(2011) / Texas South Central (m)", "state": "TX", "zone": "South Central", "epsg": 6587, "units": "m", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    6585: {"name": "NAD83(2011) / Texas South (m)", "state": "TX", "zone": "South", "epsg": 6585, "units": "m", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    # ---- NAD83(2011), US survey feet ...................................................
    6582: {"name": "NAD83(2011) / Texas North (USft)", "state": "TX", "zone": "North", "epsg": 6582, "units": "USft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    6584: {"name": "NAD83(2011) / Texas North Central (USft)", "state": "TX", "zone": "North Central", "epsg": 6584, "units": "USft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    6578: {"name": "NAD83(2011) / Texas Central (USft)", "state": "TX", "zone": "Central", "epsg": 6578, "units": "USft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    6588: {"name": "NAD83(2011) / Texas South Central (USft)", "state": "TX", "zone": "South Central", "epsg": 6588, "units": "USft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    6586: {"name": "NAD83(2011) / Texas South (USft)", "state": "TX", "zone": "South", "epsg": 6586, "units": "USft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011"},
    # ---- NAD83(2011), international feet (derived - no EPSG code exists) ...............
    "6582-ft": {"name": "NAD83(2011) / Texas North (intl ft)", "state": "TX", "zone": "North", "epsg": "6582-ft", "units": "ft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011", "derived_from": 6582},
    "6584-ft": {"name": "NAD83(2011) / Texas North Central (intl ft)", "state": "TX", "zone": "North Central", "epsg": "6584-ft", "units": "ft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011", "derived_from": 6584},
    "6578-ft": {"name": "NAD83(2011) / Texas Central (intl ft)", "state": "TX", "zone": "Central", "epsg": "6578-ft", "units": "ft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011", "derived_from": 6578},
    "6588-ft": {"name": "NAD83(2011) / Texas South Central (intl ft)", "state": "TX", "zone": "South Central", "epsg": "6588-ft", "units": "ft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011", "derived_from": 6588},
    "6586-ft": {"name": "NAD83(2011) / Texas South (intl ft)", "state": "TX", "zone": "South", "epsg": "6586-ft", "units": "ft", "proj": "lcc", "datum": "NAD83(2011)", "era": "2011", "derived_from": 6586},
    # ---- NAD83 (original realisation) - still on live records ..........................
    32137: {"name": "NAD83 / Texas North (m)", "state": "TX", "zone": "North", "epsg": 32137, "units": "m", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    32138: {"name": "NAD83 / Texas North Central (m)", "state": "TX", "zone": "North Central", "epsg": 32138, "units": "m", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    32139: {"name": "NAD83 / Texas Central (m)", "state": "TX", "zone": "Central", "epsg": 32139, "units": "m", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    32140: {"name": "NAD83 / Texas South Central (m)", "state": "TX", "zone": "South Central", "epsg": 32140, "units": "m", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    32141: {"name": "NAD83 / Texas South (m)", "state": "TX", "zone": "South", "epsg": 32141, "units": "m", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    2275: {"name": "NAD83 / Texas North (USft)", "state": "TX", "zone": "North", "epsg": 2275, "units": "USft", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    2276: {"name": "NAD83 / Texas North Central (USft)", "state": "TX", "zone": "North Central", "epsg": 2276, "units": "USft", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    2277: {"name": "NAD83 / Texas Central (USft)", "state": "TX", "zone": "Central", "epsg": 2277, "units": "USft", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    2278: {"name": "NAD83 / Texas South Central (USft)", "state": "TX", "zone": "South Central", "epsg": 2278, "units": "USft", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    2279: {"name": "NAD83 / Texas South (USft)", "state": "TX", "zone": "South", "epsg": 2279, "units": "USft", "proj": "lcc", "datum": "NAD83", "era": "1986"},
    "2276-ft": {"name": "NAD83 / Texas North Central (intl ft)", "state": "TX", "zone": "North Central", "epsg": "2276-ft", "units": "ft", "proj": "lcc", "datum": "NAD83", "era": "1986", "derived_from": 2276},
    "2278-ft": {"name": "NAD83 / Texas South Central (intl ft)", "state": "TX", "zone": "South Central", "epsg": "2278-ft", "units": "ft", "proj": "lcc", "datum": "NAD83", "era": "1986", "derived_from": 2278},
    "2275-ft": {"name": "NAD83 / Texas North (intl ft)", "state": "TX", "zone": "North", "epsg": "2275-ft", "units": "ft", "proj": "lcc", "datum": "NAD83", "era": "1986", "derived_from": 2275},
    "2277-ft": {"name": "NAD83 / Texas Central (intl ft)", "state": "TX", "zone": "Central", "epsg": "2277-ft", "units": "ft", "proj": "lcc", "datum": "NAD83", "era": "1986", "derived_from": 2277},
    "2279-ft": {"name": "NAD83 / Texas South (intl ft)", "state": "TX", "zone": "South", "epsg": "2279-ft", "units": "ft", "proj": "lcc", "datum": "NAD83", "era": "1986", "derived_from": 2279},
    # ---- NAD27 - the old surveys; US survey feet only in EPSG ..........................
    32037: {"name": "NAD27 / Texas North (USft)", "state": "TX", "zone": "North", "epsg": 32037, "units": "USft", "proj": "lcc", "datum": "NAD27", "era": "1927"},
    32038: {"name": "NAD27 / Texas North Central (USft)", "state": "TX", "zone": "North Central", "epsg": 32038, "units": "USft", "proj": "lcc", "datum": "NAD27", "era": "1927"},
    32039: {"name": "NAD27 / Texas Central (USft)", "state": "TX", "zone": "Central", "epsg": 32039, "units": "USft", "proj": "lcc", "datum": "NAD27", "era": "1927"},
    32040: {"name": "NAD27 / Texas South Central (USft)", "state": "TX", "zone": "South Central", "epsg": 32040, "units": "USft", "proj": "lcc", "datum": "NAD27", "era": "1927"},
    32041: {"name": "NAD27 / Texas South (USft)", "state": "TX", "zone": "South", "epsg": 32041, "units": "USft", "proj": "lcc", "datum": "NAD27", "era": "1927"},
    # ---- WGS 84 direct (lat/lon input, KML) ............................................
    4326: {"name": "WGS 84 (lat/lon)", "state": "WORLD", "zone": "Geographic", "epsg": 4326, "units": "deg", "proj": "longlat", "datum": "WGS84", "era": ""},
}

#: Zones whose *numbers* still matter on old records, and what they are today.  Nothing
#: migrates behind the user's back any more - this is offered as a one-click "use the 2011
#: equivalent" in the dialog - but the map is kept because the field window and
#: `plumbline doctor` both check it.
DEFAULT_ACTIVE_EPSGS = [6584, 6582, 6578, 6588, 6586, 6583, 6581, 6577, 6587, 6585,
                        2275, 2276, 2277, 2278, 2279, 32137, 32138, 32139, 32140, 32141,
                        "2275-ft", "2276-ft", "2277-ft", "2278-ft", "2279-ft",
                        32038, 32037, 32039, 32040, 32041,
                        "6584-ft", "6582-ft", "6578-ft", "6588-ft", "6586-ft", 4326]

LEGACY_2011_MAP = {
    # NAD83 (1986) Texas, US survey feet
    2275: 6582, 2276: 6584, 2277: 6578, 2278: 6588, 2279: 6586,
    # NAD83 (1986) Texas, metres  (32138 is NORTH CENTRAL - the numbers do not line up
    # with the feet series, which is exactly why this map has to be written down)
    32137: 6581, 32138: 6583, 32139: 6577, 32140: 6587, 32141: 6585,
}
def is_derived(key) -> bool:
    """True for a zone this program builds itself because EPSG has no code for it
    (the international-foot Texas zones).  Keyed "<epsg>-ft"."""
    return isinstance(key, str) and key.endswith("-ft")


def base_epsg(key):
    """The EPSG code a derived key stands for, or None for a real EPSG code."""
    return int(str(key)[:-3]) if is_derived(key) else None


def migrate_epsg(epsg):
    """Legacy Texas zone code -> its NAD83(2011) equivalent (2276 -> 6584).

    An unknown code - including the derived "<epsg>-ft" keys - is returned unchanged, so
    this is safe to call on anything.  It is *offered*, never applied silently: modern
    records are still on the older realisations, so a job that says 2276 means 2276.
    """
    if is_derived(epsg):
        return f"{migrate_epsg(base_epsg(epsg))}-ft"
    try:
        return LEGACY_2011_MAP.get(int(epsg), int(epsg))
    except Exception:
        return epsg
def migrate_active_list(lst):
    out=[]
    for e in (lst or []):
        me = migrate_epsg(e)
        if me not in out:
            out.append(me)
    # Ensure at least one 2011 Texas + WGS84
    if not out:
        return DEFAULT_ACTIVE_EPSGS[:]
    # Filter to only known EPSG_LIBRARY (2011 Texas only) + 4326; drop unknowns but keep if they are 2011 migrated
    filtered = [x for x in out if x in EPSG_LIBRARY]
    return filtered or DEFAULT_ACTIVE_EPSGS[:]

def list_texas_systems():
    return {k: v for k, v in EPSG_LIBRARY.items() if v["state"] == "TX"}

def list_active_systems(active_epsgs=None):
    if active_epsgs is None:
        active_epsgs = DEFAULT_ACTIVE_EPSGS
    return {k: EPSG_LIBRARY[k] for k in active_epsgs if k in EPSG_LIBRARY}

def get_epsg_info(epsg: int):
    return EPSG_LIBRARY.get(int(epsg))

def add_custom_epsg(epsg: int, name: str, units="USft", state="CUSTOM", zone="", proj="lcc", datum="NAD83"):
    try:
        epsg = int(epsg)
        try:
            from pyproj import CRS
            crs = CRS.from_epsg(epsg)
            units_auto = "m" if crs.axis_info[0].unit_name == "metre" else "USft" if "foot" in crs.axis_info[0].unit_name.lower() else units
            EPSG_LIBRARY[epsg] = {"name": name or str(crs.name), "state": state, "zone": zone, "epsg": epsg, "units": units_auto, "proj": proj, "datum": datum}
        except Exception:
            EPSG_LIBRARY[epsg] = {"name": name, "state": state, "zone": zone, "epsg": epsg, "units": units, "proj": proj, "datum": datum}
        return True
    except Exception as e:
        print(f"add_custom_epsg failed {epsg}: {e}")
        return False

USFT_TO_METERS = 1200.0 / 3937.0
METERS_TO_USFT = 3937.0 / 1200.0

# Texas LCC params for pure-python fallback (accurate per pyproj EPSG)
# Each entry: lat1, lat2, lat0, lon0 (degrees), fe (meters), fn (meters) — for USft zones fe/fn are in meters (converted from USft)
# Values from pyproj CRS.to_json for each EPSG (see comments above)
# 2011 Texas LCC params (all 2011, USft and meters) — fe/fn in meters (for USft, fe_m = fe_usft * 0.3048006096)
# From pyproj CRS.to_json for 6581-6588
TEXAS_LCC_PARAMS = {
    6581: {"lat1": 36.18333333333333, "lat2": 34.65, "lat0": 34.0, "lon0": -101.5, "fe": 200000.0, "fn": 1000000.0},
    6582: {"lat1": 36.18333333333333, "lat2": 34.65, "lat0": 34.0, "lon0": -101.5, "fe": 200000.0, "fn": 1000000.0},
    6583: {"lat1": 33.96666666666667, "lat2": 32.13333333333333, "lat0": 31.66666666666667, "lon0": -98.5, "fe": 600000.0, "fn": 2000000.0},
    6584: {"lat1": 33.96666666666667, "lat2": 32.13333333333333, "lat0": 31.66666666666667, "lon0": -98.5, "fe": 600000.0, "fn": 2000000.0},
    6577: {"lat1": 31.88333333333333, "lat2": 30.11666666666667, "lat0": 29.66666666666667, "lon0": -100.333333333333, "fe": 700000.0, "fn": 3000000.0},
    6578: {"lat1": 31.88333333333333, "lat2": 30.11666666666667, "lat0": 29.66666666666667, "lon0": -100.333333333333, "fe": 700000.0, "fn": 3000000.0},
    6587: {"lat1": 30.28333333333333, "lat2": 28.38333333333333, "lat0": 27.83333333333333, "lon0": -99.0, "fe": 600000.0, "fn": 4000000.0},
    6588: {"lat1": 30.28333333333333, "lat2": 28.38333333333333, "lat0": 27.83333333333333, "lon0": -99.0, "fe": 600000.0, "fn": 4000000.0},
    6585: {"lat1": 27.83333333333333, "lat2": 26.16666666666667, "lat0": 25.66666666666667, "lon0": -98.5, "fe": 300000.0, "fn": 5000000.0},
    6586: {"lat1": 27.83333333333333, "lat2": 26.16666666666667, "lat0": 25.66666666666667, "lon0": -98.5, "fe": 300000.0, "fn": 5000000.0},
}

# Correct USft vs meters for fallback: For USft EPSG, fe/fn stored as meters (converted), but input E/N are in USft, so we convert to meters first.
# For 2011 Texas (6581-6588, 6577/6578), fe/fn in TEXAS_LCC_PARAMS are already in meters, so we just convert input when units==USft.

GRS80_A = 6378137.0
GRS80_F = 1.0/298.257222101
GRS80_E2 = 2*GRS80_F - GRS80_F*GRS80_F
GRS80_E = math.sqrt(GRS80_E2)

def _lcc_m(lat_rad):
    return math.cos(lat_rad) / math.sqrt(1 - GRS80_E2 * math.sin(lat_rad)**2)

def _lcc_t(lat_rad):
    esin = GRS80_E * math.sin(lat_rad)
    return math.tan(math.pi/4 - lat_rad/2) / ((1 - esin)/(1 + esin))**(GRS80_E/2)

def _lcc_inverse(x_m, y_m, lat1_d, lat2_d, lat0_d, lon0_d, fe_m, fn_m):
    lat1 = math.radians(lat1_d); lat2 = math.radians(lat2_d); lat0 = math.radians(lat0_d); lon0 = math.radians(lon0_d)
    m1 = _lcc_m(lat1); m2 = _lcc_m(lat2)
    t1 = _lcc_t(lat1); t2 = _lcc_t(lat2); t0 = _lcc_t(lat0)
    n = math.log(m1/m2) / math.log(t1/t2)
    F = m1 / (n * t1**n)
    rho0 = GRS80_A * F * t0**n
    dx = x_m - fe_m
    dy = y_m - fn_m
    rho = math.hypot(dx, rho0 - dy)
    if n < 0:
        rho = -rho
    theta = math.atan2(dx, rho0 - dy)
    t = (rho / (GRS80_A * F))**(1/n)
    lat_rad = math.pi/2 - 2*math.atan(t)
    for _ in range(5):
        esin = GRS80_E * math.sin(lat_rad)
        lat_rad = math.pi/2 - 2*math.atan(t * ((1 - esin)/(1 + esin))**(GRS80_E/2))
    lon_rad = lon0 + theta / n
    return math.degrees(lat_rad), math.degrees(lon_rad)

def _texas_lcc_to_wgs84(e, n, epsg, units):
    params = TEXAS_LCC_PARAMS.get(int(epsg))
    if not params:
        return None, None
    if units == "USft":
        e_m = e * USFT_TO_METERS
        n_m = n * USFT_TO_METERS
    else:
        e_m = e
        n_m = n
    lat, lon = _lcc_inverse(e_m, n_m, params["lat1"], params["lat2"], params["lat0"], params["lon0"], params["fe"], params["fn"])
    return lon, lat

def _saf_scaler(saf, base_n=None, base_e=None):
    """The affine scaling itself lives in exactly one place: ``plumbline.core.crs``.

    This field-side spelling exists because the field window's export code has always called
    a function with this shape, and because a second implementation of the same arithmetic is
    how two programs end up disagreeing about where a job is.  SAF is ground over grid, so
    ``ground = grid * saf`` and the scalar is applied about the base point - which the TXDOT
    SOP sets to the projection origin (0, 0).
    """
    from ..core.crs import SurfaceAdjustmentFactor
    g = SurfaceAdjustmentFactor(enabled=True, saf=float(saf))
    if base_n is not None and base_e is not None:
        g.base_y, g.base_x = float(base_n), float(base_e)
    return g


def apply_surface_factor(n, e, factor: float, base_n=None, base_e=None, direction="ground_to_grid"):
    """TXDOT SOP SAF — affine scaling from origin (0,0), not base point.
    SAF (Surface Adjustment Factor) is county-wide factor per TXDOT. Ground = Grid * SAF, Grid = Ground / SAF.
    Scaling is from origin (0,0) — i.e., N_grid = N_ground / SAF, E_grid = E_ground / SAF if ground, else no change.
    This is NOT the same as CSF manipulation via base point. For TXDOT, always scale from 0,0.
    direction: "ground_to_grid" means input is ground (SAF applied) → divide by SAF to get grid for projection.
               "grid_to_ground" means input is grid → multiply by SAF (not used for KML, but kept for completeness).
    base_n/base_e are IGNORED per TXDOT SOP (kept for backward compat but not used).
    """
    if factor is None or abs(factor - 1.0) < 1e-12:
        return n, e
    try:
        g = _saf_scaler(factor, base_n, base_e)
        if direction == "ground_to_grid":                       # ground in -> reduce to grid
            x, y = g.to_grid(float(e), float(n))
        else:                                                   # grid in -> scale up to ground
            x, y = g.from_grid(float(e), float(n))
        return float(y), float(x)
    except Exception:
        return n, e

def apply_saf(n, e, saf: float, is_ground: bool = True):
    """TXDOT SAF helper — is_ground True means input is ground (SAF applied) and needs to be reduced to grid.
    Ground = Grid * SAF  => Grid = Ground / SAF
    """
    if saf is None or abs(saf - 1.0) < 1e-12:
        return n, e
    try:
        g = _saf_scaler(saf)
        x, y = (g.to_grid(float(e), float(n)) if is_ground else g.from_grid(float(e), float(n)))
        return float(y), float(x)
    except Exception:
        return n, e

def convert_to_wgs84(n, e, epsg: int, surface_factor=1.0, factor_mode="ground_to_grid", base_n=None, base_e=None, is_ground=None):
    try:
        n = float(n); e = float(e)
    except:
        return None, None
    # TXDOT SOP: surface_factor is SAF (ground = grid * SAF). If is_ground is not None, use it; else infer from factor_mode
    # factor_mode "ground_to_grid" => is_ground True => divide by SAF
    # Preserve backward compat: surface_factor param is SAF
    if is_ground is None:
        is_ground = (factor_mode == "ground_to_grid")
    # Only apply if is_ground True (input is ground) — otherwise no conversion needed for grid
    if is_ground and surface_factor is not None and abs(surface_factor - 1.0) > 1e-12:
        n, e = apply_saf(n, e, surface_factor, is_ground=True)
    info = get_epsg_info(epsg)
    if info and info["epsg"] == 4326:
        return float(e), float(n)
    try:
        from pyproj import Transformer, CRS
        transformer = Transformer.from_crs(CRS.from_epsg(int(epsg)), CRS.from_epsg(4326), always_xy=True)
        lon, lat = transformer.transform(e, n)
        return lon, lat
    except ImportError:
        try:
            info2 = get_epsg_info(epsg)
            units = info2["units"] if info2 else "USft"
            if int(epsg) in TEXAS_LCC_PARAMS:
                lon2, lat2 = _texas_lcc_to_wgs84(e, n, int(epsg), units)
                if lon2 is not None and lat2 is not None:
                    return lon2, lat2
        except Exception as e2:
            print(f"pure-python fallback failed {e2}")
        return None, None
    except Exception as ex:
        try:
            info2 = get_epsg_info(epsg)
            units = info2["units"] if info2 else "USft"
            if int(epsg) in TEXAS_LCC_PARAMS:
                lon2, lat2 = _texas_lcc_to_wgs84(e, n, int(epsg), units)
                if lon2 is not None:
                    return lon2, lat2
        except: pass
        print(f"convert_to_wgs84 failed epsg {epsg} N={n} E={e}: {ex}")
        return None, None

def bulk_convert(working_rows, epsg: int, surface_factor=1.0, factor_mode="ground_to_grid", base_n=None, base_e=None, is_ground=None):
    out = []
    for row in working_rows:
        if len(row) < 5:
            continue
        oid = row[0]
        pt = row[1]
        n = row[2]
        e = row[3]
        z = row[4] if len(row) > 4 else ""
        try:
            lon, lat = convert_to_wgs84(n, e, epsg, surface_factor, factor_mode, base_n, base_e, is_ground)
        except:
            lon, lat = None, None
        out.append({"oid": oid, "pt": pt, "lat": lat, "lon": lon, "z": z, "n": n, "e": e, "desc": row[5] if len(row) > 5 else ""})
    return out

def epsg_choices_for_combo(active_epsgs=None, include_all=False):
    if include_all:
        items = list(EPSG_LIBRARY.values())
    else:
        items = list(list_active_systems(active_epsgs).values())
    items.sort(key=lambda x: (x["state"], x["zone"]))
    return [(it["epsg"], f"{it['epsg']} — {it['name']} ({it['units']})") for it in items]

MESQUITE_TX_LAT = 32.77
MESQUITE_TX_LON = -96.61
MESQUITE_TX_RECOMMENDED_EPSG = 6584  # NAD83 Texas North Central (USft) — 2276 is North Central per pyproj

