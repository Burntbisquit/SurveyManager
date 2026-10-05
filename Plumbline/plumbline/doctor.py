"""``plumbline doctor`` - check that Python and every library Plumbline needs is installed and really works.

Paste its output when asking for help: it says what is installed, where, and what (if anything) is broken.
Output is plain ASCII on purpose so it prints correctly in any Windows console.
"""
from __future__ import annotations

import importlib
import os
import platform
import sys
import warnings

from . import __version__

VC_REDIST = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
FOREIGN_GIS_VARS = ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA", "GDAL_DRIVER_PATH")


def _expect(ok: bool, message: str):
    if not ok:
        raise RuntimeError(message)


# -- probes: each one really *uses* its library a little (an import alone can pass while the DLLs underneath are broken)
# and returns (version, short note).
def _qt():
    import PySide6
    from PySide6 import QtCore, QtGui, QtWidgets  # noqa: F401  (a missing Visual C++ runtime fails right here)
    return PySide6.__version__, f"Qt {QtCore.qVersion()}"


def _numpy():
    import numpy
    return numpy.__version__, ""


def _scipy():
    import numpy as np
    import scipy
    from scipy.spatial import Delaunay
    Delaunay(np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [1.0, 1.0]]))
    return scipy.__version__, ""


def _shapely():
    import shapely
    from shapely.geometry import Polygon
    _expect(abs(Polygon([(0, 0), (2, 0), (2, 2), (0, 2)]).area - 4.0) < 1e-9, "polygon area is wrong")
    return shapely.__version__, f"GEOS {shapely.geos_version_string}"


def _pyproj():
    import pyproj
    t = pyproj.Transformer.from_crs(4326, 2276, always_xy=True)          # WGS84 -> Texas North Central (US ft)
    x, y = t.transform(-96.6, 32.77)
    _expect(2.0e6 < x < 3.0e6 and 6.0e6 < y < 8.0e6, f"coordinate transform gave {x:.1f}, {y:.1f}")
    return pyproj.__version__, f"PROJ {pyproj.proj_version_str}"


def _ezdxf():
    import ezdxf
    ezdxf.new("R2010")
    return ezdxf.__version__, ""


def _pyogrio():
    import pyogrio
    drivers = pyogrio.list_drivers()
    _expect("GPKG" in drivers and "ESRI Shapefile" in drivers, "GeoPackage / Shapefile drivers are missing")
    return pyogrio.__version__, f"GDAL {pyogrio.__gdal_version_string__}"


def _matplotlib():
    import matplotlib
    import matplotlib.tri  # noqa: F401
    from matplotlib.backends import backend_agg  # noqa: F401
    return matplotlib.__version__, ""


def _openpyxl():
    import openpyxl
    return openpyxl.__version__, ""


def _pillow():
    import PIL
    from PIL import Image
    Image.new("RGB", (2, 2))
    return PIL.__version__, ""


def _rasterio():
    import rasterio
    return rasterio.__version__, f"GDAL {rasterio.__gdal_version__}"


# (name, required?, probe, what it is for)
LIBRARIES = [
    ("PySide6", True, _qt, "windows, menus and the drawing canvas"),
    ("numpy", True, _numpy, "fast arrays"),
    ("scipy", True, _scipy, "triangulation"),
    ("shapely", True, _shapely, "polygons and volumes"),
    ("pyproj", True, _pyproj, "coordinate systems"),
    ("ezdxf", True, _ezdxf, "DXF in and out"),
    ("pyogrio", True, _pyogrio, "Shapefile / GeoJSON / GeoPackage"),
    ("matplotlib", True, _matplotlib, "surface shading"),
    ("openpyxl", True, _openpyxl, "Excel reports"),
    ("Pillow", True, _pillow, "image files"),
    ("rasterio", False, _rasterio, "GeoTIFF orthophotos (PNG/JPG with a world file work without it)"),
]


def _program():
    """Import one module from every part of the program, so a missing file is caught here
    rather than the first time somebody clicks the wrong menu."""
    for m in ("plumbline.core.project", "plumbline.core.jobtemplate", "plumbline.io.dxf_io",
              "plumbline.io.landxml", "plumbline.io.gis_io", "plumbline.sample",
              "plumbline.fieldwork.bridge", "plumbline.fieldwork.io_carlson",
              "plumbline.fieldwork.coord_systems",
              "plumbline.ui.main_window", "plumbline.ui.fieldwork_window", "plumbline.ui.job_setup"):
        importlib.import_module(m)
    return __version__, ""


def _fieldwork(): 
    """Check the field-data half specifically: the Texas zone library and the crew rule."""
    from .fieldwork import coord_systems as CS, config as FC
    assert CS.EPSG_LIBRARY.get(6584) and CS.migrate_epsg(2276) == 6584
    assert FC.crew_blocks(7)[2] == (70000, 79999)
    return len(CS.EPSG_LIBRARY), ""


def _user_folder():
    from .core.settings import user_dir
    d = user_dir()
    probe = d / ".write_test"
    probe.write_text("ok", "utf-8")
    probe.unlink()
    return d


#: The Python Plumbline was built and tested against.  Newer/older interpreters that still
#: satisfy `requires-python` are allowed, with a note rather than a failure.
PREFERRED_PYTHON = (3, 14)
OLDEST_PYTHON = (3, 13)


def python_version_issues(version_info=None) -> tuple[list[str], list[str]]:
    """(problems, notes) about the running Python.

    Plumbline needs Python 3.13 or newer.  3.14 is what this release was developed and tested
    against (and what `install_windows.bat` picks when it is available); 3.13 passes the whole
    test suite too, so it is supported and only gets an advisory note.
    """
    v = version_info or sys.version_info
    ver = tuple(v[:2])
    if ver < OLDEST_PYTHON:
        return [f"Python {v[0]}.{v[1]} is too old - Plumbline needs Python "
                f"{OLDEST_PYTHON[0]}.{OLDEST_PYTHON[1]} or newer (3.14 recommended; "
                f"install it, then repeat the setup with py -3.14)"], []
    if ver > PREFERRED_PYTHON:
        return [], [f"Plumbline is developed and tested on Python {PREFERRED_PYTHON[0]}.{PREFERRED_PYTHON[1]}. "
                    f"Python {v[0]}.{v[1]} may work, but some libraries may not have releases for it yet - "
                    f"if installing failed, use Python {PREFERRED_PYTHON[0]}.{PREFERRED_PYTHON[1]}."]
    if ver < PREFERRED_PYTHON:
        return [], [f"Python {v[0]}.{v[1]} works and passes the test suite, but this release was built and "
                    f"tested against Python {PREFERRED_PYTHON[0]}.{PREFERRED_PYTHON[1]}. If anything misbehaves, "
                    f"that is the first thing to rule out."]
    return [], []


def explain(name: str, exc: BaseException) -> str:
    """One plain-English line saying what a failed probe most likely means and what to do."""
    text = f"{type(exc).__name__}: {exc}"
    if "DLL load failed" in text:
        return (f"{name}: a 'DLL load failed' error usually means the Microsoft Visual C++ runtime is missing - "
                f"install it from {VC_REDIST} and run this check again")
    if isinstance(exc, ModuleNotFoundError):
        return f"{name} is not installed - run install_windows.bat again (or: pip install -r requirements.txt)"
    return f"{name} is installed but does not work ({' '.join(text.split())[:140]}) - send me this whole output"


def run(write=print) -> int:
    """Print a health report. Returns 0 when everything Plumbline needs works, 1 otherwise."""
    problems: list[str] = []
    notes: list[str] = []

    write(f"Plumbline {__version__}")
    write(f"Python    {platform.python_version()} ({platform.architecture()[0]}) on {platform.platform()}")
    write(f"Program   {sys.executable}")
    try:
        write(f"User data {_user_folder()}   (settings, plugins, imagery cache)")
    except Exception as e:                                       # e.g. a locked-down or redirected profile folder
        write(f"User data PROBLEM {type(e).__name__}: {e}")
        problems.append("Plumbline cannot write to its settings folder - set PLUMBLINE_HOME to a folder you can write to")

    py_problems, py_notes = python_version_issues()
    problems += py_problems
    notes += py_notes
    if platform.architecture()[0] != "64bit":
        problems.append("this is a 32-bit Python - Qt (PySide6) needs 64-bit Python")

    write("")
    write("Libraries (the first check after installing can take a minute):")
    all_required_ok = True
    for name, required, probe, purpose in LIBRARIES:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                ver, note = probe()
            write(f"  ok        {name:11} {ver:9} {note}".rstrip())
        except Exception as e:
            msg = " ".join(f"{type(e).__name__}: {e}".split())[:150]
            if required:
                all_required_ok = False
                write(f"  PROBLEM   {name:11} {msg}")
                problems.append(explain(name, e))
            else:
                write(f"  optional  {name:11} not available - {purpose}")

    if all_required_ok:
        try:
            ver, _ = _program()
            write(f"  ok        {'Plumbline':11} {ver:9} all program modules load")
        except Exception as e:
            write(f"  PROBLEM   {'Plumbline':11} {' '.join(f'{type(e).__name__}: {e}'.split())[:150]}")
            problems.append(explain("Plumbline", e))
        try:
            zones, _ = _fieldwork()
            write(f"  ok        {'Fieldwork':11} {'':9} {zones} coordinate systems, crew rule intact")
        except Exception as e:
            write(f"  PROBLEM   {'Fieldwork':11} {' '.join(f'{type(e).__name__}: {e}'.split())[:150]}")
            problems.append(explain("Fieldwork", e))

    for var in FOREIGN_GIS_VARS:
        if os.environ.get(var):
            notes.append(f"{var} is set to {os.environ[var]}. Another GIS program probably set it. If coordinate systems or "
                         f"GIS files misbehave, clear it (Plumbline.bat does that for you).")

    write("")
    for n in notes:
        write(f"Note: {n}")
    if problems:
        write(f"{len(problems)} problem(s) found:")
        for p in problems:
            write(f"  - {p}")
        return 1
    write("Everything Plumbline needs is installed and working.")
    return 0
