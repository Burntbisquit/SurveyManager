"""Open a place in Google Maps: lat/lon of a plan-view center, a matching zoom level and the link."""
from __future__ import annotations

import math

from . import units as U

M_PER_PX_Z0 = 156543.03392804097          # Web-Mercator metres per pixel at zoom 0 on the equator (256 px tiles)


def meters_per_pixel(view_scale: float, h_unit: str) -> float:
    """Plan view scale (pixels per project unit) -> metres per screen pixel."""
    return U.M_PER_UNIT[h_unit] / max(view_scale, 1e-12)


def zoom_for_meters_per_pixel(m_per_px: float, lat: float, lo: float = 3.0, hi: float = 21.0) -> float:
    """The Google Maps zoom level whose pixels are the same size on the ground as the plan view's."""
    z = math.log2(M_PER_PX_Z0 * max(math.cos(math.radians(lat)), 1e-6) / max(m_per_px, 1e-9))
    return float(min(max(z, lo), hi))


def google_maps_url(lat: float, lon: float, zoom: float = 18.0, satellite: bool = True, pin: bool = True) -> str:
    """A Google Maps link centered on lat/lon.  `pin` drops a marker there; `satellite` selects the imagery layer."""
    ll = f"{lat:.7f},{lon:.7f}"
    z = f"{zoom:.2f}".rstrip("0").rstrip(".")
    path = (f"place/{ll}/" if pin else "") + f"@{ll},{z}z"
    if satellite:
        path += "/data=!3m1!1e3"
    return "https://www.google.com/maps/" + path


def view_center_lonlat(project, x: float, y: float):
    """(lon, lat) in WGS84 of a point in project coordinates.  Raises LocalCRSError for a local coordinate system."""
    try:
        lon, lat = project.crs.to_lonlat(x, y, target=4326)
    except Exception as e:                       # a missing datum-shift grid etc.: fall back to the project's own datum
        from .crs import LocalCRSError
        if isinstance(e, LocalCRSError):
            raise
        lon, lat = project.crs.to_lonlat(x, y)
    return float(lon), float(lat)


def maps_link_for_view(project, cx: float, cy: float, view_scale: float, satellite: bool = True) -> tuple[str, float, float, float]:
    """(url, lat, lon, zoom) for the plan view centered on (cx, cy) at `view_scale` pixels per project unit."""
    lon, lat = view_center_lonlat(project, cx, cy)
    zoom = zoom_for_meters_per_pixel(meters_per_pixel(view_scale, project.h_unit), lat)
    return google_maps_url(lat, lon, zoom, satellite), lat, lon, zoom
