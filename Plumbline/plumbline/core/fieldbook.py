"""Core field book management: archiving old versions, placing/copying into project, and reporting."""
from __future__ import annotations

import csv
import datetime
from pathlib import Path
import shutil
import zipfile

from ..core.featurecodes import FeatureCodeTable
from ..io import f2f


def archive_old_fieldbooks(fieldbook_dir: Path | str, exclude_file: Path | str | None = None) -> list[Path]:
    """Move existing field book files in fieldbook_dir into a timestamped zip archive in fieldbook_dir/Archive/.

    Returns the list of files that were archived.
    """
    fb_dir = Path(fieldbook_dir)
    if not fb_dir.exists():
        return []

    exclude_path = Path(exclude_file).resolve() if exclude_file else None

    # Identify loose field book files directly under fieldbook_dir (ignore subdirectories like Archive)
    old_files = [
        f for f in fb_dir.iterdir()
        if f.is_file() and f.suffix.lower() in (".fwb", ".csv")
        and (exclude_path is None or f.resolve() != exclude_path)
    ]
    if not old_files:
        return []

    archive_dir = fb_dir / "Archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = archive_dir / f"fieldbook_archive_{ts}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for old_file in old_files:
            zf.write(old_file, arcname=old_file.name)

    for old_file in old_files:
        try:
            old_file.unlink()
        except OSError:
            pass

    return old_files


def place_fieldbook_in_project(src_path: Path | str, project, custom_dest_name: str | None = None) -> Path:
    """Copy or place a field book into the project's Field Book directory.

    If old field books exist in the project's Field Book directory, moves them into
    a timestamped zipped archive inside Field Book/Archive/.
    """
    src = Path(src_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"Source field book not found: {src}")

    # Determine project root
    if hasattr(project, "path") and project.path:
        p = Path(project.path)
        if p.suffix.lower() == ".plb" or p.is_file():
            job_dir = p.parent
        else:
            job_dir = p
    else:
        job_dir = Path(".")

    fb_dir = job_dir / "Field Book"
    fb_dir.mkdir(parents=True, exist_ok=True)

    dest_name = custom_dest_name or src.name
    if not dest_name.lower().endswith(".fwb") and not dest_name.lower().endswith(".csv"):
        dest_name = f"{dest_name}.fwb"

    target_dest = (fb_dir / dest_name).resolve()

    # Archive existing files in fb_dir (excluding target_dest if it is identical to src)
    archive_old_fieldbooks(fb_dir, exclude_file=src)

    if src != target_dest:
        shutil.copy2(src, target_dest)

    return target_dest


def generate_fieldbook_report_text(project, fwb_path: Path | str | None = None) -> str:
    """Generate a plain-text report of the current field book and feature codes."""
    lines = []
    lines.append("=" * 78)
    proj_name = getattr(project, "name", "") or "Untitled Project"
    lines.append(f"PLUMBLINE FIELD BOOK REPORT — {proj_name}")
    lines.append(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if fwb_path:
        lines.append(f"Field Book File: {fwb_path}")
    lines.append("=" * 78)
    lines.append("")

    codes = getattr(project, "codes", {}) or {}
    codes_items = list(codes.items()) if hasattr(codes, "items") else list(getattr(codes, "codes", {}).items()) if hasattr(codes, "codes") else ([(c.code, c) for c in codes] if isinstance(codes, (list, tuple)) else [])
    codes_values = list(codes.values()) if hasattr(codes, "values") else [fc for _, fc in codes_items]

    lines.append(f"Summary: {len(codes_items):,} feature code(s) defined.")
    by_kind = {"point": 0, "line": 0, "polygon": 0}
    layers = set()
    symbols = set()
    for c in codes_values:
        by_kind[c.kind] = by_kind.get(c.kind, 0) + 1
        if c.layer:
            layers.add(c.layer)
        if c.symbol:
            symbols.add(c.symbol)

    lines.append(f"  • Points: {by_kind.get('point', 0):,}")
    lines.append(f"  • Lines / Polylines: {by_kind.get('line', 0):,}")
    lines.append(f"  • Polygons: {by_kind.get('polygon', 0):,}")
    lines.append(f"  • Unique Layers: {len(layers):,}")
    lines.append(f"  • Unique Symbols: {len(symbols):,}")
    lines.append("")

    # Code Commands
    settings = getattr(project, "settings", {}) or {}
    commands = settings.get("f2f_commands") or list(f2f.DEFAULT_COMMANDS)
    lines.append("-" * 78)
    lines.append("Code Commands (Line & Curve Control):")
    for meaning, cmd in zip(f2f.DEFAULT_COMMAND_LABELS, commands):
        lines.append(f"  {meaning:<26}: {cmd}")
    lines.append("")

    # Correction Rules
    rules = settings.get("f2f_rules") or []
    lines.append("-" * 78)
    lines.append(f"Correction Rules ({len(rules)} defined):")
    if rules:
        for r in rules:
            if isinstance(r, (list, tuple)) and len(r) >= 2:
                lines.append(f"  '{r[0]}' -> '{r[1]}'")
    else:
        lines.append("  (None defined)")
    lines.append("")

    # Code Table
    max_code_len = max([len(str(c)) for c, _ in codes_items] + [4])
    max_desc_len = max([len(str(fc.name or "")) for _, fc in codes_items] + [11])
    max_kind_len = max([len("Point" if fc.kind == "point" else "Line" if fc.kind == "line" else "Polygon") for _, fc in codes_items] + [4])
    max_layer_len = max([len(str(fc.layer or "")) for _, fc in codes_items] + [5])
    max_symbol_len = max([len(str(fc.symbol or "")) for _, fc in codes_items] + [6])

    w_code = max(max_code_len + 3, 10)
    w_desc = max(max_desc_len + 3, 24)
    w_kind = max(max_kind_len + 3, 8)
    w_layer = max(max_layer_len + 3, 22)
    w_symbol = max(max_symbol_len + 3, 12)

    header_line = f"{'Code':<{w_code}} {'Description':<{w_desc}} {'Kind':<{w_kind}} {'Layer':<{w_layer}} {'Symbol':<{w_symbol}}"
    sep_len = max(len(header_line), 78)

    lines.append("-" * sep_len)
    lines.append(header_line)
    lines.append("-" * sep_len)
    for code, fc in sorted(codes_items):
        kind_str = "Point" if fc.kind == "point" else "Line" if fc.kind == "line" else "Polygon"
        lines.append(f"{code:<{w_code}} {fc.name:<{w_desc}} {kind_str:<{w_kind}} {fc.layer:<{w_layer}} {fc.symbol:<{w_symbol}}")

    lines.append("-" * sep_len)
    lines.append("End of Field Book Report")
    return "\n".join(lines)
