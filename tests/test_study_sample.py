"""Exercise the comparison workflow and exact saved run selections.

Saved runners use controlled HTTP. The ten-plan case uses distinct fictional
PDFs and saved outputs to check assessment/reporting without paid requests or
scientific judgments. Existing comparison files remain historical inputs.
"""

import asyncio
from copy import deepcopy
import json

import pytest

import agents
import assessment_validation
import assessments
import cli
import documents
import metrics
import metric_summaries
import storage
import validation
from test_agent_loop import PLAN_ID, SOURCE, project, scripted, message, answer
from test_assessment_creation import clone_c, create, metadata, publish, snapshot, study, template_directory
from test_assessment_validation import finish
from test_collaboration_contracts import configured
from test_extract_cli import connected_cli
from test_metric_summaries import clone_plan
from test_run_storage import running
from test_saved_collaboration import ready, run as run_c
from test_saved_extractor import facts
from test_verifier import baseline, PROFILE as VERIFIER_PROFILE, prepare_replies


def comparison_outputs(root):
    """Build later fixture outputs, preserving the earlier comparison records."""
    e = storage.load_run_record(root, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    v = storage.load_run_record(root, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    e["purpose"] = v["purpose"] = "comparison"
    publish(root, e, "extractor", 2)
    publish(root, v, "verifier", 2, input_run_id="run_extract_0002")
    c = clone_c(root, 2)
    c["purpose"] = "comparison"
    path = root / f"runs/{PLAN_ID}/run_collaboration_0002/output.json"
    path.write_text(json.dumps(c))
    storage.load_run_record(root, path.relative_to(root).as_posix())
    return {"extractor_run_id": "run_extract_0002", "verifier_run_id": "run_verify_0002",
            "collaboration_run_id": "run_collaboration_0002"}


def test_saved_e_and_v_default_to_comparison_and_retain_exact_history(
    project, baseline, scripted, facts, run_record,
):
    before = snapshot(project)
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    e = asyncio.run(agents.run_extractor(project, PLAN_ID, source_path=SOURCE,
        profile_name="fictional_extractor", _transport=scripted.transport))
    assert e.record["status"] == "succeeded", e.record["error"]
    prepare_replies(scripted, {key: deepcopy(e.record[key]) for key in ("plan_data", "plan_issues")})
    v = asyncio.run(agents.run_verifier(project, PLAN_ID, profile_name=VERIFIER_PROFILE,
        input_run_id=e.record["run_id"], _transport=scripted.transport))
    assert v.record["status"] == "succeeded", v.record["error"]
    assert v.record["input_run_id"] == e.record["run_id"] != baseline.record["run_id"]
    assert storage.load_run_record(project, v.record_path)["purpose"] == "comparison"
    assert all((project / name).read_bytes() == raw for name, raw in before.items())


@pytest.mark.parametrize("explicit_purpose", [False, True])
def test_saved_c_defaults_to_comparison_and_accepts_explicit_comparison(ready, explicit_purpose):
    documents.update_document_metadata(ready.root, PLAN_ID, study_set="comparison")
    saved = run_c(ready, **({"purpose": "comparison"} if explicit_purpose else {}))
    assert saved.record["status"] == "succeeded", saved.record["error"]
    assert storage.load_run_record(ready.root, saved.record_path)["purpose"] == "comparison"


def test_comparison_cli_feedback_is_available_on_a_comparison_sample_plan(
    project, scripted, facts, run_record, connected_cli, capsys,
):
    documents.update_document_metadata(project, PLAN_ID, study_set="comparison")
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    assert cli.main(["run_extract_mode", PLAN_ID, "--project-root", str(project),
                     "--source-path", SOURCE, "--profile", "fictional_extractor"]) == 0
    output = capsys.readouterr()
    assert "Status: succeeded" in output.out and "Model requests: 2" in output.out
    assert "withheld" not in output.out + output.err
    assert storage.load_run_record(project, f"runs/{PLAN_ID}/run_extract_0001/output.json")["purpose"] == "comparison"


def test_comparison_retry_preserves_its_failed_attempt(project, run_record):
    failed = running(run_record)
    path = storage.create_run_record(project, failed)
    failed.update(status="failed", ended_at=run_record["ended_at"], elapsed_seconds=0.5, error="Fictional failure.")
    storage.save_run_record(project, failed)
    before = (project / path).read_bytes()
    retry = running(run_record, "run_extract_0002")
    retry.update(retry_of_run_id=failed["run_id"])
    retry_path = storage.create_run_record(project, retry)
    assert storage.load_run_record(project, retry_path)["purpose"] == "comparison"
    assert (project / path).read_bytes() == before


def test_unchanged_sample_membership_preserves_existing_assessments(study):
    path = create(study)
    before = snapshot(study)
    entry, changed = documents.update_document_metadata(study, PLAN_ID, study_set="comparison")
    assert not changed and entry["study_set"] == "comparison"
    for run in (study / f"runs/{PLAN_ID}").glob("*/output.json"):
        assert storage.load_run_record(study, run.relative_to(study).as_posix())["purpose"] == "comparison"
    assert assessment_validation.validate_assessment(study, PLAN_ID, path.rsplit("/", 1)[-1]).valid
    after = snapshot(study)
    assert all(after[name] == raw for name, raw in before.items() if name != "data/registry/plans.json")


@pytest.mark.parametrize("missing", ["extractor_run_id", "verifier_run_id", "collaboration_run_id"])
def test_assessment_defaults_resolve_omitted_run_ids(study, missing):
    selected = {"extractor_run_id": "run_extract_0001", "verifier_run_id": "run_verify_0001",
                "collaboration_run_id": "run_collaboration_0001"}
    del selected[missing]
    path = create(study, **selected)
    data = metadata(study, path)
    assert data["schema_version"] == 2 and "purpose" not in data
    assert data["runs"]["E"]["run_id"] == "run_extract_0001"
    assert data["runs"]["E+V"]["run_id"] == "run_verify_0001"
    assert data["runs"]["C"]["run_id"] == "run_collaboration_0001"


def test_explicit_manual_selections_pin_earlier_runs_when_newer_runs_exist(study):
    comparison_outputs(study)
    path = create(study, extractor_run_id="run_extract_0001", verifier_run_id="run_verify_0001",
                  collaboration_run_id="run_collaboration_0001")
    data = metadata(study, path)
    assert all(run["selected_via"] == "explicit" for run in data["runs"].values())
    assert [run["run_id"] for run in data["runs"].values()] == [
        "run_extract_0001", "run_verify_0001", "run_collaboration_0001"]


def test_saved_automatic_selection_remains_fixed_when_newer_runs_exist(study):
    path = create(study)
    before = snapshot(study / path)
    comparison_outputs(study)
    report = assessment_validation.validate_assessment(study, PLAN_ID, "assessment_0001")
    assert report.valid and report.data.metadata["runs"]["E"]["run_id"] == "run_extract_0001"
    assert snapshot(study / path) == before


def test_cli_assessment_omits_purpose_and_metrics_preserve_selected_inputs(study, capsys):
    selected = comparison_outputs(study)
    args = ["create_assessment", PLAN_ID, "--project-root", str(study)]
    for key, identifier in selected.items():
        args.extend(["--" + key.replace("_", "-"), identifier])
    assert cli.main(args) == 0
    output = capsys.readouterr().out
    assert "Creation makes no model calls and calculates no metrics." in output
    assert "Assessment purpose:" not in output
    path = f"data/comparison/assessments/{PLAN_ID}/assessment_0001"
    finish(study, path)
    folder = metrics.calculate_metrics(study, PLAN_ID, "assessment_0001", require_complete=True)
    result = json.loads((study / folder / "results.json").read_text())
    assert result["purpose"] == "comparison"
    assert result["assessment"]["metadata"]["schema_version"] == 2
    assert "purpose" not in result["assessment"]["metadata"]
    assert not validation.validate_metrics_results(result)
    result["purpose"] = "outside_study"
    assert validation.validate_metrics_results(result)


def test_expansion_plans_cannot_supply_study_runs_or_assessments(study):
    registry = storage.load_registry(study)
    registry["plans"][0]["study_set"] = "expansion"
    storage.save_registry(study, registry)
    selected = {"extractor_run_id": "run_extract_0001", "verifier_run_id": "run_verify_0001",
                "collaboration_run_id": "run_collaboration_0001"}
    with pytest.raises(ValueError, match="study sample"):
        create(study, **selected)
    from collaboration_contracts import build_collaboration_input
    with pytest.raises(ValueError, match="study sample"):
        build_collaboration_input(study, PLAN_ID, source_path=SOURCE)


def test_ten_plan_comparison_report_preserves_comparison_history(study, monkeypatch):
    selected = comparison_outputs(study)
    documents.update_document_metadata(study, PLAN_ID, study_set="comparison")
    plan_ids = [PLAN_ID, *(clone_plan(study, f"plan_{number:04d}") for number in range(100, 109))]
    assert len({entry["document_sha256"] for entry in storage.load_registry(study)["plans"]}) == 10
    before = snapshot(study)
    result_paths = []
    monkeypatch.delenv("HF_TOKEN", raising=False)
    for index, plan_id in enumerate(plan_ids):
        folder = assessments.create_assessment(study, plan_id,
            notes="Initial workflow refinement." if index < 2 else "Additional study plan.",
            **selected)
        finish(study, folder)
        result_paths.append(metrics.calculate_metrics(study, plan_id, "assessment_0001", require_complete=True))
    exported = metric_summaries.summarize_metrics(study, result_paths)
    report = json.loads((study / exported / "summary.json").read_text())
    assert report["purpose"] == "comparison" and len(report["selections"]) == 10
    assert len(report["aggregates"]) == 44
    assert all(item["scope"] != "failure_reporting" and item["metric"] != "failed_executions"
               for item in report["aggregates"])
    for configuration in ("E", "E+V", "C"):
        measure = next(row for row in report["aggregates"] if row["scope"] == "configuration"
                       and row["configuration"] == configuration and row["metric"] == "action_score_percentage")
        assert measure["value"] == 50 and measure["contributing_plan_count"] == 10
        assert not measure["excluded_plans"]
    assert all((study / name).read_bytes() == raw for name, raw in before.items())
