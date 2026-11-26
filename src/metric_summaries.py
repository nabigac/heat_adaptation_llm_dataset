"""Validate saved metric packages and summarize exact selections across plans.

Archived review files supply judgments; live reference, source, and run files
still have to match their recorded identities. Per-plan percentages and paired
changes receive equal plan weight. Every aggregate identifies its contributors.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
import re
from statistics import mean

import assessment_validation
import assessments
import metrics
import storage
import validation


SUMMARY_COLUMNS = (
    "summary_id", "level", "scope", "configuration", "metric", "aggregation", "plan_id",
    "value", "unit", "numerator", "denominator", "status", "reason",
    "contributing_plan_count", "contributing_plans", "excluded_plans",
)
ESSENTIAL_CODE = {
    "src/metrics.py", "src/assessment_validation.py", "src/validation.py", "src/storage.py",
    "schemas/metrics_results.schema.json", "schemas/assessment_metadata.schema.json", "pyproject.toml", "uv.lock",
}


@dataclass(frozen=True)
class MetricSnapshot:
    """One accepted package, with fingerprints for publication-time rechecks."""

    folder: str
    result: dict
    raw_result: bytes
    fingerprints: dict[str, str]


def _identity(value):
    """Ignore object-key order while preserving JSON numeric/type identities."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False)


def _package_folder(value):
    if not isinstance(value, str):
        raise ValueError("Select project-relative saved metrics folders using --result.")
    folder = value.rstrip("/").removesuffix("/results.json")
    parts = PurePosixPath(folder).parts
    if len(parts) != 6 or parts[:3] != ("data", "comparison", "assessments") or "/".join(parts) != folder:
        raise ValueError("Select data/comparison/assessments/<plan_id>/assessment_NNNN/metrics_NNNN (or its results.json).")
    storage._require_run_identifier(parts[3])
    for label, identifier in (("assessment", parts[4]), ("metrics", parts[5])):
        match = re.fullmatch(rf"{label}_([0-9]+)", identifier)
        if match is None or not match[1].strip("0"):
            raise ValueError(f"Select a numbered {label}_NNNN ID.")
    return folder, parts[3:]


def _package_file(root, folder, name):
    path = storage.resolve_project_path(root, f"{folder}/{name}")
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("Metric package paths must not use symbolic links.")
    return path


def load_metric_snapshot(project_root: Path | str, result_path: str) -> MetricSnapshot:
    """Check package bytes and recompute the supported method from its archive.

    No archived code is executed. Later live CSV edits are intentionally ignored;
    altered reference/run/source evidence still invalidates the selected inputs.
    """
    root = Path(project_root).resolve()
    folder, identifiers = _package_folder(result_path)
    raw = _package_file(root, folder, "results.json").read_bytes()
    try:
        result = validation._decode_json(raw.decode("utf-8"))
        problems = validation.validate_metrics_results(result)
    except (ValueError, RecursionError) as error:
        raise ValueError(f"Invalid saved metrics JSON in {folder}: {error}") from error
    if problems:
        raise ValueError(f"Invalid saved metrics in {folder}: " + "; ".join(problem.message for problem in problems))
    if tuple(result[key] for key in ("plan_id", "assessment_id", "calculation_id")) != identifiers:
        raise ValueError("Saved metric identities must match the selected folder.")
    plan_id, assessment_id, _ = identifiers
    if result["assessment"]["path"] != f"data/comparison/assessments/{plan_id}/{assessment_id}":
        raise ValueError("Saved metrics must identify their canonical assessment path.")
    if not ESSENTIAL_CODE <= result["code_files"].keys():
        raise ValueError("The metric package lacks required calculation-code fingerprints.")
    expected = {
        "results.json": assessments._fingerprint(raw), "summary.csv": result["summary"]["sha256"],
        **{f"code/{name}": fingerprint for name, fingerprint in result["code_files"].items()},
        **{f"assessment_inputs/{name}": fingerprint for name, fingerprint in result["assessment"]["files"].items()},
    }
    for name, fingerprint in expected.items():
        if assessments._fingerprint(_package_file(root, folder, name).read_bytes()) != fingerprint:
            raise ValueError(f"Saved metric package fingerprint does not match: {folder}/{name}")
    report = assessment_validation._validate_assessment_folder(root, plan_id, assessment_id, f"{folder}/assessment_inputs")
    if not report.valid:
        raise ValueError("Archived assessment validation failed: " + "; ".join(
            f"{problem.location or '$'}: {problem.message}" for problem in report.problems))
    if (report.data.fingerprints != result["assessment"]["files"]
            or _identity(report.data.metadata) != _identity(result["assessment"]["metadata"])):
        raise ValueError("Saved metric metadata differs from its archived assessment.")
    expected_review = {"complete": report.complete, "pending": [asdict(item) for item in report.pending],
                       "readiness": report.readiness}
    computed = metrics.summarize_assessment(report)
    if _identity(result["review"]) != _identity(expected_review):
        raise ValueError("Saved metric review state differs from its archived judgments.")
    if any(_identity(result[name]) != _identity(value) for name, value in computed.items()):
        raise ValueError("Saved measures differ from the supported calculation of archived judgments.")
    expected_summary = metrics._summary_bytes({**result, **computed})
    if _package_file(root, folder, "summary.csv").read_bytes() != expected_summary:
        raise ValueError("Saved summary CSV differs from its calculated measures.")
    snapshot = MetricSnapshot(folder, result, raw, expected)
    _recheck_snapshots(root, [snapshot])
    return snapshot


def _recheck_snapshots(root, snapshots):
    for snapshot in snapshots:
        for name, expected in snapshot.fingerprints.items():
            if assessments._fingerprint(_package_file(root, snapshot.folder, name).read_bytes()) != expected:
                raise ValueError(f"Selected metric package changed; retry with stable inputs: {snapshot.folder}/{name}")
        assessments._recheck_inputs(root, snapshot.result["plan_id"], snapshot.result["assessment"]["metadata"])


def _aggregate(scope, configuration, name, observations):
    unit = observations[0][1]["unit"]
    if any(measure["unit"] != unit for _, measure in observations):
        raise ValueError("Selected measures must use compatible units.")
    aggregation = ("confirmed_over_claimed" if scope == "verifier_resolution" else
                   "mean" if scope == "paired_change" or unit == "percent" else "sum")
    accepted, excluded = [], []
    for plan_id, measure in observations:
        # Zero claims are known zero counts, although their ratio is undefined.
        no_claims = (scope == "verifier_resolution" and measure["status"] == "not_applicable"
                     and measure["numerator"] == measure["denominator"] == 0)
        if measure["status"] == "available" or no_claims:
            accepted.append((plan_id, measure))
        else:
            excluded.append({"plan_id": plan_id, "status": measure["status"], "reason": measure["reason"]})
    numerator = denominator = value = None
    if not accepted:
        states = {item["status"] for item in excluded}
        status = next(state for state in ("pending", "unavailable", "not_applicable") if state in states)
        reason = "No selected plan has an applicable available value; see excluded_plans."
    elif aggregation == "confirmed_over_claimed":
        numerator = sum(measure["numerator"] for _, measure in accepted)
        denominator = sum(measure["denominator"] for _, measure in accepted)
        status = "available" if denominator else "not_applicable"
        value = numerator if denominator else None
        reason = None if denominator else "No contributing plan has an eligible V resolution claim."
    elif aggregation == "mean":
        value = mean(measure["value"] for _, measure in accepted)
        status, reason = "available", None
    else:
        total = metrics._observed_sum([measure["value"] for _, measure in accepted], unit)
        value, status, reason = total["value"], total["status"], total["reason"]
        if all(measure["denominator"] is not None for _, measure in accepted):
            denominator = sum(measure["denominator"] for _, measure in accepted)
    return {
        "scope": scope, "configuration": configuration, "metric": name, "aggregation": aggregation,
        "value": value, "unit": unit, "status": status, "reason": reason,
        "numerator": numerator, "denominator": denominator,
        "contributing_plan_count": len(accepted), "contributing_plans": [plan_id for plan_id, _ in accepted],
        "excluded_plans": excluded,
    }


def aggregate_results(results: list[dict]) -> list[dict]:
    """Combine validated per-plan results without pooling activity percentages."""
    if not isinstance(results, list) or not results:
        raise ValueError("Select at least one saved metric result.")
    if len({result["plan_id"] for result in results}) != len(results):
        raise ValueError("Select exactly one calculation per plan; duplicate plans would count twice.")
    if (any(result["purpose"] != "comparison" for result in results)
            or len({result["method_version"] for result in results}) != 1):
        raise ValueError("Select supported comparison results using the same calculation method.")
    groups = defaultdict(list)
    for result in sorted(results, key=lambda item: item["plan_id"]):
        for scope, configuration, name, measure in metrics.metric_rows(result):
            groups[scope, configuration, name].append((result["plan_id"], measure))
    return [_aggregate(*key, observations) for key, observations in groups.items()]


def _summary_bytes(report, results):
    rows = []
    for result in results:
        for scope, configuration, name, measure in metrics.metric_rows(result):
            rows.append({"summary_id": report["summary_id"], "level": "per_plan", "scope": scope,
                         "configuration": configuration, "metric": name, "aggregation": "none",
                         "plan_id": result["plan_id"], **measure})
    for measure in report["aggregates"]:
        rows.append({"summary_id": report["summary_id"], "level": "aggregate", **measure,
                     "contributing_plans": assessments._json(measure["contributing_plans"]),
                     "excluded_plans": assessments._json(measure["excluded_plans"])})
    return assessments._csv_bytes(SUMMARY_COLUMNS, rows)


def _report_directory(root):
    parent = storage.resolve_project_path(root, "data/comparison/reports")
    if parent.resolve() != parent:
        raise ValueError("Report paths must not use symbolic links.")
    numbers = []
    if parent.exists():
        for path in parent.iterdir():
            match = re.fullmatch(r"summary_([0-9]+)", path.name)
            if match:
                numbers.append(int(match[1]))
    identifier = f"summary_{max(numbers, default=0) + 1:04d}"
    return identifier, parent / identifier


def summarize_metrics(project_root: Path | str, result_paths: list[str]) -> str:
    """Publish a new summary, preserving chosen results and earlier reports."""
    if not isinstance(result_paths, list) or not result_paths:
        raise ValueError("Supply at least one --result folder.")
    folders = [_package_folder(path)[0] for path in result_paths]
    plans = [_package_folder(path)[1][0] for path in folders]
    if len(set(plans)) != len(plans):
        raise ValueError("Select exactly one calculation per plan; duplicate plans would count twice.")
    root = Path(project_root).resolve()
    snapshots = sorted((load_metric_snapshot(root, folder) for folder in folders), key=lambda item: item.result["plan_id"])
    results = [snapshot.result for snapshot in snapshots]
    identifier, destination = _report_directory(root)
    code = metrics._code_snapshot()
    report = {
        "schema_version": 1, "summary_id": identifier, "purpose": "comparison",
        "method_version": results[0]["method_version"], "created_at": datetime.now(timezone.utc).isoformat(),
        "selections": [{"plan_id": snapshot.result["plan_id"], "assessment_id": snapshot.result["assessment_id"],
                        "calculation_id": snapshot.result["calculation_id"], "result_path": f"{snapshot.folder}/results.json",
                        "package_files": snapshot.fingerprints} for snapshot in snapshots],
        "aggregates": aggregate_results(results),
        "code_files": {name: assessments._fingerprint(raw) for name, raw in code.items()},
    }
    summary = _summary_bytes(report, results)
    report["summary"] = {"path": "summary.csv", "sha256": assessments._fingerprint(summary)}
    problems = validation.validate_metrics_summary(report)
    if problems:
        raise ValueError("Metric summary is invalid: " + "; ".join(problem.message for problem in problems))
    def recheck():
        _recheck_snapshots(root, snapshots)
        if metrics._code_snapshot() != code:
            raise ValueError("Summary calculation code changed; retry with stable code.")
    recheck()
    destination.mkdir(parents=True, exist_ok=False)
    for snapshot in snapshots:
        path = destination / "inputs" / snapshot.result["plan_id"] / "results.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        storage._publish_new_bytes(path, snapshot.raw_result)
    for name, raw in code.items():
        path = destination / "code" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        storage._publish_new_bytes(path, raw)
    storage._publish_new_bytes(destination / "summary.csv", summary)
    recheck()
    storage._publish_new_bytes(destination / "summary.json", storage._serialize_run_json(report).encode("utf-8"))
    return destination.relative_to(root).as_posix()
