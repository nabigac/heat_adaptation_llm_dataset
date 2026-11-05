"""Exercise run file handling in isolated temporary projects, without LLM calls.

The source PDF contains blank fixture pages; prepared text and model outputs are
fictional. These tests check identity and preservation, not extraction fidelity.
"""
# The project fixture supplies real temporary files and a shared fictional
# run_record from conftest.py. Read the lifecycle helpers first, then tests of
# updates, file boundaries, linked runs, and interrupted writes. All filesystem
# damage and monkeypatch failures are limited to these temporary projects.

import copy
import hashlib
import json
from pathlib import Path

import pytest
from pypdf import PdfWriter

import storage
import validation
import agents


@pytest.fixture
def project(tmp_path: Path, run_record: dict) -> Path:
    # Build enough source identity and preparation state for strict run loading.
    # The PDF is intentionally blank and its prepared/model text is fictional: the
    # checks here concern saved identities and relationships, not content fidelity.
    root = tmp_path / "project"
    root.mkdir()
    pdf_path = root / "data/raw/plan_0099.pdf"
    pdf_path.parent.mkdir(parents=True)
    with PdfWriter() as writer:
        for _ in range(5):
            writer.add_blank_page(width=100, height=100)
        writer.write(pdf_path)
    checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    preparation = {
        "schema_version": 3, "plan_id": "plan_0099", "pdf_path": "data/raw/plan_0099.pdf",
        "document_sha256": checksum, "source_url": "https://example.org/plan.pdf", "date_accessed": "2026-11-03",
        "prepared_at": "2026-11-03T11:00:00Z", "pages_path": "data/processed/plan_0099/preparation_02/pages.json",
        "page_count": 5, "settings": {
            "ocr_enabled": False, "ocr_engine": None, "ocr_version": None, "ocr_language": None,
            "image_render_dpi": 150, "candidate_image_min_area": 0.10,
        }, "status": "ready", "problem": None,
    }
    pages = [{
        "page_number": number, "text": "Fixture prepared text.", "text_source": "native",
        "readable": True, "image_available": False, "image_path": None, "image_regions": [], "problem": None,
    } for number in range(1, 6)]
    source_path = storage.save_preparation(root, preparation, pages)
    storage.save_registry(root, {"schema_version": 1, "plans": [{
        "plan_id": "plan_0099", "plan_title": "Fictional test plan", "pdf_path": "data/raw/plan_0099.pdf",
        "document_sha256": checksum, "source_url": preparation["source_url"], "date_accessed": preparation["date_accessed"],
        "study_set": "development", "prepared_source_path": source_path,
    }]})
    return root


def running(record: dict, run_id: str = "run_extract_0001", *, stage: str = "extractor", input_run_id=None) -> dict:
    # Deep-copy the complete fixture before removing final results. This leaves
    # the original template available for constructing the later successful record
    # and prevents setup changes leaking between examples.
    result = copy.deepcopy(record)
    result.update(run_id=run_id, stage=stage, input_run_id=input_run_id, status="running", ended_at=None,
        elapsed_seconds=None, content=None, review=None, model_calls=[], tool_log_path=None, error=None)
    result["settings"]["stage"] = stage
    return result


@pytest.fixture
def active_run(project: Path, run_record: dict) -> str:
    return storage.create_run_record(project, running(run_record))


def snapshot(root: Path) -> dict:
    # Compare byte contents of every saved file. The assertion protects evidence
    # contents; it does not by itself assert that modification times are identical.
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def passing_report(raw_path: str) -> dict:
    return {"raw_response_path": raw_path, "repaired_response_path": None, "initial_errors": [],
        "remaining_errors": [], "repairs": [], "valid": True}


def publish_response(project: Path, path: str, record: dict) -> None:
    # Simulate the required order: preserve raw bytes, then a report pointing to
    # those bytes, then let the test finalize its record. No model or repair code
    # runs here; the report is explicitly constructed fixture data.
    raw_path = storage.save_run_file(project, path, "responses/response_01.json", json.dumps({
        "content": record["content"], "review": record["review"],
    }, ensure_ascii=False).encode("utf-8"))
    record["model_calls"][0]["response_path"] = raw_path
    storage.save_run_file(project, path, "validation_report.json", json.dumps(passing_report(raw_path)).encode())


def complete(project: Path, path: str, record: dict) -> None:
    # Successful finalization must find its supporting response/report files
    # already saved. Keeping that order in one helper makes lifecycle tests easier
    # to read without hiding an actual model request.
    publish_response(project, path, record)
    storage.save_run_record(project, record)


def tool_entry(**changes) -> dict:
    result = {"tool": "page_text", "arguments": {"page_number": 1}, "result": {"text": "Exact fixture text."},
        "elapsed_seconds": 0.25, "error": None}
    result.update(changes)
    return result


def test_id_suggestion_creates_no_files_and_separates_stages(tmp_path: Path) -> None:
    assert storage.next_run_id(tmp_path, "plan_0099", "extractor") == "run_extract_0001"
    assert storage.next_run_id(tmp_path, "plan_0099", "verifier") == "run_verify_0001"
    assert list(tmp_path.iterdir()) == []


def test_id_suggestion_skips_files_incomplete_folders_and_old_gaps(tmp_path: Path) -> None:
    parent = tmp_path / "runs/plan_0099"
    (parent / "run_extract_0002").mkdir(parents=True)
    (parent / "run_extract_0042").write_text("incomplete occupied number")
    (parent / "run_verify_9999").mkdir()
    assert storage.next_run_id(tmp_path, "plan_0099", "extractor") == "run_extract_0043"
    assert storage.next_run_id(tmp_path, "plan_0099", "verifier") == "run_verify_10000"
    assert storage.next_run_id(tmp_path, "plan_0001", "extractor") == "run_extract_0001"


@pytest.mark.parametrize("plan_id", ["../other", "", "plan/other", "C:other", None])
def test_id_suggestion_rejects_unsafe_plan_ids(tmp_path: Path, plan_id: object) -> None:
    with pytest.raises(ValueError):
        storage.next_run_id(tmp_path, plan_id, "extractor")
    assert list(tmp_path.iterdir()) == []


def test_id_suggestion_rejects_unknown_stage(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="stage"):
        storage.next_run_id(tmp_path, "plan_0099", "expert")


def test_create_and_load_preserve_values_and_all_source_files(project: Path, run_record: dict) -> None:
    before_sources = snapshot(project)
    record = running(run_record)
    before_record = copy.deepcopy(record)
    path = storage.create_run_record(project, record)
    assert path == "runs/plan_0099/run_extract_0001/output.json"
    assert storage.load_run_record(project, path) == before_record
    assert record == before_record
    assert all((project / name).read_bytes() == data for name, data in before_sources.items())
    loaded = storage.load_run_record(project, path)
    loaded["settings"]["name"] = "Only an in-memory edit."
    assert storage.load_run_record(project, path) == before_record


@pytest.mark.parametrize("damage", ["missing-field", "completed-status", "unregistered-plan"])
def test_invalid_creation_does_not_publish_a_run(project: Path, run_record: dict, damage: str) -> None:
    record = running(run_record)
    if damage == "missing-field":
        del record["settings"]
    elif damage == "completed-status":
        record = copy.deepcopy(run_record)
    else:
        record["plan_id"] = "plan_9999"
    before = snapshot(project)
    with pytest.raises(storage.RunValidationError):
        storage.create_run_record(project, record)
    assert snapshot(project) == before
    assert not (project / "runs").exists()


@pytest.mark.parametrize("occupied", ["empty", "partial", "file"])
def test_creation_refuses_occupied_run_folders(project: Path, run_record: dict, occupied: str) -> None:
    folder = project / "runs/plan_0099/run_extract_0001"
    folder.parent.mkdir(parents=True)
    if occupied == "file":
        folder.write_bytes(b"retain occupied path")
    else:
        folder.mkdir()
        if occupied == "partial":
            (folder / "retained.txt").write_bytes(b"partial attempt evidence")
    before = snapshot(project)
    with pytest.raises(FileExistsError):
        storage.create_run_record(project, running(run_record))
    assert snapshot(project) == before
    assert storage.next_run_id(project, "plan_0099", "extractor") == "run_extract_0002"


def test_successful_finalization_round_trips_all_measurements(project: Path, active_run: str, run_record: dict) -> None:
    complete(project, active_run, run_record)
    assert storage.load_run_record(project, active_run) == run_record
    assert json.loads((project / active_run).read_text())["elapsed_seconds"] == 1.0


@pytest.mark.parametrize("invalid_link", [False, True])
def test_real_repair_report_and_texts_can_be_saved_before_finalization(
    project: Path, active_run: str, run_record: dict, invalid_link: bool,
) -> None:
    # Exercise the actual validation/repair result with the existing storage API.
    # Raw -> separate candidate -> report -> final record is deliberate: a report
    # must never point to response files that have not been preserved yet.
    answer = copy.deepcopy({"content": run_record["content"], "review": run_record["review"]})
    if invalid_link:
        answer["content"]["plan_actions"][0]["related_goal_ids"] = ["missing_goal"]
    raw = "```json\n" + json.dumps(answer, ensure_ascii=False) + "\n```"
    raw_path = storage.save_run_file(project, active_run, "responses/response_01.txt", raw.encode("utf-8"))
    result = validation.validate_and_repair_agent_response(
        raw, page_count=5, stage="extractor", completion_status="normal", raw_response_path=raw_path,
    )
    repaired_path = storage.save_run_file(
        project, active_run, "responses/repaired_final.txt", result.candidate_text.encode("utf-8")
    )
    storage.save_run_file(project, active_run, "validation_report.json", json.dumps(result.report).encode("utf-8"))
    final = copy.deepcopy(run_record)
    final["model_calls"][0]["response_path"] = raw_path
    if result.response is None:
        final.update(status="failed", content=None, review=None, error="Final response contains an invalid record link.")
    else:
        final.update(content=result.response["content"], review=result.response["review"])
    storage.save_run_record(project, final)
    assert storage.load_run_record(project, active_run) == final
    assert (project / raw_path).read_bytes() == raw.encode("utf-8")
    assert (project / repaired_path).read_bytes() == json.dumps(answer, ensure_ascii=False).encode("utf-8")
    assert json.loads((project / active_run).with_name("validation_report.json").read_text()) == result.report


def test_completed_run_keeps_loaded_settings_after_config_and_prompts_are_removed(project: Path, run_record: dict) -> None:
    # Start with the fixture's editable configuration, load it once, and supply
    # explicitly fictional observed environment values. This checks the boundary
    # between today's configuration loader and the existing saved-run APIs.
    profile = copy.deepcopy(run_record["settings"])
    tools = profile.pop("document_tools")
    profile.pop("prompt_texts")
    environment = profile.pop("environment")
    config = {"schema_version": 1, "document_tools": tools, "profiles": [profile]}
    (project / "configs").mkdir()
    config_file = project / "configs/profiles.json"
    config_file.write_text(json.dumps(config), encoding="utf-8")
    prompt_files = []
    for index, prompt_path in enumerate(profile["prompt_paths"]):
        path = project / prompt_path
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(f"Exact instruction {index}.\r\n".encode("utf-8"))
        prompt_files.append(path)
    settings = agents.load_profile(project, profile["name"], stage="extractor")
    settings["environment"] = environment
    final = copy.deepcopy(run_record)
    final["settings"] = settings
    active = storage.create_run_record(project, running(final))
    complete(project, active, final)

    config_file.unlink()
    for path in prompt_files:
        path.unlink()
    loaded = storage.load_run_record(project, active)
    assert loaded == final
    assert loaded["settings"]["prompt_texts"] == ["Exact instruction 0.\r\n", "Exact instruction 1.\r\n"]


def test_failed_finalization_preserves_unknown_measurements(project: Path, active_run: str) -> None:
    record = storage.load_run_record(project, active_run)
    record.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Controlled model timeout.")
    storage.save_run_record(project, record)
    assert storage.load_run_record(project, active_run) == record
    assert record["elapsed_seconds"] is None


def test_active_measurements_can_become_known_without_replacing_previous_observations(project: Path, active_run: str) -> None:
    record = storage.load_run_record(project, active_run)
    record["model_calls"] = [{"input_tokens": None, "output_tokens": None, "finish_reason": None, "truncated": None, "response_path": None}]
    storage.save_run_record(project, record)
    path = storage.save_run_file(project, active_run, "responses/response_01.json", b"raw provider response")
    record["model_calls"][0].update(input_tokens=10, output_tokens=20, finish_reason="stop", truncated=False, response_path=path)
    record["settings"]["environment"]["runtime_version"] = "fixture-version"
    storage.save_run_record(project, record)
    assert storage.load_run_record(project, active_run) == record


@pytest.mark.parametrize("field", ["purpose", "source_path", "started_at"])
def test_run_inputs_cannot_change_during_an_attempt(project: Path, active_run: str, field: str) -> None:
    record = storage.load_run_record(project, active_run)
    record[field] = {"purpose": "exploratory", "source_path": "data/processed/plan_0099/preparation_03/preparation.json",
        "started_at": "2026-11-03T11:59:59Z"}[field]
    before = (project / active_run).read_bytes()
    with pytest.raises(storage.RunValidationError, match="cannot change"):
        storage.save_run_record(project, record)
    assert (project / active_run).read_bytes() == before


@pytest.mark.parametrize("field", ["name", "prompt_texts", "generation", "document_tools"])
def test_saved_run_configuration_cannot_change_during_an_attempt(project: Path, active_run: str, field: str) -> None:
    record = storage.load_run_record(project, active_run)
    if field == "name":
        record["settings"][field] = "changed-profile"
    elif field == "prompt_texts":
        record["settings"][field][0] = "Changed instructions."
    elif field == "generation":
        record["settings"][field]["temperature"] = 0.5
    else:
        record["settings"][field]["image_render_dpi"] = 300
    before = (project / active_run).read_bytes()
    with pytest.raises(storage.RunValidationError, match="stay unchanged"):
        storage.save_run_record(project, record)
    assert (project / active_run).read_bytes() == before


@pytest.mark.parametrize("change", ["erase-environment", "change-call", "remove-call"])
def test_known_observations_cannot_be_erased_or_rewritten(project: Path, active_run: str, change: str) -> None:
    record = storage.load_run_record(project, active_run)
    record["settings"]["environment"]["runtime_version"] = "observed-fixture-version"
    record["model_calls"] = [{"input_tokens": 10, "output_tokens": None, "finish_reason": None, "truncated": None, "response_path": None}]
    storage.save_run_record(project, record)
    if change == "erase-environment":
        record["settings"]["environment"]["runtime_version"] = None
    elif change == "change-call":
        record["model_calls"][0]["input_tokens"] = 11
    else:
        record["model_calls"] = []
    before = snapshot(project)
    with pytest.raises(storage.RunValidationError):
        storage.save_run_record(project, record)
    assert snapshot(project) == before


@pytest.mark.parametrize("status", ["succeeded", "failed"])
def test_completed_runs_and_all_file_writers_are_protected(project: Path, active_run: str, run_record: dict, status: str) -> None:
    if status == "succeeded":
        complete(project, active_run, run_record)
    else:
        failed = storage.load_run_record(project, active_run)
        failed.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Controlled failure.")
        storage.save_run_record(project, failed)
    before = snapshot(project)
    with pytest.raises(storage.RunValidationError, match="Completed runs"):
        storage.save_run_record(project, storage.load_run_record(project, active_run))
    with pytest.raises(storage.RunValidationError, match="Completed runs"):
        storage.save_run_file(project, active_run, "responses/new.txt", b"new response")
    with pytest.raises(storage.RunValidationError, match="Completed runs"):
        storage.append_run_tool_log(project, active_run, tool_entry())
    assert snapshot(project) == before


def test_raw_responses_are_preserved_verbatim_and_never_overwritten(project: Path, active_run: str) -> None:
    # Malformed JSON and even invalid UTF-8 remain useful failure evidence. The
    # byte-saving function must not decode, repair, or replace that original payload.
    raw = b'not valid JSON\n```json\n{"unfinished":\xff'
    path = storage.save_run_file(project, active_run, "responses/raw.txt", raw)
    assert (project / path).read_bytes() == raw
    with pytest.raises(FileExistsError):
        storage.save_run_file(project, active_run, "responses/raw.txt", b"replacement")
    assert (project / path).read_bytes() == raw
    empty = storage.save_run_file(project, active_run, "responses/empty.txt", b"")
    assert (project / empty).read_bytes() == b""


@pytest.mark.parametrize("path", ["output.json", "tool_log.json", "../other.txt", "/tmp/file.txt", "C:/file.txt", "responses/../../other.txt"])
def test_supporting_file_paths_cannot_replace_metadata_or_escape_the_run(project: Path, active_run: str, path: str) -> None:
    before = snapshot(project)
    with pytest.raises((ValueError, storage.RunValidationError)):
        storage.save_run_file(project, active_run, path, b"unwanted write")
    assert snapshot(project) == before


def test_run_file_symlink_cannot_borrow_another_runs_artifact_folder(project: Path, active_run: str) -> None:
    other = project / "runs/plan_0099/run_extract_0002/artifacts"
    other.mkdir(parents=True)
    (project / active_run).parent.joinpath("artifacts").symlink_to(other, target_is_directory=True)
    with pytest.raises(storage.RunValidationError, match="outside"):
        storage.save_run_file(project, active_run, "artifacts/image.png", b"bytes")
    assert list(other.iterdir()) == []


def test_tool_log_appends_in_order_and_must_be_linked_at_completion(project: Path, active_run: str, run_record: dict) -> None:
    first = tool_entry()
    second = tool_entry(tool="ocr", result=None, elapsed_seconds=None, error="Controlled OCR error.")
    log_path = storage.append_run_tool_log(project, active_run, first)
    storage.append_run_tool_log(project, active_run, second)
    assert json.loads((project / log_path).read_text()) == [first, second]
    publish_response(project, active_run, run_record)
    with pytest.raises(storage.RunValidationError, match="link its preserved tool activity"):
        storage.save_run_record(project, run_record)
    run_record["tool_log_path"] = log_path
    storage.save_run_record(project, run_record)
    assert storage.load_run_record(project, active_run) == run_record


@pytest.mark.parametrize("entry", [
    {}, tool_entry(elapsed_seconds=-1), tool_entry(result=[]),
    tool_entry(arguments={"value": float("inf")}), tool_entry(elapsed_seconds=float("nan")),
])
def test_invalid_tool_entries_do_not_change_the_saved_log(project: Path, active_run: str, entry: dict) -> None:
    path = storage.append_run_tool_log(project, active_run, tool_entry())
    before = (project / path).read_bytes()
    with pytest.raises(storage.RunValidationError):
        storage.append_run_tool_log(project, active_run, entry)
    assert (project / path).read_bytes() == before


@pytest.mark.parametrize("arguments", [{1: "numeric-key"}, {"tuple": (1, 2)}])
def test_tool_arguments_are_not_silently_converted_while_saving(project: Path, active_run: str, arguments: dict) -> None:
    with pytest.raises(ValueError, match="implicit conversion"):
        storage.append_run_tool_log(project, active_run, tool_entry(arguments=arguments))
    assert not (project / active_run).with_name("tool_log.json").exists()


def test_linked_tool_log_cannot_be_hidden_later(project: Path, active_run: str) -> None:
    record = storage.load_run_record(project, active_run)
    record["tool_log_path"] = storage.append_run_tool_log(project, active_run, tool_entry())
    storage.save_run_record(project, record)
    record["tool_log_path"] = None
    with pytest.raises(storage.RunValidationError, match="hidden"):
        storage.save_run_record(project, record)


def test_success_requires_existing_raw_response_and_validation_report(project: Path, active_run: str, run_record: dict) -> None:
    with pytest.raises(FileNotFoundError, match="response"):
        storage.save_run_record(project, run_record)
    storage.save_run_file(project, active_run, "responses/response_01.json", b"raw")
    with pytest.raises(FileNotFoundError, match="validation report"):
        storage.save_run_record(project, run_record)
    assert storage.load_run_record(project, active_run)["status"] == "running"


def test_failed_validation_keeps_unparseable_raw_response_and_report(project: Path, active_run: str, run_record: dict) -> None:
    raw_path = storage.save_run_file(project, active_run, "responses/response_01.json", b'{"unfinished":')
    error = {"category": "syntax", "location": "line 1, column 15", "message": "Missing value."}
    report = dict(passing_report(raw_path), initial_errors=[error], remaining_errors=[error], valid=False)
    storage.save_run_file(project, active_run, "validation_report.json", json.dumps(report).encode())
    failed = copy.deepcopy(run_record)
    failed.update(status="failed", content=None, review=None, error="Final JSON did not validate.")
    storage.save_run_record(project, failed)
    assert storage.load_run_record(project, active_run) == failed
    assert (project / raw_path).read_bytes() == b'{"unfinished":'


def test_success_cannot_use_a_failing_validation_report(project: Path, active_run: str, run_record: dict) -> None:
    raw = storage.save_run_file(project, active_run, "responses/response_01.json", b"raw")
    error = {"category": "structure", "location": "$", "message": "Missing field."}
    report = dict(passing_report(raw), initial_errors=[error], remaining_errors=[error], valid=False)
    storage.save_run_file(project, active_run, "validation_report.json", json.dumps(report).encode())
    with pytest.raises(storage.RunValidationError, match="passing"):
        storage.save_run_record(project, run_record)


def test_repaired_candidate_is_separate_and_both_files_survive(project: Path, active_run: str) -> None:
    raw = storage.save_run_file(project, active_run, "responses/raw.txt", b"```json\n{}\n```")
    repaired = storage.save_run_file(project, active_run, "responses/repaired_final.txt", b"{}")
    report = dict(passing_report(raw), repaired_response_path=repaired,
        initial_errors=[{"category": "syntax", "location": None, "message": "Code fence."}],
        repairs=[{"rule": "json_code_fence", "location": "$", "before": "```json\n{}\n```", "after": "{}"}])
    storage.save_run_file(project, active_run, "validation_report.json", json.dumps(report).encode())
    assert (project / raw).read_bytes().startswith(b"```")
    assert (project / repaired).read_bytes() == b"{}"


@pytest.mark.parametrize("bad_report", ["malformed", "contradictory-validity", "same-raw-and-repaired", "missing-raw"])
def test_invalid_reports_are_rejected_before_publication(project: Path, active_run: str, bad_report: str) -> None:
    raw = storage.save_run_file(project, active_run, "responses/raw.txt", b"raw")
    report = passing_report(raw)
    if bad_report == "malformed":
        data = b'{"unfinished":'
    else:
        if bad_report == "contradictory-validity":
            report["remaining_errors"] = [{"category": "syntax", "location": None, "message": "Still invalid."}]
        elif bad_report == "same-raw-and-repaired":
            report.update(repaired_response_path=raw, repairs=[{"rule": "fixture", "location": "$", "before": "x", "after": ""}])
        else:
            report["raw_response_path"] = str(Path(raw).with_name("missing.txt"))
        data = json.dumps(report).encode()
    with pytest.raises((storage.RunValidationError, FileNotFoundError)):
        storage.save_run_file(project, active_run, "validation_report.json", data)
    assert not (project / active_run).with_name("validation_report.json").exists()


@pytest.mark.parametrize("damage", ["missing-pdf", "changed-pdf", "missing-preparation", "damaged-pages", "missing-registry"])
def test_damaged_source_files_stop_loading_without_repair_or_status_changes(project: Path, active_run: str, damage: str) -> None:
    paths = {
        "missing-pdf": project / "data/raw/plan_0099.pdf",
        "changed-pdf": project / "data/raw/plan_0099.pdf",
        "missing-preparation": project / "data/processed/plan_0099/preparation_02/preparation.json",
        "damaged-pages": project / "data/processed/plan_0099/preparation_02/pages.json",
        "missing-registry": project / "data/registry/plans.json",
    }
    file = paths[damage]
    if damage.startswith("missing"):
        file.unlink()
    else:
        file.write_bytes(b"damaged fixture data")
    before = snapshot(project)
    with pytest.raises((FileNotFoundError, storage.RunValidationError, storage.PreparationValidationError)):
        storage.load_run_record(project, active_run)
    assert snapshot(project) == before


@pytest.mark.parametrize("missing_input", ["data/raw/plan_0099.pdf", "data/processed/plan_0099/preparation_02/preparation.json"])
def test_failure_evidence_can_be_preserved_after_an_input_disappears(
    project: Path, active_run: str, missing_input: str
) -> None:
    # Saving failure evidence and using accepted output need different checks.
    # Preservation remains possible for this active attempt, but strict loading
    # still refuses reuse until the original input is restored.
    record = storage.load_run_record(project, active_run)
    (project / missing_input).unlink()
    raw_path = storage.save_run_file(project, active_run, "responses/failure.txt", b"Actual available response bytes.")
    record["tool_log_path"] = storage.append_run_tool_log(project, active_run, tool_entry(
        result=None, elapsed_seconds=None, error="The selected input disappeared."
    ))
    record["model_calls"] = [{"input_tokens": None, "output_tokens": None, "finish_reason": None,
        "truncated": None, "response_path": raw_path}]
    record.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Input unavailable; restore it before reuse.")
    storage.save_run_record(project, record)
    assert json.loads((project / active_run).read_text()) == record
    assert (project / raw_path).read_bytes() == b"Actual available response bytes."
    assert record["elapsed_seconds"] is None
    with pytest.raises(FileNotFoundError):
        storage.load_run_record(project, active_run)
    with pytest.raises(storage.RunValidationError, match="Completed runs"):
        storage.save_run_file(project, active_run, "responses/another.txt", b"blocked")


def test_new_preparation_and_collection_corrections_do_not_rewrite_earlier_inputs(project: Path, active_run: str, run_record: dict) -> None:
    complete(project, active_run, run_record)
    before = (project / active_run).read_bytes()
    registry = storage.load_registry(project)
    entry = registry["plans"][0]
    preparation, pages = storage.load_preparation(project, entry["prepared_source_path"])
    preparation.update(source_url="https://example.org/corrected.pdf", date_accessed="2026-11-04",
        pages_path="data/processed/plan_0099/preparation_03/pages.json")
    entry.update(source_url=preparation["source_url"], date_accessed=preparation["date_accessed"], plan_title="Corrected collection title")
    entry["prepared_source_path"] = storage.save_preparation(project, preparation, pages)
    storage.save_registry(project, registry)
    assert storage.load_run_record(project, active_run) == run_record
    assert (project / active_run).read_bytes() == before


@pytest.mark.parametrize("field", ["source_url", "date_accessed"])
def test_content_collection_fields_must_use_the_selected_preparation_snapshot(project: Path, active_run: str, run_record: dict, field: str) -> None:
    publish_response(project, active_run, run_record)
    run_record["content"]["plan_info"][field] = "https://example.org/wrong.pdf" if field == "source_url" else "2026-11-04"
    with pytest.raises(storage.RunValidationError, match="snapshot"):
        storage.save_run_record(project, run_record)


@pytest.mark.parametrize("file_name", ["output.json", "validation_report.json", "responses/response_01.json"])
def test_missing_completed_run_files_are_not_recreated_or_substituted(project: Path, active_run: str, run_record: dict, file_name: str) -> None:
    complete(project, active_run, run_record)
    file = (project / active_run).parent / file_name
    file.unlink()
    before = snapshot(project)
    with pytest.raises(FileNotFoundError):
        storage.load_run_record(project, active_run)
    assert snapshot(project) == before


@pytest.mark.parametrize("file_name", ["output.json", "validation_report.json", "tool_log.json"])
def test_malformed_saved_json_is_reported_and_preserved(project: Path, active_run: str, run_record: dict, file_name: str) -> None:
    run_record["tool_log_path"] = storage.append_run_tool_log(project, active_run, tool_entry())
    complete(project, active_run, run_record)
    file = (project / active_run).parent / file_name
    file.write_text('{"unfinished":', encoding="utf-8")
    before = snapshot(project)
    with pytest.raises(storage.RunValidationError) as error:
        storage.load_run_record(project, active_run)
    assert error.value.problems[0].category == "syntax"
    assert snapshot(project) == before


def test_selected_run_path_must_match_the_saved_identity(project: Path, active_run: str) -> None:
    other = project / "runs/plan_0099/run_extract_0002/output.json"
    other.parent.mkdir()
    other.write_bytes((project / active_run).read_bytes())
    with pytest.raises(storage.RunValidationError, match="IDs do not match"):
        storage.load_run_record(project, str(other.relative_to(project)))


def test_run_namespace_cannot_be_redirected_to_a_backup_folder(project: Path, tmp_path: Path, run_record: dict) -> None:
    backup = project / "backup"
    backup.mkdir()
    folder = project / "runs/plan_0099/run_extract_0001"
    folder.parent.mkdir(parents=True)
    folder.symlink_to(backup, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        storage.create_run_record(project, running(run_record))
    assert list(backup.iterdir()) == []


def test_verification_uses_a_successful_exact_extractor_run(project: Path, active_run: str, run_record: dict) -> None:
    complete(project, active_run, run_record)
    verifier = running(run_record, "run_verify_0001", stage="verifier", input_run_id="run_extract_0001")
    verifier["settings"]["name"] = "fictional_verifier"
    verifier["settings"]["model"]["name"] = "different-fictional-model"
    path = storage.create_run_record(project, verifier)
    assert storage.load_run_record(project, path) == verifier


@pytest.mark.parametrize("problem", ["missing", "running", "failed", "wrong-stage", "different-preparation", "different-tools"])
def test_invalid_verifier_links_cannot_start_a_run(project: Path, active_run: str, run_record: dict, problem: str) -> None:
    if problem in {"different-preparation", "different-tools", "missing", "wrong-stage"}:
        complete(project, active_run, run_record)
    elif problem == "failed":
        failed = storage.load_run_record(project, active_run)
        failed.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Controlled failure.")
        storage.save_run_record(project, failed)
    verifier = running(run_record, "run_verify_0001", stage="verifier", input_run_id="run_extract_0001")
    if problem == "missing":
        verifier["input_run_id"] = "run_extract_9999"
    elif problem == "wrong-stage":
        first = storage.create_run_record(project, verifier)
        # Complete this verifier so it is a valid saved target with the wrong role.
        finished = copy.deepcopy(run_record)
        finished.update(stage="verifier", run_id="run_verify_0001", input_run_id="run_extract_0001")
        finished["settings"]["stage"] = "verifier"
        complete(project, first, finished)
        verifier.update(run_id="run_verify_0002", input_run_id="run_verify_0001")
    elif problem == "different-preparation":
        prep, pages = storage.load_preparation(project, run_record["source_path"])
        prep["pages_path"] = "data/processed/plan_0099/preparation_03/pages.json"
        verifier["source_path"] = storage.save_preparation(project, prep, pages)
    elif problem == "different-tools":
        verifier["settings"]["document_tools"]["image_render_dpi"] = 300
    before = snapshot(project)
    with pytest.raises((FileNotFoundError, storage.RunValidationError)):
        storage.create_run_record(project, verifier)
    assert snapshot(project) == before


def test_retry_keeps_the_failed_attempt_and_gets_a_new_id(project: Path, active_run: str, run_record: dict) -> None:
    failed = storage.load_run_record(project, active_run)
    failed.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Controlled failure.")
    storage.save_run_record(project, failed)
    old_bytes = (project / active_run).read_bytes()
    retry = running(run_record, storage.next_run_id(project, "plan_0099", "extractor"))
    retry["retry_of_run_id"] = "run_extract_0001"
    path = storage.create_run_record(project, retry)
    assert storage.load_run_record(project, path) == retry
    assert (project / active_run).read_bytes() == old_bytes


@pytest.mark.parametrize("target_status", ["running", "succeeded"])
def test_retry_link_requires_a_failed_attempt(project: Path, active_run: str, run_record: dict, target_status: str) -> None:
    if target_status == "succeeded":
        complete(project, active_run, run_record)
    retry = running(run_record, "run_extract_0002")
    retry["retry_of_run_id"] = "run_extract_0001"
    with pytest.raises(storage.RunValidationError, match="failed same-plan"):
        storage.create_run_record(project, retry)


def test_verifier_retry_preserves_its_exact_extractor_input(project: Path, active_run: str, run_record: dict) -> None:
    complete(project, active_run, run_record)
    second_extractor = copy.deepcopy(run_record)
    second_extractor["run_id"] = "run_extract_0002"
    second_path = storage.create_run_record(project, running(second_extractor, "run_extract_0002"))
    complete(project, second_path, second_extractor)
    verifier = running(run_record, "run_verify_0001", stage="verifier", input_run_id="run_extract_0001")
    verifier_path = storage.create_run_record(project, verifier)
    verifier.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Controlled verifier failure.")
    storage.save_run_record(project, verifier)
    before = snapshot(project)

    retry = running(run_record, "run_verify_0002", stage="verifier", input_run_id="run_extract_0002")
    retry["retry_of_run_id"] = "run_verify_0001"
    with pytest.raises(storage.RunValidationError, match="exact extractor input"):
        storage.create_run_record(project, retry)
    assert snapshot(project) == before
    retry["input_run_id"] = "run_extract_0001"
    retry_path = storage.create_run_record(project, retry)
    assert storage.load_run_record(project, retry_path) == retry
    assert (project / active_run).read_bytes() == before[active_run]
    assert (project / verifier_path).read_bytes() == before[verifier_path]


def test_retry_cannot_change_model_stage(project: Path, active_run: str, run_record: dict) -> None:
    complete(project, active_run, run_record)
    verifier = running(run_record, "run_verify_0001", stage="verifier", input_run_id="run_extract_0001")
    path = storage.create_run_record(project, verifier)
    verifier.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Controlled verifier failure.")
    storage.save_run_record(project, verifier)
    retry = running(run_record, "run_extract_0002")
    retry["retry_of_run_id"] = "run_verify_0001"
    with pytest.raises(storage.RunValidationError, match="same-stage"):
        storage.create_run_record(project, retry)


@pytest.mark.parametrize("purpose", ["comparison", "exploratory"])
def test_comparison_extraction_can_support_main_or_exploratory_verification(
    project: Path, run_record: dict, purpose: str
) -> None:
    registry = storage.load_registry(project)
    registry["plans"][0]["study_set"] = "comparison"
    storage.save_registry(project, registry)
    extractor = copy.deepcopy(run_record)
    extractor["purpose"] = "comparison"
    path = storage.create_run_record(project, running(extractor))
    complete(project, path, extractor)
    verifier = running(extractor, "run_verify_0001", stage="verifier", input_run_id="run_extract_0001")
    verifier["purpose"] = purpose
    assert storage.load_run_record(project, storage.create_run_record(project, verifier)) == verifier


def test_exploratory_extraction_cannot_be_selected_as_the_main_comparison_input(project: Path, run_record: dict) -> None:
    registry = storage.load_registry(project)
    registry["plans"][0]["study_set"] = "comparison"
    storage.save_registry(project, registry)
    extractor = copy.deepcopy(run_record)
    extractor["purpose"] = "exploratory"
    path = storage.create_run_record(project, running(extractor))
    complete(project, path, extractor)
    verifier = running(extractor, "run_verify_0001", stage="verifier", input_run_id="run_extract_0001")
    verifier["purpose"] = "comparison"
    with pytest.raises(storage.RunValidationError, match="comparison extractor"):
        storage.create_run_record(project, verifier)


def test_development_plan_cannot_be_used_for_comparison(project: Path, run_record: dict) -> None:
    record = running(run_record)
    record["purpose"] = "comparison"
    with pytest.raises(storage.RunValidationError, match="study-set"):
        storage.create_run_record(project, record)


def test_tool_log_append_failure_preserves_previous_entries(project: Path, active_run: str, monkeypatch: pytest.MonkeyPatch) -> None:
    path = storage.append_run_tool_log(project, active_run, tool_entry())
    before = (project / path).read_bytes()
    def fail(source, destination):
        raise OSError("Controlled tool-log replacement failure.")
    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError) as error:
        storage.append_run_tool_log(project, active_run, tool_entry(tool="ocr"))
    assert (project / path).read_bytes() == before
    assert "Run files retained" in " ".join(error.value.__notes__)


def test_invalid_unicode_is_rejected_before_creating_a_run(project: Path, run_record: dict) -> None:
    record = running(run_record)
    record["settings"]["prompt_texts"][0] = "Invalid isolated surrogate: \ud800"
    with pytest.raises(UnicodeEncodeError):
        storage.create_run_record(project, record)
    assert not (project / "runs").exists()


def test_circular_retry_links_stop_with_a_clear_error(project: Path, active_run: str, run_record: dict) -> None:
    failed = storage.load_run_record(project, active_run)
    failed.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Controlled failure.")
    storage.save_run_record(project, failed)
    retry = running(run_record, "run_extract_0002")
    retry["retry_of_run_id"] = "run_extract_0001"
    retry_path = storage.create_run_record(project, retry)
    retry.update(status="failed", ended_at="2026-11-03T12:00:01Z", error="Second controlled failure.")
    storage.save_run_record(project, retry)
    # Simulate damaged saved data directly; public writers never create a cycle.
    failed["retry_of_run_id"] = "run_extract_0002"
    (project / active_run).write_text(json.dumps(failed), encoding="utf-8")
    with pytest.raises(storage.RunValidationError, match="cycle"):
        storage.load_run_record(project, retry_path)


@pytest.mark.parametrize("committed", [False, True], ids=["before-publication", "after-publication"])
def test_interrupted_initial_publication_retains_the_attempt_folder(
    project: Path, run_record: dict, monkeypatch: pytest.MonkeyPatch, committed: bool
) -> None:
    publish = storage._publish_new_json
    def fail(destination, text):
        if committed:
            publish(destination, text)
        raise OSError("Controlled initial publication failure.")
    monkeypatch.setattr(storage, "_publish_new_json", fail)
    with pytest.raises(OSError) as error:
        storage.create_run_record(project, running(run_record))
    assert "Run files retained" in " ".join(error.value.__notes__)
    assert (project / "runs/plan_0099/run_extract_0001").is_dir()
    assert storage.next_run_id(project, "plan_0099", "extractor") == "run_extract_0002"
    assert (project / "runs/plan_0099/run_extract_0001/output.json").exists() is committed


@pytest.mark.parametrize("committed", [False, True], ids=["before-replacement", "after-replacement"])
def test_uncertain_final_record_replacement_never_rolls_back_or_deletes_evidence(
    project: Path, active_run: str, run_record: dict, monkeypatch: pytest.MonkeyPatch, committed: bool
) -> None:
    # The fake OS error can happen before or after replacement actually commits.
    # Both outcomes must leave a readable complete record and retained evidence;
    # the caller must inspect which state survived rather than assume rollback.
    publish_response(project, active_run, run_record)
    replace = storage.os.replace
    before = (project / active_run).read_bytes()
    def fail(source, destination):
        if committed:
            replace(source, destination)
        raise OSError("Controlled uncertain replacement.")
    monkeypatch.setattr(storage.os, "replace", fail)
    with pytest.raises(OSError) as error:
        storage.save_run_record(project, run_record)
    loaded = storage.load_run_record(project, active_run)
    assert loaded["status"] == ("succeeded" if committed else "running")
    if not committed:
        assert (project / active_run).read_bytes() == before
    assert (project / run_record["model_calls"][0]["response_path"]).is_file()
    assert "publication may already have completed" in " ".join(error.value.__notes__)
    assert list((project / active_run).parent.glob(".output-*.tmp")) == []


def test_failed_sync_leaves_the_previous_complete_record(project: Path, active_run: str, monkeypatch: pytest.MonkeyPatch) -> None:
    record = storage.load_run_record(project, active_run)
    record["settings"]["environment"]["runtime_version"] = "new-observation"
    before = (project / active_run).read_bytes()
    def fail(fd):
        raise OSError("Controlled sync failure.")
    monkeypatch.setattr(storage.os, "fsync", fail)
    with pytest.raises(OSError):
        storage.save_run_record(project, record)
    assert (project / active_run).read_bytes() == before


@pytest.mark.parametrize("format_name", ["tool-log", "validation-report"])
def test_supporting_schemas_and_strict_parsers_are_exercised(format_name: str) -> None:
    if format_name == "tool-log":
        data, problems = validation.parse_tool_log_json('[{"tool":"a","tool":"b"}]')
    else:
        data, problems = validation.parse_validation_report_json('{"valid":true,"valid":false}')
    assert data is None and problems[0].category == "syntax"
