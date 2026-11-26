"""Combine exact completed plan reviews into preserved, issue-free versions.

The data product contains metadata/actions only. A separate contents record and
input/code copies retain the review evidence and the recorded common workflow.
Loading checks these records; it never executes archived code or calls a model.
"""

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
import re

from artifact_io import (canonical_json_bytes, json_bytes, sha256_bytes, project_file, next_artifact_id, source_code_snapshot)
import plan_reviews
import storage
import validation


ROOT = "data/dataset_building/heat_action_datasets"
REVIEW_FILES = plan_reviews.REVIEW_FILES
# Git observations can change when adding documents without changing execution.
# Hardware/loaded-state observations are per-run facts, not configuration choices.
# They remain preserved in source_run.json rather than defining compatibility.
RUN_OBSERVATIONS = {"code_commit", "code_dirty", "hardware", "model_loaded_at_start"}


def _workflow_sha(workflow: dict) -> str:
    """Identify the common definition independently of JSON key ordering."""
    return sha256_bytes(canonical_json_bytes(workflow))


def _dataset_file(root: Path, relative_path: str) -> Path:
    """Apply the shared project boundary to dataset files and archived copies."""
    return project_file(root, relative_path, label="Dataset")


def _review_folder(value):
    if not isinstance(value, str):
        raise ValueError("Select a project-relative completed review folder or reviewed_plan.json.")
    value = value.rstrip("/")
    match = re.fullmatch(r"data/dataset_building/reviewed_plans/([^/]+)/(review_0*[1-9][0-9]*)(?:/reviewed_plan\.json)?", value)
    if match is None:
        raise ValueError("Select data/dataset_building/reviewed_plans/<plan_id>/review_NNNN, or its reviewed_plan.json.")
    plan_id, review_id = match.groups()
    return plan_reviews.review_directory(plan_id, review_id, completed=True), plan_id, review_id


def _dataset_folder(value):
    if not isinstance(value, str):
        raise ValueError("Select a dataset_NNNN folder or dataset_contents.json.")
    match = re.fullmatch(ROOT + r"/(dataset_0*[1-9][0-9]*)(?:/(?:dataset_contents|heat_action_dataset)\.json)?", value.rstrip("/"))
    if match is None:
        raise ValueError("Select data/dataset_building/heat_action_datasets/dataset_NNNN.")
    return ROOT + "/" + match[1], match[1]


def _schema(data: object, name: str) -> list[validation.ValidationProblem]:
    """Validate local contracts without retrieving schemas from the network."""
    return validation._validate_structure(data, plan_reviews.SCHEMAS / f"{name}.schema.json", name,
        required_formats=("date", "date-time"),
        schema_references=(("urn:heat-adaptation:plan-data", plan_reviews.SCHEMAS / "plan_data.schema.json"),),
    ) + validation._nonfinite_json_numbers(data)


def _require_valid(problems):
    if problems:
        raise ValueError("Dataset validation failed: " + "; ".join(f"{p.location}: {p.message}" for p in problems))


def _stage_definition(root: Path, record: dict) -> dict:
    """Separate the saved execution definition from per-run observations."""
    record_path = f"runs/{record['plan_id']}/{record['run_id']}/output.json"
    folder = PurePosixPath(record_path).parent.as_posix()
    fingerprints = validation._decode_json(_dataset_file(root, folder + "/artifacts/code_fingerprints.json").read_text(encoding="utf-8"))
    # The completed-review loader already validates these exact archived bytes.
    # Include the map itself so different code versions cannot be combined.
    settings = deepcopy(record["settings"])
    environment = settings.pop("environment")
    return {"stage": record["stage"], "settings": settings,
            "environment": {name: value for name, value in environment.items() if name not in RUN_OBSERVATIONS},
            "code_files": fingerprints["sha256"]}


def _workflow(root: Path, record: dict, configuration: str) -> dict:
    """Include every stage that produced this reviewed answer."""
    records = [record]
    if configuration == "E+V":
        # Matching V profiles alone would miss changes in the E that supplied it.
        baseline = storage.load_run_record(root, f"runs/{record['plan_id']}/{record['input_run_id']}/output.json")
        records.insert(0, baseline)
    return {"definition_version": 1, "configuration": configuration,
            "stages": [_stage_definition(root, item) for item in records]}


@dataclass(frozen=True)
class ReviewedInput:
    folder: str
    plan_id: str
    review_id: str
    data: dict
    record: dict
    files: dict[str, bytes]
    workflow: dict


def _load_review(root: Path, folder: str, plan_id: str, review_id: str) -> ReviewedInput:
    """Use review's public snapshot API, then attach its execution definition."""
    snapshot = plan_reviews.load_completed_review(root, plan_id, review_id, folder=folder)
    workflow = _workflow(root, snapshot.source_run, snapshot.record["configuration"])
    return ReviewedInput(folder, plan_id, review_id, snapshot.data, snapshot.record, snapshot.files, workflow)


def _compatible(snapshots: list[ReviewedInput]) -> None:
    """Reject repeated documents and mixed execution definitions before output."""
    first = snapshots[0]
    if len({item.plan_id for item in snapshots}) != len(snapshots):
        raise ValueError("Select one completed review per plan; duplicate plans are not allowed.")
    hashes = [item.record["source"]["document_sha256"] for item in snapshots]
    if len(set(hashes)) != len(hashes):
        raise ValueError("Duplicate original PDFs are not allowed under different plan IDs.")
    for item in snapshots:
        if item.record["configuration"] != first.record["configuration"]:
            raise ValueError("All reviewed plans must use the same configuration: E, E+V, or C.")
        if item.workflow != first.workflow:
            raise ValueError(f"Plan {item.plan_id} uses a different recorded workflow version: models, prompts, settings, software versions, or archived code differ.")


def _product(snapshots):
    # Action IDs are local to each plan. Do not renumber them across the dataset.
    return {"schema_version": 1, "plans": [{"plan_id": item.plan_id, **deepcopy(item.data)} for item in snapshots]}


def _assembly_code() -> dict[str, bytes]:
    """Keep an explicit checkpoint for detecting code changes during a build."""
    return source_code_snapshot()


def _next_dataset(root: Path) -> str:
    """Completed and interrupted versions both reserve their numbers."""
    return next_artifact_id(root, (ROOT,), "dataset")


def _recheck(root, snapshots, code):
    for original in snapshots:
        current = _load_review(root, original.folder, original.plan_id, original.review_id)
        if current.files != original.files or current.workflow != original.workflow:
            raise ValueError("Selected review inputs or workflow changed during assembly; retry with stable inputs.")
    if _assembly_code() != code:
        raise ValueError("Dataset assembly code changed; retry with stable code.")


def build_heat_action_dataset(project_root: Path | str, review_paths: list[str]) -> str:
    """Build a new preserved dataset from explicit completed review versions.

    There is no latest-review default. A completion record is published last;
    interrupted folders reserve their IDs and are never treated as datasets.
    Use one writer while selecting and publishing these files.
    """
    if not isinstance(review_paths, list) or not review_paths:
        raise ValueError("Supply at least one --review completed-review folder.")
    # Resolve explicit versions and reject duplicate identities before any writes.
    selections = [_review_folder(value) for value in review_paths]
    if len({plan_id for _, plan_id, _ in selections}) != len(selections):
        raise ValueError("Select one completed review per plan; duplicate plans are not allowed.")
    root = Path(project_root).resolve()
    snapshots = sorted((_load_review(root, *selection) for selection in selections), key=lambda item: item.plan_id)
    # Validate the selected reviews and common workflow before constructing data.
    _compatible(snapshots)
    product = _product(snapshots)
    _require_valid(_schema(product, "heat_action_dataset"))
    raw_product = json_bytes(product)
    code = _assembly_code()
    identifier = _next_dataset(root)
    folder = ROOT + "/" + identifier
    contents = {"schema_version": 1, "dataset_id": identifier,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "configuration": snapshots[0].record["configuration"], "review_scope": "open_issues_only",
                "workflow": snapshots[0].workflow, "workflow_sha256": _workflow_sha(snapshots[0].workflow),
                "plans": [{"plan_id": item.plan_id, "review_id": item.review_id, "review_path": item.folder,
                           "run_id": item.record["source"]["run_id"],
                           "files": {name: sha256_bytes(raw) for name, raw in item.files.items()}} for item in snapshots],
                "dataset": {"path": "heat_action_dataset.json", "sha256": sha256_bytes(raw_product),
                            "plan_count": len(snapshots), "action_count": sum(len(item.data["actions"]) for item in snapshots)},
                "assembly_code_files": {name: sha256_bytes(raw) for name, raw in code.items()}}
    _require_valid(_schema(contents, "dataset_contents"))
    _recheck(root, snapshots, code)
    destination = _dataset_file(root, folder)
    # Claim a fresh version. Input/code copies are evidence, not completion markers.
    destination.mkdir(parents=True, exist_ok=False)
    for item in snapshots:
        copy_folder = _dataset_file(root, f"{folder}/inputs/{item.plan_id}/{item.review_id}")
        copy_folder.mkdir(parents=True, exist_ok=False)
        for name, raw in item.files.items():
            storage._publish_new_bytes(copy_folder / name, raw)
    for name, raw in code.items():
        target = _dataset_file(root, folder + "/artifacts/code/" + name)
        target.parent.mkdir(parents=True, exist_ok=True)
        storage._publish_new_bytes(target, raw)
    storage._publish_new_bytes(destination / "heat_action_dataset.json", raw_product)
    _recheck(root, snapshots, code)
    # Publish completion only after checking the copied evidence and clean product.
    _check_package(root, folder, contents)
    storage._publish_new_bytes(destination / "dataset_contents.json", json_bytes(contents))
    return folder


def _check_code(root, folder, fingerprints):
    for name, digest in fingerprints.items():
        path = PurePosixPath(name)
        if (not name or name == "." or path.is_absolute() or ".." in path.parts or "\\" in name
                or PureWindowsPath(name).drive or path.as_posix() != name):
            raise ValueError("Assembly code paths must stay inside the archived code folder.")
        if sha256_bytes(_dataset_file(root, folder + "/artifacts/code/" + name).read_bytes()) != digest:
            raise ValueError("Preserved assembly code differs from its saved fingerprint.")
    required = {"src/dataset_assembly.py", "src/plan_reviews.py", "schemas/heat_action_dataset.schema.json", "schemas/dataset_contents.schema.json"}
    if not required.issubset(fingerprints):
        raise ValueError("Missing assembly code or schema evidence.")


def _load_archived_reviews(root: Path, folder: str, selections: list[dict]) -> list[ReviewedInput]:
    """Resolve fixed identities, then check each preserved four-file review."""
    snapshots = []
    for selection in selections:
        original, plan_id, review_id = _review_folder(selection["review_path"])
        if (selection["review_path"] != original or selection["plan_id"] != plan_id or selection["review_id"] != review_id):
            raise ValueError("Dataset contents must identify canonical review paths and matching plan/review IDs.")
        archived = f"{folder}/inputs/{plan_id}/{review_id}"
        item = _load_review(root, archived, plan_id, review_id)
        if ({name: sha256_bytes(raw) for name, raw in item.files.items()} != selection["files"]
                or item.record["source"]["run_id"] != selection["run_id"]):
            raise ValueError("Archived review files differ from their dataset selections.")
        snapshots.append(item)
    return snapshots


def _check_product(root: Path, folder: str, contents: dict, snapshots: list[ReviewedInput]) -> dict:
    """Rebuild expected clean data from archived reviews, never from live drafts."""
    raw = _dataset_file(root, folder + "/heat_action_dataset.json").read_bytes()
    data = validation._decode_json(raw.decode("utf-8"))
    _require_valid(_schema(data, "heat_action_dataset"))
    if (data != _product(snapshots) or sha256_bytes(raw) != contents["dataset"]["sha256"]
            or contents["dataset"]["plan_count"] != len(snapshots)
            or contents["dataset"]["action_count"] != sum(len(item.data["actions"]) for item in snapshots)):
        raise ValueError("Combined data, counts, and fingerprints must match the exact reviewed plan versions.")
    return data


def _check_package(root: Path, folder: str, contents: dict) -> tuple[dict, dict]:
    """Check identity, archived reviews, common workflow, clean data, then code."""
    _require_valid(_schema(contents, "dataset_contents"))
    if contents["dataset_id"] != folder.rsplit("/", 1)[1]:
        raise ValueError("Dataset identity differs from its folder.")

    snapshots = _load_archived_reviews(root, folder, contents["plans"])
    _compatible(snapshots)
    snapshots.sort(key=lambda item: item.plan_id)
    if [item["plan_id"] for item in contents["plans"]] != [item.plan_id for item in snapshots]:
        raise ValueError("Dataset contents must list each plan once in plan-ID order.")

    # A matching E/E+V/C label alone is insufficient: both settings and saved
    # execution-code versions must match the definition recorded at assembly.
    workflow = snapshots[0].workflow
    if (contents["configuration"] != snapshots[0].record["configuration"] or contents["workflow"] != workflow
            or contents["workflow_sha256"] != _workflow_sha(workflow)):
        raise ValueError("The recorded common workflow differs from the preserved source runs.")
    data = _check_product(root, folder, contents, snapshots)
    _check_code(root, folder, contents["assembly_code_files"])
    return data, contents


def load_heat_action_dataset(project_root: Path | str, dataset_path: str) -> tuple[dict, dict]:
    """Validate preserved input copies, common workflow, clean data, and code.

    Later edits/removal of live review folders do not replace archived inputs.
    Their original source runs and supporting evidence must remain preserved.
    """
    root = Path(project_root).resolve()
    folder, _ = _dataset_folder(dataset_path)
    marker = _dataset_file(root, folder + "/dataset_contents.json")
    raw = marker.read_bytes()
    contents = validation._decode_json(raw.decode("utf-8"))
    result = _check_package(root, folder, contents)
    if marker.read_bytes() != raw:
        raise ValueError("Dataset contents changed during loading.")
    return result
