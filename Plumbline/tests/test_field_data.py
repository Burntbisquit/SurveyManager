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
    assert imported_file_matches([record], source_root, source)
    assert imported_file_matches([record], stored_root, stored)

    source.write_bytes(b"changed-size")
    assert not imported_file_matches([record], source_root, source)
