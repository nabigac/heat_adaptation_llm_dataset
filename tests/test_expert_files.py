"""Check reference creation, CLI wiring, independence, and preservation of expert work."""

import json
from pathlib import Path

import pytest

import cli
import documents
import expert_files
import storage
from validation import validate_expert_reference_structure


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "study project"
    root.mkdir()
    pdf = tmp_path / "incoming plan.pdf"
    # Creation checks registered bytes, without parsing pages or requiring OCR.
    pdf.write_bytes(b"%PDF-1.4\nFictional reference creation fixture\n%%EOF\n")
    documents.register_document(
        root, pdf, plan_title="Fictional heat plan — 2026",
        source_url="https://example.org/heat-plan.pdf", date_accessed="2026-11-21",
        study_set="comparison",
    )
    return root


def _reference_path(root: Path) -> Path:
    return root / "data/expert_references/plan_0001/expert_reference.json"


def _file_contents(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


def test_creates_guided_form_from_collection_without_model_outputs(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    run = project / "runs/plan_0001/run_extract_0001/output.json"
    run.parent.mkdir(parents=True)
    run.write_text("Invalid model output must never seed an expert reference.", encoding="utf-8")
    before = _file_contents(project)
    reviewers = ["Reviewer A", "researcher_02"]

    path = expert_files.create_expert_reference(project, "plan_0001", prepared_by=reviewers)

    assert path == "data/expert_references/plan_0001/expert_reference.json"
    reference = json.loads((project / path).read_text(encoding="utf-8"))
    assert reference["schema_version"] == 1
    assert reference["plan_id"] == "plan_0001"
    assert reference["prepared_by"] == reviewers
    assert reference["plan_data"]["metadata"] == {
        "plan_title": "Fictional heat plan — 2026",
        "jurisdiction_name": None,
        "country": None,
        "plan_scale": None,
        "plan_type": None,
        "publication_year": None,
        "lead_agencies": [],
        "source_url": "https://example.org/heat-plan.pdf",
        "date_accessed": "2026-11-21",
        "language": "English",
    }
    assert reference["instructions"] and all(isinstance(line, str) for line in reference["instructions"])
    assert len(reference["plan_data"]["actions"]) == len(reference["plan_issues"]["issues"]) == 1
    action = reference["plan_data"]["actions"][0]
    assert action["action_id"] == "action_0001"
    assert action["action_status"] == "unspecified"
    assert action["action_type"] == action["evidence"] == []
    for field in ("action", "action_location", "action_recipient", "action_cost", "action_benefit"):
        assert action[field].startswith("TODO:")
    issue = reference["plan_issues"]["issues"][0]
    assert issue["issue_id"] == "issue_0001" and issue["issue_origin"] == "expert"
    assert issue["issue_status"] == "open" and issue["issue_description"].startswith("TODO:")
    assert all(issue[field] is None for field in ("related_action_id", "issue_type", "resolved_by", "resolution"))
    assert validate_expert_reference_structure(reference) == []
    after = _file_contents(project)
    assert after.pop(path).decode("utf-8").endswith("\n")
    assert after == before
    assert reviewers == ["Reviewer A", "researcher_02"]


def test_creation_does_not_lock_study_set_as_saved_model_work(project: Path) -> None:
    expert_files.create_expert_reference(project, "plan_0001", prepared_by=["reviewer"])

    entry, changed = documents.update_document_metadata(
        project, "plan_0001", study_set="expansion"
    )

    assert changed
    assert entry["study_set"] == "expansion"
    assert not (project / "runs").exists()


def test_copies_current_registered_collection_details(project: Path) -> None:
    documents.update_document_metadata(
        project, "plan_0001", plan_title="Corrected title",
        source_url="https://example.org/corrected.pdf", date_accessed="2026-11-20",
    )

    expert_files.create_expert_reference(project, "plan_0001", prepared_by=["reviewer"])

    metadata = json.loads(_reference_path(project).read_text())["plan_data"]["metadata"]
    assert metadata["plan_title"] == "Corrected title"
    assert metadata["source_url"] == "https://example.org/corrected.pdf"
    assert metadata["date_accessed"] == "2026-11-20"


@pytest.mark.parametrize("reviewers", [[], [""], [" \n"], [None], "reviewer", None])
def test_invalid_expert_identity_writes_nothing(project: Path, reviewers: object) -> None:
    before = _file_contents(project)

    with pytest.raises(ValueError, match="Expert reference structure validation"):
        expert_files.create_expert_reference(project, "plan_0001", prepared_by=reviewers)

    assert _file_contents(project) == before
    assert not (project / "data/expert_references").exists()


def test_unknown_plan_writes_nothing(project: Path) -> None:
    before = _file_contents(project)

    with pytest.raises(ValueError, match="registered plan ID"):
        expert_files.create_expert_reference(project, "plan_9999", prepared_by=["reviewer"])

    assert _file_contents(project) == before


@pytest.mark.parametrize("damage", ["registry", "pdf_changed", "pdf_missing"])
def test_damaged_collection_is_rejected_without_writes(project: Path, damage: str) -> None:
    if damage == "registry":
        (project / "data/registry/plans.json").write_text("invalid JSON")
    elif damage == "pdf_changed":
        (project / "data/raw/plan_0001.pdf").write_bytes(b"changed source")
    else:
        (project / "data/raw/plan_0001.pdf").unlink()
    before = _file_contents(project)

    with pytest.raises((OSError, ValueError)):
        expert_files.create_expert_reference(project, "plan_0001", prepared_by=["reviewer"])

    assert _file_contents(project) == before
    assert not (project / "data/expert_references").exists()


@pytest.mark.parametrize("occupied", ["expert_edits", "invalid_json", "directory", "dangling_link"])
def test_existing_destination_is_never_replaced(project: Path, occupied: str) -> None:
    path = _reference_path(project)
    path.parent.mkdir(parents=True)
    if occupied == "expert_edits":
        path.write_text('{"expert_work": "preserve this"}', encoding="utf-8")
    elif occupied == "invalid_json":
        path.write_bytes(b"unfinished expert edits {")
    elif occupied == "directory":
        path.mkdir()
        (path / "notes.txt").write_text("preserve these notes")
    else:
        path.symlink_to(path.parent / "missing.json")
    before = _file_contents(project)

    with pytest.raises(FileExistsError):
        expert_files.create_expert_reference(project, "plan_0001", prepared_by=["reviewer"])

    assert _file_contents(project) == before
    if occupied == "dangling_link":
        assert path.is_symlink()
        assert not path.exists()


@pytest.mark.parametrize("outside", [False, True])
def test_reference_folder_cannot_redirect_to_another_location(
    project: Path, tmp_path: Path, outside: bool,
) -> None:
    target = tmp_path / "outside references" if outside else project / "other references"
    target.mkdir()
    (project / "data/expert_references").symlink_to(target, target_is_directory=True)

    with pytest.raises(ValueError):
        expert_files.create_expert_reference(project, "plan_0001", prepared_by=["reviewer"])

    assert list(target.iterdir()) == []


def test_publication_failure_leaves_no_partial_form_or_temporary_file(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = _file_contents(project)

    def fail_publication(source: Path, destination: Path) -> None:
        raise OSError("fictional publication failure")

    monkeypatch.setattr(storage.os, "link", fail_publication)
    with pytest.raises(OSError, match="publication failure"):
        expert_files.create_expert_reference(project, "plan_0001", prepared_by=["reviewer"])

    assert _file_contents(project) == before
    assert list(_reference_path(project).parent.iterdir()) == []


def test_concurrent_file_is_preserved_at_publication(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    def occupy_destination(source: Path, destination: Path) -> None:
        destination.write_bytes(b"expert work created during publication")
        raise FileExistsError("destination became occupied")

    monkeypatch.setattr(storage.os, "link", occupy_destination)
    with pytest.raises(FileExistsError):
        expert_files.create_expert_reference(project, "plan_0001", prepared_by=["reviewer"])

    assert _reference_path(project).read_bytes() == b"expert work created during publication"
    assert list(_reference_path(project).parent.iterdir()) == [_reference_path(project)]


def test_cli_creates_form_with_repeated_expert_flag(
    project: Path, capsys: pytest.CaptureFixture,
) -> None:
    assert cli.main([
        "create_expert_reference", "plan_0001", "--prepared-by", "Reviewer A",
        "--prepared-by", "Reviewer B", "--project-root", str(project),
    ]) == 0

    output = capsys.readouterr()
    assert "data/expert_references/plan_0001/expert_reference.json" in output.out
    assert "guided blank action action_0001 and expert issue issue_0001" in output.out
    assert "TODO:" in output.out
    assert "before viewing model outputs" in output.out
    assert output.err == ""
    reference = json.loads(_reference_path(project).read_text())
    assert reference["prepared_by"] == ["Reviewer A", "Reviewer B"]


def test_cli_uses_current_directory_by_default(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(project)
    assert cli.main(["create_expert_reference", "plan_0001", "--prepared-by", "reviewer"]) == 0
    assert _reference_path(project).is_file()


def test_cli_requires_expert_identity(project: Path) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["create_expert_reference", "plan_0001", "--project-root", str(project)])
    assert error.value.code == 2
    assert not _reference_path(project).exists()


@pytest.mark.parametrize("plan_id,reviewer", [("plan_9999", "reviewer"), ("plan_0001", " ")])
def test_cli_reports_expected_input_errors(
    project: Path, capsys: pytest.CaptureFixture, plan_id: str, reviewer: str,
) -> None:
    assert cli.main([
        "create_expert_reference", plan_id, "--prepared-by", reviewer,
        "--project-root", str(project),
    ]) == 1
    output = capsys.readouterr()
    assert "Error:" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""
    assert not _reference_path(project).exists()


def test_cli_reports_collision_and_preserves_completed_work(
    project: Path, capsys: pytest.CaptureFixture,
) -> None:
    arguments = [
        "create_expert_reference", "plan_0001", "--prepared-by", "reviewer",
        "--project-root", str(project),
    ]
    assert cli.main(arguments) == 0
    capsys.readouterr()
    _reference_path(project).write_text("expert edits", encoding="utf-8")

    assert cli.main(arguments) == 1
    assert "already exists" in capsys.readouterr().err
    assert _reference_path(project).read_text() == "expert edits"
