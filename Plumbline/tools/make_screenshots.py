"""Regenerate the documentation screenshots:  QT_QPA_PLATFORM=offscreen python tools/make_screenshots.py
(only the 3D / depth view shots, no internet needed:  python tools/make_screenshots.py views)

The imagery shot uses live Esri tiles (needs internet) laid under the SYNTHETIC sample site - the survey points do not
correspond to the real features in the picture; the shot only illustrates the panel.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("PLUMBLINE_HOME", "/tmp/plumbline_shots_home")

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from plumbline.core.surface import apply_contours, compute_contour_data
from plumbline.core.tiles import PRESETS
from plumbline.sample import make_sample_project, write_sample_files
from plumbline.ui import theme
from plumbline.ui.crs_dialog import CRSDialog
from plumbline.ui.import_export import CsvImportDialog
from plumbline.ui.main_window import MainWindow

ONLY = set(sys.argv[1:])
OUT = Path(__file__).resolve().parent.parent / "docs" / "img"
OUT.mkdir(parents=True, exist_ok=True)
app = QApplication([])


def pump(sec=0.3):
    t = time.time()
    while time.time() - t < sec:
        app.processEvents()
        QTest.qWait(20)


def project_with_contours():
    pr = make_sample_project()
    sf = next(iter(pr.surfaces.values()))
    apply_contours(pr, sf, compute_contour_data(sf, 0.5), 0.5, 5, 0.0, True, 3.0)
    return pr


# ---- main window, dark and light
for name in ("dark", "light"):
    from plumbline.core.settings import settings
    settings().set("theme", name)
    w = MainWindow(project=project_with_contours())
    w.resize(1500, 920)
    w.show()
    pump()
    w.canvas.opts.show_numbers = False
    w.canvas.opts.show_elev = False
    w.view_toggles["show_numbers"].setChecked(False)
    w.view_toggles["show_elev"].setChecked(False)
    w.canvas.zoom_extents()
    w.canvas.invalidate()
    pump()
    w.grab().save(str(OUT / f"main_{name}.png"))
    w.state.tiles.shutdown()
    w.close()

from plumbline.core.settings import settings
settings().set("theme", "dark")
theme.apply_theme(app, "dark")

# ---- the field-data window, opened the way the Tools menu opens it, on the real job
if not ONLY or "fieldwork" in ONLY:
    from plumbline.core.project import Project
    from plumbline.ui.fieldwork_window import open_fieldwork_manager
    job = Path(__file__).resolve().parent.parent / "samples" / "Real World"
    if not (job / "Real World.plb").exists():
        print("fieldwork shot skipped: build samples/Real World first (python -m plumbline sample-real)")
    else:
        w = MainWindow(project=Project.load(job / "Real World.plb"))
        w.resize(1500, 920)
        w.show()
        pump()
        fw = open_fieldwork_manager(w)
        if fw is not None:
            fw.fieldwork_path = str(job / "Field Data")
            fw._scan_fieldwork()
            fw._load_edit_file(str(job / "Field Data" / "Week 1" / "Week 1 Consolidated.fwk"))
            fw._load_fieldbook_file(str(job / "Field Book" / "Real World.fwb"))
            fw.resize(1500, 900)
            pump(0.8)
            fw.grab().save(str(OUT / "fieldwork_manager.png"))
            fw.close()
        w.state.tiles.shutdown()
        w.close()
if ONLY == {"fieldwork"}:
    print("wrote:", sorted(p.name for p in OUT.iterdir()))
    sys.exit(0)

# ---- 3D view and depth view (the depth view looks across a diagonal line, not just from the front)
if not ONLY or "views" in ONLY:
    w = MainWindow(project=project_with_contours())
    w.resize(1500, 920)
    w.show()
    pump()
    w.view_toggles["show_numbers"].setChecked(False)
    w.view_toggles["show_elev"].setChecked(False)
    w.canvas.zoom_extents()
    w.a_3d.setChecked(True)
    pump(0.6)
    v3 = w.view3d.view
    v3.cam.set_view(32.0, 40.0)
    v3.fit()
    pump()
    v3.grab().save(str(OUT / "view3d.png"))
    w.a_depth.setChecked(True)
    pump(0.6)
    x0, y0, x1, y1 = w.state.project.extents()
    w.depth.view.set_line((x0 + 40, y0 + 70), (x1 - 60, y1 - 30))
    pump(0.6)
    w.depth.view.grab().save(str(OUT / "depthview.png"))
    w.grab().save(str(OUT / "main_depth.png"))
    w.state.tiles.shutdown()
    w.close()
if ONLY == {"views"}:
    sys.exit(0)

# ---- Convert Field to Finish: the real office standard, read Carlson's way
if not ONLY or "table" in ONLY:
    from plumbline.core.project import Project
    from plumbline.io import f2f
    from plumbline.ui.f2f_dialog import ConvertFieldToFinishDialog
    from plumbline.sample import make_sample_project as _sample

    codes_file = Path(__file__).resolve().parent.parent / "samples" / "Real World" / "Source" / "CARLSON F2F.csv"
    if not codes_file.exists():
        print("field-to-finish shot skipped: build samples/Real World first")
    else:
        job = Project("23-036 Murchison")
        job.codes = _sample().codes                       # a job that already has a code table
        d = ConvertFieldToFinishDialog(f2f.read(codes_file), job)
        d.resize(1000, 760)
        d.show()
        d.rb_merge.setChecked(True)
        pump(0.4)
        d.grab().save(str(OUT / "f2f_dialog.png"))
        d.close()
if ONLY == {"table"}:
    sys.exit(0)

# ---- Check Fieldwork (item 15): its own dock, and the point list's source columns
if not ONLY or "check" in ONLY:
    from plumbline.core.project import Project
    from plumbline.core.settings import settings as _settings
    from plumbline.fieldwork import bridge as FB
    from plumbline.sample import make_sample_project as _sample

    pr = _sample()                                     # 238 field points, provenance from the new path
    rows = [FB.working_row(9001, "7001", 6967480.0, 2552900.0, 512.10, "GS",
                           "2026-07-26-S1", "2026-07-26GPS S7.csv"),
            FB.working_row(9002, "7001", 6967484.5, 2552904.5, 512.30, "GS",
                           "2026-07-26-S1", "2026-07-26GPS S7.csv"),
            FB.working_row(9003, "7002", 6967500.0, 2552920.0, 512.40, "ZZTOP",
                           "2026-07-26-S1", "2026-07-26GPS S7.csv")]
    FB.apply_rows_to_project(pr, rows, dup_policy="keep")   # a second crew's download, as it arrived

    w = MainWindow(project=pr)
    w.resize(1500, 920)
    w.show()
    pump()
    w.resizeDocks([w.d_pts], [320], Qt.Vertical)        # room for the findings in a still
    w.points.show_column("imported", True)             # the doc shot shows all four columns
    w.points.show_column("import_set", True)
    w.d_check.show()
    w.d_check.raise_()                                 # the dock has its own tab beside the point list
    w.check.run()
    pump(0.6)
    w.grab().save(str(OUT / "check_fieldwork.png"))

    # ... and the same dock with the office's code table on the job: the description half runs
    book_dir = Path("/tmp/plumbline_shots_job") / "Field Book"
    book = book_dir / "office.fwb"
    from plumbline.fieldwork.io_carlson import write_fwb_file
    book_dir.mkdir(parents=True, exist_ok=True)
    write_fwb_file(book, ["Code", "Description", "Symbol", "Layer", "Entity Type", "Category"],
                   [[c.code, c.name, c.symbol or "cross", c.layer, "1", ""]
                    for c in sorted(_sample().codes.codes.values(), key=lambda c: c.code)],
                   commands=["ST", "PC", "PT", "END"], rules=[])
    w.state.project.settings["fieldbook_file"] = str(book)   # a shot must not dirty the project
    w.check.refresh_banner()
    w.check.run()
    pump(0.6)
    w.grab().save(str(OUT / "check_fieldwork_with_fieldbook.png"))

    # ... and the other half of the item: the point list's source columns, filtering a crew out
    w.d_pts.show()
    w.d_pts.raise_()
    w.points.ed.setText("2026-07-26")
    pump(0.5)
    w.grab().save(str(OUT / "point_metadata_columns.png"))
    w.state.tiles.shutdown()
    w.close()
    settings().set("point_columns", ["source_file", "source_folder"])
if ONLY == {"check"}:
    print("wrote:", sorted(p.name for p in OUT.iterdir()))
    sys.exit(0)

files = write_sample_files("/tmp/plumbline_shots_samples")

# ---- CRS manager and CSV import
w = MainWindow(project=make_sample_project())
w.show()
pump()
d = CRSDialog(w.state, w)
d.show()
d.picker.select_key("EPSG:2276")
d.tabs.setCurrentIndex(0)
pump()
d.grab().save(str(OUT / "crs_manager.png"))
d.tabs.setCurrentIndex(3)
d.sp_bx.setValue(2552700)
d.sp_by.setValue(6967100)
d.sp_h.setValue(500)
d.cmb_hu.setCurrentIndex(d.cmb_hu.findData("ftUS"))
d._compute_cf()
pump()
d.grab().save(str(OUT / "crs_ground_scale.png"))
d.close()
from plumbline.core import crs as C
from plumbline.ui.app_state import AppState
from plumbline.core.project import Project
st = AppState(Project("shot", C.ProjectCRS.from_epsg(2276)))
cd = CsvImportDialog(st, files["tsv"])
cd.show()
pump()
cd.grab().save(str(OUT / "csv_import.png"))
cd.close()

# ---- imagery: real Esri tiles + the panel (the check workflow was removed - see CHANGE_LIST item 16)
w.state.set_project(make_sample_project())
esri = PRESETS[0]
w.create_imagery_layer({"kind": "tiles", "name": esri.name, "source": esri.to_dict()})
w.resize(1500, 920)
pr = w.state.project
x, y = pr.crs.from_lonlat(-96.5992, 32.7668)
w.state.center_on(float(x), float(y), pr.crs.unit_factor / 0.45)
w.canvas.opts.show_numbers = False
w.canvas.opts.show_elev = False
t0 = time.time()
while time.time() - t0 < 25:
    pump(0.3)
    if w.canvas.imagery.pending == 0 and len(w.canvas.imagery._pix) > 8 and time.time() - t0 > 4:
        break
w.d_img.show()
w.d_img.raise_()
w.imagery.lst.setCurrentRow(0)
try:
    w.imagery._lookup()
except Exception as ex:
    print("metadata lookup skipped:", ex)
pump(0.5)
w.grab().save(str(OUT / "imagery_panel.png"))
w.state.tiles.shutdown()
print("wrote:", sorted(p.name for p in OUT.iterdir()))
