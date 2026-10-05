"""Web tile sources with an on-disk cache and a small background download pool (no Qt needed)."""
from __future__ import annotations

import hashlib
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "Plumbline/0.1 (+desktop survey CAD; contact: local user)"


def _md5(text: str) -> str:
    """md5 for cache keys only. `usedforsecurity=False` keeps it working on FIPS builds."""
    try:
        return hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()
    except TypeError:                                   # Python < 3.9 or an unusual build
        return hashlib.md5(text.encode()).hexdigest()


@dataclass
class TileSource:
    name: str
    url: str                              # {z} {x} {y} and optional {s}
    max_zoom: int = 19
    min_zoom: int = 0
    attribution: str = ""
    tile_size: int = 256
    subdomains: str = ""
    ext: str = "jpg"
    headers: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        slug = "".join(c if c.isalnum() else "_" for c in self.name)[:24]
        return f"{slug}_{_md5(self.url)[:8]}"

    def url_for(self, z: int, x: int, y: int) -> str:
        s = self.subdomains[(x + y) % len(self.subdomains)] if self.subdomains else ""
        return self.url.format(z=z, x=x, y=y, s=s)

    def to_dict(self) -> dict:
        return {"name": self.name, "url": self.url, "max_zoom": self.max_zoom, "min_zoom": self.min_zoom,
                "attribution": self.attribution, "tile_size": self.tile_size,
                "subdomains": self.subdomains, "ext": self.ext, "headers": self.headers}

    @classmethod
    def from_dict(cls, d: dict) -> "TileSource":
        return cls(d["name"], d["url"], d.get("max_zoom", 19), d.get("min_zoom", 0), d.get("attribution", ""),
                   d.get("tile_size", 256), d.get("subdomains", ""), d.get("ext", "jpg"), d.get("headers", {}))


PRESETS = [
    TileSource("Esri World Imagery",
               "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
               19, 0, "Imagery © Esri, Maxar, Earthstar Geographics, and the GIS User Community"),
    TileSource("USGS Imagery (The National Map)",
               "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/tile/{z}/{y}/{x}",
               16, 0, "USGS The National Map: Orthoimagery"),
    TileSource("OpenStreetMap (context only)", "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
               19, 0, "© OpenStreetMap contributors", ext="png"),
]


class TileStore:
    """Disk-cached tile access. get_cached() is instant; request() downloads in the background."""

    def __init__(self, cache_dir, offline: bool = False, workers: int = 6, retry_after: float = 45.0):
        self.cache_dir = Path(cache_dir)
        self.offline = offline
        self.retry_after = retry_after
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="tiles")
        self._inflight: set = set()
        self._failed: dict = {}
        self._lock = threading.Lock()

    def path_for(self, src: TileSource, z: int, x: int, y: int) -> Path:
        return self.cache_dir / src.key / str(z) / str(x) / f"{y}.{src.ext}"

    def get_cached(self, src: TileSource, z: int, x: int, y: int) -> bytes | None:
        p = self.path_for(src, z, x, y)
        try:
            return p.read_bytes()
        except OSError:
            return None

    def fetch(self, src: TileSource, z: int, x: int, y: int, timeout: float = 15.0) -> bytes:
        """Blocking download (writes the cache). Raises on failure."""
        data = self.get_cached(src, z, x, y)
        if data:
            return data
        if self.offline:
            raise RuntimeError("offline mode")
        req = urllib.request.Request(src.url_for(z, x, y), headers={"User-Agent": USER_AGENT, **src.headers})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read()
        if len(data) < 64:
            raise RuntimeError("empty tile")
        p = self.path_for(src, z, x, y)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(p)
        return data

    def request(self, src: TileSource, z: int, x: int, y: int, callback) -> bool:
        """Queue a load. callback(src, z, x, y, data_or_None) runs on a worker thread.

        In offline mode only the disk cache is consulted (the worker finds nothing -> data is None).
        """
        key = (src.key, z, x, y)
        with self._lock:
            if key in self._inflight:
                return False
            t = self._failed.get(key)
            if t and time.time() - t < self.retry_after:
                return False
            self._inflight.add(key)

        def work():
            data = None
            try:
                data = self.fetch(src, z, x, y)
            except Exception:
                with self._lock:
                    self._failed[key] = time.time()
            finally:
                with self._lock:
                    self._inflight.discard(key)
            try:
                callback(src, z, x, y, data)
            except Exception:
                pass

        self._pool.submit(work)
        return True

    def pending(self) -> int:
        with self._lock:
            return len(self._inflight)

    def clear_failed(self):
        with self._lock:
            self._failed.clear()

    def cache_size_mb(self) -> float:
        total = 0
        for p in self.cache_dir.rglob("*"):
            if p.is_file():
                total += p.stat().st_size
        return total / 1e6

    def shutdown(self):
        self._pool.shutdown(wait=False, cancel_futures=True)


# ----------------------------------------------------------------------------- imagery metadata
ESRI_IDENTIFY = "https://services.arcgisonline.com/arcgis/rest/services/World_Imagery/MapServer/identify"


def fetch_esri_metadata(lon: float, lat: float, timeout: float = 15.0) -> dict:
    """Ask Esri's World Imagery service who made the imagery at this spot, when, and how accurate it claims to be.

    Blocking network call (run it on a worker thread).  Returns {} fields as strings/floats or raises on failure.
    """
    import json
    import urllib.parse

    d = 0.0004
    q = urllib.parse.urlencode({
        "geometry": f"{lon},{lat}", "geometryType": "esriGeometryPoint", "sr": "4326", "layers": "all",
        "tolerance": "2", "mapExtent": f"{lon - d},{lat - d},{lon + d},{lat + d}", "imageDisplay": "400,400,96",
        "returnGeometry": "false", "f": "json"})
    req = urllib.request.Request(f"{ESRI_IDENTIFY}?{q}", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8", "replace"))
    best = None
    for res in data.get("results", []):
        a = res.get("attributes", {})
        if res.get("layerId") in (3, 2, 0) and ("ACCURACY (M)" in a):
            best = a
            if res.get("layerId") == 0:
                break
    if best is None:
        raise RuntimeError("no metadata returned for this location")

    def num(k):
        try:
            return float(best.get(k))
        except (TypeError, ValueError):
            return None

    date = best.get("SRC_DATE2") or best.get("DATE (YYYYMMDD)") or ""
    return {"provider": "Esri World Imagery", "source": best.get("SOURCE", ""), "product": best.get("SOURCE_INFO", ""),
            "sensor": best.get("DESCRIPTION", ""), "date": date, "resolution_m": num("RESOLUTION (M)"),
            "accuracy_m": num("ACCURACY (M)"), "lon": lon, "lat": lat,
            "queried": time.strftime("%Y-%m-%d %H:%M")}
