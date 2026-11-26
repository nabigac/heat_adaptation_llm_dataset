"""Create assessment inputs from exact saved runs and a frozen reference.

Creation copies context and leaves every expert judgment blank. It never calls a
model, matches activities by ID, calculates scores, or changes research inputs.
"""

import csv
import hashlib
import json
from io import StringIO
from pathlib import Path
import re
from datetime import datetime, timezone

import expert_files
import storage
import validation
from legacy_records import canonical_data_path, effective_run_purpose


PREFIXES = {"extractor": "run_extract", "verifier": "run_verify", "collaboration": "run_collaboration"}
ACTION_COLUMNS = (
    "configuration", "run_id", "reference_action_id", "reference_action", "reference_evidence",
    "matched_output_action_ids", "score", "reason",
)
OUTPUT_COLUMNS = (
    "configuration", "run_id", "output_activity_id", "output_action_ids", "activity_description",
    "evidence", "activity_supported", "evidence_adequate", "reason",
)
RESOLUTION_COLUMNS = (
    "issue_id", "related_action_id", "extractor_description", "verifier_description",
    "claimed_resolution", "confirmed", "reason",
)
INSTRUCTIONS = [
    "All study work uses comparison. Check final versions and first-successful-run selections against the manual study log; this form does not certify which runs belong in the final analysis.",
    "All judgment cells start blank (pending). A blank score is not zero, and blank judgments are not false.",
    "action_scores.csv: match by meaning. Enter matched_output_action_ids as a JSON list, for example [\"action_0001\", \"action_0003\"]. Use [] for a confirmed omission. Score 0, 0.5, or 1 and give a reason.",
    "output_review.csv starts with one candidate activity per output record. Confirm activity grouping before scoring: combine repeated/split records or split bundled activities. Each group needs a unique output_activity_id within its configuration and a JSON list of output_action_ids.",
    "activity_description can label a regrouped activity. Evidence is reading context copied from linked output records; keep its original quotations/pages and judge the saved outputs and PDF. IDs are local to each dataset. Supported activity does not imply every detail is correct.",
    "For activity_supported, evidence_adequate, and confirmed, use yes, no, or undetermined and explain the judgment. Leave unreviewed cells blank.",
    "verifier_resolutions.csv contains initially open E issues that V marks resolved by verifier. Confirm only when every grouped concern is addressed. C issues and reference issues are separate.",
    "Metadata fixes the selected inputs; newer runs do not replace them. Keep original outputs and the frozen reference intact. Later corrections belong in review drafts from fresh dataset_building runs.",
    "Metrics cover the selected successful outputs. Failed and superseded attempts remain execution history and are excluded from study outcomes.",
]


def _json(data):
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


def _fingerprint(raw):
    return hashlib.sha256(raw).hexdigest()


def _run_snapshot(root, plan_id, stage, run_id):
    prefix = PREFIXES[stage]
    match = re.fullmatch(rf"{prefix}_([0-9]+)", run_id) if isinstance(run_id, str) else None
    if match is None or not match[1].strip("0"):
        raise ValueError(f"Expected a numbered {prefix}_NNNN ID.")
    relative = f"runs/{plan_id}/{run_id}/output.json"
    path = storage.resolve_project_path(root, relative)
    raw = path.read_bytes()
    record = storage.load_run_record(root, relative)
    if path.read_bytes() != raw:
        raise ValueError(f"Saved run changed while selecting it: {run_id}")
    if (record["plan_id"] != plan_id or record["stage"] != stage
            or record["status"] != "succeeded" or effective_run_purpose(record["purpose"]) != "comparison"):
        raise ValueError(f"Select a validated, successful comparison {stage} run for this plan: {run_id}")
    return {"record": record, "record_path": relative, "record_sha256": _fingerprint(raw)}


def _select_run(root, plan_id, stage, *, run_id=None, source_path=None, input_run_id=None):
    """Use number order, skip ineligible defaults, and never replace an explicit ID."""
    def checked(identifier):
        snapshot = _run_snapshot(root, plan_id, stage, identifier)
        record = snapshot["record"]
        if source_path is not None and canonical_data_path(record["source_path"]) != canonical_data_path(source_path):
            raise ValueError(f"Run {identifier} uses another preparation; select a compatible set of runs.")
        if input_run_id is not None and record["input_run_id"] != input_run_id:
            raise ValueError(f"Verifier {identifier} is not linked to selected E {input_run_id}.")
        return snapshot

    if run_id is not None:
        result = checked(run_id)
        result["selected_via"] = "explicit"
        return result
    parent = storage.resolve_project_path(root, f"runs/{plan_id}")
    candidates = []
    if parent.exists():
        for path in parent.iterdir():
            match = re.fullmatch(rf"{PREFIXES[stage]}_([0-9]+)", path.name)
            if match and match[1].strip("0"):
                candidates.append((int(match[1]), path.name))
    for _, identifier in sorted(candidates, reverse=True):
        try:
            result = checked(identifier)
        except (OSError, ValueError):
            continue
        result["selected_via"] = "latest_successful"
        return result
    context = f" linked to E {input_run_id}" if input_run_id else ""
    raise ValueError(f"No validated, successful {stage} run{context} uses the selected source. "
                     "Select earlier compatible run IDs explicitly or complete the missing run.")


def select_assessment_runs(
    project_root: Path | str, plan_id: str, *, extractor_run_id: str | None = None,
    verifier_run_id: str | None = None, collaboration_run_id: str | None = None,
) -> dict:
    """Select one linked E/V pair and independent C without writes or paid calls.

    An explicit V supplies its E when no E is specified. Otherwise the latest
    eligible E is fixed first; absence of a linked V cannot silently select an
    older E. Latest C is constrained to that exact preparation.
    """
    root = Path(project_root).resolve()
    storage._require_run_identifier(plan_id)
    registry = storage.load_registry(root)
    plan = next((entry for entry in registry["plans"] if entry["plan_id"] == plan_id), None)
    if plan is None or not validation.is_study_sample(plan["study_set"]):
        raise ValueError("Assessment creation requires a registered plan in the study sample.")
    explicit_v = None
    if verifier_run_id is not None and extractor_run_id is None:
        explicit_v = _select_run(root, plan_id, "verifier", run_id=verifier_run_id)
        extractor_run_id = explicit_v["record"]["input_run_id"]
    extractor = _select_run(root, plan_id, "extractor", run_id=extractor_run_id)
    if explicit_v is not None:
        extractor["selected_via"] = "verifier_link"
    source_path = extractor["record"]["source_path"]
    verifier = _select_run(root, plan_id, "verifier", run_id=verifier_run_id,
                           source_path=source_path, input_run_id=extractor["record"]["run_id"])
    collaboration = _select_run(root, plan_id, "collaboration", run_id=collaboration_run_id,
                                source_path=source_path)
    return {"E": extractor, "E+V": verifier, "C": collaboration}


def _reference_snapshot(root, plan_id):
    reference = expert_files.validate_expert_reference(root, plan_id)
    freeze = storage.load_expert_reference_freeze(root, plan_id)
    if freeze is None:
        raise ValueError("Complete, review, and freeze the expert reference before creating an assessment.")
    reference_path = f"data/comparison/expert_references/{plan_id}/expert_reference.json"
    freeze_path = f"data/comparison/expert_references/{plan_id}/reference_freeze.json"
    raw = storage.read_expert_reference_bytes(root, plan_id)
    # A changed form cannot be paired with the earlier validated data, even if
    # someone also rewrites the freeze file between reads.
    if validation._decode_json(raw.decode("utf-8")) != reference:
        raise ValueError("The reference changed while creating the assessment.")
    freeze_raw = storage.resolve_project_path(root, freeze_path).read_bytes()
    if validation._decode_json(freeze_raw.decode("utf-8")) != freeze:
        raise ValueError("The reference freeze changed while creating the assessment.")
    return reference, freeze, {
        "path": reference_path, "sha256": _fingerprint(raw),
        "freeze_path": freeze_path, "freeze_sha256": _fingerprint(freeze_raw),
    }


def _csv_bytes(columns, rows):
    text = StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode("utf-8")


def _review_files(reference, snapshots):
    scores, outputs = [], []
    for configuration, snapshot in snapshots.items():
        record = snapshot["record"]
        for action in reference["plan_data"]["actions"]:
            scores.append({
                "configuration": configuration, "run_id": record["run_id"],
                "reference_action_id": action["action_id"], "reference_action": action["action"],
                "reference_evidence": _json(action["evidence"]),
            })
        for number, action in enumerate(record["plan_data"]["actions"], 1):
            outputs.append({
                "configuration": configuration, "run_id": record["run_id"],
                "output_activity_id": f"activity_{number:04d}",
                "output_action_ids": _json([action["action_id"]]),
                "activity_description": action["action"], "evidence": _json(action["evidence"]),
            })
    return {
        "action_scores.csv": _csv_bytes(ACTION_COLUMNS, scores),
        "output_review.csv": _csv_bytes(OUTPUT_COLUMNS, outputs),
        "verifier_resolutions.csv": _csv_bytes(RESOLUTION_COLUMNS, _verifier_resolution_rows(snapshots)),
    }


def _verifier_resolution_rows(snapshots):
    """Share eligibility and copied claim context between creation and validation."""
    resolutions = []
    initially_open = {issue["issue_id"]: issue
                      for issue in snapshots["E"]["record"]["plan_issues"]["issues"]
                      if issue["issue_status"] == "open"}
    for issue in snapshots["E+V"]["record"]["plan_issues"]["issues"]:
        previous = initially_open.get(issue["issue_id"])
        if previous is not None and issue["issue_status"] == "resolved" and issue["resolved_by"] == "verifier":
            resolutions.append({
                "issue_id": issue["issue_id"], "related_action_id": issue["related_action_id"],
                "extractor_description": previous["issue_description"],
                "verifier_description": issue["issue_description"], "claimed_resolution": issue["resolution"],
            })
    return resolutions


def _assessment_directory(root, plan_id):
    parent = storage.resolve_project_path(root, f"data/comparison/assessments/{plan_id}")
    if parent.resolve() != parent:
        raise ValueError("Assessment paths must not use symbolic links.")
    numbers = []
    if parent.exists():
        for path in parent.iterdir():
            match = re.fullmatch(r"assessment_([0-9]+)", path.name)
            if match:
                numbers.append(int(match[1]))
    identifier = f"assessment_{max(numbers, default=0) + 1:04d}"
    return identifier, parent / identifier


def _recheck_inputs(root, plan_id, metadata):
    """Recheck exact saved inputs for assessment creation and validation."""
    identities = [(metadata["reference"]["path"], metadata["reference"]["sha256"]),
                  (metadata["reference"]["freeze_path"], metadata["reference"]["freeze_sha256"])]
    identities.extend((run["record_path"], run["record_sha256"]) for run in metadata["runs"].values())
    for path, expected in identities:
        if _fingerprint(storage.resolve_project_path(root, path).read_bytes()) != expected:
            raise ValueError(f"An assessment input changed; its recorded fingerprint no longer matches: {path}")
    for run in metadata["runs"].values():
        # The output fingerprint pins the accepted record. Its supporting files
        # must also remain valid at use, not merely at selection.
        storage.load_run_record(root, run["record_path"])
    expert_files.validate_expert_reference(root, plan_id)
    _, preparation, pages = storage.load_plan_preparation(root, plan_id, metadata["source"]["preparation_path"])
    if storage.preparation_text_fingerprint(preparation, pages) != metadata["source"]["fingerprint"]:
        raise ValueError("Prepared source differs from its recorded assessment fingerprint.")


def create_assessment(
    project_root: Path | str, plan_id: str, *,
    extractor_run_id: str | None = None, verifier_run_id: str | None = None,
    collaboration_run_id: str | None = None, notes: str | None = None,
) -> str:
    """Create metadata and three prefilled CSVs, preserving every earlier assessment.

    Judgments remain pending and a completed frozen reference is required.
    Explicit IDs pin manual selections; defaults select latest eligible runs.
    No model calls run.
    Like run storage, an interrupted publication can retain partial files. The
    metadata file is published last; a folder without it is not a complete form.
    """
    if notes is not None and (not isinstance(notes, str) or not notes.strip()):
        raise ValueError("Assessment notes must be nonblank text when supplied.")
    root = Path(project_root).resolve()
    snapshots = select_assessment_runs(root, plan_id, extractor_run_id=extractor_run_id,
                                      verifier_run_id=verifier_run_id, collaboration_run_id=collaboration_run_id)
    reference, freeze, reference_identity = _reference_snapshot(root, plan_id)
    source_path = snapshots["E"]["record"]["source_path"]
    _, preparation, pages = storage.load_plan_preparation(root, plan_id, source_path)
    if (preparation["document_sha256"].lower() != freeze["document_sha256"]
            or preparation["page_count"] != freeze["page_count"]):
        raise ValueError("The selected preparation and frozen reference must identify the same original PDF.")
    identifier, destination = _assessment_directory(root, plan_id)
    metadata = {
        "schema_version": 2, "assessment_id": identifier, "plan_id": plan_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": notes, "reference": reference_identity,
        "source": {
            "preparation_path": source_path, "fingerprint": storage.preparation_text_fingerprint(preparation, pages),
            "document_sha256": preparation["document_sha256"].lower(), "page_count": preparation["page_count"],
        },
        "runs": {configuration: {
            "run_id": snapshot["record"]["run_id"], "record_path": snapshot["record_path"],
            "record_sha256": snapshot["record_sha256"], "selected_via": snapshot["selected_via"],
        } for configuration, snapshot in snapshots.items()},
        "instructions": list(INSTRUCTIONS),
    }
    problems = validation.validate_assessment_metadata(metadata)
    if problems:
        raise ValueError("Assessment metadata is invalid: " + "; ".join(problem.message for problem in problems))
    files = _review_files(reference, snapshots)
    _recheck_inputs(root, plan_id, metadata)
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in files.items():
        storage._publish_new_bytes(destination / name, data)
    _recheck_inputs(root, plan_id, metadata)
    storage._publish_new_bytes(destination / "metadata.json", storage._serialize_run_json(metadata).encode("utf-8"))
    return destination.relative_to(root).as_posix()
