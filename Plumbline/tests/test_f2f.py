"""Convert Field to Finish (item 13): an office's code table becomes this job's feature codes.

The file that arrives is big (the office standard in ``samples/`` is 1,717 codes over 216 layers
and 249 columns), it is not shaped like a Plumbline table, and half of it belongs to work this job
is not doing.  So the tests here are about three things: reading Carlson's own layout without being
told how, reading somebody else's layout when told, and never touching the job's codes until the
user has ticked what they want.

The real office standard is tested too, against the door Fieldwork Manager uses - the two must
agree, because the field window offers "load the job's feature code table" from the same file.
"""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from plumbline.core.featurecodes import (CARLSON_ENTITY_TYPES, FeatureCodeTable,  # noqa: E402
                                        kind_for_entity)
from plumbline.core.project import Project                                     # noqa: E402
from plumbline.fieldwork import config as FM_CONFIG                            # noqa: E402
from plumbline.io import f2f                                                   # noqa: E402
from test_ui import auto, win  # noqa: F401  (the fixture set the other UI tests use)

REAL_F2F = Path(__file__).resolve().parent.parent / "samples" / "Real World" / "Source" / "CARLSON F2F.csv"

#: Carlson's own export shape: note **Symbol Size in column 4**, so the layer is column 5 and the
#: entity type column 6 - reading the first six columns in order puts every code on a number.
CARLSON = """Code,Description,Symbol,Symbol Size,Layer,Entity Type,Tie,Linetype
DEFAULT,default,CG08,0.08,V-SITE-DEFAULT,0,1,BYLAYER
Category,Corners,,,,,,
DNF,Did Not Find,SPT10,1,V-PROP-CRNR-NOT FOUND,0,1,BYLAYER
MAGF,MAG Nail Found,Iron_Pin_Found,1,V-PROP-CRNR,0,1,BYLAYER
Category,Utilities,,,,,,
UGC,UGC,CG08,0.08,E_Utility_Cable_Line,2,1,BYLAYER
SANI,SAN Sewer,CG08,0.08,E_Utility_Sewer_Line,3,1,BYLAYER
NOLAYER,No layer named,CG08,0.08,,0,1,BYLAYER
CIR,Manhole cover,CG08,0.08,E_Utility_Sewer_Point,4,1,BYLAYER
"""

#: The same six facts in somebody else's order, with headers that say nothing.
SHUFFLED = """col1,col2,col3,col4,col5
V-SITE-DEFAULT,default,CG08,DEFAULT,0
V-PROP-CRNR-NOT FOUND,Did Not Find,SPT10,DNF,0
E_Utility_Cable_Line,UGC,CG08,UGC,2
"""


def _write(tmp_path: Path, text: str, name: str = "office standard.csv") -> Path:
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


# ------------------------------------------------------------------ reading Carlson's own layout
def test_carlsons_layout_is_read_by_column_name_not_by_position(tmp_path):
    table = f2f.read(_write(tmp_path, CARLSON))
    assert len(table) == 7 and table.category_rows == 2 and table.blank_rows == 0
    assert [c for c in table.categories] == ["Default", "Corners", "Corners", "Utilities",
                                             "Utilities", "Utilities", "Utilities"]
    m = f2f.auto_map(table)
    assert m.found_by == "the header names"
    assert (m.code, m.description, m.symbol, m.layer, m.entity) == (0, 1, 2, 4, 5)
    codes, stats = f2f.convert(table, m)
    assert len(codes) == 7 and stats["points"] == 5 and stats["lines"] == 2
    dnf = codes.get("DNF")
    assert (dnf.name, dnf.kind, dnf.layer, dnf.symbol) == ("Did Not Find", "point",
                                                           "V-PROP-CRNR-NOT FOUND", "SPT10")
    ugc = codes.get("UGC")
    assert (ugc.kind, ugc.breakline, ugc.layer) == ("line", True, "E_Utility_Cable_Line")
    san = codes.get("SANI")
    assert (san.kind, san.breakline) == ("line", True)          # 3 = 3D Polyline
    assert codes.get("NOLAYER").layer == "V-UTIL"               # the category filled the gap in
    assert not codes.get("CATEGORY")                            # and it is not a code


def test_a_header_row_that_says_nothing_falls_back_to_carlsons_own_positions(tmp_path):
    """A file whose headers were stripped must not lose its codes - it just gets read the way
    Carlson writes them.  What must never happen is a *half* understood map."""
    text = CARLSON.replace("Code,Description,Symbol,Symbol Size,Layer,Entity Type,Tie,Linetype",
                           "A,B,C,D,E,F,G,H")
    p = _write(tmp_path, text)
    table = f2f.read(p, header_row=True)            # what the dialog's switch does for such a file
    m = f2f.auto_map(table)
    assert m.found_by == "Carlson's own column positions"
    assert (m.code, m.layer, m.entity) == (0, 4, 5)
    codes, _ = f2f.convert(table, m)
    assert len(codes) == 7 and codes.get("UGC").layer == "E_Utility_Cable_Line"


def test_the_columns_can_be_pointed_at_by_hand_when_the_layout_is_somebody_elses(tmp_path):
    """Custom: five columns in an order of the office's own choosing, headers meaningless."""
    table = f2f.read(_write(tmp_path, SHUFFLED, "from-the-database.csv"), header_row=True)
    chosen = f2f.ColumnMap(code=3, description=1, symbol=2, layer=0, entity=4, category=-1,
                           found_by="the columns you chose")
    codes, stats = f2f.convert(table, chosen)
    assert len(codes) == 3 and stats["points"] == 2 and stats["lines"] == 1
    assert codes.get("UGC").layer == "E_Utility_Cable_Line"
    assert codes.get("DNF").name == "Did Not Find"


def test_a_file_that_starts_on_a_code_reads_without_a_header(tmp_path):
    text = "\n".join(CARLSON.splitlines()[1:]) + "\n"
    table = f2f.read(_write(tmp_path, text), header_row=False)
    assert table.header_row is False and len(table) == 7
    assert f2f.auto_map(table).found_by == "Carlson's own column positions"


def test_a_point_file_picked_by_mistake_is_refused_by_name(tmp_path):
    """The likeliest wrong file is the crew's own download.  Turning it into hundreds of codes
    called "1" would be worse than saying so."""
    p = _write(tmp_path, "OID,Pt,N,E,Z,Desc\n1,1,2552700,6967100,500,GS\n", "a job file.csv")
    with pytest.raises(ValueError) as err:
        f2f.read(p)
    assert "a job file.csv" in str(err.value) and "point or job file" in str(err.value)
    north = _write(tmp_path, "Northing,Easting,Elevation,Description\n6967100,2552700,500,GS\n",
                   "from gis.csv")
    with pytest.raises(ValueError):
        f2f.read(north)
    empty = _write(tmp_path, "Code,Description\n", "empty table.csv")
    with pytest.raises(ValueError) as err:
        f2f.read(empty)
    assert "empty table.csv" in str(err.value) and "no code rows" in str(err.value)


# ------------------------------------------------------------------ entity types
def test_entity_types_map_to_plumbline_kinds(tmp_path):
    for word, kind, breakline in (("Point", "point", False), ("Line", "line", True),
                                  ("2D Polyline", "line", True), ("3D Polyline", "line", True),
                                  ("Arc", "line", True), ("Circle", "polygon", True),
                                  ("Polygon", "polygon", True), ("Text", "point", False)):
        assert kind_for_entity(word) == (kind, breakline, True)
    for number, word in CARLSON_ENTITY_TYPES.items():          # Carlson writes numbers
        assert kind_for_entity(number) == kind_for_entity(word)
    assert kind_for_entity("Zigzag") == ("point", False, False)
    assert kind_for_entity("") == ("point", False, False)


def test_the_two_programs_agree_on_carlsons_entity_numbers():
    """Fieldwork Manager ships separately and keeps its own copy of this table.  A copy that
    silently drifts is how the field window and the main window start disagreeing about what a
    "2" is, so the copies are pinned against each other."""
    assert FM_CONFIG.carlson_entity_types == CARLSON_ENTITY_TYPES


def test_an_unknown_entity_type_is_kept_as_a_point_and_reported(tmp_path):
    table = f2f.read(_write(tmp_path, CARLSON))
    _codes, stats = f2f.convert(table)
    assert stats["unknown_entity_types"] == ["4"]               # CIR - kept, and said out loud
    assert "Entity types not recognised: 4" in f2f.describe_stats(stats)


# ------------------------------------------------------------------ choosing the rows
def test_rows_can_be_ticked_one_by_one(tmp_path):
    table = f2f.read(_write(tmp_path, CARLSON))
    codes, stats = f2f.convert(table, only={1, 3})
    assert sorted(codes.codes) == ["DNF", "UGC"]
    assert stats["codes"] == 2 and stats["skipped_by_choice"] == 5
    assert "5 row(s) left unticked." in f2f.describe_stats(stats)


def test_codes_can_be_picked_by_name_for_a_filter_box(tmp_path):
    table = f2f.read(_write(tmp_path, CARLSON))
    assert f2f.select_by_code(table, ["ugc", "DNF"]) == {1, 3}
    assert f2f.select_by_code(table, []) == set()


# ------------------------------------------------------------------ into the job's table
def test_a_merge_keeps_the_job_codes_the_file_does_not_name(tmp_path):
    table = f2f.read(_write(tmp_path, CARLSON))
    job = FeatureCodeTable.from_list([{"code": "EP", "name": "Edge of pavement", "kind": "line",
                                       "layer": "ROAD-EP"},
                                      {"code": "DNF", "name": "ours", "kind": "point",
                                       "layer": "OURS"}])
    before = {c.code: (c.name, c.layer) for c in job}
    codes, stats = f2f.convert(table, existing=job)
    assert codes.get("EP").layer == "ROAD-EP"                   # not in the file: kept
    assert codes.get("DNF").layer == "V-PROP-CRNR-NOT FOUND"    # in the file: the file wins
    assert stats["kept"] == 1 and stats["replaced"] == 1
    assert {c.code: (c.name, c.layer) for c in job} == before   # the job's table is never written through


def test_a_replace_drops_the_job_codes_entirely(tmp_path):
    table = f2f.read(_write(tmp_path, CARLSON))
    job = FeatureCodeTable.from_list([{"code": "EP", "name": "Edge of pavement", "kind": "line",
                                       "layer": "ROAD-EP"}])
    codes, stats = f2f.convert(table)
    assert not codes.get("EP") and stats["kept"] == 0
    assert len(codes) == 7
    assert job.get("EP") is not None                            # and the old table is untouched


def test_a_repeated_code_is_the_last_row_and_is_counted(tmp_path):
    text = CARLSON + "DNF,Did Not Find (again),SPT10,1,V-PROP-CRNR-NEW,0,1,BYLAYER\n"
    table = f2f.read(_write(tmp_path, text))
    codes, stats = f2f.convert(table)
    assert stats["duplicates"] == 1 and stats["codes"] == 8 and len(codes) == 7
    assert codes.get("DNF").layer == "V-PROP-CRNR-NEW"
    assert "repeated a code already read" in f2f.describe_stats(stats)


def test_a_code_with_no_layer_and_no_category_names_no_layer(tmp_path):
    """The old behaviour made a layer called "V-" here.  A layer with a name like that is a
    layer somebody has to delete later, so a code with nothing to say about its layer says
    nothing - Plumbline draws it on the current layer, as it does for any code without one."""
    text = "Code,Description,Symbol,Layer,Entity Type\nORPHAN,Nowhere,CG08,,0\n"
    table = f2f.read(_write(tmp_path, text))
    codes, stats = f2f.convert(table)
    assert codes.get("ORPHAN").layer == "" and stats["no_layer"] == 1
    assert "named no layer" in f2f.describe_stats(stats)


# ------------------------------------------------------------------ the real office standard
def test_the_real_office_standard_reads_the_same_through_both_doors():
    """1,717 codes, 1,593 points, 124 lines, 216 layers: the sample job's own code table, read
    once by Plumbline's converter and once by the door Fieldwork Manager uses."""
    from plumbline.fieldwork.bridge import feature_codes_from_f2f

    table = f2f.read(REAL_F2F)
    mine, stats = f2f.convert(table)
    theirs, their_stats = feature_codes_from_f2f(REAL_F2F)
    assert (len(table), table.category_rows) == (1717, 23)
    assert (stats["codes"], stats["points"], stats["lines"]) == (1717, 1593, 124)
    assert len(stats["layers"]) == 216 and len(stats["symbols"]) == 133
    assert stats["categories"] == their_stats["categories"] and stats["layers"] == their_stats["layers"]
    assert stats["unknown_entity_types"] == []
    as_dict = lambda t: {c.code: (c.name, c.kind, c.layer, c.symbol, c.breakline) for c in t}  # noqa: E731
    assert as_dict(mine) == as_dict(theirs)
    assert f2f.auto_map(table).found_by == "the header names"


def test_the_office_standard_is_named_in_one_line():
    table = f2f.read(REAL_F2F)
    _codes, stats = f2f.convert(table)
    line = f2f.describe_stats(stats)
    assert line.startswith("1,717 codes - 1,593 points / 124 lines - 216 layers")
    assert "133 symbols" in line
    assert f2f.ColumnMap().describe(table.headers).startswith("Read by Carlson's own column positions")


# ------------------------------------------------------------------ the dialog
@pytest.fixture()
def app():
    from PySide6.QtWidgets import QApplication
    from plumbline.ui import theme
    a = QApplication.instance() or QApplication([])
    theme.apply_theme(a, "dark")
    return a


def test_the_dialog_opens_on_carlson_with_every_code_ticked(app, tmp_path):
    from plumbline.ui.f2f_dialog import ConvertFieldToFinishDialog

    dlg = ConvertFieldToFinishDialog(f2f.read(_write(tmp_path, CARLSON)), Project("Job"))
    assert dlg.rb_carlson.isChecked() and not dlg.custom.isVisible()
    assert len(dlg._ticked()) == 7 and dlg.choices()[2] == "replace"
    assert dlg.choices()[0].found_by == "the header names"
    assert "7 codes" in dlg.lbl_preview.text()
    assert dlg.tbl.item(0, 0).text() == "DEFAULT" and dlg.tbl.item(0, 3).text() == "V-SITE-DEFAULT"
    assert dlg.tbl.item(3, 2).text() == "Line"                  # the kind column reads the entity type
    assert dlg.tbl.item(6, 2).text() == "Point"                 # ... including an unknown entity type


def test_the_filter_and_only_the_matches_leave_the_rest_alone(app, tmp_path):
    from PySide6.QtWidgets import QDialogButtonBox
    from plumbline.ui.f2f_dialog import ConvertFieldToFinishDialog

    dlg = ConvertFieldToFinishDialog(f2f.read(_write(tmp_path, CARLSON)), Project("Job"))
    dlg.le_filter.setText("E_Utility")                          # the layer is searched...
    assert [i for i in range(7) if not dlg.tbl.isRowHidden(i)] == [3, 4, 6]
    assert "3 shown of 7" in dlg.lbl_rows.text()
    dlg.le_filter.setText("corner")                             # ... and so is the category
    assert [i for i in range(7) if not dlg.tbl.isRowHidden(i)] == [1, 2]
    dlg.le_filter.setText("E_Utility")
    dlg._tick("matches")
    assert sorted(dlg._ticked_codes()) == ["CIR", "SANI", "UGC"]
    assert "4 row(s) left unticked." in dlg.lbl_preview.text()
    dlg._tick("invert")
    assert sorted(dlg._ticked_codes()) == ["DEFAULT", "DNF", "MAGF", "NOLAYER"]
    dlg._tick("none")
    assert not dlg._ticked()
    assert "nothing would be converted" in dlg.lbl_preview.text()
    assert not dlg.buttons.button(QDialogButtonBox.Ok).isEnabled()   # nothing ticked, nothing to do


def test_custom_columns_and_the_header_switch(app, tmp_path):
    from plumbline.ui.f2f_dialog import ConvertFieldToFinishDialog

    path = _write(tmp_path, SHUFFLED, "from-the-database.csv")
    dlg = ConvertFieldToFinishDialog(f2f.read(path), Project("Job"))
    assert dlg.mapping.found_by == "Carlson's own column positions"  # five bare columns, no names
    dlg.rb_custom.setChecked(True)
    assert not dlg.custom.isHidden() and dlg.mapping.found_by == "the columns you chose"
    for fact, column in (("code", 3), ("description", 1), ("symbol", 2), ("layer", 0), ("entity", 4)):
        combo = dlg.custom.combos[fact]
        combo.setCurrentIndex(combo.findData(column))
    codes, stats = f2f.convert(dlg.table, dlg.mapping)
    assert codes.get("UGC").layer == "E_Utility_Cable_Line"
    assert (stats["points"], stats["lines"]) == (3, 1)      # the header row is still being read
    # "The first row is a header": the file is read again with that row kept out, and the ticks
    # are remembered by *code*, so the three real codes come back ticked rather than lost
    dlg.custom.chk_header.setChecked(True)
    assert len(dlg.table) == 3 and dlg._ticked_codes() == {"DEFAULT", "DNF", "UGC"}
    codes, stats = f2f.convert(dlg.table, dlg.mapping)
    assert codes.get("UGC").layer == "E_Utility_Cable_Line" and (stats["points"], stats["lines"]) == (2, 1)


def test_the_job_gets_the_codes_and_the_file_is_remembered(win, app, auto, monkeypatch, tmp_path):
    """The whole way through: Survey > Convert Field to Finish, a file chosen, Carlson's layout,
    the ticked codes in the project, the path remembered on the job - and undo puts it back."""
    from PySide6.QtWidgets import QFileDialog
    from plumbline.ui import main_window as MW

    path = _write(tmp_path, CARLSON)
    pr = win.state.project
    was = len(pr.codes)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(path), "")))
    logged = []
    win.state.message.connect(lambda level, text: logged.append((level, text)))
    win.a_f2f.trigger()
    assert len(pr.codes) == 7 and pr.codes.get("UGC").kind == "line"
    assert pr.settings["f2f_path"] == str(path)
    assert any("Field to Finish" in t for _lvl, t in logged)
    win.undo()
    assert len(pr.codes) == was and pr.codes.get("UGC") is None
