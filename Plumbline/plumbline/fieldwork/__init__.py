"""Fieldwork Manager — the field-data front end of Plumbline.

This package used to be a standalone program.  It is now the *fieldwork* half of
Plumbline: it takes raw downloaded field data (Carlson .fwk / field book / CSV),
finds the mistakes surveyors actually make (duplicate point numbers, transposed
coordinates, impossible descriptions), and hands clean points to the drawing half.

Importing this package is deliberately cheap and Qt-free
---------------------------------------------------------
``import plumbline.fieldwork`` must work on a headless machine with no Qt
installed, because the core (config, detectors, io_carlson, parse, steps_report,
coord_systems) is pure Python and is used by the CLI and by tests.

Qt is only imported when you actually ask for something that draws — the
:func:`clean_dialog`, :func:`renumber_dialogs` and :func:`main_window` helpers
below, or the ``ui_main`` submodule directly.  Everything else is available
immediately::

    from plumbline.fieldwork import read_carlson_fieldbook      # no Qt needed
    from plumbline.fieldwork.ui_main import MainWindow          # Qt needed

Naming note for anyone reading the ported code
----------------------------------------------
The field-data modules keep their original names (``clean``, ``renumber_tool``,
``ui_main`` …) so diffs against the standalone Fieldwork Manager stay readable.
Inside Plumbline they live under ``plumbline.fieldwork``; relative imports do not
need changing, and nothing here knows about the drawing half of the program.
"""
from __future__ import annotations

__all__ = [
    # --- Qt-free core (safe to import anywhere) ---
    "config", "detectors", "io_carlson", "parse", "steps_report", "coord_systems", "utils_sort",
    # --- Qt-backed ---
    "clean", "renumber_tool", "ui_main", "bridge",
    # --- Qt-backed entry points ---
    "clean_dialog", "renumber_dialogs", "main_window", "run",
]

# --------------------------------------------------------------------------- Qt-free core
from . import config                     # noqa: F401  (constants + point-number schemes)
from . import detectors                  # noqa: F401  (duplicate / transposition finders)
from . import io_carlson                 # noqa: F401  (Carlson .fwk, field book, check report)
from . import parse                      # noqa: F401  (description parser + line-command rules)
from . import steps_report               # noqa: F401  (steps / progress report writer)
from . import coord_systems              # noqa: F401  (Texas 2011 library + pure-python LCC)

# Convenience re-exports — the handful of functions callers actually reach for.
from .config import (                    # noqa: F401
    CONTROL_RANGE, BOUNDARY_RANGE, GENERAL_START, DEFAULT_CREW_NUMBER,
    crew_blocks, is_in_crew_block, number_type_label,
    PROJECT_FILE_EXT, WORKING_FILE_EXT, FIELDBOOK_EXT, CHECK_REPORT_EXT, LEGACY_CHECK_EXT,
)
from .detectors import (                 # noqa: F401
    normalize_point_number, find_exact_duplicate_groups, find_similar_number_groups,
    find_close_ne_groups, find_close_xy_groups,
)
from .io_carlson import (                # noqa: F401
    read_carlson_fieldbook, write_fwb_file, read_fwb_file,
    write_check_report, read_check_report,
)
from .parse import parse_desc_field       # noqa: F401
from .coord_systems import (              # noqa: F401
    EPSG_LIBRARY, DEFAULT_ACTIVE_EPSGS, TEXAS_LCC_PARAMS,
    get_epsg_info, migrate_epsg, migrate_active_list,
    apply_saf, apply_surface_factor, convert_to_wgs84,
    MESQUITE_TX_RECOMMENDED_EPSG,
)


# --------------------------------------------------------------------------- lazy Qt entry points
_QT_MODULES = {
    "clean": "clean",
    "renumber_tool": "renumber_tool",
    "ui_main": "ui_main",
}
_LAZY_PLAIN = ("bridge", "sample_real")


def __getattr__(name: str):
    """Import Qt-backed submodules only when someone actually asks for one."""
    import importlib
    if name in _QT_MODULES:
        mod = importlib.import_module(f".{_QT_MODULES[name]}", __name__)
        globals()[name] = mod
        return mod
    if name in _LAZY_PLAIN:
        mod = importlib.import_module(f".{name}", __name__)
        globals()[name] = mod
        return mod
    if name == "clean_dialog":
        return importlib.import_module(".clean", __name__).CleanDescriptionDialog
    if name == "renumber_dialogs":
        mod = importlib.import_module(".renumber_tool", __name__)
        return (mod.SingleRenumberDialog, mod.RangeRenumberDialog)
    if name in ("main_window", "run"):
        mod = importlib.import_module(".ui_main", __name__)
        globals()["ui_main"] = mod
        return mod.MainWindow if name == "main_window" else mod.main
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(__all__) | set(globals()))
