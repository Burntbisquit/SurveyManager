"""Vector icons drawn from inline SVG (no image files to ship)."""
from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "select": '<path d="M5 3l14 7-6 2-2 6z"/>',
    "pan": '<path d="M18 11V6a2 2 0 0 0-4 0v4M14 10V4a2 2 0 0 0-4 0v6M10 10.5V6a2 2 0 0 0-4 0v8a6 6 0 0 0 12 0v-3a2 2 0 0 0-4 0v0"/>',
    "zoom_window": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21M10.5 8v5M8 10.5h5"/>',
    "zoom_extents": '<path d="M3 8V3h5M21 8V3h-5M3 16v5h5M21 16v5h-5M3 3l6 6M21 3l-6 6M3 21l6-6M21 21l-6-6"/><circle cx="12" cy="12" r="2.5"/>',
    "zoom_selected": '<rect x="3" y="3" width="18" height="18" rx="2" stroke-dasharray="3 3"/><circle cx="12" cy="12" r="4"/><path d="M12 9v6M9 12h6"/>',
    "check_points": '<circle cx="9" cy="9" r="3"/><path d="M9 2v4M9 12v4M2 9h4M12 9h4M13 17l3 3 5-5"/>',
    "check_lines": '<path d="M3 14l4-7 5 5 4-6"/><circle cx="3" cy="14" r="1.4"/><circle cx="7" cy="7" r="1.4"/><circle cx="12" cy="12" r="1.4"/><circle cx="16" cy="6" r="1.4"/><path d="M13 18l3 3 5-5"/>',
    "measure": '<g transform="rotate(-35 12 12)"><rect x="1.5" y="8.5" width="21" height="7" rx="1"/><path d="M5 8.5v3M8.5 8.5v2M12 8.5v3M15.5 8.5v2M19 8.5v3"/></g>',
    "polyline": '<path d="M4 18l5-9 5 6 6-10"/><circle cx="4" cy="18" r="1.4"/><circle cx="9" cy="9" r="1.4"/><circle cx="14" cy="15" r="1.4"/><circle cx="20" cy="5" r="1.4"/>',
    "arc": '<path d="M4 19A12 12 0 0 1 20 19"/><circle cx="4" cy="19" r="1.4"/><circle cx="20" cy="19" r="1.4"/><circle cx="12" cy="7.4" r="1.2"/>',
    "point": '<circle cx="12" cy="12" r="3"/><path d="M12 3v4M12 17v4M3 12h4M17 12h4"/>',
    "text": '<path d="M5 6V4h14v2M12 4v16M9 20h6"/>',
    "check": '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="1.8"/><path d="M12 1.5v4M12 18.5v4M1.5 12h4M18.5 12h4"/>',
    "layers": '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 12.5l9 5 9-5"/><path d="M3 17l9 5 9-5"/>',
    "table": '<rect x="3" y="4" width="18" height="16" rx="1.5"/><path d="M3 10h18M3 15h18M9 4v16"/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10a6 6 0 0 1 0 12h-3"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H10a6 6 0 0 0 0 12h3"/>',
    "open": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "save": '<path d="M5 3h11l3 3v15H5z"/><path d="M8 3v6h8V3M8 21v-7h8v7"/>',
    "new": '<path d="M6 3h8l5 5v13H6z"/><path d="M14 3v5h5M12 12v6M9 15h6"/>',
    "import": '<path d="M12 3v12M7 10l5 5 5-5M4 20h16"/>',
    "export": '<path d="M12 15V3M7 8l5-5 5 5M4 20h16"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3.5 3 3.5 15 0 18M12 3c-3.5 3-3.5 15 0 18"/>',
    "surface": '<path d="M3 18L8 7l6 5 7-7v13z"/><path d="M8 7v11M14 12v6M8 18l6-6"/>',
    "contour": '<ellipse cx="12" cy="12" rx="9" ry="6"/><ellipse cx="12" cy="12" rx="5.5" ry="3.3"/><ellipse cx="12" cy="12" rx="2" ry="1.1"/>',
    "volume": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M12 12l8-4.5M12 12v9M12 12L4 7.5"/>',
    "profile": '<path d="M3 20h18M3 20V4"/><path d="M5 15l4-5 4 3 6-7"/>',
    "report": '<path d="M6 3h9l4 4v14H6z"/><path d="M9 11h7M9 14h7M9 17h4"/>',
    "play": '<path d="M7 4l13 8-13 8z"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v6M14 11v6"/>',
    "eye": '<path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>',
    "eye_off": '<path d="M3 3l18 18M10.6 5.1A9.7 9.7 0 0 1 12 5c6 0 10 7 10 7a17 17 0 0 1-3.2 4M6.3 6.4C3.5 8.2 2 12 2 12s4 7 10 7c1.6 0 3-.4 4.3-1M9.9 9.9a3 3 0 0 0 4.2 4.2"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
    "unlock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.5-2"/>',
    "snap": '<path d="M5 3v8a7 7 0 0 0 14 0V3h-4v8a3 3 0 0 1-6 0V3z"/><path d="M5 7h4M15 7h4"/>',
    "inverse": '<path d="M4 20L20 4"/><circle cx="4" cy="20" r="1.8"/><circle cx="20" cy="4" r="1.8"/><path d="M4 20h9M8 20a6 6 0 0 0 2-4"/>',
    "area": '<path d="M5 18l2-11 10-3 3 12z"/>',
    "search": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5L21 21"/>',
    "star": '<path d="M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
    "move": '<path d="M12 2v20M2 12h20M12 2l-3 3M12 2l3 3M12 22l-3-3M12 22l3-3M2 12l3-3M2 12l3 3M22 12l-3-3M22 12l-3 3"/>',
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0zM12 18v4"/>',
    "terminal": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9l3 3-3 3M12 15h5"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="9" cy="10" r="1.8"/><path d="M3 17l5-5 4 4 3-3 6 6"/>',
    "warning": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6M12 7.5v.5"/>',
    "close": '<path d="M5 5l14 14M19 5L5 19"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "minus": '<path d="M5 12h14"/>',
    "refresh": '<path d="M20 11A8 8 0 0 0 5.5 7M4 4v4h4M4 13a8 8 0 0 0 14.5 4M20 20v-4h-4"/>',
    "copy": '<rect x="9" y="9" width="11" height="11" rx="1.5"/><path d="M5 15V5a1 1 0 0 1 1-1h10"/>',
    "tag": '<path d="M3 12V4h8l10 10-8 8z"/><circle cx="7.5" cy="8.5" r="1.3"/>',
    "grid": '<path d="M3 3h18v18H3zM3 9h18M3 15h18M9 3v18M15 3v18"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/>',
    "compass": '<circle cx="12" cy="12" r="9"/><path d="M15.5 8.5l-2 5-5 2 2-5z"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r=".8"/>',
    "next": '<path d="M5 12h14M13 6l6 6-6 6"/>',
    "prev": '<path d="M19 12H5M11 6l-6 6 6 6"/>',
    "skip": '<path d="M5 5l8 7-8 7zM16 5v14"/>',
    "orbit": '<circle cx="12" cy="12" r="3.4"/><ellipse cx="12" cy="12" rx="10" ry="4.2" transform="rotate(-28 12 12)"/><path d="M12 2.5v3M12 18.5v3"/>',
    "section": '<path d="M3 20h18"/><path d="M3 16l5-4 4 2 4-5 5 3"/><path d="M12 3v6M9.5 6.6L12 9.1l2.5-2.5"/>',
    "section_line": '<path d="M3 18h18"/><path d="M12 14V4M8.5 7.5L12 4l3.5 3.5"/><circle cx="3" cy="18" r="1.5"/><circle cx="21" cy="18" r="1.5"/>',
    "pin": '<path d="M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z"/><circle cx="12" cy="10" r="2.6"/>',
    "edit": '<path d="M12 20h9M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
}

APP_ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
<rect width="64" height="64" rx="14" fill="#16314d"/>
<path d="M32 8v30" stroke="#e8f1fa" stroke-width="3" stroke-linecap="round"/>
<path d="M32 38l9 8-9 12-9-12z" fill="#2fa8ff" stroke="#e8f1fa" stroke-width="2.5" stroke-linejoin="round"/>
<circle cx="32" cy="9" r="3.5" fill="#ffd24a"/>
<path d="M10 56h44" stroke="#2fa8ff" stroke-width="2" stroke-linecap="round" opacity=".6"/></svg>"""

_cache: dict = {}


def _svg(name: str, color: str, size: int, sw: float = 1.8) -> str:
    inner = _P[name]
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{size}" height="{size}" fill="none" '
            f'stroke="{color}" stroke-width="{sw}" stroke-linecap="round" stroke-linejoin="round">{inner}</svg>')


def pixmap(name: str, color: str = "#d9dee5", size: int = 22, dpr: float = 2.0) -> QPixmap:
    px = int(size * dpr)
    img = QImage(px, px, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, color, px).encode()))
    p = QPainter(img)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm = QPixmap.fromImage(img)
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str | None = None) -> QIcon:
    from . import theme
    col = color or theme.colors()["text"]
    key = (name, col)
    ic = _cache.get(key)
    if ic is None:
        ic = QIcon()
        ic.addPixmap(pixmap(name, col, 22))
        ic.addPixmap(pixmap(name, theme.colors()["dim"], 22), QIcon.Disabled)
        # a white version for checked (accent background) buttons
        ic.addPixmap(pixmap(name, "#ffffff", 22), QIcon.Normal, QIcon.On)
        _cache[key] = ic
    return ic



def clear_cache():
    _cache.clear()


def app_icon() -> QIcon:
    r = QSvgRenderer(QByteArray(APP_ICON_SVG.encode()))
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        img = QImage(s, s, QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        p = QPainter(img)
        r.render(p, QRectF(0, 0, s, s))
        p.end()
        ic.addPixmap(QPixmap.fromImage(img))
    return ic
