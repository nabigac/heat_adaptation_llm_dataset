"""Keep archived labels readable while new study work uses comparison.

All archives here are fictional temporary files. Rebinding an old verifier's
parent snapshot models its original saved bytes; production history is never
rewritten or relabeled by these readers.
"""

import asyncio
import hashlib
import json

import pytest

import agents
import assessment_validation
import assessments
import cli
import collaboration_runner
import documents
import legacy_records
import metric_summaries
import metrics
import storage
import validation
from test_agent_loop import PLAN_ID, SOURCE, project
from test_assessment_creation import create, metadata, snapshot, study, template_directory
from test_assessment_validation import finish
from test_collaboration_contracts import configured
from test_saved_collaboration import ready
from test_saved_extractor import facts
from test_run_storage import running


def archived_labels(root):
    """Represent an intact earlier-format project before invoking new readers."""
    path = root / "data/registry/plans.json"
    registry = json.loads(path.read_text())
    registry["plans"][0]["study_set"] = legacy_records.LEGACY_SAMPLE
    path.write_text(json.dumps(registry))
    for path in (root / f"runs/{PLAN_ID}").glob("*/output.json"):
        record = json.loads(path.read_text())
        record["purpose"] = legacy_records.LEGACY_PURPOSE
        path.write_text(json.dumps(record))
    for path in (root / f"runs/{PLAN_ID}").glob("run_verify_*/artifacts/verifier_input.json"):
        saved = json.loads(path.read_text())
        baseline = root / f"runs/{PLAN_ID}/{saved['input_run_id']}/output.json"
        saved["input_run"] = json.loads(baseline.read_text())
        saved["input_run_fingerprint"] = hashlib.sha256(baseline.read_bytes()).hexdigest()
        path.write_text(json.dumps(saved))


def test_historical_run_loading_preserves_raw_records_and_verifier_snapshots(study):
    archived_labels(study)
    before = snapshot(study)
    assert documents.list_documents(study)[0]["study_set"] == "comparison"
    assert storage.load_registry(study)["plans"][0]["study_set"] == legacy_records.LEGACY_SAMPLE
    for path in (study / f"runs/{PLAN_ID}").glob("*/output.json"):
        record = storage.load_run_record(study, path.relative_to(study).as_posix())
        assert record == json.loads(path.read_text())
        assert record["purpose"] == legacy_records.LEGACY_PURPOSE
    assert snapshot(study) == before


def test_new_assessment_can_select_archived_outputs_without_relabeling_them(study):
    archived_labels(study)
    before = snapshot(study)
    path = create(study)
    data = metadata(study, path)
    assert data["schema_version"] == 2 and "purpose" not in data
    for run in data["runs"].values():
        assert run["record_sha256"] == hashlib.sha256(before[run["record_path"]]).hexdigest()
    assert assessment_validation.validate_assessment(study, PLAN_ID, "assessment_0001").valid
    assert all((study / name).read_bytes() == raw for name, raw in before.items())


def test_current_assessments_metrics_and_reports_can_use_archived_runs(study):
    archived_labels(study)
    path = create(study)
    meta = metadata(study, path)
    finish(study, path)
    before = snapshot(study)
    folder = metrics.calculate_metrics(study, PLAN_ID, "assessment_0001", require_complete=True)
    result_path = study / folder / "results.json"
    result = json.loads(result_path.read_text())
    assert result["purpose"] == "comparison"
    assert result["assessment"]["metadata"] == meta
    archived = snapshot(study / folder)
    assert metric_summaries.load_metric_snapshot(study, folder).result == result
    report_path = metric_summaries.summarize_metrics(study, [folder])
    report = json.loads((study / report_path / "summary.json").read_text())
    assert report["purpose"] == "comparison"
    # Only real run/registry history uses label adapters. Generated study
    # artifacts must satisfy their current schemas directly.
    assert validation.validate_assessment_metadata({**meta, "schema_version": 1,
                                                   "purpose": legacy_records.LEGACY_PURPOSE})
    assert validation.validate_metrics_results({**result, "purpose": legacy_records.LEGACY_PURPOSE})
    assert validation.validate_metrics_summary({**report, "purpose": legacy_records.LEGACY_PURPOSE})
    assert snapshot(study / folder) == archived
    assert all((study / name).read_bytes() == raw for name, raw in before.items())


@pytest.mark.parametrize("command,flags", [
    ("run_extract_mode", [PLAN_ID, "--source-path", SOURCE, "--profile", "fixture"]),
    ("run_verify_mode", [PLAN_ID, "--profile", "fixture"]),
    ("run_collaboration_mode", [PLAN_ID, "--source-path", SOURCE]),
    ("create_assessment", [PLAN_ID]),
])
@pytest.mark.parametrize("retired", [legacy_records.LEGACY_PURPOSE, legacy_records.LEGACY_EXTERNAL_PURPOSE])
def test_active_cli_rejects_retired_choices_before_creating_files(tmp_path, command, flags, retired):
    with pytest.raises(SystemExit) as error:
        cli.main([command, *flags, "--purpose", retired, "--project-root", str(tmp_path)])
    assert error.value.code == 2 and not list(tmp_path.iterdir())


@pytest.mark.parametrize("command", ["run_extract_mode", "run_verify_mode", "run_collaboration_mode", "create_assessment"])
def test_active_help_exposes_supported_run_and_assessment_options(command, capsys):
    with pytest.raises(SystemExit) as error:
        cli.main([command, "--help"])
    assert error.value.code == 0
    help_text = capsys.readouterr().out
    assert legacy_records.LEGACY_PURPOSE not in help_text
    assert legacy_records.LEGACY_EXTERNAL_PURPOSE not in help_text
    if command == "create_assessment":
        assert "--purpose" not in help_text
    else:
        assert "{comparison,dataset_building}" in help_text


@pytest.mark.parametrize("entrypoint", ["extractor", "verifier", "collaboration", "assessment"])
def test_public_entrypoints_reject_retired_purpose_before_work(tmp_path, entrypoint):
    expected_error = TypeError if entrypoint == "assessment" else ValueError
    message = "purpose" if entrypoint == "assessment" else "comparison"
    with pytest.raises(expected_error, match=message):
        if entrypoint == "extractor":
            asyncio.run(agents.run_extractor(tmp_path, PLAN_ID, source_path=SOURCE,
                profile_name="fixture", purpose=legacy_records.LEGACY_PURPOSE))
        elif entrypoint == "verifier":
            asyncio.run(agents.run_verifier(tmp_path, PLAN_ID, profile_name="fixture", purpose=legacy_records.LEGACY_PURPOSE))
        elif entrypoint == "collaboration":
            asyncio.run(collaboration_runner.run_collaboration(tmp_path, PLAN_ID, source_path=SOURCE,
                purpose=legacy_records.LEGACY_PURPOSE))
        else:
            assessments.create_assessment(tmp_path, PLAN_ID,
                purpose=legacy_records.LEGACY_PURPOSE)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("retired", [legacy_records.LEGACY_PURPOSE, legacy_records.LEGACY_EXTERNAL_PURPOSE])
def test_new_run_writer_rejects_retired_labels_before_allocating_a_folder(tmp_path, run_record, retired):
    record = running(run_record)
    record["purpose"] = retired
    with pytest.raises(ValueError, match="purpose"):
        storage.create_run_record(tmp_path, record)
    assert not list(tmp_path.iterdir())


def test_new_registration_cannot_create_a_retired_sample_label(tmp_path):
    with pytest.raises(ValueError, match="comparison membership"):
        documents.register_document(tmp_path, tmp_path / "unused.pdf", plan_title="Fictional plan",
            source_url="https://example.org/plan.pdf", date_accessed="2026-11-24",
            study_set=legacy_records.LEGACY_SAMPLE)
    assert not list(tmp_path.iterdir())
