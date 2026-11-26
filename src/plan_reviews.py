"""Review dataset-building answers without changing model or comparison records.

Drafts remain editable. Finalization checks the issues before removing them from
the data product, then publishes a separate completion record last. No model,
OCR, or automatic factual judgments run here.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re

from expert_templates import placeholder_locations
from artifact_io import json_bytes, sha256_bytes, project_file, next_artifact_id
import storage
import validation


REVIEW_FILES = ("reviewed_plan.json", "review_record.json", "review_draft.json", "source_run.json")
SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
STAGES = {"E": "extractor", "E+V": "verifier", "C": "collaboration"}
PREFIXES = {"E": "run_extract", "E+V": "run_verify", "C": "run_collaboration"}
ACTORS = {"E": {"extractor"}, "E+V": {"extractor", "verifier"},
          "C": {"worker_1", "worker_2", "coordinator"}}
INSTRUCTIONS = [
    "Edit plan_data and plan_issues only. Source, configuration, and review identity are fixed.",
    "Review scope is remaining open issues only; this is not a full audit of the output or omissions.",
    "Keep every original issue ID, origin, description, and type. Preserve model-resolved statuses and resolutions; those concerns are outside this review scope.",
    "For each open issue, check the PDF, edit the data as needed, then set issue_status to resolved, resolved_by to expert, and give a nonblank resolution explaining the decision.",
    "Keep issue links valid after action edits. If an action is removed or merged, update related_action_id to a surviving action or null and explain the change in the resolution.",
    "Additional concerns found during this review may use new issue IDs with issue_origin expert. Address all of them before finalization.",
    "Validate while editing. Finalization requires all issues addressed and retains the review history separately from the clean metadata/actions JSON.",
]


def _review_file(root: Path, relative_path: str) -> Path:
    """Use the shared artifact boundary for live and archived review files."""
    return project_file(root, relative_path, label="Review")


def review_directory(plan_id: str, review_id: str, *, completed: bool = False) -> str:
    storage._require_run_identifier(plan_id)
    if not isinstance(review_id, str) or not re.fullmatch(r"review_0*[1-9][0-9]*", review_id):
        raise ValueError("Select a numbered review_NNNN ID.")
    kind = "reviewed_plans" if completed else "review_drafts"
    return f"data/dataset_building/{kind}/{plan_id}/{review_id}"


def _schema(data, name):
    references = tuple((f"urn:heat-adaptation:{uri}", SCHEMAS / f"{file}.schema.json") for uri, file in (
        ("plan-data", "plan_data"), ("agent-response", "agent_response"), ("review-draft", "review_draft"),
    ))
    return validation._validate_structure(data, SCHEMAS / f"{name}.schema.json", name,
        required_formats=("date", "date-time"), schema_references=references) + validation._nonfinite_json_numbers(data)


def _raise(problems):
    if problems:
        raise ValueError("Review validation failed: " + "; ".join(
            f"{item.location}: {item.message}" for item in problems))


def _problem(location, message):
    return validation.ValidationProblem("reference", location, message)


def _snapshot(root, plan_id, configuration, run_id):
    if configuration not in STAGES:
        raise ValueError("Select configuration E, E+V, or C.")
    if not isinstance(run_id, str) or not re.fullmatch(rf"{PREFIXES[configuration]}_0*[1-9][0-9]*", run_id):
        raise ValueError(f"Select a numbered {PREFIXES[configuration]}_NNNN run ID.")
    relative = f"runs/{plan_id}/{run_id}/output.json"
    path = _review_file(root, relative)
    raw = path.read_bytes()
    record = storage.load_run_record(root, relative)
    if path.read_bytes() != raw:
        raise ValueError("Source run changed during review selection.")
    if (record["plan_id"] != plan_id or record["stage"] != STAGES[configuration]
            or record["status"] != "succeeded" or record["purpose"] != "dataset_building"):
        raise ValueError("Review requires a validated, successful dataset_building run of the selected configuration.")
    _, preparation, pages = storage.load_plan_preparation(root, plan_id, record["source_path"])
    source = {"run_id": run_id, "record_path": relative, "record_sha256": sha256_bytes(raw),
              "preparation_path": record["source_path"],
              "fingerprint": storage.preparation_text_fingerprint(preparation, pages),
              "document_sha256": preparation["document_sha256"].lower(), "page_count": preparation["page_count"]}
    return record, raw, source


def _select(root, plan_id, configuration, run_id):
    if configuration not in STAGES:
        raise ValueError("Select configuration E, E+V, or C.")
    storage._require_run_identifier(plan_id)
    if run_id is not None:
        return _snapshot(root, plan_id, configuration, run_id)
    parent = _review_file(root, f"runs/{plan_id}")
    candidates = []
    if parent.is_dir():
        for path in parent.iterdir():
            match = re.fullmatch(rf"{PREFIXES[configuration]}_([0-9]+)", path.name)
            if match and int(match[1]) > 0:
                candidates.append((int(match[1]), path.name))
    for _, candidate in sorted(candidates, reverse=True):
        try:
            return _snapshot(root, plan_id, configuration, candidate)
        except (OSError, ValueError):
            continue
    raise ValueError("No validated, successful dataset_building run is eligible for this plan/configuration.")


def _next_review(root: Path, plan_id: str) -> str:
    """Reserve numbers across both draft and completed-review locations."""
    directories = tuple(f"data/dataset_building/{kind}/{plan_id}"
                        for kind in ("review_drafts", "reviewed_plans"))
    return next_artifact_id(root, directories, "review")


def create_review_draft(project_root: Path | str, plan_id: str, *, configuration: str, run_id: str | None = None) -> str:
    """Copy one exact eligible answer; default to its latest successful run.

    Configuration selection is explicit. A bad explicit ID never falls back;
    creating this form does not choose a workflow for the entire collection.
    """
    root = Path(project_root).resolve()
    record, raw, source = _select(root, plan_id, configuration, run_id)
    source["selected_via"] = "explicit" if run_id is not None else "latest_successful"
    review_id = _next_review(root, plan_id)
    folder = review_directory(plan_id, review_id)
    draft = {"schema_version": 1, "plan_id": plan_id, "review_id": review_id,
             "created_at": datetime.now(timezone.utc).isoformat(), "configuration": configuration,
             "review_scope": "open_issues_only", "source": source,
             "plan_data": deepcopy(record["plan_data"]), "plan_issues": deepcopy(record["plan_issues"]),
             "instructions": list(INSTRUCTIONS)}
    _raise(_schema(draft, "review_draft"))
    # Resolve once, then recheck before allocating/publication. A newer run cannot
    # replace the selected answer during this operation.
    if _snapshot(root, plan_id, configuration, record["run_id"])[1] != raw:
        raise ValueError("Source run changed before draft publication.")
    destination = _review_file(root, folder)
    destination.mkdir(parents=True, exist_ok=False)
    storage._publish_new_bytes(destination / "source_run.json", raw)
    if _snapshot(root, plan_id, configuration, record["run_id"])[1] != raw:
        raise ValueError("Source run changed before draft publication.")
    storage._publish_new_bytes(destination / "review_draft.json", json_bytes(draft))
    return folder


@dataclass(frozen=True)
class ReviewValidation:
    """Keep invalid content unavailable, and valid-but-open reviews pending."""

    data: dict | None
    problems: list[validation.ValidationProblem]
    pending_issue_ids: tuple[str, ...]

    @property
    def valid(self) -> bool:
        return self.data is not None and not self.problems

    @property
    def complete(self) -> bool:
        return self.valid and not self.pending_issue_ids


def _validate_issue_history(draft: dict, baseline: dict) -> tuple[list, tuple[str, ...], set]:
    """Retain original concerns and distinguish expert work from model claims.

    A review ledger keeps multiple historical concerns after action merges; the
    one-issue-per-action rule for model generation does not apply to this ledger.
    """
    problems = []
    original = {item["issue_id"]: item for item in baseline["plan_issues"]["issues"]}
    current = {}
    actions = {item["action_id"] for item in draft["plan_data"]["actions"]}
    pending = []
    for index, issue in enumerate(draft["plan_issues"]["issues"]):
        location = f"$.plan_issues.issues[{index}]"
        identifier = issue["issue_id"]
        if identifier in current:
            problems.append(_problem(location + ".issue_id", "Issue IDs must be unique."))
        current[identifier] = issue
        prior = original.get(identifier)
        if issue["issue_origin"] not in ACTORS[draft["configuration"]] | {"expert"}:
            problems.append(_problem(location + ".issue_origin", "Issue identity belongs to another configuration."))
        if prior is not None:
            if any(issue.get(field) != prior.get(field) for field in ("issue_origin", "issue_description", "issue_type")):
                problems.append(_problem(location, "Preserve the original issue's origin, description, and type."))
            # This workflow reviews remaining open concerns. It must not turn an
            # earlier model resolution into a claim of fresh expert verification.
            if prior["issue_status"] == "resolved":
                if any(issue[field] != prior[field] for field in ("issue_status", "resolved_by", "resolution")):
                    problems.append(_problem(location, "Preserve model-resolved issues; they are outside this review scope."))
            elif issue["issue_status"] == "resolved" and issue["resolved_by"] != "expert":
                problems.append(_problem(location + ".resolved_by", "An open source issue must be addressed by expert review."))
        elif issue["issue_origin"] != "expert" or issue["resolved_by"] not in {"expert", None}:
            problems.append(_problem(location, "New review issues must use expert origin and resolution identities."))
        if issue["related_action_id"] is not None and issue["related_action_id"] not in actions:
            problems.append(_problem(location + ".related_action_id", "Relink this issue to an existing action or null."))
        if issue["issue_status"] == "open":
            pending.append(identifier)
    for identifier in original.keys() - current.keys():
        problems.append(_problem("$.plan_issues.issues", f"Keep original issue {identifier}; resolve it rather than deleting it."))
    linked_actions = {item["related_action_id"] for item in current.values()}
    return problems, tuple(pending), linked_actions


def _check_draft(draft: dict, baseline: dict, source: dict) -> tuple[list, tuple[str, ...]]:
    """Check fields first, then source, action records, and review decisions."""
    problems = _schema(draft, "review_draft")
    if problems:
        return problems, ()

    # Source identity is fixed at creation. Expert edits affect the answer and
    # issue decisions, never which model run or PDF supplied this review.
    selected_source = {key: value for key, value in draft["source"].items() if key != "selected_via"}
    if selected_source != source:
        problems.append(_problem("$.source", "Draft source must match the exact preserved dataset-building run and preparation."))
    for field in ("source_url", "date_accessed"):
        if draft["plan_data"]["metadata"][field] != baseline["plan_data"]["metadata"][field]:
            problems.append(_problem(f"$.plan_data.metadata.{field}", "Keep the selected source's collection metadata."))
    problems += validation._validate_plan_data_references(
        draft["plan_data"], page_count=source["page_count"], location="$.plan_data")
    issue_problems, pending, linked_actions = _validate_issue_history(draft, baseline)
    problems += issue_problems

    # Missing values remain permissible only with a retained explanation. This
    # check happens while issues still exist, before finalization strips them.
    for index, action in enumerate(draft["plan_data"]["actions"]):
        for field in ("action_type", "evidence"):
            if not action[field] and action["action_id"] not in linked_actions:
                problems.append(_problem(f"$.plan_data.actions[{index}].{field}", f"An empty {field} requires a linked issue in the review record."))
    for location in placeholder_locations(draft):
        problems.append(_problem(location, "Complete or remove unfinished TODO guidance."))
    return problems, pending


def _read_validated_draft(root: Path, folder: str, plan_id: str, review_id: str) -> tuple[dict, bytes, bytes, tuple[str, ...]]:
    """Bind editable content to the exact source snapshot before using it."""
    draft_file = _review_file(root, folder + "/review_draft.json")
    raw = draft_file.read_bytes()
    draft = validation._decode_json(raw.decode("utf-8"))
    _raise(_schema(draft, "review_draft"))
    if draft["plan_id"] != plan_id or draft["review_id"] != review_id:
        raise ValueError("Review identity must match its selected folder.")
    baseline, source_raw, source = _snapshot(root, plan_id, draft["configuration"], draft["source"]["run_id"])
    if _review_file(root, folder + "/source_run.json").read_bytes() != source_raw:
        raise ValueError("Source run differs from the preserved review input.")
    problems, pending = _check_draft(draft, baseline, source)
    _raise(problems)
    if draft_file.read_bytes() != raw:
        raise ValueError("Review draft changed during validation; save it and retry.")
    return draft, raw, source_raw, pending


def validate_review_draft(project_root: Path | str, plan_id: str, review_id: str) -> ReviewValidation:
    """Read-only checks; an otherwise valid draft may still have open issues."""
    root = Path(project_root).resolve()
    try:
        folder = review_directory(plan_id, review_id)
        draft, raw, _, pending = _read_validated_draft(root, folder, plan_id, review_id)
        final = _review_file(root, review_directory(plan_id, review_id, completed=True) + "/review_record.json")
        if final.exists():
            record = load_reviewed_plan(root, plan_id, review_id)[1]
            if record["draft_sha256"] != sha256_bytes(raw):
                raise ValueError("This draft differs from its finalized review; create a new draft for further work.")
        return ReviewValidation(draft, [], pending)
    except (OSError, ValueError) as error:
        return ReviewValidation(None, [_problem("$", str(error))], ())


def _issue_groups(draft):
    expert = [item["issue_id"] for item in draft["plan_issues"]["issues"] if item["resolved_by"] == "expert"]
    model = [item["issue_id"] for item in draft["plan_issues"]["issues"] if item["resolved_by"] != "expert"]
    return expert, model


def _check_clean(data, page_count):
    # Empty type/evidence may be explained by an addressed source issue. Check
    # that relationship before stripping issues; the sidecar keeps the reason.
    problems = _schema(data, "reviewed_plan")
    if not problems:
        problems += validation._validate_plan_data_references(data, page_count=page_count, location="$")
    return problems


def finalize_reviewed_plan(project_root: Path | str, plan_id: str, review_id: str) -> str:
    """Confirm issue review and save clean plan data plus immutable history.

    A completion record is published last. Interrupted saves may resume only
    when every existing file matches the same reviewed bytes; nothing is replaced.
    """
    # Validate the full answer and its issue ledger before producing clean data.
    root = Path(project_root).resolve()
    folder = review_directory(plan_id, review_id)
    draft, raw, source_raw, pending = _read_validated_draft(root, folder, plan_id, review_id)
    if pending:
        raise ValueError("Address every open issue before finalization: " + ", ".join(pending))
    product = deepcopy(draft["plan_data"])
    _raise(_check_clean(product, draft["source"]["page_count"]))
    target = review_directory(plan_id, review_id, completed=True)
    destination = _review_file(root, target)
    marker = _review_file(root, target + "/review_record.json")
    if marker.exists():
        raise FileExistsError("This review is already finalized; create a new draft for further work.")
    payloads = {"reviewed_plan.json": json_bytes(product), "review_draft.json": raw, "source_run.json": source_raw}
    # Resume only identical partial saves. Completed or differing work is never replaced.
    if destination.exists():
        if not destination.is_dir() or any(p.name not in payloads for p in destination.iterdir()):
            raise FileExistsError("Finalization folder is occupied by unrelated files.")
        for name, expected in payloads.items():
            file = _review_file(root, target + "/" + name)
            if file.exists() and file.read_bytes() != expected:
                raise FileExistsError("Interrupted finalization contains different bytes; preserve it and create a new review draft.")
    destination.mkdir(parents=True, exist_ok=True)
    for name, expected in payloads.items():
        file = _review_file(root, target + "/" + name)
        if not file.exists():
            storage._publish_new_bytes(file, expected)
    expert, model = _issue_groups(draft)
    record = {"schema_version": 1, "plan_id": plan_id, "review_id": review_id,
              "configuration": draft["configuration"], "review_scope": "open_issues_only",
              "finalized_at": datetime.now(timezone.utc).isoformat(),
              "draft_path": folder + "/review_draft.json", "draft_sha256": sha256_bytes(raw),
              "source": deepcopy(draft["source"]), "reviewed_plan_sha256": sha256_bytes(payloads["reviewed_plan.json"]),
              "expert_addressed_issue_ids": expert, "model_resolved_issue_ids": model,
              "issues": deepcopy(draft["plan_issues"]["issues"])}
    _raise(_schema(record, "review_record"))
    if _read_validated_draft(root, folder, plan_id, review_id)[1:3] != (raw, source_raw):
        raise ValueError("Review inputs changed before finalization; no completion record was published.")
    # Completion is the last publication step; incomplete folders cannot be used downstream.
    _check_completed(root, target, record, plan_id, review_id)
    storage._publish_new_bytes(marker, json_bytes(record))
    return target


def _check_completed(root, folder, record, plan_id, review_id):
    """Use the same checks before publication and when assembling later data."""
    _raise(_schema(record, "review_record"))
    draft, raw, _, pending = _read_validated_draft(root, folder, plan_id, review_id)
    product_raw = _review_file(root, folder + "/reviewed_plan.json").read_bytes()
    product = validation._decode_json(product_raw.decode("utf-8"))
    _raise(_check_clean(product, draft["source"]["page_count"]))
    expert, model = _issue_groups(draft)
    expected = {"plan_id": plan_id, "review_id": review_id, "configuration": draft["configuration"],
                "review_scope": "open_issues_only", "draft_path": review_directory(plan_id, review_id) + "/review_draft.json",
                "draft_sha256": sha256_bytes(raw), "source": draft["source"], "reviewed_plan_sha256": sha256_bytes(product_raw),
                "expert_addressed_issue_ids": expert, "model_resolved_issue_ids": model,
                "issues": draft["plan_issues"]["issues"]}
    if pending or product != draft["plan_data"] or any(record[key] != value for key, value in expected.items()):
        raise ValueError("Completed review, source, issues, fingerprints, and clean plan data must agree.")
    created = validation.parse_utc_timestamp(draft["created_at"])
    finalized = validation.parse_utc_timestamp(record["finalized_at"])
    if finalized < created:
        raise ValueError("Finalization cannot precede draft creation.")
    return product, record


@dataclass(frozen=True)
class CompletedReviewSnapshot:
    """Parsed decisions and exact bytes from one checked completion record."""

    data: dict
    record: dict
    source_run: dict
    files: dict[str, bytes]


def load_completed_review(project_root: Path | str, plan_id: str, review_id: str,
                          *, folder: str | None = None) -> CompletedReviewSnapshot:
    """Read one completed review, or a preserved copy selected by its caller.

    Both live reviews and dataset input copies use the same checks. Rereading
    their bytes prevents returning a mixture of files edited during validation.
    """
    root = Path(project_root).resolve()
    canonical = review_directory(plan_id, review_id, completed=True)
    selected = canonical if folder is None else folder
    files = {name: _review_file(root, selected + "/" + name).read_bytes() for name in REVIEW_FILES}
    record = validation._decode_json(files["review_record.json"].decode("utf-8"))
    data, record = _check_completed(root, selected, record, plan_id, review_id)
    if any(_review_file(root, selected + "/" + name).read_bytes() != raw for name, raw in files.items()):
        raise ValueError("Completed review changed while loading it.")
    source_run = validation._decode_json(files["source_run.json"].decode("utf-8"))
    return CompletedReviewSnapshot(data, record, source_run, files)


def load_reviewed_plan(project_root: Path | str, plan_id: str, review_id: str) -> tuple[dict, dict]:
    """Load completed data/history independently of later original draft edits."""
    snapshot = load_completed_review(project_root, plan_id, review_id)
    return snapshot.data, snapshot.record
