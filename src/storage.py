"""Read and preserve collection metadata, PDFs, preparations, and run records.

The registry is editable collection metadata, so saving deliberately replaces its
previous version. Original PDFs and preparation attempts use new destinations.
Run records and tool logs may grow while running; completed runs and supporting
response/artifact files cannot be overwritten. Use one writer at a time.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import NoReturn

from validation import (
    ValidationProblem,
    parse_pages_json,
    parse_preparation_json,
    parse_registry_json,
    parse_run_record_structure_json,
    parse_tool_log_json,
    parse_validation_report_json,
    validate_preparation_pages,
    validate_registry_structure,
    validate_run_links,
    validate_run_record,
    validate_run_record_structure,
    validate_tool_log,
)


# Reading guide for this module:
# - Run functions create/update/load one attempt and preserve its supporting files.
# - Registry functions replace editable collection metadata.
# - PDF/preparation functions preserve inputs at new destinations.
# - Helpers at the end publish complete files and check project boundaries.
# "Atomic" below means one file changes from old to new in a single publication;
# it does not make a folder of files one transaction or coordinate several writers.
class RegistryValidationError(ValueError):
    """Stop a storage operation while retaining its structured validation problems."""

    def __init__(self, problems: list[ValidationProblem]) -> None:
        # Keep the records for the future CLI, as well as a readable exception message.
        self.problems = problems
        details = "\n".join(
            f"{problem.location or '$'}: {problem.message}" for problem in problems
        )
        # Initialize the ValueError part of this exception with our explanation.
        super().__init__(f"Registry validation failed:\n{details}")


class PreparationValidationError(ValueError):
    """Stop preparation storage while retaining the structured problem report."""

    def __init__(self, problems: list[ValidationProblem]) -> None:
        # Match the registry exception's interface so callers can inspect problems
        # while still distinguishing which kind of saved data could not be used.
        self.problems = problems
        details = "\n".join(
            f"{problem.location or '$'}: {problem.message}" for problem in problems
        )
        super().__init__(f"Preparation validation failed:\n{details}")


class RunValidationError(ValueError):
    """A run or its saved inputs failed checks; preserve the problems for callers."""

    def __init__(self, problems: list[ValidationProblem]) -> None:
        # Keep machine-readable problems as well as the exception's printable
        # summary, so a future CLI can show exact field paths and categories.
        self.problems = problems
        details = "\n".join(f"{problem.location or '$'}: {problem.message}" for problem in problems)
        super().__init__(f"Run validation failed:\n{details}")


def next_run_id(project_root: Path | str, plan_id: str, stage: str) -> str:
    """Suggest an unused numbered ID, including occupied/incomplete run folders.

    This does not reserve the ID. create_run_record claims its directory and
    refuses collisions. Extraction and verification have separate sequences.
    """
    _require_run_identifier(plan_id)
    if stage not in ("extractor", "verifier"):
        raise ValueError("Run stage must be 'extractor' or 'verifier'.")
    prefix = "run_extract" if stage == "extractor" else "run_verify"
    parent = resolve_project_path(project_root, f"runs/{plan_id}")
    largest = 0
    # Count names rather than successful outputs. An empty folder or a file with
    # a numbered run name can be evidence of an interrupted attempt and reserves
    # its number. A suggestion becomes a reservation only when mkdir succeeds.
    if parent.exists():
        for path in parent.iterdir():
            match = re.fullmatch(rf"{prefix}_([0-9]+)", path.name)
            if match:
                largest = max(largest, int(match.group(1)))
    return f"{prefix}_{largest + 1:04d}"


def create_run_record(project_root: Path | str, record: dict) -> str:
    """Validate and save a new running record without reusing an occupied folder.

    The caller supplies observed metadata and saved run settings; storage neither
    starts models nor invents timestamps, measurements, or environment values.
    """
    _require_run_structure(record)
    if record["status"] != "running":
        _run_problem("$.status", "A new run record must start with status 'running'.")
    record_path = _run_record_path(record)
    # Check selected inputs/links before claiming a new folder, then ensure JSON
    # and UTF-8 encoding can succeed before any run file is published.
    _check_stored_run(project_root, record, record_path, set(), {})
    text = _serialize_run_json(record)
    directory = _run_record_file(project_root, record_path).parent
    directory.mkdir(parents=True, exist_ok=False)
    # exist_ok=False is the final collision check. Another occupied destination
    # is refused even if next_run_id suggested this ID earlier.
    try:
        _publish_new_json(directory / "output.json", text)
    except Exception as error:
        _note_run_recovery(error, record_path)
        raise
    return record_path


def save_run_record(project_root: Path | str, record: dict) -> str:
    """Update an existing active record or finalize it once; never replace a completed run.

    Identity, selected preparation, prompts, and chosen configuration stay fixed.
    Previously unknown environment/call measurements may become known; recorded
    values and existing model calls cannot be erased or silently rewritten. A
    failed record without accepted content/review may be finalized after an input
    disappears; its frozen links and surviving evidence remain for later recovery.
    """
    _require_run_structure(record)
    record_path = _run_record_path(record)
    failed_without_output = record["status"] == "failed" and record["content"] is None and record["review"] is None
    # Strict loading is appropriate before using accepted results. Preserving a
    # failure needs a narrower read when the missing source is the failure's
    # cause; that branch must not publish accepted content or change input links.
    previous = (
        _read_run_record_fields(project_root, record_path)
        if failed_without_output else load_run_record(project_root, record_path)
    )
    _require_active_run(previous)
    # Schema validity alone does not authorize a change: compare the proposal
    # with the previous record to protect fixed settings and known observations.
    _check_run_update(previous, record)
    if failed_without_output:
        # Input damage can be the failure itself. Preserve the failure and known
        # measurements without claiming newly accepted content or changing links.
        problems = validate_run_record(record)
        if problems:
            raise RunValidationError(problems)
        _check_run_files(project_root, record, record_path)
    else:
        _check_stored_run(project_root, record, record_path, set(), {})
    text = _serialize_run_json(record)
    try:
        # Replace only the validated active record. Raw response/artifact files
        # take a different path below that always refuses an existing filename.
        _replace_run_json(_run_record_file(project_root, record_path), text)
    except Exception as error:
        _note_run_recovery(error, record_path)
        raise
    return record_path


def load_run_record(project_root: Path | str, record_path: str) -> dict:
    """Load exactly the selected output.json and check its saved files and linked runs.

    Reading never creates files, picks a newer attempt, changes status, retries,
    repairs JSON, or reloads current prompt text over the saved run settings.
    Missing/damaged inputs must be restored explicitly before this strict load.
    """
    return _load_run_record(project_root, record_path, set(), {})


def save_run_file(
    project_root: Path | str, record_path: str, relative_path: str, data: bytes
) -> str:
    """Preserve bytes once under responses/, artifacts/, or validation_report.json.

    relative_path is relative to this run's folder. Raw responses may be invalid
    JSON or empty; preserve them verbatim. Validation reports have their own
    format checks. Use append_run_tool_log for the active ordered tool log.
    """
    record = _read_run_record_fields(project_root, record_path)
    _require_active_run(record)
    # Read identity and lifecycle fields before accepting any bytes. This permits
    # failure evidence to be saved after source loss, while still blocking writes
    # to a completed attempt or through a damaged output.json.
    if not isinstance(data, bytes):
        raise TypeError("A saved run file must contain bytes.")
    if not isinstance(relative_path, str):
        raise TypeError("A run-relative file path must be a string.")
    relative = PurePosixPath(relative_path)
    if (
        relative.is_absolute()
        or ".." in relative.parts or "\\" in relative_path or PureWindowsPath(relative_path).drive
        or (relative_path != "validation_report.json" and (len(relative.parts) < 2 or relative.parts[0] not in {"responses", "artifacts"}))
    ):
        raise ValueError("Save run files under responses/ or artifacts/, or use validation_report.json.")
    path = f"{PurePosixPath(record_path).parent}/{relative.as_posix()}"
    destination = _bound_run_file(project_root, record_path, path)
    if relative_path == "validation_report.json":
        # Reports describe checks on other files, so verify their format and
        # response links. Ordinary raw responses are opaque bytes and may contain
        # malformed JSON; parsing those here would discard useful failure evidence.
        report = _read_validation_report(data.decode("utf-8"), path)
        _check_report_files(project_root, record_path, report)
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        _publish_new_bytes(destination, data)
    except Exception as error:
        _note_run_recovery(error, record_path)
        raise
    return path


def append_run_tool_log(project_root: Path | str, record_path: str, entry: dict) -> str:
    """Append one completed tool request atomically, preserving every earlier entry.

    Return the path to put in the active record's tool_log_path. This file and
    record update are separate saves; a failure retains the log for inspection.
    """
    record = _read_run_record_fields(project_root, record_path)
    _require_active_run(record)
    path = f"{PurePosixPath(record_path).parent}/tool_log.json"
    if record["tool_log_path"] not in (None, path):
        _run_problem("$.tool_log_path", "Append tool activity to this run's tool_log.json.")
    destination = _bound_run_file(project_root, record_path, path)
    entries = _read_tool_log(destination.read_text(encoding="utf-8"), path) if destination.exists() else []
    # Build a new list with one extra entry. The caller cannot replace or reorder
    # earlier log rows through this function. Input dictionaries are not edited.
    candidate = entries + [entry]
    problems = validate_tool_log(candidate)
    if problems:
        raise RunValidationError(problems)
    text = _serialize_run_json(candidate)
    try:
        if destination.exists():
            # The active log is the exception to save-once supporting files:
            # publish the complete longer list rather than append half a JSON row.
            _replace_run_json(destination, text)
        else:
            _publish_new_json(destination, text)
    except Exception as error:
        _note_run_recovery(error, record_path)
        raise
    return path


def _load_run_record(
    project_root: Path | str, record_path: str, visiting: set[str], cache: dict[str, dict]
) -> dict:
    """Follow exact saved links once and reject cycles rather than recurse forever."""
    record_path = str(PurePosixPath(record_path))
    # visiting tracks links still being checked; cache holds fully checked runs.
    # A link back into visiting is a cycle. A second link to a cached extraction
    # can reuse its result within this single load instead of checking it again.
    if record_path in visiting:
        _run_problem(record_path, "A cycle was found in the saved run links.")
    if record_path in cache:
        return cache[record_path]
    record = _read_run_record_fields(project_root, record_path)
    visiting.add(record_path)
    try:
        _check_stored_run(project_root, record, record_path, visiting, cache)
    finally:
        # Remove this in-progress marker even on error. Only successful checks
        # reach the cache assignment; damaged targets never become accepted data.
        visiting.remove(record_path)
    cache[record_path] = record
    return record


def _read_run_record_fields(project_root: Path | str, record_path: str) -> dict:
    """Trust no lifecycle/identity fields until the saved JSON has passed its schema.

    Evidence writers use this smaller check so missing source inputs cannot stop
    them preserving failure evidence. Full load_run_record also checks all inputs.
    """
    record_path = str(PurePosixPath(record_path))
    file = _run_record_file(project_root, record_path)
    record, problems = parse_run_record_structure_json(file.read_text(encoding="utf-8"))
    if problems:
        raise RunValidationError(_problems_in_preparation_file(record_path, problems))
    assert record is not None
    # This assert documents our parser's success contract. Input validation is
    # performed above and does not depend on Python assertions being enabled.
    if _run_record_path(record) != record_path:
        _run_problem(record_path, "The run's plan/run IDs do not match its selected output.json path.")
    return record


def _check_stored_run(
    project_root: Path | str, record: dict, record_path: str, visiting: set[str], cache: dict[str, dict]
) -> None:
    # A trusted page count comes from the exact preserved preparation. The model
    # cannot choose its own count to make out-of-range evidence appear valid.
    preparation = _check_run_source(project_root, record)
    problems = validate_run_record(record, page_count=preparation["page_count"])
    if problems:
        raise RunValidationError(problems)
    _check_run_files(project_root, record, record_path)
    targets = {}
    # Resolve only explicitly named targets in this plan. Do not search for an
    # equivalent/newer run if one is missing: that would change the comparison.
    for field, name in (("input_run_id", "input_run"), ("retry_of_run_id", "retry_run")):
        target = record[field]
        if target is not None:
            path = f"runs/{record['plan_id']}/{target}/output.json"
            targets[name] = _load_run_record(project_root, path, visiting, cache)
    problems = validate_run_links(record, **targets)
    if problems:
        raise RunValidationError(problems)


def _check_run_source(project_root: Path | str, record: dict) -> dict:
    """Use the preserved preparation, allowing later collection metadata corrections."""
    try:
        entry, preparation, _ = load_plan_preparation(project_root, record["plan_id"], record["source_path"])
    except PreparationValidationError as error:
        # Reuse the same source checks as input assembly, while retaining the
        # run API's exception type and its structured error locations.
        raise RunValidationError(error.problems) from error
    if record["purpose"] in {"development", "comparison"} and entry["study_set"] != record["purpose"]:
        _run_problem("$.purpose", "Development/comparison work must match the plan's study-set assignment.")
    if record["content"] is not None:
        # Collection corrections affect future preparations. Earlier content
        # must match the collection values saved with its own preparation.
        for field in ("source_url", "date_accessed"):
            if record["content"]["plan_info"][field] != preparation[field]:
                _run_problem("$.content.plan_info." + field, "Collection values must match the selected preparation snapshot.")
    return preparation


def load_plan_preparation(
    project_root: Path | str, plan_id: str, source_path: str
) -> tuple[dict, dict, list[dict]]:
    """Return (registry entry, preparation, pages) for one explicit usable source.

    Input assembly and run storage share these checks. Current registry metadata
    and preparation links may change; the selected snapshot's URL/date and page
    text remain authoritative for this input. No newer attempt is substituted.
    Missing files propagate OSError; invalid source relationships raise
    PreparationValidationError. This function does not modify files or run OCR.
    """
    _require_run_identifier(plan_id)

    def problem(location: str, message: str) -> NoReturn:
        raise PreparationValidationError([ValidationProblem("reference", location, message)])

    if not isinstance(source_path, str) or re.fullmatch(
        rf"data/processed/{re.escape(plan_id)}/preparation_[0-9]+/preparation\.json", source_path
    ) is None:
        # Restrict the kind of selected file before opening it. Expert references
        # or other project JSON must never become model input through this API.
        problem("$.source_path", "Select a preserved preparation.json for this plan.")
    registry = load_registry(project_root)
    matches = [entry for entry in registry["plans"] if entry["plan_id"] == plan_id]
    if len(matches) != 1:
        problem("$.plan_id", "The source must identify exactly one registered plan.")
    entry = matches[0]
    preparation, pages = load_preparation(project_root, source_path)
    if (
        preparation["plan_id"] != plan_id or preparation["pdf_path"] != entry["pdf_path"]
        or preparation["document_sha256"].lower() != entry["document_sha256"].lower()
    ):
        problem("$.source_path", "The saved preparation does not match the registered PDF identity.")
    pdf_path = resolve_project_path(project_root, entry["pdf_path"])
    with pdf_path.open("rb") as source:
        # Verify actual original bytes; matching names and JSON fields alone do
        # not establish that the PDF still belongs to this saved preparation.
        checksum = hashlib.file_digest(source, "sha256").hexdigest()
    if checksum != entry["document_sha256"].lower():
        problem(entry["pdf_path"], "The preserved PDF no longer matches its registered checksum.")
    if preparation["status"] == "failed" or preparation["page_count"] is None:
        problem("$.source_path", "Model work requires a usable saved preparation.")
    return entry, preparation, pages


def _check_run_files(project_root: Path | str, record: dict, record_path: str) -> None:
    # These checks establish that known supporting files exist and reports/logs
    # have valid structure. Raw answer correctness remains an expert judgment.
    for index, call in enumerate(record["model_calls"]):
        if call["response_path"] is not None:
            _require_response_file(project_root, record_path, call["response_path"])
    folder = str(PurePosixPath(record_path).parent)
    canonical_log = f"{folder}/tool_log.json"
    log_path = record["tool_log_path"]
    if log_path is not None:
        if log_path != canonical_log:
            _run_problem("$.tool_log_path", "The ordered tool log must be saved as this run's tool_log.json.")
        file = _bound_run_file(project_root, record_path, log_path)
        entries = _read_tool_log(file.read_text(encoding="utf-8"), log_path)
        if not entries:
            _run_problem("$.tool_log_path", "Use null when no tools were called.")
    elif record["status"] != "running":
        # A log can be saved before its pointer reaches the active record. Permit
        # that brief intermediate state, but refuse to finalize while hiding it.
        file = _bound_run_file(project_root, record_path, canonical_log)
        if file.exists() and _read_tool_log(file.read_text(encoding="utf-8"), canonical_log):
            _run_problem("$.tool_log_path", "A completed run must link its preserved tool activity.")

    report_path = f"{folder}/validation_report.json"
    # Accepted content/review implies final-response checks were attempted.
    # Their report must survive too, including when a later stage error fails a run.
    report_file = _bound_run_file(project_root, record_path, report_path)
    if report_file.exists():
        report = _read_validation_report(report_file.read_text(encoding="utf-8"), report_path)
        _check_report_files(project_root, record_path, report)
        if record["status"] == "succeeded" and not report["valid"]:
            _run_problem(report_path, "A successful run requires a passing final-response validation report.")
    elif record["status"] == "succeeded" or record["content"] is not None or record["review"] is not None:
        raise FileNotFoundError(f"Final-response validation report is missing: {report_file}")


def _check_report_files(project_root: Path | str, record_path: str, report: dict) -> None:
    raw = _require_response_file(project_root, record_path, report["raw_response_path"])
    repaired_path = report["repaired_response_path"]
    if repaired_path is not None:
        repaired = _require_response_file(project_root, record_path, repaired_path)
        if repaired.resolve() == raw.resolve():
            _run_problem("$.repaired_response_path", "Preserve a repaired candidate separately from the raw response.")


def _require_response_file(project_root: Path | str, record_path: str, path: str) -> Path:
    file = _bound_run_file(project_root, record_path, path)
    expected = PurePosixPath(record_path).parent / "responses"
    if not PurePosixPath(path).is_relative_to(expected):
        _run_problem(path, "Model responses and repaired candidates belong under this run's responses/ folder.")
    if not file.is_file():
        raise FileNotFoundError(f"Saved response is missing: {file}")
    return file


def _read_tool_log(text: str, path: str) -> list[dict]:
    data, problems = parse_tool_log_json(text)
    if problems:
        raise RunValidationError(_problems_in_preparation_file(path, problems))
    assert data is not None
    return data


def _read_validation_report(text: str, path: str) -> dict:
    data, problems = parse_validation_report_json(text)
    if problems:
        raise RunValidationError(_problems_in_preparation_file(path, problems))
    assert data is not None
    return data


def _check_run_update(previous: dict, candidate: dict) -> None:
    # Fixed fields describe which attempt this is. Changing one would turn an
    # update into different work, which needs a new run ID and preserved history.
    for field in (
        "schema_version", "plan_id", "run_id", "stage", "purpose", "input_run_id",
        "retry_of_run_id", "source_path", "started_at",
    ):
        if previous[field] != candidate[field]:
            _run_problem("$." + field, "Run identity and selected inputs cannot change within an attempt.")
    for field in previous["settings"]:
        if field != "environment" and previous["settings"][field] != candidate["settings"][field]:
            _run_problem("$.settings." + field, "Chosen configuration and saved prompt text must stay unchanged; start a new run.")
    for field, value in previous["settings"]["environment"].items():
        # None can become an actual detected value. Use "is not None" rather than
        # truthiness so recorded False and other known values stay protected.
        if value is not None and candidate["settings"]["environment"][field] != value:
            _run_problem("$.settings.environment." + field, "A recorded environment observation cannot be erased or changed.")
    if len(candidate["model_calls"]) < len(previous["model_calls"]):
        _run_problem("$.model_calls", "Previously recorded model calls cannot be removed.")
    for index, call in enumerate(previous["model_calls"]):
        # Keep the old list as a prefix: append calls or fill unknown fields, but
        # do not remove calls, reorder their known data, or change saved responses.
        for field, value in call.items():
            if value is not None and candidate["model_calls"][index][field] != value:
                _run_problem(f"$.model_calls[{index}].{field}", "A recorded model-call observation cannot be erased or changed.")
    if previous["tool_log_path"] is not None and candidate["tool_log_path"] != previous["tool_log_path"]:
        _run_problem("$.tool_log_path", "Previously linked tool activity cannot be hidden or redirected.")


def _require_run_structure(record: object) -> None:
    problems = validate_run_record_structure(record)
    if problems:
        raise RunValidationError(problems)


def _require_active_run(record: dict) -> None:
    if record["status"] != "running":
        _run_problem("$.status", "Completed runs and their preserved files cannot be overwritten; start a new run.")


def _require_run_identifier(value: object) -> None:
    if (
        not isinstance(value, str) or not value.strip() or value in {".", ".."}
        or "/" in value or "\\" in value or "\x00" in value or PureWindowsPath(value).drive
    ):
        raise ValueError("A run/plan ID must be one nonblank portable path component.")


def _run_record_path(record: dict) -> str:
    _require_run_identifier(record["plan_id"])
    _require_run_identifier(record["run_id"])
    return f"runs/{record['plan_id']}/{record['run_id']}/output.json"


def _run_record_file(project_root: Path | str, record_path: str) -> Path:
    relative = PurePosixPath(record_path)
    if len(relative.parts) != 4 or relative.parts[0] != "runs" or relative.parts[-1] != "output.json":
        raise ValueError("Select runs/<plan_id>/<run_id>/output.json explicitly.")
    file = resolve_project_path(project_root, str(relative))
    # Keep run namespaces literal: a symlink must not redirect an attempt into
    # another run or a backup folder, even when both are inside the project.
    if file.resolve() != file:
        raise ValueError("Run folders and output.json must not be redirected through symbolic links.")
    return file


def _bound_run_file(project_root: Path | str, record_path: str, path: str) -> Path:
    folder = _run_record_file(project_root, record_path).parent
    file = resolve_project_path(project_root, path)
    # The lexical check covers the written path; resolve() also follows symlinks.
    # Remaining inside the project is insufficient if the link borrows another run.
    if not file.is_relative_to(folder) or not file.resolve().is_relative_to(folder):
        _run_problem(path, "The file resolves outside the selected run folder.")
    return file


def _serialize_run_json(data: object) -> str:
    # Serialize means convert Python values to JSON text. This only prepares a
    # string in memory; checking its UTF-8 bytes below does not create a file.
    text = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    text.encode("utf-8")
    # Arbitrary tool arguments must already be JSON values: do not silently turn
    # tuples into lists or numeric dictionary keys into strings while saving.
    if json.loads(text) != data:
        raise ValueError("Run data must use JSON-compatible values without implicit conversion.")
    return text


def _replace_run_json(destination: Path, text: str) -> None:
    """Publish a complete active record/log atomically; callers enforce its lifecycle."""
    temporary = None
    # Write beside the destination so os.replace can publish on the same
    # filesystem. flush/fsync request that the complete file data reaches the OS
    # and storage before its final name becomes visible to readers.
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=destination.parent,
            prefix=f".{destination.stem}-", suffix=".tmp", delete=False) as file:
            temporary = Path(file.name)
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _note_run_recovery(error: Exception, record_path: str) -> None:
    # An OS call can complete and then report an error. Leave all completed files
    # in place and attach recovery context; never assume a rollback is safe.
    error.add_note(
        f"Run files retained under {PurePosixPath(record_path).parent}. Inspect {record_path} "
        "before recovery; publication may already have completed. Do not overwrite or automatically retry this attempt."
    )


def _run_problem(location: str, message: str) -> NoReturn:
    # NoReturn tells readers/type checkers that this helper always raises. The
    # surrounding operation stops; it never continues with a repaired guess.
    raise RunValidationError([ValidationProblem("reference", location, message)])


def load_registry(project_root: Path | str) -> dict:
    """Read and structure-check data/registry/plans.json, or raise an error.

    Missing files raise FileNotFoundError; malformed data raises
    RegistryValidationError. Reading never initializes or repairs the registry.
    """
    registry_path = resolve_project_path(project_root, "data/registry/plans.json")
    text = registry_path.read_text(encoding="utf-8")
    registry, problems = parse_registry_json(text)
    if problems:
        raise RegistryValidationError(problems)

    # This is the parser's internal success contract, not an input-validation rule.
    assert registry is not None
    return registry


def save_registry(project_root: Path | str, registry: dict) -> None:
    """Structure-check and atomically save the mutable registry.

    An initial save explicitly creates the registry. Existing damaged registries
    must be restored before this function will replace them. Cross-record and
    source-file checks remain the responsibility of the growing registration flow.
    """
    _require_valid_structure(registry)

    # Serialize before touching files. allow_nan=False keeps output strict JSON;
    # ensure_ascii=False preserves readable Unicode titles in the saved text.
    text = json.dumps(registry, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    registry_path = resolve_project_path(project_root, "data/registry/plans.json")
    if registry_path.exists():
        # A normal save must not silently erase evidence of a damaged registry.
        load_registry(project_root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = None
    try:
        # The temporary file must share the destination's directory: os.replace
        # can then publish the complete file atomically on the same filesystem.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=registry_path.parent,
            prefix=".plans-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(text)
            # Move buffered text to the OS, then request that its file data be synced.
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # Readers see the previous complete registry or the new complete registry.
        # This is an atomic replacement, not a backup or a multi-writer transaction.
        os.replace(temporary_path, registry_path)
    finally:
        # Run cleanup after success or a caught/unhandled exception. An abrupt
        # process kill may leave a temporary file, but it does not publish that file.
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def next_plan_id(project_root: Path | str, registry: dict) -> str:
    """Suggest an ID above existing numbered records and stored PDF filenames.

    This function does not reserve the ID or create files. Registration must use
    it in the one-document-at-a-time workflow and refuse to overwrite originals.
    """
    _require_valid_structure(registry)
    used_ids = {plan["plan_id"] for plan in registry["plans"]}

    raw_directory = resolve_project_path(project_root, "data/raw")
    if raw_directory.exists():
        # A previous interrupted import may have saved its PDF before the registry.
        # Consider filenames even if the corresponding registry entry is missing.
        for path in raw_directory.iterdir():
            if path.suffix.lower() == ".pdf":
                used_ids.add(path.stem)

    largest_number = 0
    for plan_id in used_ids:
        # The schema allows string IDs. Only our generated plan_<number> names
        # contribute to this sequence; another valid string ID cannot collide.
        match = re.fullmatch(r"plan_([0-9]+)", plan_id)
        if match:
            largest_number = max(largest_number, int(match.group(1)))

    # :04d pads to at least four digits; plan_10000 still works after plan_9999.
    return f"plan_{largest_number + 1:04d}"


def preserve_original_pdf(
    project_root: Path | str,
    source_path: Path | str,
    plan_id: str,
    expected_sha256: str,
) -> str:
    """Copy the source bytes to a new raw PDF and return its project-relative path.

    A checksum mismatch or filename collision fails before publication. This
    preserves bytes, but does not check PDF readability or study eligibility.
    """
    if re.fullmatch(r"plan_[0-9]+", plan_id) is None:
        raise ValueError("A stored PDF needs a generated plan_<number> ID.")
    relative_path = f"data/raw/{plan_id}.pdf"
    destination = resolve_project_path(project_root, relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = None
    try:
        # Copy into an independent file first. Linking the supplied source itself
        # would let later source edits change our supposedly preserved original.
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".pdf-", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            with Path(source_path).open("rb") as source_file:
                shutil.copyfileobj(source_file, temporary_file)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # Check the completed copy against the fingerprint used for registration.
        # This also detects source changes between initial hashing and copying.
        with temporary_path.open("rb") as copied_file:
            copied_sha256 = hashlib.file_digest(copied_file, "sha256").hexdigest()
        if copied_sha256 != expected_sha256.lower():
            raise ValueError("The copied PDF differs from its expected checksum; retry import.")

        # A hard link gives our completed temporary file its final name. Unlike
        # os.replace, os.link fails if the destination already exists. Both names
        # refer to our independent copy until the temporary name is removed below.
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return relative_path


def next_preparation_directory(project_root: Path | str, plan_id: str) -> str:
    """Suggest a new project-relative preparation folder without creating it.

    Count existing numbered entries, including incomplete attempts. This does not
    reserve a name; save_preparation must still refuse an occupied destination.
    """
    if re.fullmatch(r"plan_[0-9]+", plan_id) is None:
        raise ValueError("A preparation needs a generated plan_<number> ID.")
    relative_parent = f"data/processed/{plan_id}"
    parent = resolve_project_path(project_root, relative_parent)

    largest_number = 0
    if parent.exists():
        for path in parent.iterdir():
            # Consider names even if they are incomplete folders or unexpected
            # files. Never reuse an occupied preparation number or fill old gaps.
            match = re.fullmatch(r"preparation_([0-9]+)", path.name)
            if match:
                largest_number = max(largest_number, int(match.group(1)))

    # :02d means at least two digits; the sequence can continue past preparation_99.
    return f"{relative_parent}/preparation_{largest_number + 1:02d}"


def save_preparation(
    project_root: Path | str, preparation: dict, pages: list[dict],
    *, artifacts: dict[str, bytes] | None = None,
) -> str:
    """Validate and preserve a new preparation and images, returning its record path.

    The preparation's pages_path selects its new folder. Existing folders are
    never reused, even if empty or damaged. This function does not edit the
    registry, check the original PDF, or establish that an OCR route works.
    """
    problems = validate_preparation_pages(preparation, pages)
    if problems:
        raise PreparationValidationError(problems)
    record_path = _preparation_record_path(preparation)
    relative_directory = str(PurePosixPath(record_path).parent)
    directory = resolve_project_path(project_root, relative_directory)
    artifacts = {} if artifacts is None else artifacts
    # Validate paths, PNGs, and crop dimensions before publishing any files. Every
    # referenced image must be supplied, and unreferenced images are refused.
    _check_preparation_images(project_root, preparation, pages, artifacts=artifacts)

    # Serialize both documents before creating the folder. Encoding and strict
    # JSON failures must not leave an attempt that never started writing data.
    record_text = json.dumps(preparation, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    pages_text = json.dumps(pages, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    # Check UTF-8 encoding now too; isolated Unicode surrogate characters cannot
    # be saved as normal UTF-8, even though Python can hold them in a string.
    record_text.encode("utf-8")
    pages_text.encode("utf-8")

    # exist_ok=False claims a fresh directory and refuses any previous attempt.
    # A suggestion from next_preparation_directory alone does not claim the name.
    directory.mkdir(parents=True, exist_ok=False)
    try:
        for relative_path, image_bytes in artifacts.items():
            destination = resolve_project_path(project_root, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _publish_new_bytes(destination, image_bytes)
        _publish_new_json(directory / "pages.json", pages_text)
        # Publish the record last. A loader needs this file before it can read the
        # pair, so an interrupted pages write cannot look like a completed pair.
        _publish_new_json(directory / "preparation.json", record_text)
    except Exception as error:
        # Keep completed files if a later write fails or publication is uncertain.
        # The next allocation skips this folder rather than overwriting evidence.
        error.add_note(
            f"Preparation folder retained at {relative_directory}. "
            "Inspect its files before recovery; a retry must use a new folder."
        )
        raise
    return record_path


def load_preparation(
    project_root: Path | str, preparation_path: str
) -> tuple[dict, list[dict]]:
    """Read and validate an explicitly selected preparation record and its pages.

    Return (preparation, pages). Missing files raise FileNotFoundError; invalid
    saved JSON or inconsistent data raises PreparationValidationError. Reading
    never repairs data, chooses a newer attempt, or creates missing files.
    """
    record_file = resolve_project_path(project_root, preparation_path)
    preparation, problems = parse_preparation_json(record_file.read_text(encoding="utf-8"))
    if problems:
        raise PreparationValidationError(
            _problems_in_preparation_file(preparation_path, problems)
        )
    assert preparation is not None  # The parser's success contract.

    expected_record_path = _preparation_record_path(preparation)
    if preparation_path != expected_record_path:
        raise PreparationValidationError(
            [
                ValidationProblem(
                    category="reference",
                    location=preparation_path,
                    message=(
                        "Preparation record and pages must belong to the same "
                        f"plan and folder; expected record at {expected_record_path}."
                    ),
                )
            ]
        )

    pages_path = preparation["pages_path"]
    pages_file = resolve_project_path(project_root, pages_path)
    pages, problems = parse_pages_json(pages_file.read_text(encoding="utf-8"))
    if problems:
        raise PreparationValidationError(_problems_in_preparation_file(pages_path, problems))
    assert pages is not None

    problems = validate_preparation_pages(preparation, pages)
    if problems:
        raise PreparationValidationError(problems)
    _check_preparation_images(project_root, preparation, pages)
    return preparation, pages


def _check_preparation_images(
    project_root: Path | str, preparation: dict, pages: list[dict],
    *, artifacts: dict[str, bytes] | None = None,
) -> None:
    """Check preserved image references, using supplied bytes on save and disk on load.

    Fixed filenames keep each page and crop inside its own preparation. Earlier
    version 2 records have no image artifacts and keep their original behavior.
    """
    from PIL import Image

    directory = str(PurePosixPath(preparation["pages_path"]).parent)
    expected_paths = set()
    problems = []

    def inspect_png(path: str, expected_path: str) -> tuple[int, int]:
        if path != expected_path or path in expected_paths:
            raise ValueError(f"Expected a unique preparation image at {expected_path}.")
        expected_paths.add(path)
        resolved = resolve_project_path(project_root, path)
        data = artifacts[path] if artifacts is not None else resolved.read_bytes()
        if not isinstance(data, bytes):
            raise ValueError(f"Image artifact must contain PNG bytes: {path}")
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError(f"Preparation images must be PNG: {path}")
            size = image.size
            image.verify()
        return size

    for index, page in enumerate(pages):
        if preparation["schema_version"] == 2:
            continue
        stem = f"{directory}/images/page_{page['page_number']:04d}"
        try:
            size = None
            if page["image_path"] is not None:
                size = inspect_png(page["image_path"], f"{stem}.png")
            for region_index, region in enumerate(page["image_regions"], start=1):
                left, top, right, bottom = region["bounds"]
                if size is not None and (right > size[0] or bottom > size[1]):
                    raise ValueError("Candidate bounds extend outside the preserved page image.")
                if region["image_path"] is not None:
                    crop_size = inspect_png(
                        region["image_path"], f"{stem}_region_{region_index:02d}.png"
                    )
                    if crop_size != (right - left, bottom - top):
                        raise ValueError("Candidate PNG dimensions differ from its recorded bounds.")
        except (KeyError, ValueError, OSError) as error:
            # Missing files on load retain the normal FileNotFoundError interface.
            if isinstance(error, FileNotFoundError):
                raise
            problems.append(ValidationProblem("reference", f"pages.json:$[{index}]", str(error)))
    if artifacts is not None and set(artifacts) != expected_paths:
        problems.append(ValidationProblem("reference", "pages.json:$",
            "Supplied image artifacts must match every referenced image, with no extra files."))
    if problems:
        raise PreparationValidationError(problems)


def _preparation_record_path(preparation: dict) -> str:
    """Check the storage layout after schema validation, then derive the record path."""
    # The two captured groups are the plan ID and preparation number. Checking
    # the whole path prevents accidental cross-plan links and unexpected layouts.
    match = re.fullmatch(
        r"data/processed/(plan_[0-9]+)/preparation_([0-9]+)/pages\.json",
        preparation["pages_path"],
    )
    if (
        match is None
        or match.group(1) != preparation["plan_id"]
        or int(match.group(2)) < 1
    ):
        raise PreparationValidationError(
            [
                ValidationProblem(
                    category="reference",
                    location="preparation.json:$.pages_path",
                    message=(
                        "Pages must be stored at data/processed/<plan_id>/"
                        "preparation_<positive number>/pages.json for this plan."
                    ),
                )
            ]
        )
    return str(PurePosixPath(preparation["pages_path"]).with_name("preparation.json"))


def _publish_new_json(destination: Path, text: str) -> None:
    """Publish one completed UTF-8 file without replacing an existing filename."""
    _publish_new_bytes(destination, text.encode("utf-8"))


def _publish_new_bytes(destination: Path, data: bytes) -> None:
    """Publish completed JSON or PNG bytes without overwriting earlier evidence."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        # As with original PDF storage, a hard link publishes our independent
        # complete temporary file and refuses to replace an occupied filename.
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _problems_in_preparation_file(
    relative_path: str, problems: list[ValidationProblem]
) -> list[ValidationProblem]:
    """Identify which saved document has an error, preserving schema setup locations."""
    return [
        ValidationProblem(
            problem.category,
            f"{relative_path}:{problem.location or '$'}",
            problem.message,
        )
        if problem.category in {"syntax", "structure"}
        else problem
        for problem in problems
    ]


def _require_valid_structure(registry: dict) -> None:
    """Translate validation reports into an exception that stops the operation."""
    problems = validate_registry_structure(registry)
    if problems:
        raise RegistryValidationError(problems)


def resolve_project_path(project_root: Path | str, relative_path: str) -> Path:
    """Resolve a project-relative path while keeping file operations inside the root."""
    # Stored paths use forward slashes. Check Windows drives even on macOS so
    # a path does not change meaning if the project is moved to another platform.
    relative = Path(relative_path)
    if (
        not relative_path.strip()
        or relative == Path(".")
        or relative.is_absolute()
        or PureWindowsPath(relative_path).drive
        or "\\" in relative_path
        or ".." in relative.parts
    ):
        raise ValueError(f"Expected a project-relative path without parent traversal: {relative_path}")
    root = Path(project_root).resolve()
    path = root / relative
    # resolve follows existing symbolic links too, so a linked data directory
    # cannot accidentally redirect registry operations outside the project.
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Project path resolves outside the project root: {path}")
    return path
