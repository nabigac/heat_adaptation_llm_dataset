"""Check agreed arithmetic and immutable exports using fictional judgments.

Small in-memory reports isolate the formulas. Saved-study tests additionally
exercise validation, publication, and provenance with the controlled C runner.
Neither set establishes scientific quality or makes paid model requests.
"""

from copy import deepcopy
import csv
import hashlib
import json

import pytest

import assessment_validation as review
import cli
import metrics
import storage
import validation
from test_agent_loop import PLAN_ID, project
from test_assessment_creation import create, snapshot, study, template_directory
from test_assessment_validation import change_row, finish
from test_collaboration_contracts import configured
from test_saved_collaboration import ready
from test_saved_extractor import facts


@pytest.fixture
def report():
    """A controlled valid-report boundary, independent of filesystem fixtures."""
    scores, groups, runs = [], [], {}
    for role, values, count, unsupported in (
        ("E", [1] * 6 + [.5] * 2 + [0] * 2, 12, 2),
        ("E+V", [1] * 8 + [.5] * 2, 10, 0), ("C", [1] * 10, 8, 0),
    ):
        scores.extend({"configuration": role, "score": score} for score in values)
        groups.extend({"configuration": role, "activity_supported": "no" if number < unsupported else "yes",
                       "evidence_adequate": "no" if number < 3 else "yes"} for number in range(count))
        runs[role] = {"plan_data": {"actions": [{}] * count},
                      "plan_issues": {"issues": [{"issue_status": "open"}] * {"E": 3, "E+V": 1, "C": 2}[role]},
                      "elapsed_seconds": {"E": 10, "E+V": 4, "C": 8}[role]}
    runs["E"]["model_calls"] = [{"input_tokens": 100, "output_tokens": 10}, {"input_tokens": 20, "output_tokens": 2}]
    runs["E+V"]["model_calls"] = [{"input_tokens": 30, "output_tokens": 3}]
    runs["C"]["model_calls"] = [{"actor": actor, "input_tokens": tokens, "output_tokens": tokens // 10,
                                "elapsed_seconds": 100} for actor, tokens in zip(("coordinator", "worker_1", "worker_2"), (50, 60, 70))]
    runs["C"]["budget"] = {"reported_usage": {"input_tokens": 99999, "output_tokens": 99999}}
    data = review.AssessmentData({}, {"plan_data": {"actions": [{}] * 10}}, runs,
                                {"action_scores.csv": scores, "output_review.csv": groups,
                                 "verifier_resolutions.csv": [{"confirmed": answer} for answer in ("yes", "yes", "no")]}, {})
    readiness = {name: dict.fromkeys(metrics.CONFIGURATIONS, True) for name in ("reference_actions", "output_support", "output_evidence")}
    readiness["verifier_resolutions"] = True
    return review.AssessmentValidation(data, [], [], readiness)


def measure(result, configuration, name):
    return result["configurations"][configuration]["metrics"][name]


def test_design_example_quality_counts_and_denominators(report):
    result = metrics.summarize_assessment(report)
    assert measure(result, "E", "action_score_percentage")["value"] == 70
    assert measure(result, "E", "action_score_percentage")["numerator"] == 7
    assert measure(result, "E", "action_score_percentage")["denominator"] == 10
    assert result["configurations"]["E"]["score_distribution"] == {"0": 2, "0.5": 2, "1": 6}
    assert measure(result, "E", "unsupported_action_count")["value"] == 2
    assert measure(result, "E", "unsupported_action_count")["denominator"] == 12
    assert measure(result, "E", "adequate_evidence_percentage")["value"] == 75
    assert measure(result, "E", "adequate_evidence_percentage")["numerator"] == 9
    assert measure(result, "E", "adequate_evidence_percentage")["denominator"] == 12
    assert [measure(result, role, "open_issue_count")["value"] for role in metrics.CONFIGURATIONS] == [3, 1, 2]
    assert result["verifier_resolutions"]["numerator"] == 2 and result["verifier_resolutions"]["denominator"] == 3


def test_shared_e_v_costs_c_parallel_time_and_each_call_once(report):
    result = metrics.summarize_assessment(report)
    for role, runtime, input_tokens, output_tokens in (("E", 10, 120, 12), ("E+V", 14, 150, 15), ("C", 8, 180, 18)):
        assert measure(result, role, "runtime_seconds")["value"] == runtime
        assert measure(result, role, "input_tokens")["value"] == input_tokens
        assert measure(result, role, "output_tokens")["value"] == output_tokens
        assert measure(result, role, "total_tokens")["value"] == input_tokens + output_tokens


def test_paired_changes_have_direction_and_percentage_point_units(report):
    result = metrics.summarize_assessment(report)
    first = result["paired_changes"]["E+V_minus_E"]["metrics"]
    second = result["paired_changes"]["C_minus_E+V"]["metrics"]
    assert first["action_score_percentage"]["value"] == 20
    assert second["action_score_percentage"]["value"] == 10
    assert first["action_score_percentage"]["unit"] == "percentage_points"
    assert first["unsupported_action_count"]["value"] == -2
    assert first["runtime_seconds"]["value"] == 4 and second["runtime_seconds"]["value"] == -6
    assert first["total_tokens"]["value"] == 33


@pytest.mark.parametrize("role", metrics.CONFIGURATIONS)
@pytest.mark.parametrize("field", ["input_tokens", "output_tokens", "elapsed_seconds"])
def test_missing_required_observation_keeps_only_affected_totals_unavailable(report, role, field):
    if field == "elapsed_seconds":
        report.data.runs[role][field] = None
        metric = "runtime_seconds"
    else:
        report.data.runs[role]["model_calls"][0][field] = None
        metric = field
    result = metrics.summarize_assessment(report)
    affected = {role, "E+V"} if role == "E" else {role}
    for configuration in metrics.CONFIGURATIONS:
        current = measure(result, configuration, metric)
        assert current["status"] == ("unavailable" if configuration in affected else "available")
        if configuration in affected:
            assert current["value"] is None
            if field != "elapsed_seconds":
                assert measure(result, configuration, "total_tokens")["value"] is None
                other = "output_tokens" if field == "input_tokens" else "input_tokens"
                assert measure(result, configuration, other)["status"] == "available"


def test_explicit_zero_usage_and_duration_are_available(report):
    report.data.runs["E"]["elapsed_seconds"] = 0
    report.data.runs["E"]["model_calls"] = [{"input_tokens": 0, "output_tokens": 0}]
    result = metrics.summarize_assessment(report)
    assert measure(result, "E", "runtime_seconds")["value"] == 0
    assert measure(result, "E", "total_tokens")["value"] == 0
    assert measure(result, "E", "total_tokens")["status"] == "available"


@pytest.mark.parametrize("role", metrics.CONFIGURATIONS)
def test_absent_call_records_cannot_establish_zero_usage(report, role):
    report.data.runs[role]["model_calls"] = []
    result = metrics.summarize_assessment(report)
    assert measure(result, role, "total_tokens")["status"] == "unavailable"
    if role == "E":
        assert measure(result, "E+V", "input_tokens")["value"] is None


def test_nonfinite_total_duration_is_unavailable(report):
    report.data.runs["E"]["elapsed_seconds"] = report.data.runs["E+V"]["elapsed_seconds"] = 1e308
    assert measure(metrics.summarize_assessment(report), "E+V", "runtime_seconds")["status"] == "unavailable"


def test_pending_reference_review_does_not_erase_completed_other_measures(report):
    report.readiness["reference_actions"]["C"] = False
    report.data.tables["action_scores.csv"][-1]["score"] = None
    result = metrics.summarize_assessment(report)
    assert measure(result, "C", "action_score_percentage")["value"] is None
    assert measure(result, "C", "action_score_percentage")["denominator"] == 10
    assert measure(result, "C", "adequate_evidence_percentage")["status"] == "available"
    assert result["paired_changes"]["E+V_minus_E"]["metrics"]["action_score_percentage"]["value"] == 20
    assert result["paired_changes"]["C_minus_E+V"]["metrics"]["action_score_percentage"]["status"] == "pending"


def test_unsettled_support_withholds_group_denominator_and_relevant_quality(report):
    report.readiness["output_support"]["E"] = report.readiness["output_evidence"]["E"] = False
    report.data.tables["output_review.csv"][0]["activity_supported"] = "undetermined"
    result = metrics.summarize_assessment(report)
    assert result["configurations"]["E"]["total_output_activities"] is None
    assert result["configurations"]["E"]["candidate_activity_groups"] == 12
    for name in ("unsupported_action_count", "adequate_evidence_percentage"):
        assert measure(result, "E", name)["status"] == "pending"
        assert measure(result, "E", name)["denominator"] is None
    assert measure(result, "E", "action_score_percentage")["value"] == 70


def test_pending_evidence_retains_confirmed_group_denominator(report):
    report.readiness["output_evidence"]["E"] = False
    result = metrics.summarize_assessment(report)
    assert measure(result, "E", "adequate_evidence_percentage")["status"] == "pending"
    assert measure(result, "E", "adequate_evidence_percentage")["denominator"] == 12
    assert measure(result, "E", "unsupported_action_count")["value"] == 2


def test_pending_resolution_review_is_not_zero_confirmations(report):
    report.readiness["verifier_resolutions"] = False
    current = metrics.summarize_assessment(report)["verifier_resolutions"]
    assert current["value"] is None and current["numerator"] is None and current["denominator"] == 3
    assert current["status"] == "pending"


def test_no_eligible_claims_is_not_applicable_with_explicit_zero_counts(report):
    report.data.tables["verifier_resolutions.csv"] = []
    current = metrics.summarize_assessment(report)["verifier_resolutions"]
    assert current["value"] is None and current["numerator"] == current["denominator"] == 0
    assert current["status"] == "not_applicable"


def test_zero_reference_denominator_is_not_a_zero_percentage(report):
    report.data.reference["plan_data"]["actions"] = []
    report.data.tables["action_scores.csv"] = []
    result = metrics.summarize_assessment(report)
    current = measure(result, "E", "action_score_percentage")
    assert current["value"] is None and current["denominator"] == 0 and current["status"] == "not_applicable"
    assert result["paired_changes"]["E+V_minus_E"]["metrics"]["action_score_percentage"]["status"] == "not_applicable"


def test_no_output_activities_has_zero_unsupported_count_and_undefined_evidence_percentage(report):
    report.data.runs["C"]["plan_data"]["actions"] = []
    report.data.tables["output_review.csv"] = [row for row in report.data.tables["output_review.csv"] if row["configuration"] != "C"]
    result = metrics.summarize_assessment(report)
    assert result["configurations"]["C"]["total_output_activities"] == 0
    assert measure(result, "C", "unsupported_action_count")["value"] == 0
    assert measure(result, "C", "adequate_evidence_percentage")["status"] == "not_applicable"


def test_confirmed_activity_groups_supply_denominator_instead_of_raw_records(report):
    report.data.runs["E"]["plan_data"]["actions"] = [{}] * 50
    result = metrics.summarize_assessment(report)
    assert result["configurations"]["E"]["raw_output_record_count"] == 50
    assert result["configurations"]["E"]["total_output_activities"] == 12
    assert measure(result, "E", "adequate_evidence_percentage")["denominator"] == 12


def test_failure_scope_is_unavailable_and_invalid_reports_are_rejected(report):
    assert metrics.summarize_assessment(report)["failure_reporting"]["counts"] == {"E": None, "V": None, "C": None}
    with pytest.raises(ValueError, match="valid assessment"):
        metrics.summarize_assessment(review.AssessmentValidation(None, [], [], {}))


@pytest.fixture
def saved_assessment(study):
    path = create(study)
    finish(study, path)
    return study, path


def calculate(root, path, **options):
    return metrics.calculate_metrics(root, PLAN_ID, path.rsplit("/", 1)[-1], **options)


def result_at(root, path):
    return json.loads((root / path / "results.json").read_text())


def test_export_validates_and_preserves_inputs_code_and_summary(saved_assessment, monkeypatch):
    root, path = saved_assessment
    monkeypatch.delenv("HF_TOKEN", raising=False)
    before = snapshot(root)
    exported = calculate(root, path, require_complete=True)
    assert exported == path + "/metrics_0001"
    result = result_at(root, exported)
    assert validation.validate_metrics_results(result) == []
    assert result["review"]["complete"] and result["purpose"] == "development"
    for name, expected in result["assessment"]["files"].items():
        raw = (root / exported / "assessment_inputs" / name).read_bytes()
        assert raw == before[f"{path}/{name}"]
        assert hashlib.sha256(raw).hexdigest() == expected
    for name, expected in result["code_files"].items():
        assert hashlib.sha256((root / exported / "code" / name).read_bytes()).hexdigest() == expected
    assert "src/metrics.py" in result["code_files"] and "uv.lock" in result["code_files"]
    summary = root / exported / "summary.csv"
    assert hashlib.sha256(summary.read_bytes()).hexdigest() == result["summary"]["sha256"]
    with summary.open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 47 and set(rows[0]) == set(metrics.SUMMARY_COLUMNS)
    assert any(row["scope"] == "paired_change" and row["unit"] == "percentage_points" for row in rows)
    failure_rows = [row for row in rows if row["metric"] == "failed_executions"]
    assert len(failure_rows) == 3 and all(row["value"] == "" and row["status"] == "unavailable" for row in failure_rows)
    after = snapshot(root)
    assert all(after[name] == raw for name, raw in before.items())
    assert all(name.startswith(exported + "/") for name in set(after) - set(before))


def test_recalculation_keeps_old_results_and_exact_earlier_judgments(saved_assessment):
    root, path = saved_assessment
    first = calculate(root, path)
    before = snapshot(root / first)
    change_row(root, path, "action_scores.csv", score="0.5", reason="Revised fictional judgment.")
    second = calculate(root, path)
    assert second.endswith("metrics_0002") and snapshot(root / first) == before
    assert measure(result_at(root, first), "E", "action_score_percentage")["value"] == 50
    assert measure(result_at(root, second), "E", "action_score_percentage")["value"] == 25


def test_partial_review_exports_nulls_and_strict_mode_writes_nothing(study):
    path = create(study)
    before = snapshot(study)
    with pytest.raises(ValueError, match="require-complete"):
        calculate(study, path, require_complete=True)
    assert snapshot(study) == before
    exported = calculate(study, path)
    result = result_at(study, exported)
    assert not result["review"]["complete"] and result["review"]["pending"]
    assert measure(result, "E", "action_score_percentage")["value"] is None
    assert measure(result, "E", "runtime_seconds")["status"] == "available"


def test_invalid_assessment_never_publishes_results(saved_assessment):
    root, path = saved_assessment
    change_row(root, path, "action_scores.csv", score="2")
    before = snapshot(root)
    with pytest.raises(ValueError, match="validation failed"):
        calculate(root, path)
    assert snapshot(root) == before


def test_occupied_and_interrupted_numbers_are_reserved(saved_assessment):
    root, path = saved_assessment
    (root / path / "metrics_0003").mkdir()
    (root / path / "metrics_0004").write_bytes(b"interrupted export")
    assert calculate(root, path).endswith("metrics_0005")
    assert (root / path / "metrics_0004").read_bytes() == b"interrupted export"


def test_failed_publication_preserves_partial_evidence_without_results_marker(saved_assessment, monkeypatch):
    root, path = saved_assessment
    original = storage._publish_new_bytes
    def failed(destination, raw):
        if destination.name == "summary.csv":
            raise OSError("Controlled metric publication failure")
        original(destination, raw)
    monkeypatch.setattr(storage, "_publish_new_bytes", failed)
    with pytest.raises(OSError, match="publication failure"):
        calculate(root, path)
    partial = root / path / "metrics_0001"
    assert (partial / "assessment_inputs/action_scores.csv").exists()
    assert not (partial / "results.json").exists()


@pytest.mark.parametrize("when", ["calculation", "publication"])
def test_changed_review_before_results_marker_is_detected(saved_assessment, monkeypatch, when):
    root, path = saved_assessment
    file = root / path / "action_scores.csv"
    if when == "calculation":
        original = metrics._summary_bytes
        def edited(result):
            file.write_bytes(file.read_bytes() + b"\n")
            return original(result)
        monkeypatch.setattr(metrics, "_summary_bytes", edited)
    else:
        original = storage._publish_new_bytes
        def edited(destination, raw):
            original(destination, raw)
            if destination.name == "summary.csv":
                file.write_bytes(file.read_bytes() + b"\n")
        monkeypatch.setattr(storage, "_publish_new_bytes", edited)
    with pytest.raises(ValueError, match="changed after validation"):
        calculate(root, path)
    assert not (root / path / "metrics_0001/results.json").exists()


def test_changed_code_is_detected_before_publication(saved_assessment, monkeypatch):
    root, path = saved_assessment
    original = metrics._code_snapshot
    calls = []
    def changed():
        files = original()
        if calls:
            files["src/metrics.py"] += b"\n"
        calls.append(True)
        return files
    monkeypatch.setattr(metrics, "_code_snapshot", changed)
    with pytest.raises(ValueError, match="code changed"):
        calculate(root, path)
    assert not (root / path / "metrics_0001").exists()


@pytest.mark.parametrize("damage", ["missing_field", "pending_zero", "unknown_status", "bad_hash"])
def test_result_schema_rejects_malformed_output(saved_assessment, damage):
    root, path = saved_assessment
    result = result_at(root, calculate(root, path))
    if damage == "missing_field": del result["paired_changes"]
    elif damage == "bad_hash": result["summary"]["sha256"] = "invalid"
    else:
        current = measure(result, "E", "action_score_percentage")
        current["status"] = "pending" if damage == "pending_zero" else "unknown"
        current["reason"] = "Fictional pending state."
    assert validation.validate_metrics_results(result)


def test_cli_statuses_and_required_assessment_id(study, capsys):
    path = create(study)
    command = ["calculate_metrics", PLAN_ID, "--assessment-id", "assessment_0001", "--project-root", str(study)]
    assert cli.main([*command, "--require-complete"]) == 1
    assert "require-complete" in capsys.readouterr().err
    assert cli.main(command) == 0
    assert "Manual review: pending" in capsys.readouterr().out
    finish(study, path)
    assert cli.main([*command, "--require-complete"]) == 0
    assert "Manual review: complete" in capsys.readouterr().out
    change_row(study, path, "action_scores.csv", score="2")
    assert cli.main(command) == 1
    assert "validation failed" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        cli.main(["calculate_metrics", PLAN_ID])
    assert error.value.code == 2
