"""Preserve the exact expert reference identity before assessment uses its IDs.

These fictional references pass software checks only. Freezing records human
confirmation, and does not demonstrate factual accuracy or independence.
"""

from datetime import datetime
import hashlib
import json

import pytest

import cli
import expert_files
import storage
from expert_templates import blank_action
from test_expert_reference_validation import (
    _read_reference, _reference_path, _snapshot, _write_reference, project,
)


PLAN_ID = "plan_0001"


def freeze(root, **options):
    return expert_files.freeze_expert_reference(root, PLAN_ID, frozen_by=options.get("frozen_by", ["reviewer_01"]))


def freeze_path(root):
    return _reference_path(root).with_name("reference_freeze.json")


def test_freeze_preserves_exact_reference_and_source_without_reading_model_outputs(project, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    output = project / f"runs/{PLAN_ID}/run_extract_0001/output.json"
    output.parent.mkdir(parents=True)
    output.write_text("This model output must not be read.")
    before = _snapshot(project)
    reference = _reference_path(project).read_bytes()

    path = freeze(project, frozen_by=["reviewer_01", "Reviewer Two"])

    after = _snapshot(project)
    metadata = json.loads(after.pop(path))
    assert after == before
    assert metadata["reference_path"] == f"expert_references/{PLAN_ID}/expert_reference.json"
    assert metadata["reference_sha256"] == hashlib.sha256(reference).hexdigest()
    assert metadata["document_sha256"] == hashlib.sha256((project / "data/raw/plan_0001.pdf").read_bytes()).hexdigest()
    assert metadata["page_count"] == 3
    assert metadata["source_url"] == "https://example.org/plan.pdf"
    assert metadata["date_accessed"] == "2026-11-21"
    assert metadata["frozen_by"] == ["reviewer_01", "Reviewer Two"]
    assert metadata["confirmed_complete"] is True
    assert datetime.fromisoformat(metadata["frozen_at"]).utcoffset().total_seconds() == 0
    assert expert_files.validate_expert_reference(project, PLAN_ID) == _read_reference(project)
    assert _snapshot(project) == before | {path: freeze_path(project).read_bytes()}


@pytest.mark.parametrize("reviewers", [[], [""], [" \n"], [None], "reviewer", None])
def test_invalid_confirmation_never_freezes_or_changes_a_reference(project, reviewers):
    before = _snapshot(project)
    with pytest.raises(storage.ExpertReferenceValidationError):
        freeze(project, frozen_by=reviewers)
    assert _snapshot(project) == before


@pytest.mark.parametrize("damage", ["template", "evidence", "type", "page", "source", "json"])
def test_incomplete_or_invalid_reference_cannot_be_frozen(project, damage):
    reference = _read_reference(project)
    action = reference["plan_data"]["actions"][0]
    if damage == "template":
        reference["plan_data"]["actions"] = [blank_action("action_0001")]
    elif damage in {"evidence", "type"}:
        action["evidence" if damage == "evidence" else "action_type"] = []
        reference.pop("plan_issues")  # Omission must not bypass completion checks.
    elif damage == "page":
        action["evidence"][0]["page_numbers"] = [4]
    elif damage == "source":
        reference["plan_data"]["metadata"]["source_url"] = "https://example.org/other.pdf"
    _write_reference(project, reference)
    if damage == "json":
        _reference_path(project).write_bytes(b'{"unfinished":')
    before = _snapshot(project)
    with pytest.raises(storage.ExpertReferenceValidationError):
        freeze(project)
    assert _snapshot(project) == before and not freeze_path(project).exists()


@pytest.mark.parametrize("operation", ["add_action", "add_issue", "remove_action", "remove_issue"])
def test_frozen_references_reject_every_editor_operation(project, operation):
    freeze(project)
    before = _snapshot(project)
    with pytest.raises(ValueError, match="frozen for assessment"):
        expert_files.edit_expert_reference(project, PLAN_ID, operation=operation)
    assert _snapshot(project) == before


def test_freeze_cannot_be_overwritten_or_bypassed_by_direct_storage_edit(project):
    freeze(project)
    before = _snapshot(project)
    with pytest.raises(ValueError, match="frozen for assessment"):
        freeze(project, frozen_by=["another_reviewer"])
    with pytest.raises(ValueError, match="frozen for assessment"):
        storage.save_expert_reference_edit(project, PLAN_ID, _read_reference(project),
                                          expected_bytes=_reference_path(project).read_bytes())
    assert _snapshot(project) == before


def test_missing_frozen_reference_cannot_be_reset_by_creation(project):
    freeze(project)
    _reference_path(project).unlink()
    before = _snapshot(project)
    with pytest.raises(ValueError, match="frozen for assessment"):
        expert_files.create_expert_reference(project, PLAN_ID, prepared_by=["reviewer"])
    assert _snapshot(project) == before


@pytest.mark.parametrize("change", ["whitespace", "action", "prepared_by", "id_counters"])
def test_any_direct_change_to_frozen_reference_is_detected(project, change):
    freeze(project)
    reference = _read_reference(project)
    if change == "whitespace":
        _reference_path(project).write_bytes(_reference_path(project).read_bytes() + b"\n")
    else:
        if change == "action":
            reference["plan_data"]["actions"][0]["action"] = "Changed activity."
        elif change == "prepared_by":
            reference["prepared_by"] = ["another_person"]
        else:
            reference["id_counters"]["action"] += 1
        _write_reference(project, reference)
    before = _snapshot(project)
    with pytest.raises(ValueError, match="fingerprint"):
        expert_files.validate_expert_reference(project, PLAN_ID)
    assert _snapshot(project) == before


@pytest.mark.parametrize("field,value", [
    ("document_sha256", "0" * 64), ("source_url", "https://example.org/changed.pdf"),
    ("date_accessed", "2026-11-20"), ("page_count", 2),
])
def test_freeze_must_still_match_registered_original_context(project, field, value):
    freeze(project)
    metadata = json.loads(freeze_path(project).read_text())
    metadata[field] = value
    freeze_path(project).write_text(json.dumps(metadata))
    with pytest.raises(ValueError, match=f"{field} no longer matches"):
        expert_files.validate_expert_reference(project, PLAN_ID)


@pytest.mark.parametrize("damage", ["json", "duplicate", "schema", "wrong_plan", "wrong_path", "directory", "symlink", "dangling"])
def test_damaged_freeze_never_silently_unlocks_a_reference(project, damage):
    freeze(project)
    path = freeze_path(project)
    if damage == "json":
        path.write_bytes(b'{"unfinished":')
    elif damage == "duplicate":
        path.write_text(path.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    elif damage in {"schema", "wrong_plan", "wrong_path"}:
        metadata = json.loads(path.read_text())
        field, value = {"schema": ("confirmed_complete", False), "wrong_plan": ("plan_id", "plan_0002"),
                        "wrong_path": ("reference_path", "other.json")}[damage]
        metadata[field] = value
        path.write_text(json.dumps(metadata))
    else:
        contents = path.read_bytes()
        path.unlink()
        if damage == "directory":
            path.mkdir()
        else:
            target = project / "elsewhere.json"
            if damage == "symlink":
                target.write_bytes(contents)
            path.symlink_to(target)
    with pytest.raises((OSError, ValueError)):
        expert_files.validate_expert_reference(project, PLAN_ID)
    with pytest.raises((OSError, ValueError)):
        expert_files.edit_expert_reference(project, PLAN_ID, operation="add_action")
    with pytest.raises((OSError, ValueError)):
        freeze(project)


def test_intervening_reference_edit_prevents_freeze_publication(project, monkeypatch):
    original = storage.save_new_expert_reference_freeze
    def changed(root, plan_id, metadata, **kwargs):
        _reference_path(root).write_bytes(_reference_path(root).read_bytes() + b"\n")
        return original(root, plan_id, metadata, **kwargs)
    monkeypatch.setattr(storage, "save_new_expert_reference_freeze", changed)
    with pytest.raises(ValueError, match="changed while freezing"):
        freeze(project)
    assert not freeze_path(project).exists()


def test_publication_failure_does_not_leave_partial_freeze_or_change_reference(project, monkeypatch):
    before = _snapshot(project)
    def failed(*args):
        raise OSError("Controlled freeze publication failure")
    monkeypatch.setattr(storage.os, "link", failed)
    with pytest.raises(OSError, match="publication failure"):
        freeze(project)
    assert _snapshot(project) == before


def test_cli_freezes_with_named_reviewers_and_validation_verifies_identity(project, capsys):
    assert cli.main(["freeze_expert_reference", PLAN_ID, "--frozen-by", "reviewer_01",
                     "--frozen-by", "Reviewer Two", "--project-root", str(project)]) == 0
    output = capsys.readouterr()
    assert "Reference frozen for assessment" in output.out and output.err == ""
    assert storage.load_expert_reference_freeze(project, PLAN_ID)["reference_sha256"] in output.out
    before = _snapshot(project)
    assert cli.main(["validate_expert_reference", PLAN_ID, "--project-root", str(project)]) == 0
    assert "Frozen reference and source fingerprints verified" in capsys.readouterr().out
    assert _snapshot(project) == before
    assert cli.main(["edit_expert_reference", "--plan-id", PLAN_ID, "--add-action",
                     "--project-root", str(project)]) == 1
    assert "frozen for assessment" in capsys.readouterr().err


@pytest.mark.parametrize("args", [[], [PLAN_ID], ["--frozen-by", "reviewer"]])
def test_cli_requires_plan_and_reviewer(args):
    with pytest.raises(SystemExit) as error:
        cli.main(["freeze_expert_reference", *args])
    assert error.value.code == 2
