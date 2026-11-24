"""Keep reference/freeze history intact when moving research data under data/."""

import json

import pytest

import expert_files
import storage
from test_expert_reference_validation import _read_reference, _reference_path, project


def legacy_folder(root):
    source = root / "data/expert_references"
    destination = root / "expert_references"
    source.rename(destination)
    return destination


@pytest.mark.parametrize("frozen", [False, True])
def test_migration_preserves_all_bytes_and_readable_frozen_history(project, frozen):
    if frozen:
        expert_files.freeze_expert_reference(project, "plan_0001", frozen_by=["reviewer"])
        path = _reference_path(project).with_name("reference_freeze.json")
        metadata = json.loads(path.read_text())
        metadata["reference_path"] = "expert_references/plan_0001/expert_reference.json"
        path.write_text(json.dumps(metadata))  # Represent a pre-move historical freeze.
    reference = _read_reference(project)
    source = legacy_folder(project)
    (source / "plan_0001/notes.txt").write_bytes(b"Preserve manual notes, too.\n")
    before = {p.relative_to(source).as_posix(): p.read_bytes() for p in source.rglob("*") if p.is_file()}

    moved = storage.migrate_expert_references(project)

    assert not source.exists()
    destination = project / "data/expert_references"
    assert before == {p.relative_to(destination).as_posix(): p.read_bytes() for p in destination.rglob("*") if p.is_file()}
    assert set(moved) == {f"data/expert_references/{name}" for name in before}
    assert expert_files.validate_expert_reference(project, "plan_0001") == reference
    assert storage.migrate_expert_references(project) == []
    if frozen:
        with pytest.raises(ValueError, match="frozen"):
            expert_files.edit_expert_reference(project, "plan_0001", operation="add_action")


def test_old_reference_cannot_be_reset_by_creation_at_the_new_path(project):
    source = legacy_folder(project)
    before = (source / "plan_0001/expert_reference.json").read_bytes()
    with pytest.raises(ValueError, match="old location"):
        expert_files.create_expert_reference(project, "plan_0001", prepared_by=["another"])
    assert (source / "plan_0001/expert_reference.json").read_bytes() == before
    assert not (project / "data/expert_references").exists()


@pytest.mark.parametrize("occupied", ["directory", "file", "symlink"])
def test_migration_never_merges_or_overwrites_a_destination(project, occupied):
    source = legacy_folder(project)
    destination = project / "data/expert_references"
    if occupied == "directory":
        destination.mkdir()
    elif occupied == "file":
        destination.write_bytes(b"existing work")
    else:
        destination.symlink_to(project / "missing")
    with pytest.raises((ValueError, FileExistsError)):
        storage.migrate_expert_references(project)
    assert source.is_dir()


def test_migration_rejects_redirected_reference_files(project):
    source = legacy_folder(project)
    reference = source / "plan_0001/expert_reference.json"
    target = project / "other.json"
    reference.rename(target)
    reference.symlink_to(target)
    before = target.read_bytes()
    with pytest.raises(ValueError, match="symbolic"):
        storage.migrate_expert_references(project)
    assert target.read_bytes() == before and reference.is_symlink()
