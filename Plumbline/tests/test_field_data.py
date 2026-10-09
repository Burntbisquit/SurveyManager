from __future__ import annotations

from plumbline.core.field_data import imported_file_matches, make_import_record


def test_imported_field_data_is_matched_by_relative_path_and_size(tmp_path):
    source_root = tmp_path / "Downloads" / "batch"
    source_root.mkdir(parents=True)
    source = source_root / "crew 1.csv"
    source.write_bytes(b"same-size")

    stored_root = tmp_path / "Job" / "Field Data"
    stored_root.mkdir(parents=True)
    stored = stored_root / "batch" / source.name
    stored.parent.mkdir()
    stored.write_bytes(source.read_bytes())

    record = make_import_record(source_root, source, stored_root, stored)
    assert record["source_relative"] == "batch/crew 1.csv"
    assert record["stored_relative"] == "field data/batch/crew 1.csv"
    assert imported_file_matches([record], source_root, source)
    assert imported_file_matches([record], stored_root, stored)

    renamed = source_root / "crew 2.csv"
    renamed.write_bytes(source.read_bytes())
    assert not imported_file_matches([record], source_root, renamed), \
        "same-sized files with different names are new field data"

    other_parent = tmp_path / "Downloads" / "other-batch"
    other_parent.mkdir()
    same_name_elsewhere = other_parent / source.name
    same_name_elsewhere.write_bytes(source.read_bytes())
    assert not imported_file_matches([record], other_parent, same_name_elsewhere), \
        "the selected parent folder name is part of field-data identity"

    source.write_bytes(b"changed-size")
    assert not imported_file_matches([record], source_root, source)
