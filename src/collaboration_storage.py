"""Publish C attempts without widening the historical E/V record contract.

Only output.json and the append-only tool log change while an attempt is active.
Supporting evidence is published once. One Python recorder owns an attempt;
MCP may add immutable OCR files but never changes the record itself.
"""

from pathlib import PurePosixPath

from collaboration_contracts import SCHEMAS, validate_bindings, validate_collaboration_response
from models import _json_object
import storage
from artifact_io import canonical_json_bytes
from validation import parse_utc_timestamp, require_run_purpose, validate_run_purpose, _nonfinite_json_numbers, _validate_structure, validate_validation_report
from legacy_records import canonical_data_path, effective_run_purpose, validation_view


def validate_record(record, *, check_settings=True):
    references = tuple((uri, SCHEMAS / filename) for uri, filename in (
        ("urn:heat-adaptation:run", "run.schema.json"),
        ("urn:heat-adaptation:plan-data", "plan_data.schema.json"),
        ("urn:heat-adaptation:collaboration-response", "collaboration_response.schema.json"),
        ("urn:heat-adaptation:collaboration-config", "collaboration_config.schema.json"),
    ))
    problems = _validate_structure(validation_view(record, "collaboration"), SCHEMAS / "collaboration_run.schema.json", "C run",
                                   required_formats=("date", "date-time"), schema_references=references)
    problems += _nonfinite_json_numbers(record)
    if problems:
        raise storage.RunValidationError(problems)
    settings = record["settings"]
    if check_settings:
        validate_bindings(settings["configuration"], settings["profiles"])
    if settings["document_tools"] != settings["profiles"]["coordinator"]["document_tools"]:
        raise ValueError("Saved shared tools must match the C binding.")
    # UTC timestamps may use different fractional precision or Z/+00:00 forms.
    # Compare their times, not the alphabetical order of their representations.
    if (record["ended_at"] is not None
            and parse_utc_timestamp(record["ended_at"]) < parse_utc_timestamp(record["started_at"])):
        raise ValueError("Run end must follow its start.")
    if record["budget"] is not None and record["budget"]["limits"] != settings["configuration"]["limits"]:
        raise ValueError("Observed budget limits must match the saved C configuration.")
    if record["budget"] is not None:
        budget = record["budget"]
        if (budget["model_requests"] > budget["limits"]["max_model_requests"]
                or sum(budget["document_tool_calls"].values()) > budget["limits"]["max_document_tool_calls"]
                or any(count > settings["profiles"][actor]["max_tool_calls"]
                       for actor, count in budget["document_tool_calls"].items())):
            raise ValueError("Recorded C requests and tool submissions exceed their limits.")


def record_path(record):
    storage._require_run_identifier(record["plan_id"])
    storage._require_run_identifier(record["run_id"])
    return f"runs/{record['plan_id']}/{record['run_id']}/output.json"


def read_record(root, path, *, check_settings=True):
    """Read identity/lifecycle without needing a source that may have failed."""
    if not storage._is_collaboration_record(path):
        raise ValueError("Select runs/<plan_id>/run_collaboration_NNNN/output.json.")
    record = _json_object(storage._run_record_file(root, path).read_bytes())
    validate_record(record, check_settings=check_settings)
    if record_path(record) != path:
        raise ValueError("C record identity differs from its folder.")
    return record


def _source(root, record):
    entry, preparation, pages = storage.load_plan_preparation(root, record["plan_id"], record["source_path"])
    problems = validate_run_purpose(record["purpose"], entry["study_set"])
    if problems:
        raise ValueError("; ".join(problem.message for problem in problems))
    if storage.preparation_text_fingerprint(preparation, pages) != record["source_fingerprint"]:
        raise ValueError("The preparation text differs from the C startup fingerprint.")
    return preparation, pages


def _check_retry(root, record):
    """Keep retry provenance valid on creation and later read-only loading.

    Read the prior lifecycle without requiring its source/evidence: a failure
    may have happened before those files could be preserved.
    """
    retry_id = record["retry_of_run_id"]
    if retry_id is None:
        return
    previous = read_record(root, f"runs/{record['plan_id']}/{retry_id}/output.json")
    if (previous["status"] != "failed"
            or canonical_data_path(previous["source_path"]) != canonical_data_path(record["source_path"])
            or effective_run_purpose(previous["purpose"]) != effective_run_purpose(record["purpose"])):
        raise ValueError("Retry links require a failed C attempt for the same source and purpose.")


def _evidence_file(root, path, name):
    file = storage._bound_run_file(root, path, name)
    if not file.is_file():
        raise ValueError(f"Missing preserved C evidence: {name}")
    return file


def _check_files(root, path, record):
    for call in record["model_calls"]:
        _evidence_file(root, path, call["request_path"])
        if call["response_path"] is not None:
            _evidence_file(root, path, call["response_path"])
    if record["tool_log_path"] is not None:
        file = _evidence_file(root, path, record["tool_log_path"])
        from validation import _decode_json
        if not isinstance(_decode_json(file.read_text()), list):
            raise ValueError("C tool log must be a list.")


def _check_record_evidence(root, path, record):
    """Use the same evidence checks before acceptance and on later loading."""
    _check_retry(root, record)
    preparation, pages = _source(root, record)
    _check_files(root, path, record)
    if record["status"] == "succeeded":
        folder = str(PurePosixPath(path).parent)
        saved = _json_object(_evidence_file(root, path, folder + "/artifacts/collaboration_input.json").read_bytes())
        packet = saved.get("packet")
        if not isinstance(packet, dict):
            raise ValueError("Preserved C input must contain a packet object.")
        from agents import _format_plan_source
        expected_packet = {
            "plan_id": record["plan_id"], "source_path": record["source_path"],
            "source_fingerprint": record["source_fingerprint"],
            "configuration": record["settings"]["configuration"], "profiles": record["settings"]["profiles"],
            "page_count": preparation["page_count"],
            "source_metadata": {k: preparation[k] for k in ("source_url", "date_accessed")},
            "source_message": {"role": "user", "content": _format_plan_source(preparation, pages)},
        }
        # Reconstruct the trusted input and compare JSON identities. Missing keys
        # become readable validation errors; bool/int substitutions cannot pass.
        expected = {"packet": expected_packet, "preparation": preparation, "pages": pages}
        if canonical_json_bytes(saved) != canonical_json_bytes(expected):
            raise ValueError("Saved C input differs from its source or settings.")
        validate_collaboration_response({k: record[k] for k in ("plan_data", "plan_issues")},
                                        page_count=packet["page_count"], source_metadata=packet["source_metadata"])
        storage._check_archived_code(root, path)
        report = _json_object(_evidence_file(root, path, folder + "/validation_report.json").read_bytes())
        if validate_validation_report(report) or not report["valid"]:
            raise ValueError("Successful C output requires a valid final-response report.")
        for key in ("raw_response_path", "repaired_response_path"):
            if report[key] is not None:
                _evidence_file(root, path, report[key])
        storage._check_accepted_candidate(root, path, record, report)
        phases = {(call["actor"], call["phase"]) for call in record["model_calls"]}
        if not {("coordinator", "final"), ("worker_1", "worker_result"), ("worker_2", "worker_result")} <= phases:
            raise ValueError("Successful C output requires both worker results and coordinator final generation.")
        if (record["budget"]["model_requests"] != len(record["model_calls"])
                or any(call["completion_status"] != "normal" for call in record["model_calls"])):
            raise ValueError("Successful C calls must complete normally and agree with the budget.")
        controller = _json_object(_evidence_file(root, path, folder + "/artifacts/controller_result.json").read_bytes())
        raw_answer = _json_object(_evidence_file(root, path, report["raw_response_path"]).read_bytes())
        if controller.get("status") != "succeeded" or controller.get("answer") != raw_answer:
            raise ValueError("Preserved C controller result differs from the final model answer.")
        diagnostic = _json_object(_evidence_file(root, path, folder + "/artifacts/quotation_page_report.json").read_bytes())
        if (diagnostic.get("source_path") != record["source_path"]
                or diagnostic.get("source_fingerprint") != record["source_fingerprint"]):
            raise ValueError("C quotation diagnostics must identify this exact source snapshot.")
    return record


def load_collaboration_record(root, path):
    """Strict read-only loading, independent of today's editable prompts/settings."""
    return _check_record_evidence(root, path, read_record(root, path))


def create_collaboration_record(root, record):
    validate_record(record)
    require_run_purpose(record["purpose"])
    if record["status"] != "running":
        raise ValueError("A new C attempt must start running.")
    _check_retry(root, record)
    _source(root, record)
    path = record_path(record)
    directory = storage._run_record_file(root, path).parent
    directory.mkdir(parents=True, exist_ok=False)
    storage._publish_new_json(directory / "output.json", storage._serialize_run_json(record))
    return path


def save_collaboration_record(root, record):
    """Checkpoint or finalize once, keeping settings and known observations fixed."""
    # Full binding checks ran before creation. Fixed settings are compared to
    # the preceding record below; do not re-read every profile schema per chunk.
    validate_record(record, check_settings=False)
    path = record_path(record)
    previous = read_record(root, path, check_settings=False)
    storage._require_active_run(previous)
    mutable = {"status", "ended_at", "elapsed_seconds", "model_calls", "tool_log_path", "budget",
               "stop_reason", "plan_data", "plan_issues", "error"}
    if any(previous[k] != record[k] for k in previous.keys() - mutable):
        raise ValueError("C identity, source, environment, and settings cannot change within an attempt.")
    if len(record["model_calls"]) < len(previous["model_calls"]):
        raise ValueError("Previously recorded C calls cannot be removed.")
    for index, old in enumerate(previous["model_calls"]):
        if any(value is not None and record["model_calls"][index][key] != value for key, value in old.items()):
            raise ValueError("Known C call observations cannot be changed or erased.")
    if previous["tool_log_path"] is not None and previous["tool_log_path"] != record["tool_log_path"]:
        raise ValueError("Previously linked C tool evidence cannot be hidden.")
    _check_files(root, path, record)
    # A failed attempt can be finalized after source loss, never with an answer.
    if record["status"] == "succeeded":
        _check_record_evidence(root, path, record)
    storage._replace_run_json(storage._run_record_file(root, path), storage._serialize_run_json(record))
    return path


def save_collaboration_file(root, path, relative, raw):
    """Use the same run boundary and no-overwrite rules for C and its MCP OCR."""
    storage._require_active_run(read_record(root, path, check_settings=False))
    if not isinstance(raw, bytes) or not isinstance(relative, str):
        raise TypeError("Run evidence needs a relative path and bytes.")
    parts = PurePosixPath(relative)
    if (parts.is_absolute() or ".." in parts.parts or "\\" in relative
            or (relative != "validation_report.json" and (len(parts.parts) < 2 or parts.parts[0] not in {"artifacts", "responses"}))):
        raise ValueError("Preserve C evidence under artifacts/ or responses/.")
    name = f"{PurePosixPath(path).parent}/{relative}"
    destination = storage._bound_run_file(root, path, name)
    if relative == "validation_report.json":
        report = _json_object(raw)
        if validate_validation_report(report):
            raise ValueError("Invalid C final-response report.")
        for key in ("raw_response_path", "repaired_response_path"):
            if report[key] is not None:
                _evidence_file(root, path, report[key])
    destination.parent.mkdir(parents=True, exist_ok=True)
    storage._publish_new_bytes(destination, raw)
    return name


def save_tool_log(root, path, entries):
    """Replace an active log only by appending completed observations."""
    record = read_record(root, path, check_settings=False)
    storage._require_active_run(record)
    name = f"{PurePosixPath(path).parent}/tool_log.json"
    file = storage._bound_run_file(root, path, name)
    text = storage._serialize_run_json(entries)
    if file.exists():
        from validation import _decode_json
        old = _decode_json(file.read_text())
        if entries[:len(old)] != old:
            raise ValueError("Earlier C tool entries cannot change.")
        storage._replace_run_json(file, text)
    else:
        storage._publish_new_json(file, text)
    return name
