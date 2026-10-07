"""Semantic Field Book command and separator handling."""
from __future__ import annotations

from plumbline.core.fieldbook_syntax import (
    DEFAULT_COMMAND_MAP,
    command_map,
    command_token_validation_error,
    find_separator,
    normalize_separator_spacing,
    separator_text,
    split_at_separator,
    trim_separator_edges,
)


def test_command_map_keeps_meanings_attached_to_tokens():
    assert command_map() == DEFAULT_COMMAND_MAP
    mapped = command_map({"Start Line": "BEGINLN", "Multi-code separator": "PLUS"})
    assert mapped["start_line"] == "BEGINLN"
    assert mapped["multicode"] == "PLUS"
    assert mapped["description"] == DEFAULT_COMMAND_MAP["description"]

    # A blank cell disables that meaning without shifting the rows that follow it.
    values = command_map(["BEGINLN", "", "ENDCURVE", "FINISH", "CLOSEFIG", "PLUS", "NOTE"])
    assert values["start_curve"] == ""
    assert values["end_curve"] == "ENDCURVE"
    assert values["end_line"] == "FINISH"
    assert values["multicode"] == "PLUS"


def test_command_tokens_must_be_assigned_single_and_case_insensitively_unique():
    assert command_token_validation_error(["", " ", ""]) == "Assign at least one semantic command token."
    assert command_token_validation_error(["Begin Line", "", ""]) == \
        "Each command token must be a single word or symbol."
    assert command_token_validation_error(["begin", "BEGIN"]) == \
        "Each semantic command token must be unique."
    assert command_token_validation_error(["+", "NOTE", ""]) is None


def test_alphanumeric_separators_match_only_as_whole_tokens():
    assert find_separator("EA NOTE oak", "NOTE") == 3
    assert find_separator("EA noteworthy oak", "NOTE") == -1
    assert split_at_separator("EA PLUS SW", "PLUS", maxsplit=0) == ["EA", "SW"]
    assert split_at_separator("SAND EA", "AND", maxsplit=0) == ["SAND EA"]
    assert normalize_separator_spacing("EA PLUS  SW", "PLUS", spaced=False) == "EAPLUSSW"
    assert separator_text("description", {"description": "NOTE"}, spaced=False) == "NOTE"


def test_separator_edge_trimming_is_whole_token_and_preserves_interior_text():
    assert trim_separator_edges("  NOTE  oak  /  ", ["NOTE", "/"]) == "oak"
    assert trim_separator_edges("noteworthy / sidewalk", ["NOTE", "/"]) == "noteworthy / sidewalk"
    assert trim_separator_edges("PLUS  Oak  tree  PLUS", "PLUS") == "Oak  tree"
    assert trim_separator_edges(" / NOTE / ", ["NOTE", "/"]) == ""


def test_parser_reads_semantic_separators_from_the_active_fieldbook(tmp_path):
    from plumbline.fieldwork.io_carlson import write_fwb_file
    from plumbline.fieldwork.parse import parse_desc_field

    commands = {
        "start_line": "BEGINLN",
        "start_curve": "BC",
        "end_curve": "EC",
        "end_line": "FINISH",
        "close": "CLOSEFIG",
        "multicode": "PLUS",
        "description": "NOTE",
    }
    book = tmp_path / "office.fwb"
    assert write_fwb_file(book, ["Code", "Description"], [["EA", "Asphalt"], ["SW", "Sidewalk"]],
                          commands=commands)
    parsed = parse_desc_field("EA BEGINLN PLUS SW NOTE roadway", {"ea", "sw"},
                              fieldbook_path=book)
    assert parsed["code_raw_tokens"] == ["EA", "BEGINLN", "SW"]
    assert parsed["code_part"] == "EA BEGINLN PLUS SW"
    assert parsed["free_desc"] == "roadway"
    assert not parsed["flags"]
