"""Check shared artifact boundaries without duplicating workflow validators."""

import json

import pytest

from artifact_io import canonical_json_bytes, json_bytes, next_artifact_id, project_file, sha256_bytes


def test_readable_encoding_retains_existing_utf8_and_newline_format():
    data = {"plan": "Montréal", "evidence": "First line.\nSecond line.", "missing": None}
    expected = (json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    assert json_bytes(data) == expected
    assert sha256_bytes(b"abc") == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_json_identity_ignores_keys_but_preserves_types_and_list_order():
    assert canonical_json_bytes({"a": 1, "b": 2}) == canonical_json_bytes({"b": 2, "a": 1})
    assert canonical_json_bytes({"page": True}) != canonical_json_bytes({"page": 1})
    assert canonical_json_bytes([1, 2]) != canonical_json_bytes([2, 1])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_numbers_never_get_encoded(value):
    with pytest.raises(ValueError): json_bytes({"value": value})
    with pytest.raises(ValueError): canonical_json_bytes({"value": value})


def test_next_id_counts_occupied_files_and_partial_folders_across_roots(tmp_path):
    draft = tmp_path / "drafts"
    completed = tmp_path / "completed"
    draft.mkdir()
    completed.mkdir()
    (draft / "review_0001").mkdir()
    (completed / "review_0003").write_text("Reserved evidence")
    assert next_artifact_id(tmp_path, ("drafts", "completed"), "review") == "review_0004"
    assert not (draft / "review_0004").exists()


@pytest.mark.parametrize("relative", ["../escape", "/absolute", "C:\\escape"])
def test_paths_cannot_escape_project(tmp_path, relative):
    with pytest.raises(ValueError): project_file(tmp_path, relative, label="Test")


def test_paths_reject_internal_symlinks_too(tmp_path):
    target = tmp_path / "original"
    target.mkdir()
    (tmp_path / "alias").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        project_file(tmp_path, "alias/input.json", label="Test")
