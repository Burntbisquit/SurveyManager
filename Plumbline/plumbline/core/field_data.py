"""Portable bookkeeping for field-data files staged into a project package."""
from __future__ import annotations

from pathlib import Path


def relative_file_key(root, file_path) -> str:
    """Return a stable, case-insensitive identity below the selected parent folder.

    The selected folder name is part of the identity as well as every nested directory and the
    filename.  Two same-sized files called ``crew.csv`` in differently named parent folders are
    therefore distinct imports, and a rename inside one folder is new field data too.
    """
    root_path = Path(root).expanduser()
    file = Path(file_path).expanduser()
    try:
        relative = file.resolve().relative_to(root_path.resolve())
    except (OSError, RuntimeError, ValueError):
        relative = Path(file.name)
    parts = ([root_path.name] if root_path.name else []) + list(relative.parts)
    return Path(*parts).as_posix().casefold()


def imported_file_matches(records, root, file_path) -> bool:
    """Whether a file has the same selected-parent identity and byte size as an earlier import.

    ``source_relative`` lets a later scan of the original download folder gray the file out;
    ``stored_relative`` lets a scan of the project's own Field Data folder do the same. Both keys
    include the selected parent folder's head name and the file's relative path. A rename, a
    different parent folder, or a changed file size is considered new and remains selectable.
    """
    try:
        size = int(Path(file_path).stat().st_size)
    except OSError:
        return False
    relative = relative_file_key(root, file_path)
    for record in records or ():
        if not isinstance(record, dict):
            continue
        try:
            prior_size = int(record.get("size", -1))
        except (TypeError, ValueError):
            continue
        if prior_size != size:
            continue
        candidates = {
            str(record.get("source_relative") or "").replace("\\", "/").casefold(),
            str(record.get("stored_relative") or "").replace("\\", "/").casefold(),
        }
        candidates.discard("")
        if relative in candidates:
            return True
    return False


def make_import_record(source_root, source_file, stored_root, stored_file) -> dict:
    """Create the portable manifest row for one successfully imported source file."""
    source_path = Path(source_file)
    stored_path = Path(stored_file)
    return {
        "source_relative": relative_file_key(source_root, source_path),
        "stored_relative": relative_file_key(stored_root, stored_path),
        "size": int(source_path.stat().st_size),
    }


__all__ = ["relative_file_key", "imported_file_matches", "make_import_record"]
