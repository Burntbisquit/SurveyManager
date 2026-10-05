"""Imagery maths: Web-Mercator tiles and survey-vs-imagery check statistics (NSSDA style)."""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

R_EARTH = 6378137.0
MERC_ORIGIN = math.pi * R_EARTH


# ----------------------------------------------------------------------------- Web Mercator
def lonlat_to_merc(lon, lat):
    lon = np.asarray(lon, float)
    lat = np.clip(np.asarray(lat, float), -85.05112878, 85.05112878)
    x = R_EARTH * np.radians(lon)
    y = R_EARTH * np.log(np.tan(np.pi / 4.0 + np.radians(lat) / 2.0))
    return x, y


def merc_to_lonlat(x, y):
    x = np.asarray(x, float)
    y = np.asarray(y, float)
    lon = np.degrees(x / R_EARTH)
    lat = np.degrees(2.0 * np.arctan(np.exp(y / R_EARTH)) - np.pi / 2.0)
    return lon, lat


def tile_size_merc(z: int) -> float:
    return 2 * MERC_ORIGIN / (2 ** z)


def tile_bounds_merc(z: int, tx: int, ty: int):
    s = tile_size_merc(z)
    xmin = -MERC_ORIGIN + tx * s
    ymax = MERC_ORIGIN - ty * s
    return xmin, ymax - s, xmin + s, ymax


def merc_to_tile_float(z: int, mx, my):
    s = tile_size_merc(z)
    return (np.asarray(mx) + MERC_ORIGIN) / s, (MERC_ORIGIN - np.asarray(my)) / s


def tiles_for_bbox(z: int, xmin, ymin, xmax, ymax, limit: int = 400):
    n = 2 ** z
    tx0, ty1 = merc_to_tile_float(z, xmin, ymin)
    tx1, ty0 = merc_to_tile_float(z, xmax, ymax)
    x0, x1 = int(math.floor(min(tx0, tx1))), int(math.floor(max(tx0, tx1)))
    y0, y1 = int(math.floor(min(ty0, ty1))), int(math.floor(max(ty0, ty1)))
    x0, y0 = max(x0, 0), max(y0, 0)
    x1, y1 = min(x1, n - 1), min(y1, n - 1)
    out = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)]
    return out if len(out) <= limit else []


def zoom_for_resolution(ground_m_per_px: float, lat_deg: float, tile_px: int = 256,
                        bias: float = 0.0) -> float:
    """Fractional web-map zoom whose pixel size matches the requested ground resolution."""
    merc_per_px = ground_m_per_px / max(math.cos(math.radians(lat_deg)), 1e-6)
    return math.log2((2 * MERC_ORIGIN / tile_px) / merc_per_px) + bias


# ----------------------------------------------------------------------------- check statistics
@dataclass
class CheckStats:
    n: int = 0
    mean_dx: float = 0.0
    mean_dy: float = 0.0
    mean_d: float = 0.0
    max_d: float = 0.0
    std_x: float = 0.0
    std_y: float = 0.0
    rmse_x: float = 0.0
    rmse_y: float = 0.0
    rmse_r: float = 0.0
    rmse_r_after_shift: float = 0.0       # scatter left once the mean shift is removed
    nssda_95: float = 0.0
    nssda_note: str = ""
    shift_dx: float = 0.0                 # suggested imagery nudge (-mean offset)
    shift_dy: float = 0.0
    fit_rot_deg: float | None = None      # best-fit similarity (image -> survey)
    fit_scale_ppm: float | None = None
    fit_rmse: float | None = None
    tol: float | None = None
    n_within_tol: int | None = None
    warnings: list = field(default_factory=list)


def compute_check_stats(dx, dy, tol: float | None = None, image_xy=None, survey_xy=None) -> CheckStats:
    dx = np.asarray(dx, float)
    dy = np.asarray(dy, float)
    n = len(dx)
    s = CheckStats(n=n, tol=tol)
    if n == 0:
        return s
    d = np.hypot(dx, dy)
    s.mean_dx, s.mean_dy = float(dx.mean()), float(dy.mean())
    s.mean_d, s.max_d = float(d.mean()), float(d.max())
    s.std_x = float(dx.std(ddof=1)) if n > 1 else 0.0
    s.std_y = float(dy.std(ddof=1)) if n > 1 else 0.0
    s.rmse_x = float(math.sqrt((dx ** 2).mean()))
    s.rmse_y = float(math.sqrt((dy ** 2).mean()))
    s.rmse_r = math.hypot(s.rmse_x, s.rmse_y)
    s.rmse_r_after_shift = float(math.sqrt(((dx - dx.mean()) ** 2 + (dy - dy.mean()) ** 2).mean()))
    lo, hi = sorted((s.rmse_x, s.rmse_y))
    ratio = lo / hi if hi > 0 else 1.0
    if ratio >= 0.6:
        s.nssda_95 = 2.4477 * 0.5 * (s.rmse_x + s.rmse_y)
        s.nssda_note = "Accuracy_r = 2.4477 x 0.5 x (RMSE_x + RMSE_y)"
    else:
        s.nssda_95 = 1.7308 * s.rmse_r
        s.nssda_note = "RMSE_x/RMSE_y < 0.6 - circular NSSDA formula is only approximate; review X and Y separately"
    if n < 20:
        s.warnings.append(f"NSSDA recommends at least 20 check points (you have {n}); treat the 95% figure as indicative.")
    s.shift_dx, s.shift_dy = -s.mean_dx, -s.mean_dy
    if tol is not None:
        s.n_within_tol = int((d <= tol).sum())
    if image_xy is not None and survey_xy is not None and n >= 3:
        try:
            sc, rot, _t, rm = fit_similarity(np.asarray(image_xy, float), np.asarray(survey_xy, float))
            s.fit_rot_deg, s.fit_scale_ppm, s.fit_rmse = math.degrees(rot), (sc - 1.0) * 1e6, rm
        except Exception:
            pass
    return s


def fit_similarity(src: np.ndarray, dst: np.ndarray):
    """Least-squares 2D similarity (Umeyama): dst ~= s * R(rot) @ src + t.  Returns (s, rot_rad, t, rmse)."""
    src = np.asarray(src, float)
    dst = np.asarray(dst, float)
    mu_s, mu_d = src.mean(axis=0), dst.mean(axis=0)
    a, b = src - mu_s, dst - mu_d
    cov = b.T @ a / len(src)
    U, S, Vt = np.linalg.svd(cov)
    D = np.eye(2)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        D[1, 1] = -1
    Rm = U @ D @ Vt
    var_s = (a ** 2).sum() / len(src)
    scale = float((S * np.diag(D)).sum() / var_s) if var_s > 0 else 1.0
    t = mu_d - scale * Rm @ mu_s
    pred = (scale * (Rm @ src.T)).T + t
    rmse = float(np.sqrt(((pred - dst) ** 2).sum(axis=1).mean()))
    rot = math.atan2(Rm[1, 0], Rm[0, 0])
    return scale, rot, t, rmse


# ----------------------------------------------------------------------------- georeferenced image files
_WORLD_EXT = {".png": [".pgw", ".pngw"], ".jpg": [".jgw", ".jpgw"], ".jpeg": [".jgw", ".jpegw"],
              ".tif": [".tfw", ".tifw"], ".tiff": [".tfw", ".tiffw"], ".bmp": [".bpw", ".bmpw"], ".gif": [".gfw", ".gifw"]}


def find_world_file(path):
    from pathlib import Path
    p = Path(path)
    for ext in _WORLD_EXT.get(p.suffix.lower(), []) + [".wld"]:
        for e in (ext, ext.upper()):
            q = p.with_suffix(e)
            if q.exists():
                return q
    return None


def read_world_file(path) -> tuple:
    with open(path, encoding="utf-8-sig", errors="replace") as fh:       # numbers only, but be explicit (Windows defaults to cp1252)
        v = [float(l.split()[0]) for l in fh.read().splitlines() if l.strip()][:6]
    if len(v) < 6:
        raise ValueError("world file needs 6 lines")
    return tuple(v)            # A, D, B, E, C, F  (file order)


def _to_rgba(arr: np.ndarray) -> np.ndarray:
    """(bands, H, W) or (H, W, bands) numeric -> (H, W, 4) uint8."""
    a = np.asarray(arr)
    if a.ndim == 2:
        a = a[None]
    if a.shape[0] in (1, 2, 3, 4) and a.shape[-1] not in (1, 2, 3, 4):
        a = np.moveaxis(a, 0, -1)
    elif a.shape[0] in (1, 3, 4) and a.shape[0] < a.shape[-1]:
        a = np.moveaxis(a, 0, -1)
    if a.dtype != np.uint8:
        f = a.astype(np.float64)
        lo, hi = np.nanpercentile(f, 1), np.nanpercentile(f, 99)
        a = np.clip((f - lo) / max(hi - lo, 1e-9) * 255.0, 0, 255).astype(np.uint8)
    h, w, b = a.shape
    out = np.empty((h, w, 4), np.uint8)
    if b == 1:
        out[..., :3] = a
        out[..., 3] = 255
    elif b == 2:
        out[..., :3] = a[..., :1]
        out[..., 3] = a[..., 1]
    elif b == 3:
        out[..., :3] = a
        out[..., 3] = 255
    else:
        out[...] = a[..., :4]
    return out


def read_georeferenced_image(path, max_dim: int = 6000) -> dict:
    """Load an image with its geo-position.

    Returns {"rgba": (H,W,4) uint8, "corners": [TL, TR, BL] as (x, y), "crs": str | None, "size": (W, H)}
    `crs` is None for plain world-file images (assume the project CRS).  Corners are PIXEL CORNERS.
    """
    from pathlib import Path
    p = Path(path)
    try:
        import warnings

        import rasterio
        from rasterio.enums import Resampling
        warnings.simplefilter("ignore", rasterio.errors.NotGeoreferencedWarning)
        with rasterio.open(p) as ds:
            W, H = ds.width, ds.height
            tr = ds.transform
            if not tr.is_identity:
                f = min(1.0, max_dim / max(W, H))
                oh, ow = max(1, int(H * f)), max(1, int(W * f))
                idx = [1, 2, 3][:ds.count] if ds.count >= 3 else [1]
                if ds.count >= 4:
                    idx = [1, 2, 3, 4]
                data = ds.read(idx, out_shape=(len(idx), oh, ow), resampling=Resampling.bilinear)
                crs = ds.crs.to_wkt() if ds.crs else None
                tl, trc, bl = tr @ (0, 0), tr @ (W, 0), tr @ (0, H)
                return {"rgba": _to_rgba(data), "corners": [tuple(tl), tuple(trc), tuple(bl)], "crs": crs, "size": (W, H)}
    except ImportError:
        pass
    except Exception:
        pass
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    wf = find_world_file(p)
    if wf is None:
        raise ValueError("No georeferencing found: this image needs a GeoTIFF header or a world file (.pgw/.jgw/.tfw/.wld).")
    A, D, B, E, C, F = read_world_file(wf)
    im = Image.open(p)
    W, H = im.size
    f = min(1.0, max_dim / max(W, H))
    if f < 1.0:
        im = im.resize((max(1, int(W * f)), max(1, int(H * f))), Image.BILINEAR)
    im = im.convert("RGBA")
    # world files give the CENTRE of the top-left pixel; convert to the pixel corner
    c0, f0 = C - 0.5 * A - 0.5 * B, F - 0.5 * D - 0.5 * E
    tl = (c0, f0)
    trc = (c0 + A * W, f0 + D * W)
    bl = (c0 + B * H, f0 + E * H)
    return {"rgba": np.asarray(im, np.uint8), "corners": [tl, trc, bl], "crs": None, "size": (W, H)}


def kml_overlay_corners(north, south, east, west, rotation_deg: float = 0.0):
    """GroundOverlay LatLonBox -> [TL, TR, BL] in (lon, lat); rotation is counter-clockwise about the centre."""
    cx, cy = (east + west) / 2, (north + south) / 2
    pts = [(west, north), (east, north), (west, south)]
    if rotation_deg:
        a = math.radians(rotation_deg)
        ca, sa = math.cos(a), math.sin(a)
        k = math.cos(math.radians(cy))               # degrees of longitude shrink with latitude
        out = []
        for x, y in pts:
            dx, dy = (x - cx) * k, (y - cy)
            out.append((cx + (dx * ca - dy * sa) / k, cy + dx * sa + dy * ca))
        pts = out
    return pts
