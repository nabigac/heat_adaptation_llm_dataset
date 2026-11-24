"""Check cross-plan reporting with fictional measures and saved study packages.

Unit cases isolate contributing-plan arithmetic. Saved-package cases additionally
exercise strict source/run/archive checks, including two distinct fictional PDFs.
No test establishes scientific quality or sends paid model requests.
"""

from copy import deepcopy
import csv
import hashlib
import json
import shutil

import pytest

import assessment_validation
import assessments
import cli
import metric_summaries as summaries
import metrics
import storage
import validation
from test_agent_loop import PLAN_ID, SOURCE, project
from test_assessment_creation import create, snapshot, study, template_directory
from test_assessment_validation import change_row, finish
from test_collaboration_contracts import configured
from test_metrics import report as calculation_report
from test_saved_collaboration import ready
from test_saved_extractor import facts


@pytest.fixture
def results(calculation_report):
    result = {"plan_id": "plan_A", "purpose": "development", "method_version": 1,
              **metrics.summarize_assessment(calculation_report)}
    second = deepcopy(result)
    second["plan_id"] = "plan_B"
    for source, scores, count in ((result, (70, 80, 85), 10), (second, (50, 70, None), 100)):
        for role, score in zip(metrics.CONFIGURATIONS, scores):
            source["configurations"][role]["reference_action_count"] = count
            source["configurations"][role]["metrics"]["action_score_percentage"] = (
                metrics._percentage(score * count / 100, count) if score is not None
                else metrics._pending("percent", "Fictional pending judgment.", denominator=count))
        source["paired_changes"] = {
            "E+V_minus_E": metrics._contrast(source["configurations"], "E", "E+V"),
            "C_minus_E+V": metrics._contrast(source["configurations"], "E+V", "C"),
        }
    return [result, second]


def aggregate(results, scope="configuration", configuration="E", metric="action_score_percentage"):
    return next(row for row in summaries.aggregate_results(results)
                if (row["scope"], row["configuration"], row["metric"]) == (scope, configuration, metric))


def test_percentages_give_each_plan_equal_weight_and_retain_missing_contributors(results):
    current = aggregate(results)
    assert current["value"] == 60 and current["aggregation"] == "mean"
    assert current["contributing_plan_count"] == 2 and current["contributing_plans"] == ["plan_A", "plan_B"]
    assert current["numerator"] is None and current["denominator"] is None
    current = aggregate(results, configuration="C")
    assert current["value"] == 85 and current["contributing_plans"] == ["plan_A"]
    assert current["excluded_plans"] == [{"plan_id": "plan_B", "status": "pending", "reason": "Fictional pending judgment."}]


def test_paired_changes_use_same_eligible_plans_on_both_sides(results):
    first = aggregate(results, "paired_change", "E+V_minus_E")
    second = aggregate(results, "paired_change", "C_minus_E+V")
    assert first["value"] == 15 and first["contributing_plan_count"] == 2
    assert second["value"] == 5 and second["contributing_plans"] == ["plan_A"]
    assert second["unit"] == "percentage_points" and second["aggregation"] == "mean"
    # Available C evidence is independent of pending C reference scoring.
    assert aggregate(results, configuration="C", metric="adequate_evidence_percentage")["contributing_plan_count"] == 2


def test_counts_and_resources_are_totals_and_paired_resource_changes_are_means(results):
    unsupported = aggregate(results, metric="unsupported_action_count")
    assert unsupported["value"] == 4 and unsupported["denominator"] == 24 and unsupported["aggregation"] == "sum"
    assert aggregate(results, metric="total_output_activities")["value"] == 24
    assert aggregate(results, metric="open_issue_count")["value"] == 6
    assert aggregate(results, configuration="E+V", metric="runtime_seconds")["value"] == 28
    assert aggregate(results, configuration="C", metric="total_tokens")["value"] == 396
    assert aggregate(results, "paired_change", "E+V_minus_E", "runtime_seconds")["value"] == 4


@pytest.mark.parametrize("state", ["pending", "unavailable", "not_applicable"])
def test_no_available_plan_preserves_its_missing_state(results, state):
    for source in results:
        source["configurations"]["E"]["metrics"]["action_score_percentage"] = metrics._measure(
            None, "percent", status=state, reason="Fictional unavailable observation.")
    current = aggregate(results)
    assert current["value"] is None and current["status"] == state
    assert current["contributing_plan_count"] == 0 and len(current["excluded_plans"]) == 2


def test_explicit_zero_is_included_and_input_order_is_deterministic(results):
    results[0]["configurations"]["E"]["metrics"]["action_score_percentage"] = metrics._percentage(0, 10)
    assert aggregate(results)["value"] == 25
    assert summaries.aggregate_results(results) == summaries.aggregate_results(list(reversed(results)))


def test_v_resolution_counts_use_same_contributing_plans_for_both_counts(results):
    current = aggregate(results, "verifier_resolution", "E+V", "expert_confirmed_verifier_resolutions")
    assert current["numerator"] == current["value"] == 4 and current["denominator"] == 6
    results[1]["verifier_resolutions"] = metrics._pending("resolutions", "Confirmation pending.", denominator=3)
    current = aggregate(results, "verifier_resolution", "E+V", "expert_confirmed_verifier_resolutions")
    assert current["numerator"] == 2 and current["denominator"] == 3
    assert current["excluded_plans"][0]["plan_id"] == "plan_B"


def test_no_claims_contributes_known_zero_counts_without_a_zero_ratio(results):
    no_claims = metrics._measure(None, "resolutions", status="not_applicable", reason="No claims.", numerator=0, denominator=0)
    results[0]["verifier_resolutions"] = deepcopy(no_claims)
    current = aggregate(results, "verifier_resolution", "E+V", "expert_confirmed_verifier_resolutions")
    assert current["numerator"] == 2 and current["denominator"] == 3 and current["contributing_plan_count"] == 2
    results[1]["verifier_resolutions"] = deepcopy(no_claims)
    current = aggregate(results, "verifier_resolution", "E+V", "expert_confirmed_verifier_resolutions")
    assert current["value"] is None and current["numerator"] == current["denominator"] == 0
    assert current["status"] == "not_applicable" and current["contributing_plan_count"] == 2


def test_failures_remain_unavailable_and_overflow_does_not_become_infinity(results):
    current = aggregate(results, "failure_reporting", "E", "failed_executions")
    assert current["status"] == "unavailable" and current["value"] is None
    for source in results:
        source["configurations"]["E"]["metrics"]["runtime_seconds"] = metrics._measure(1e308, "seconds")
        source["paired_changes"]["E+V_minus_E"]["metrics"]["runtime_seconds"] = metrics._measure(1e308, "seconds")
    assert aggregate(results, metric="runtime_seconds")["status"] == "unavailable"
    assert aggregate(results, "paired_change", "E+V_minus_E", "runtime_seconds")["value"] == 1e308


@pytest.mark.parametrize("damage", ["empty", "duplicate", "purpose", "method", "unit"])
def test_incompatible_selections_are_rejected(results, damage):
    if damage == "empty": results.clear()
    elif damage == "duplicate": results[1]["plan_id"] = results[0]["plan_id"]
    elif damage == "purpose": results[1]["purpose"] = "comparison"
    elif damage == "method": results[1]["method_version"] = 2
    else: results[1]["configurations"]["E"]["metrics"]["action_score_percentage"]["unit"] = "tokens"
    with pytest.raises(ValueError):
        summaries.aggregate_results(results)


@pytest.fixture
def package(study):
    path = create(study)
    finish(study, path)
    return study, path, metrics.calculate_metrics(study, PLAN_ID, "assessment_0001")


def rewrite_result(root, folder, transform):
    path = root / folder / "results.json"
    result = json.loads(path.read_text())
    transform(result)
    path.write_text(json.dumps(result), encoding="utf-8")


def clone_plan(root, new_id="plan_0100"):
    """Build a second fictional source/identity before creating its assessment.

    This is isolated test setup, including refreshed PDF/preparation/freeze
    fingerprints. Production reference and run files are never rewritten.
    """
    _, preparation, pages = storage.load_plan_preparation(root, PLAN_ID, SOURCE)
    old_pdf_hash = preparation["document_sha256"]
    old_fingerprint = storage.preparation_text_fingerprint(preparation, pages)
    new_pdf = root / f"data/raw/{new_id}.pdf"
    new_pdf.write_bytes((root / f"data/raw/{PLAN_ID}.pdf").read_bytes() + b"\n% Second fictional PDF.\n")
    new_pdf_hash = hashlib.sha256(new_pdf.read_bytes()).hexdigest()
    new_preparation = json.loads(json.dumps(preparation).replace(PLAN_ID, new_id).replace(old_pdf_hash, new_pdf_hash))
    new_fingerprint = storage.preparation_text_fingerprint(new_preparation, pages)
    registry = storage.load_registry(root)
    registry["plans"].append(json.loads(json.dumps(registry["plans"][0]).replace(PLAN_ID, new_id).replace(old_pdf_hash, new_pdf_hash)))
    storage.save_registry(root, registry)
    for parent in ("data/processed", "data/expert_references", "runs"):
        destination = root / parent / new_id
        shutil.copytree(root / parent / PLAN_ID, destination)
        for path in destination.rglob("*.json"):
            text = path.read_text()
            revised = text.replace(PLAN_ID, new_id).replace(old_pdf_hash, new_pdf_hash).replace(old_fingerprint, new_fingerprint)
            if revised != text:
                path.write_text(revised)
    reference = root / f"data/expert_references/{new_id}/expert_reference.json"
    freeze = reference.with_name("reference_freeze.json")
    data = json.loads(freeze.read_text())
    data["reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
    freeze.write_text(json.dumps(data))
    for path in (root / f"runs/{new_id}").glob("run_verify_*/artifacts/verifier_input.json"):
        saved = json.loads(path.read_text())
        baseline = root / f"runs/{new_id}/{saved['input_run_id']}/output.json"
        saved["input_run"] = json.loads(baseline.read_text())
        saved["input_run_fingerprint"] = hashlib.sha256(baseline.read_bytes()).hexdigest()
        path.write_text(json.dumps(saved))
    for path in (root / f"runs/{new_id}").glob("*/output.json"):
        storage.load_run_record(root, path.relative_to(root).as_posix())
    return new_id


def test_loader_recomputes_saved_package_and_ignores_later_live_csv_edits(package):
    root, assessment, folder = package
    before = snapshot(root)
    accepted = summaries.load_metric_snapshot(root, folder)
    assert accepted.result["review"]["complete"]
    change_row(root, assessment, "action_scores.csv", score="2")
    (root / assessment / "metadata.json").unlink()
    assert not assessment_validation.validate_assessment(root, PLAN_ID, "assessment_0001").valid
    assert summaries.load_metric_snapshot(root, folder + "/results.json").fingerprints == accepted.fingerprints
    assert (root / folder / "results.json").read_bytes() == before[folder + "/results.json"]


def test_end_to_end_two_plan_report_preserves_inputs_and_per_plan_rows(package, monkeypatch):
    root, _, folder = package
    new_id = clone_plan(root)
    path = assessments.create_assessment(root, new_id, reviewers=["fictional_reviewer"])
    finish(root, path)
    change_row(root, path, "action_scores.csv", score="0.5")
    second = metrics.calculate_metrics(root, new_id, "assessment_0001")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    before = snapshot(root)
    exported = summaries.summarize_metrics(root, [second, folder])
    assert exported == "data/reports/summary_0001"
    result = json.loads((root / exported / "summary.json").read_text())
    assert validation.validate_metrics_summary(result) == []
    assert [selection["plan_id"] for selection in result["selections"]] == [PLAN_ID, new_id]
    action = next(row for row in result["aggregates"] if row["scope"] == "configuration" and row["configuration"] == "E" and row["metric"] == "action_score_percentage")
    assert action["value"] == 37.5 and action["contributing_plan_count"] == 2
    for selection in result["selections"]:
        raw = (root / exported / "inputs" / selection["plan_id"] / "results.json").read_bytes()
        assert hashlib.sha256(raw).hexdigest() == selection["package_files"]["results.json"]
    for name, expected in result["code_files"].items():
        assert hashlib.sha256((root / exported / "code" / name).read_bytes()).hexdigest() == expected
    csv_path = root / exported / "summary.csv"
    assert hashlib.sha256(csv_path.read_bytes()).hexdigest() == result["summary"]["sha256"]
    with csv_path.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 47 * 3
    assert {row["plan_id"] for row in rows if row["level"] == "per_plan"} == {PLAN_ID, new_id}
    assert all(row["contributing_plans"] for row in rows if row["level"] == "aggregate")
    after = snapshot(root)
    assert all(after[name] == raw for name, raw in before.items())
    assert all(name.startswith(exported + "/") for name in set(after) - set(before))


@pytest.mark.parametrize("damage", ["metrics", "review", "metadata", "identity", "path", "version", "purpose", "missing_code"])
def test_altered_result_claims_are_rejected(package, damage):
    root, _, folder = package
    def change(result):
        if damage == "metrics": result["configurations"]["E"]["metrics"]["action_score_percentage"]["value"] = 99
        elif damage == "review": result["review"]["complete"] = False
        elif damage == "metadata": result["assessment"]["metadata"]["reviewers"] = ["Different reviewer"]
        elif damage == "identity": result["plan_id"] = "plan_9999"
        elif damage == "path": result["assessment"]["path"] = "elsewhere"
        elif damage == "version": result["method_version"] = 2
        elif damage == "purpose": result["purpose"] = "comparison"
        else: result["code_files"].pop("src/metrics.py")
    rewrite_result(root, folder, change)
    with pytest.raises(ValueError): summaries.summarize_metrics(root, [folder])
    assert not (root / "data/reports").exists()


@pytest.mark.parametrize("name", ["summary.csv", "assessment_inputs/action_scores.csv", "code/src/metrics.py"])
def test_changed_archival_files_are_rejected(package, name):
    root, _, folder = package
    file = root / folder / name
    file.write_bytes(file.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="fingerprint"):
        summaries.load_metric_snapshot(root, folder)


def test_rehashed_edited_archive_still_has_to_reproduce_saved_measures(package):
    root, _, folder = package
    change_row(root, folder + "/assessment_inputs", "action_scores.csv", score="0.5")
    raw = (root / folder / "assessment_inputs/action_scores.csv").read_bytes()
    rewrite_result(root, folder, lambda result: result["assessment"]["files"].update({"action_scores.csv": hashlib.sha256(raw).hexdigest()}))
    with pytest.raises(ValueError, match="Saved measures differ"):
        summaries.load_metric_snapshot(root, folder)


def test_rehashed_csv_must_match_the_saved_calculation(package):
    root, _, folder = package
    file = root / folder / "summary.csv"
    file.write_bytes(file.read_bytes() + b"invented row\n")
    rewrite_result(root, folder, lambda result: result["summary"].update(sha256=hashlib.sha256(file.read_bytes()).hexdigest()))
    with pytest.raises(ValueError, match="summary CSV differs"):
        summaries.load_metric_snapshot(root, folder)


def test_changed_underlying_model_evidence_is_rejected(package):
    root, _, folder = package
    file = root / f"runs/{PLAN_ID}/run_extract_0001/output.json"
    file.write_bytes(file.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="Archived assessment validation failed"):
        summaries.load_metric_snapshot(root, folder)


@pytest.mark.parametrize("name", ["results.json", "summary.csv", "assessment_inputs", "code/src/metrics.py"])
def test_package_symlinks_are_rejected_inside_project_too(package, name):
    root, _, folder = package
    file = root / folder / name
    replacement = root / "redirected"
    file.rename(replacement)
    file.symlink_to(replacement, target_is_directory=replacement.is_dir())
    with pytest.raises(ValueError, match="symbolic"):
        summaries.load_metric_snapshot(root, folder)


@pytest.mark.parametrize("value", ["../metrics_0001", "/tmp/metrics_0001", "data/assessments/plan_0099/assessment_0000/metrics_0001", "data/assessments/plan_0099/assessment_0001/metrics_0000", None])
def test_selection_paths_are_canonical(value, tmp_path):
    with pytest.raises(ValueError): summaries.summarize_metrics(tmp_path, [value])
    assert list(tmp_path.iterdir()) == []


def test_duplicate_plans_are_rejected_before_publication(package):
    root, _, folder = package
    with pytest.raises(ValueError, match="one calculation per plan"):
        summaries.summarize_metrics(root, [folder, folder + "/results.json"])
    assert not (root / "data/reports").exists()


def test_reports_keep_earlier_versions_and_reserve_interrupted_numbers(package):
    root, _, folder = package
    first = summaries.summarize_metrics(root, [folder])
    before = snapshot(root / first)
    (root / "data/reports/summary_0004").write_bytes(b"interrupted")
    second = summaries.summarize_metrics(root, [folder])
    assert second == "data/reports/summary_0005" and snapshot(root / first) == before


def test_reports_cannot_redirect_inside_project(package):
    root, _, folder = package
    target = root / "elsewhere"
    target.mkdir()
    (root / "data/reports").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        summaries.summarize_metrics(root, [folder])
    assert list(target.iterdir()) == []


def test_failed_publication_leaves_partial_evidence_without_completion_marker(package, monkeypatch):
    root, _, folder = package
    original = storage._publish_new_bytes
    def failed(path, raw):
        if path.name == "summary.csv": raise OSError("Controlled summary publication failure")
        original(path, raw)
    monkeypatch.setattr(storage, "_publish_new_bytes", failed)
    with pytest.raises(OSError, match="publication failure"):
        summaries.summarize_metrics(root, [folder])
    partial = root / "data/reports/summary_0001"
    assert (partial / "inputs" / PLAN_ID / "results.json").exists()
    assert not (partial / "summary.json").exists()


def test_source_package_changes_during_publication_are_detected(package, monkeypatch):
    root, _, folder = package
    original = storage._publish_new_bytes
    def edited(path, raw):
        original(path, raw)
        if path.name == "summary.csv":
            file = root / folder / "results.json"
            file.write_bytes(file.read_bytes() + b"\n")
    monkeypatch.setattr(storage, "_publish_new_bytes", edited)
    with pytest.raises(ValueError, match="package changed"):
        summaries.summarize_metrics(root, [folder])
    assert not (root / "data/reports/summary_0001/summary.json").exists()


def test_cli_requires_explicit_results_and_reports_contributing_plans(package, capsys):
    root, _, folder = package
    command = ["summarize_metrics", "--result", folder, "--project-root", str(root)]
    assert cli.main(command) == 0
    output = capsys.readouterr()
    assert "Summary: data/reports/summary_0001" in output.out and "1 contributing plans" in output.out
    assert cli.main([*command, "--result", folder]) == 1
    assert "one calculation per plan" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error: cli.main(["summarize_metrics"])
    assert error.value.code == 2
