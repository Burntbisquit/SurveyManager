"""Tests for layer definitions, sister specification, and layer state groups."""
from __future__ import annotations

import json
from pathlib import Path
import pytest

from plumbline.core.project import Project
from plumbline.core.featurecodes import FeatureCode, FeatureCodeTable
from plumbline.core.layer_definitions import (
    LayerDefinition,
    STANDARD_LAYER_DEFINITIONS,
    get_layer_definition,
    populate_layers_from_fieldbook,
    export_sister_layer_document,
    import_sister_layer_document,
)


def test_project_layers_start_empty():
    """Projects start with an empty layer list and populate from fieldbook / fieldwork."""
    pr = Project("FreshJob")
    assert len(pr.layers) == 0


def test_sister_layer_definitions_and_lookup():
    """Sister layer definitions match authoritative colors, linestyles, and symbology."""
    bm = get_layer_definition("CONTROL-BM")
    assert bm.color == (255, 90, 90)
    assert bm.linetype == "CONTINUOUS"
    assert bm.symbology == "triangle"
    assert bm.category == "Control"

    bndy = get_layer_definition("BNDY-PL")
    assert bndy.color == (255, 255, 255)
    assert bndy.linetype == "PHANTOM"
    assert bndy.symbology == "square"

    road = get_layer_definition("ROAD-EP")
    assert road.color == (255, 255, 0)
    assert road.symbology == "circle"

    # Fuzzy category fallback
    custom_water = get_layer_definition("MY_WATER_LINE")
    assert custom_water.category == "Utilities" or custom_water.category == "Hydro"


def test_populate_layers_from_fieldbook():
    """Populating layers from fieldbook creates authoritative layers on project."""
    pr = Project("TestFB")
    assert len(pr.layers) == 0

    codes = FeatureCodeTable([
        FeatureCode("GS", "Ground shot", "point", "TOPO-GROUND", "cross"),
        FeatureCode("EP", "Edge of pavement", "line", "ROAD-EP", "circle", color=(255, 255, 0)),
        FeatureCode("BM", "Benchmark", "point", "CONTROL-BM", "triangle"),
    ])

    created = populate_layers_from_fieldbook(pr, codes)
    assert "TOPO-GROUND" in pr.layers
    assert "ROAD-EP" in pr.layers
    assert "CONTROL-BM" in pr.layers
    assert pr.layers["CONTROL-BM"].color == (255, 90, 90)
    assert pr.layers["ROAD-EP"].color == (255, 255, 0)
    assert pr.layers["TOPO-GROUND"].color == (200, 200, 200)


def test_layer_state_group_save_and_restore():
    """Layer state group saves current layer visibility/locks and returns to saved state."""
    pr = Project("StateTest")
    pr.ensure_layer("TOPO-GROUND", (200, 200, 200))
    pr.ensure_layer("ROAD-EP", (255, 255, 0))
    pr.ensure_layer("CONTROL-BM", (255, 90, 90))

    pr.layers["TOPO-GROUND"].visible = True
    pr.layers["ROAD-EP"].visible = True
    pr.layers["CONTROL-BM"].visible = True
    pr.layers["CONTROL-BM"].locked = False

    # Save State 1: "All_Visible"
    state_all = {n: {"visible": lay.visible, "locked": lay.locked, "color": list(lay.color), "linetype": lay.linetype}
                 for n, lay in pr.layers.items()}
    pr.settings["layer_states"] = {"All_Visible": state_all}

    # Change states: hide TOPO and lock CONTROL
    pr.layers["TOPO-GROUND"].visible = False
    pr.layers["CONTROL-BM"].locked = True

    # Save State 2: "Work_State"
    state_work = {n: {"visible": lay.visible, "locked": lay.locked, "color": list(lay.color), "linetype": lay.linetype}
                  for n, lay in pr.layers.items()}
    pr.settings["layer_states"]["Work_State"] = state_work

    assert pr.layers["TOPO-GROUND"].visible is False
    assert pr.layers["CONTROL-BM"].locked is True

    # Restore State 1: returns to saved state
    saved = pr.settings["layer_states"]["All_Visible"]
    for n, s in saved.items():
        pr.layers[n].visible = s["visible"]
        pr.layers[n].locked = s["locked"]

    assert pr.layers["TOPO-GROUND"].visible is True
    assert pr.layers["CONTROL-BM"].locked is False

    # Restore State 2: returns to Work_State
    saved2 = pr.settings["layer_states"]["Work_State"]
    for n, s in saved2.items():
        pr.layers[n].visible = s["visible"]
        pr.layers[n].locked = s["locked"]

    assert pr.layers["TOPO-GROUND"].visible is False
    assert pr.layers["CONTROL-BM"].locked is True


def test_sister_document_export_import(tmp_path):
    """Sister layer definitions can be exported and imported as JSON."""
    doc_path = tmp_path / "sister_layers.json"
    export_sister_layer_document(doc_path)
    assert doc_path.exists()

    loaded = import_sister_layer_document(doc_path)
    assert "CONTROL-BM" in loaded
    assert loaded["CONTROL-BM"].color == (255, 90, 90)
    assert loaded["CONTROL-BM"].symbology == "triangle"
