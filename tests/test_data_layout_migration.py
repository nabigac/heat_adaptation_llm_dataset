"""Exercise layout changes on fictional saved E/V/C evidence, never real data."""

import hashlib
import json
from pathlib import Path

import pytest

import agents
import assessments
import cli
import expert_files
import metric_summaries
import metrics
import storage
import validation
from legacy_records import canonical_data_path
from test_agent_loop import PLAN_ID, project
from test_assessment_creation import snapshot, study, template_directory
from test_assessment_validation import finish
from test_collaboration_contracts import configured
from test_saved_collaboration import ready
from test_saved_extractor import facts


OLD_DIRECTORIES = (("data/raw", "data/source_pdfs"), ("data/processed", "data/prepared_plans"),
                   ("data/expert_references", "data/comparison/expert_references"))


@pytest.fixture
def historical_study(study):
    """Construct valid earlier-layout evidence before asking migration to read it.

    These fixture edits represent how records were originally saved. Hashes and
    V's exact E snapshot are bound before the migration baseline is captured.
    Production migration never performs these rewrites.
    """
    for file in study.rglob("*.json"):
        text = file.read_text()
        for old, new in OLD_DIRECTORIES:
            text = text.replace(new, old)
        file.write_text(text)
    for old, new in OLD_DIRECTORIES:
        (study / new).rename(study / old)
    source_path = f"data/processed/{PLAN_ID}/preparation_02/preparation.json"
    _, preparation, pages = storage.load_plan_preparation(study, PLAN_ID, source_path)
    fingerprint = storage.preparation_text_fingerprint(preparation, pages)
    for folder in (study / f"runs/{PLAN_ID}").iterdir():
        file = folder / "output.json"
        record = json.loads(file.read_text())
        if record["stage"] == "collaboration":
            record["source_fingerprint"] = fingerprint
            file.write_text(json.dumps(record))
            input_path = folder / "artifacts/collaboration_input.json"
            data = json.loads(input_path.read_text())
            data["packet"]["source_fingerprint"] = fingerprint
            data["packet"]["source_message"] = {"role": "user", "content": agents._format_plan_source(preparation, pages)}
            input_path.write_text(json.dumps(data))
            diagnostic = folder / "artifacts/quotation_page_report.json"
            data = json.loads(diagnostic.read_text())
            data["source_fingerprint"] = fingerprint
            diagnostic.write_text(json.dumps(data))
        else:
            input_path = folder / f"artifacts/{record['stage']}_input.json"
            data = json.loads(input_path.read_text())
            data["source_fingerprint"] = fingerprint
            if record["stage"] == "verifier":
                baseline = folder.parent / record["input_run_id"] / "output.json"
                data.update(input_run=json.loads(baseline.read_text()),
                            input_run_fingerprint=hashlib.sha256(baseline.read_bytes()).hexdigest())
            input_path.write_text(json.dumps(data))
    reference = study / f"data/expert_references/{PLAN_ID}/expert_reference.json"
    freeze = reference.with_name("reference_freeze.json")
    data = json.loads(freeze.read_text())
    data["reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
    freeze.write_text(json.dumps(data))
    # Prove this is readable prior history, not broken input rescued by a move.
    for file in (study / "runs").glob("*/*/output.json"):
        storage.load_run_record(study, file.relative_to(study).as_posix())
    return study


def directory_names(root):
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))


def test_preview_changes_no_files_or_directories(historical_study, monkeypatch):
    root = historical_study
    before, names = snapshot(root), directory_names(root)
    monkeypatch.setattr(agents, "require_huggingface_token", lambda: pytest.fail("Migration must not authenticate."))
    result = storage.migrate_data_layout(root, dry_run=True)
    assert result["dry_run"] and result["registry_updated"] and result["validated_runs"] == 3
    assert len(result["moves"]) == 3
    assert snapshot(root) == before and directory_names(root) == names


def test_migration_preserves_bytes_fingerprints_frozen_reference_and_saved_parents(historical_study):
    root = historical_study
    before = snapshot(root)
    records = {path: storage.load_run_record(root, path) for path in before if path.endswith("/output.json")}
    result = storage.migrate_data_layout(root)
    assert result["validated_runs"] == 3 and result["registry_updated"]
    after = snapshot(root)
    for path, raw in before.items():
        if path != "data/registry/plans.json":
            assert after[canonical_data_path(path)] == raw
    for old, new in OLD_DIRECTORIES:
        assert not (root / old).exists() and (root / new).is_dir()
    for path, record in records.items():
        assert storage.load_run_record(root, path) == record
    registry = storage.load_registry(root)
    assert registry["plans"][0]["pdf_path"].startswith("data/source_pdfs/")
    assert registry["plans"][0]["prepared_source_path"].startswith("data/prepared_plans/")
    assert expert_files.validate_expert_reference(root, PLAN_ID)
    with pytest.raises(ValueError, match="frozen"):
        expert_files.edit_expert_reference(root, PLAN_ID, operation="add_action")
    again = storage.migrate_data_layout(root)
    assert not again["moves"] and not again["registry_updated"] and snapshot(root) == after


@pytest.mark.parametrize("kind", ["directory", "file", "symlink"])
def test_every_destination_is_checked_before_any_move(historical_study, kind):
    root = historical_study
    target = root / "data/prepared_plans"
    if kind == "directory": target.mkdir()
    elif kind == "file": target.write_bytes(b"existing work")
    else: target.symlink_to(root / "missing")
    before = snapshot(root)
    with pytest.raises((ValueError, OSError)):
        storage.migrate_data_layout(root)
    assert snapshot(root) == before and (root / "data/raw").is_dir()


def test_symlink_inside_source_is_rejected_before_any_move(historical_study):
    root = historical_study
    (root / "data/processed/redirect").symlink_to(root / "data/raw", target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        storage.migrate_data_layout(root)
    assert (root / "data/raw").is_dir() and not (root / "data/source_pdfs").exists()


def test_damaged_run_blocks_migration_without_repair(historical_study):
    root = historical_study
    output = root / f"runs/{PLAN_ID}/run_extract_0001/output.json"
    data = json.loads(output.read_text())
    data["plan_data"]["actions"][0]["action"] = "Different accepted answer."
    output.write_text(json.dumps(data))
    before = snapshot(root)
    with pytest.raises(ValueError, match="differs"):
        storage.migrate_data_layout(root)
    assert snapshot(root) == before


def test_interrupted_move_preserves_readable_history_and_can_resume(historical_study, monkeypatch):
    root = historical_study
    before = snapshot(root)
    rename = Path.rename
    def interrupted(path, target):
        if path == root / "data/processed":
            raise OSError("Controlled interrupted directory move.")
        return rename(path, target)
    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", interrupted)
        with pytest.raises(OSError, match="interrupted"):
            storage.migrate_data_layout(root)
    assert (root / "data/source_pdfs").is_dir() and (root / "data/processed").is_dir()
    for file in (root / "runs").glob("*/*/output.json"):
        storage.load_run_record(root, file.relative_to(root).as_posix())
    storage.migrate_data_layout(root)
    for path, raw in before.items():
        if path != "data/registry/plans.json":
            assert (root / canonical_data_path(path)).read_bytes() == raw


def test_old_paths_never_hide_missing_or_conflicting_data(historical_study):
    root = historical_study
    storage.migrate_data_layout(root)
    path = f"data/processed/{PLAN_ID}/preparation_02/preparation.json"
    storage.resolve_project_path(root, path).unlink()
    with pytest.raises(FileNotFoundError):
        storage.load_preparation(root, path)
    (root / "data/processed").mkdir()
    with pytest.raises(ValueError, match="Both old and new"):
        storage.resolve_project_path(root, path)


def test_new_preparations_require_migration_first(historical_study):
    before = snapshot(historical_study)
    with pytest.raises(ValueError, match="migrate_data_layout"):
        storage.next_preparation_directory(historical_study, PLAN_ID)
    assert snapshot(historical_study) == before


def test_moved_history_supports_new_assessments_metrics_and_reports(historical_study):
    root = historical_study
    storage.migrate_data_layout(root)
    assert storage.next_preparation_directory(root, PLAN_ID).endswith("preparation_03")
    path = assessments.create_assessment(root, PLAN_ID)
    assert path.startswith("data/comparison/assessments/")
    finish(root, path)
    folder = metrics.calculate_metrics(root, PLAN_ID, "assessment_0001", require_complete=True)
    report = metric_summaries.summarize_metrics(root, [folder])
    assert report.startswith("data/comparison/reports/")
    assert metric_summaries.load_metric_snapshot(root, folder)


def test_assessment_matches_old_and_current_spellings_of_the_same_preparation(historical_study):
    root = historical_study
    storage.migrate_data_layout(root)
    folder = root / f"runs/{PLAN_ID}/run_collaboration_0001"
    output = folder / "output.json"
    data = json.loads(output.read_text())
    data["source_path"] = canonical_data_path(data["source_path"])
    output.write_text(json.dumps(data))
    packet = folder / "artifacts/collaboration_input.json"
    saved = json.loads(packet.read_text())
    saved["packet"]["source_path"] = data["source_path"]
    packet.write_text(json.dumps(saved))
    diagnostic = folder / "artifacts/quotation_page_report.json"
    saved = json.loads(diagnostic.read_text())
    saved["source_path"] = data["source_path"]
    diagnostic.write_text(json.dumps(saved))
    # Represent a later C execution using today's spelling. Each individual
    # run still has an exact matching startup packet and unchanged source hash.
    storage.load_run_record(root, output.relative_to(root).as_posix())
    selected = assessments.select_assessment_runs(root, PLAN_ID)
    assert canonical_data_path(selected["E"]["record"]["source_path"]) == selected["C"]["record"]["source_path"]


def test_e_and_v_links_recognize_migrated_source_identity(historical_study):
    root = historical_study
    storage.migrate_data_layout(root)
    e = storage.load_run_record(root, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    v = storage.load_run_record(root, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    v["source_path"] = canonical_data_path(v["source_path"])
    assert validation.validate_run_links(v, input_run=e) == []


def test_cli_migrates_and_preserves_original_records(historical_study, capsys):
    root = historical_study
    before = snapshot(root)
    assert cli.main(["migrate_data_layout", "--dry-run", "--project-root", str(root)]) == 0
    assert "Migration preview" in capsys.readouterr().out and snapshot(root) == before
    assert cli.main(["migrate_data_layout", "--project-root", str(root)]) == 0
    assert "Historical runs validated: 3" in capsys.readouterr().out


def test_new_empty_project_has_clear_directories_without_fabricated_records(tmp_path):
    result = storage.migrate_data_layout(tmp_path)
    assert not result["moves"] and result["validated_runs"] == 0
    assert (tmp_path / "data/dataset_building/review_drafts").is_dir()
    assert (tmp_path / "data/comparison/assessments").is_dir()
    assert not snapshot(tmp_path)
