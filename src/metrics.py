"""Calculate per-plan study measures from validated, saved expert judgments.

Pure arithmetic is separate from publication. Pending review, missing measured
usage, and zero-denominator percentages have distinct states; none becomes zero.
Every export preserves the reviewed CSV bytes and calculation code for audit.
"""

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import math
import re

import assessment_validation
import assessments
import storage
import validation


CONFIGURATIONS = assessment_validation.CONFIGURATIONS
METRIC_UNITS = {
    "action_score_percentage": "percent", "unsupported_action_count": "activities",
    "adequate_evidence_percentage": "percent", "open_issue_count": "issues",
    "runtime_seconds": "seconds", "input_tokens": "tokens", "output_tokens": "tokens", "total_tokens": "tokens",
}
SUMMARY_COLUMNS = (
    "plan_id", "assessment_id", "calculation_id", "scope", "configuration", "metric",
    "value", "unit", "numerator", "denominator", "status", "reason",
)


def _measure(value, unit, *, status="available", reason=None, numerator=None, denominator=None):
    return {"value": value, "unit": unit, "status": status, "reason": reason,
            "numerator": numerator, "denominator": denominator}


def _pending(unit, reason, *, denominator=None):
    return _measure(None, unit, status="pending", reason=reason, denominator=denominator)


def _percentage(numerator, denominator):
    if denominator == 0:
        return _measure(None, "percent", status="not_applicable", reason="The denominator is zero.",
                        numerator=numerator, denominator=0)
    return _measure(numerator / denominator * 100, "percent", numerator=numerator, denominator=denominator)


def _observed_sum(values, unit):
    """Unknown components invalidate their total; explicitly reported zero is valid."""
    if not values or any(value is None for value in values):
        return _measure(None, unit, status="unavailable", reason="A required measurement is missing.")
    total = sum(values)
    if isinstance(total, float) and not math.isfinite(total):
        return _measure(None, unit, status="unavailable", reason="The measured total is not finite.")
    return _measure(total, unit)


def _configuration(report, configuration):
    data = report.data
    scores = [row for row in data.tables["action_scores.csv"] if row["configuration"] == configuration]
    groups = [row for row in data.tables["output_review.csv"] if row["configuration"] == configuration]
    run = data.runs[configuration]
    reference_count = len(data.reference["plan_data"]["actions"])
    scoring_ready = report.readiness["reference_actions"][configuration]
    support_ready = report.readiness["output_support"][configuration]
    evidence_ready = report.readiness["output_evidence"][configuration]
    # Candidate rows become the denominator only after support/group review.
    # A raw model record may contain several activities, or repeat another one.
    output_count = len(groups) if support_ready else None
    distribution = {str(score): sum(row["score"] == score for row in scores) for score in (0, 0.5, 1)} if scoring_ready else None
    action_score = (_percentage(sum(row["score"] for row in scores), reference_count) if scoring_ready
                    else _pending("percent", "Reference matches, scores, or reasons remain pending.", denominator=reference_count))
    unsupported = (_measure(sum(row["activity_supported"] == "no" for row in groups), "activities", denominator=output_count)
                   if support_ready else _pending("activities", "Output grouping, support, or reasons remain pending."))
    adequate = (_percentage(sum(row["evidence_adequate"] == "yes" for row in groups), output_count) if evidence_ready
                else _pending("percent", "Output grouping, support, evidence, or reasons remain pending.", denominator=output_count))
    # E+V includes the shared extractor exactly once. C's model_calls already
    # contain coordinator and worker calls; summing budget/worker totals again
    # would count those same calls twice. Elapsed C time includes parallel work.
    cost_runs = [data.runs["E"], run] if configuration == "E+V" else [run]
    calls = [call for source in cost_runs for call in source["model_calls"]]
    input_tokens = _observed_sum([call["input_tokens"] for call in calls], "tokens")
    output_tokens = _observed_sum([call["output_tokens"] for call in calls], "tokens")
    # An empty call list in either constituent run cannot establish zero usage.
    if any(not source["model_calls"] for source in cost_runs):
        input_tokens = _observed_sum([], "tokens")
        output_tokens = _observed_sum([], "tokens")
    return {
        "reference_action_count": reference_count, "raw_output_record_count": len(run["plan_data"]["actions"]),
        "candidate_activity_groups": len(groups), "total_output_activities": output_count,
        "score_distribution": distribution,
        "metrics": {
            "action_score_percentage": action_score, "unsupported_action_count": unsupported,
            "adequate_evidence_percentage": adequate,
            "open_issue_count": _measure(sum(issue["issue_status"] == "open" for issue in run["plan_issues"]["issues"]), "issues"),
            "runtime_seconds": _observed_sum([source["elapsed_seconds"] for source in cost_runs], "seconds"),
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "total_tokens": _observed_sum([input_tokens["value"], output_tokens["value"]], "tokens"),
        },
    }


def _contrast(configurations, before, after):
    differences = {}
    for name, unit in METRIC_UNITS.items():
        left = configurations[before]["metrics"][name]
        right = configurations[after]["metrics"][name]
        unit = "percentage_points" if unit == "percent" else unit
        if left["status"] == right["status"] == "available":
            differences[name] = _measure(right["value"] - left["value"], unit)
        else:
            states = {left["status"], right["status"]}
            status = next(state for state in ("not_applicable", "pending", "unavailable") if state in states)
            differences[name] = _measure(None, unit, status=status,
                reason=f"Requires available values: {before} is {left['status']}; {after} is {right['status']}.")
    return {"before": before, "after": after, "metrics": differences}


def summarize_assessment(report: assessment_validation.AssessmentValidation) -> dict:
    """Calculate from a valid report in memory, including incomplete review.

    Measures have independent readiness: pending evidence does not erase a
    finished reference score or automatically turn an unknown judgment false.
    Source correctness remains the expert's responsibility.
    """
    if not report.valid:
        raise ValueError("Metric calculation requires a valid assessment.")
    configurations = {configuration: _configuration(report, configuration) for configuration in CONFIGURATIONS}
    claims = report.data.tables["verifier_resolutions.csv"]
    if not claims:
        resolutions = _measure(None, "resolutions", status="not_applicable", reason="There are no eligible V resolution claims.",
                               numerator=0, denominator=0)
    elif report.readiness["verifier_resolutions"]:
        confirmed = sum(row["confirmed"] == "yes" for row in claims)
        resolutions = _measure(confirmed, "resolutions", numerator=confirmed, denominator=len(claims))
    else:
        resolutions = _pending("resolutions", "V resolution confirmations or reasons remain pending.", denominator=len(claims))
    return {
        "configurations": configurations,
        "paired_changes": {
            "E+V_minus_E": _contrast(configurations, "E", "E+V"),
            "C_minus_E+V": _contrast(configurations, "E+V", "C"),
        },
        "verifier_resolutions": resolutions,
        "failure_reporting": {
            "status": "unavailable", "included_attempts": None, "counts": {"E": None, "V": None, "C": None},
            "reason": "Failure-reporting scope has not been selected; selected successful runs do not establish zero failures.",
        },
    }


def metric_rows(result):
    """Use the same per-plan measures in CSV exports and cross-plan reports."""
    for configuration, data in result["configurations"].items():
        for name, measure in data["metrics"].items():
            yield "configuration", configuration, name, measure
        total = data["total_output_activities"]
        measure = (_measure(total, "activities") if total is not None
                   else _pending("activities", "Output grouping/support review remains pending."))
        yield "configuration", configuration, "total_output_activities", measure
    for comparison, data in result["paired_changes"].items():
        for name, measure in data["metrics"].items():
            yield "paired_change", comparison, name, measure
    yield "verifier_resolution", "E+V", "expert_confirmed_verifier_resolutions", result["verifier_resolutions"]
    for configuration in ("E", "V", "C"):
        yield "failure_reporting", configuration, "failed_executions", _measure(
            None, "executions", status="unavailable", reason=result["failure_reporting"]["reason"])


def _summary_bytes(result):
    """Long-form CSV keeps each value's status, unit, and denominator together."""
    identity = {key: result[key] for key in ("plan_id", "assessment_id", "calculation_id")}
    rows = [{**identity, "scope": scope, "configuration": configuration, "metric": name, **measure}
            for scope, configuration, name, measure in metric_rows(result)]
    return assessments._csv_bytes(SUMMARY_COLUMNS, rows)


def _code_snapshot():
    """Preserve executable rules and locked dependencies, including dirty code."""
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted((root / "src").glob("*.py")), *sorted((root / "schemas").glob("*.json")),
             root / "pyproject.toml", root / "uv.lock"]
    return {path.relative_to(root).as_posix(): path.read_bytes() for path in paths}


def _assessment_snapshot(root, folder, fingerprints):
    result = {}
    for name, expected in fingerprints.items():
        raw = assessment_validation._assessment_file(root, folder, name).read_bytes()
        if assessments._fingerprint(raw) != expected:
            raise ValueError(f"Assessment file changed after validation; save it and retry: {name}")
        result[name] = raw
    return result


def _calculation_directory(root, folder):
    parent = storage.resolve_project_path(root, folder)
    if parent.resolve() != parent:
        raise ValueError("Metric paths must not use symbolic links.")
    numbers = []
    for path in parent.iterdir():
        match = re.fullmatch(r"metrics_([0-9]+)", path.name)
        if match:
            numbers.append(int(match[1]))
    identifier = f"metrics_{max(numbers, default=0) + 1:04d}"
    return identifier, parent / identifier


def calculate_metrics(project_root: Path | str, plan_id: str, assessment_id: str, *, require_complete: bool = False) -> str:
    """Validate, calculate, and publish a new immutable per-plan result package.

    results.json is published last. An interrupted directory is preserved without
    that completion marker; existing numbers are never reused or overwritten.
    Use one writer at a time, as with assessment creation and saved runs.
    """
    root = Path(project_root).resolve()
    report = assessment_validation.validate_assessment(root, plan_id, assessment_id)
    if not report.valid:
        details = "; ".join(f"{problem.location or '$'}: {problem.message}" for problem in report.problems)
        raise ValueError("Assessment validation failed: " + details)
    if require_complete and not report.complete:
        raise ValueError("--require-complete requires all manual judgments and output coverage to be settled.")
    data = report.data
    folder = f"data/assessments/{plan_id}/{assessment_id}"
    review_files = _assessment_snapshot(root, folder, data.fingerprints)
    code = _code_snapshot()
    identifier, destination = _calculation_directory(root, folder)
    result = {
        "schema_version": 1, "method_version": 1, "calculation_id": identifier,
        "plan_id": plan_id, "assessment_id": assessment_id, "purpose": "development",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "assessment": {"path": folder, "files": data.fingerprints, "metadata": data.metadata},
        "code_files": {name: assessments._fingerprint(raw) for name, raw in code.items()},
        "review": {"complete": report.complete, "pending": [asdict(item) for item in report.pending],
                   "readiness": report.readiness},
        **summarize_assessment(report),
    }
    summary = _summary_bytes(result)
    result["summary"] = {"path": "summary.csv", "sha256": assessments._fingerprint(summary)}
    problems = validation.validate_metrics_results(result)
    if problems:
        raise ValueError("Metric results are invalid: " + "; ".join(problem.message for problem in problems))
    def recheck():
        assessments._recheck_inputs(root, plan_id, data.metadata)
        _assessment_snapshot(root, folder, data.fingerprints)
        if _code_snapshot() != code:
            raise ValueError("Calculation code changed; retry with stable code.")
    recheck()
    destination.mkdir(exist_ok=False)
    for name, raw in review_files.items():
        path = destination / "assessment_inputs" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        storage._publish_new_bytes(path, raw)
    for name, raw in code.items():
        path = destination / "code" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        storage._publish_new_bytes(path, raw)
    storage._publish_new_bytes(destination / "summary.csv", summary)
    recheck()
    storage._publish_new_bytes(destination / "results.json", storage._serialize_run_json(result).encode("utf-8"))
    return destination.relative_to(root).as_posix()
