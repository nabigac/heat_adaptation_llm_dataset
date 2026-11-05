"""Exercise fictional run records without starting models or saving research runs.

These tests establish format and internal consistency. Checking that linked files
exist, selecting linked runs, and protecting completed files belong to the later
storage/workflow increment. All measurements and model names below are fixtures.
"""
# The shared run_record fixture comes from conftest.py and describes a
# fictional successful attempt. Helpers below create other internally consistent
# starting states; each negative test then introduces a targeted contradiction.
# Storage existence checks are deliberately separate from these pure validators.

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import validation




def set_status(record: dict, status: str) -> None:
    """Make controlled running/failed examples with no accepted final response."""
    # Change related lifecycle fields together so running/failed examples start
    # valid. Tests of an invalid status/field combination then change just that
    # combination, rather than inheriting unrelated errors from setup.
    record["status"] = status
    if status == "running":
        record.update(ended_at=None, elapsed_seconds=None, content=None, review=None, model_calls=[])
    elif status == "failed":
        record.update(error="Controlled failure before the first model request.", content=None, review=None, model_calls=[])


def set_verifier(record: dict) -> None:
    # Changing role also changes the run ID, selected extractor link, saved
    # settings stage, and response paths. Keeping these consistent isolates tests
    # of the one verifier-specific rule each case intends to examine.
    record.update(stage="verifier", run_id="run_verify_0001", input_run_id="run_extract_0001")
    record["settings"]["stage"] = "verifier"
    for call in record["model_calls"]:
        call["response_path"] = "runs/plan_0099/run_verify_0001/responses/response_01.json"


def issue(*, related_record_id: str | None = "action_0001") -> dict:
    return {
        "issue_id": "issue_0001", "related_record_id": related_record_id,
        "description": "Check unclear chart values on PDF page 1.", "type": "source_issue",
        "origin_stage": "extractor", "status": "open", "resolved_by": None, "resolution": None,
    }


def select_path(data: object, path: tuple):
    # Walk keys and list indices from a tuple to select a nested fixture value.
    # The invalid-value table can then target many fields without repeating
    # long dictionary/list indexing expressions.
    for part in path:
        data = data[part]
    return data


def test_run_schema_is_valid() -> None:
    path = Path(__file__).resolve().parents[1] / "schemas" / "run.schema.json"
    Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


@pytest.mark.parametrize("status", ["running", "succeeded", "failed"])
@pytest.mark.parametrize("stage", ["extractor", "verifier"])
def test_parses_each_run_state_and_role_without_changing_values(run_record: dict, status: str, stage: str) -> None:
    if stage == "verifier":
        set_verifier(run_record)
    set_status(run_record, status)
    before = copy.deepcopy(run_record)
    data, problems = validation.parse_run_record_json(json.dumps(run_record), page_count=5)
    assert data == before and problems == []
    assert run_record == before


@pytest.mark.parametrize("purpose", ["development", "comparison", "exploratory"])
def test_accepts_each_defined_purpose(run_record: dict, purpose: str) -> None:
    run_record["purpose"] = purpose
    assert validation.validate_run_record(run_record, page_count=5) == []


OBJECT_PATHS = (
    (), ("settings",), ("settings", "model"), ("settings", "generation"),
    ("settings", "document_tools"), ("settings", "environment"), ("model_calls", 0),
)


@pytest.mark.parametrize("path", OBJECT_PATHS)
def test_all_declared_run_fields_are_required_including_nullable_fields(run_record: dict, path: tuple) -> None:
    for field in select_path(run_record, path):
        candidate = copy.deepcopy(run_record)
        del select_path(candidate, path)[field]
        before = copy.deepcopy(candidate)
        problems = validation.validate_run_record_structure(candidate)
        assert problems, (path, field)
        assert all(problem.category == "structure" for problem in problems)
        assert any(field in problem.message for problem in problems)
        assert candidate == before


@pytest.mark.parametrize("path", OBJECT_PATHS)
def test_unknown_run_fields_are_not_silently_saved(run_record: dict, path: tuple) -> None:
    select_path(run_record, path)["unexpected"] = "Unrecognized setting."
    problems = validation.validate_run_record_structure(run_record)
    assert problems and all(problem.category == "structure" for problem in problems)
    assert any("unexpected" in problem.message for problem in problems)


@pytest.mark.parametrize(("path", "value"), [
    (("schema_version",), 2), (("schema_version",), True),
    (("plan_id",), "  "), (("run_id",), ""), (("stage",), "expert"),
    (("purpose",), "expansion"), (("status",), "complete"),
    (("started_at",), "2026-02-29T12:00:00Z"),
    (("started_at",), "2026-11-03"),
    (("started_at",), "2026-11-03T12:00:00-08:00"),
    (("started_at",), "2026-11-03T12:00:00+01:00"),
    (("ended_at",), "2026-11-03T12:00:01Z\n"),
    (("elapsed_seconds",), -1), (("elapsed_seconds",), True),
    (("settings", "name"), "\t"),
    (("settings", "context_limit"), 0), (("settings", "context_limit"), True),
    (("settings", "generation", "temperature"), -0.1),
    (("settings", "generation", "top_p"), 0), (("settings", "generation", "top_p"), 1.1),
    (("settings", "generation", "seed"), True), (("settings", "generation", "seed"), 1.5),
    (("settings", "generation", "max_output_tokens"), 0),
    (("settings", "max_tool_calls"), 0), (("settings", "max_tool_calls"), 1.5),
    (("settings", "model_timeout_seconds"), 0),
    (("settings", "image_input_enabled"), "false"),
    (("settings", "model", "execution_mode"), "remote"),
    (("settings", "model", "endpoint"), ""),
    (("settings", "document_tools", "image_render_dpi"), 0),
    (("settings", "document_tools", "tool_timeout_seconds"), -1),
    (("settings", "environment", "code_dirty"), None),
    (("settings", "environment", "hardware"), 64),
    (("settings", "environment", "model_loaded_at_start"), "unknown"),
    (("settings", "prompt_paths"), []), (("settings", "prompt_texts"), []),
    (("settings", "prompt_texts"), [""]),
    (("model_calls", 0, "input_tokens"), -1),
    (("model_calls", 0, "output_tokens"), True),
    (("model_calls", 0, "output_tokens"), 1.5),
    (("model_calls", 0, "truncated"), "false"),
    (("model_calls", 0, "response_path"), ""),
    (("content",), {}), (("review",), {}),
])
def test_invalid_run_values_are_structure_errors(run_record: dict, path: tuple, value: object) -> None:
    select_path(run_record, path[:-1])[path[-1]] = value
    problems = validation.validate_run_record_structure(run_record)
    assert problems and all(problem.category == "structure" for problem in problems)


@pytest.mark.parametrize(("status", "field", "value"), [
    ("running", "ended_at", "2026-11-03T12:00:01Z"),
    ("running", "error", "Already failed."),
    ("succeeded", "ended_at", None),
    ("succeeded", "content", None), ("succeeded", "review", None),
    ("succeeded", "error", "Failed."), ("succeeded", "model_calls", []),
    ("failed", "ended_at", None), ("failed", "error", None), ("failed", "error", "  "),
])
def test_status_must_agree_with_completion_and_result_fields(
    run_record: dict, status: str, field: str, value: object
) -> None:
    set_status(run_record, status)
    run_record[field] = value
    problems = validation.validate_run_record_structure(run_record)
    assert problems and all(problem.category == "structure" for problem in problems)


def test_unknown_measurements_remain_null_even_for_a_successful_run(run_record: dict) -> None:
    run_record["elapsed_seconds"] = None
    run_record["model_calls"][0] = {key: None for key in run_record["model_calls"][0]}
    before = copy.deepcopy(run_record)
    data, problems = validation.parse_run_record_json(json.dumps(run_record), page_count=5)
    assert data == before and problems == []
    assert data["elapsed_seconds"] is None
    assert data["model_calls"][0]["input_tokens"] is None


def test_does_not_reconstruct_duration_from_timestamps(run_record: dict) -> None:
    # A later recovery timestamp does not reveal when an interrupted process
    # actually stopped. elapsed_seconds must remain unknown even though both
    # timestamps are present in the failed record.
    run_record.update(status="failed", error="Interrupted; confirmed stopped during later recovery.", elapsed_seconds=None)
    run_record["ended_at"] = "2026-11-04T12:00:00Z"
    assert validation.validate_run_record(run_record, page_count=5) == []
    assert run_record["elapsed_seconds"] is None


def test_measured_duration_need_not_equal_rounded_wall_clock_difference(run_record: dict) -> None:
    run_record["elapsed_seconds"] = 1.4321
    assert validation.validate_run_record(run_record, page_count=5) == []


@pytest.mark.parametrize("timestamp", ["2026-11-03T12:00:00Z", "2026-11-03T12:00:00+00:00", "2026-11-03t12:00:00z"])
def test_accepts_supported_utc_notation(run_record: dict, timestamp: str) -> None:
    run_record["started_at"] = timestamp
    assert validation.validate_run_record(run_record, page_count=5) == []


def test_end_time_cannot_precede_start_time(run_record: dict) -> None:
    run_record["ended_at"] = "2026-11-03T11:59:59Z"
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$.ended_at"


NUMBER_PATHS = (
    ("elapsed_seconds",), ("settings", "generation", "temperature"),
    ("settings", "generation", "top_p"), ("settings", "model_timeout_seconds"),
    ("settings", "document_tools", "tool_timeout_seconds"),
)


@pytest.mark.parametrize("path", NUMBER_PATHS)
@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_numbers_are_rejected(run_record: dict, path: tuple, value: float) -> None:
    select_path(run_record, path[:-1])[path[-1]] = value
    problems = validation.validate_run_record_structure(run_record)
    assert problems and all(problem.category == "structure" for problem in problems)


def test_overflowing_json_exponent_does_not_become_a_saved_infinity(run_record: dict) -> None:
    text = json.dumps(run_record).replace('"elapsed_seconds": 1.0', '"elapsed_seconds": 1e400')
    data, problems = validation.parse_run_record_json(text, page_count=5)
    assert data is None and len(problems) == 1
    assert problems[0].category == "structure" and problems[0].location == "$.elapsed_seconds"


def test_local_settings_can_leave_provider_details_unknown(run_record: dict) -> None:
    assert validation.validate_run_record(run_record, page_count=5) == []


@pytest.mark.parametrize("field", ["api_service", "provider"])
def test_hosted_settings_require_service_and_provider(run_record: dict, field: str) -> None:
    model = run_record["settings"]["model"]
    model.update(execution_mode="hosted_api", api_service="fictional-service", provider="fictional-provider")
    model[field] = None
    assert validation.validate_run_record_structure(run_record)


def test_accepts_complete_hosted_settings_and_supported_generation_values(run_record: dict) -> None:
    run_record["settings"]["model"].update(
        execution_mode="hosted_api", endpoint="https://example.org/api",
        api_service="fictional-service", provider="fictional-provider",
    )
    run_record["settings"]["generation"].update(temperature=None, top_p=1, seed=0)
    assert validation.validate_run_record(run_record, page_count=5) == []


@pytest.mark.parametrize(("enabled", "engine", "language"), [
    (True, None, "en"), (True, "easyocr", None),
    (False, "easyocr", None), (False, None, "en"),
])
def test_ocr_settings_must_agree_with_enabled_flag(run_record: dict, enabled: bool, engine: str | None, language: str | None) -> None:
    run_record["settings"]["document_tools"].update(ocr_enabled=enabled, ocr_engine=engine, ocr_language=language)
    assert validation.validate_run_record_structure(run_record)


def test_accepts_enabled_ocr_and_known_environment_details(run_record: dict) -> None:
    run_record["settings"]["document_tools"].update(ocr_enabled=True, ocr_engine="easyocr", ocr_language="en")
    run_record["settings"]["environment"].update(ocr_version="fixture-version", hardware="Fictional test hardware", model_loaded_at_start=True)
    assert validation.validate_run_record(run_record, page_count=5) == []


def test_saved_prompt_paths_and_texts_must_have_matching_counts(run_record: dict) -> None:
    run_record["settings"]["prompt_texts"].pop()
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$.settings.prompt_texts"


def test_saved_run_settings_preserve_exact_order_and_text_without_reading_current_prompt_files(run_record: dict) -> None:
    run_record["settings"]["prompt_paths"] = ["prompts/shared.md", "prompts/extractor.md"]
    run_record["settings"]["prompt_texts"] = ['  Keep “quotations” and £1,000.\n', "Then extract actions."]
    before = copy.deepcopy(run_record["settings"])
    assert validation.validate_run_record(run_record, page_count=5) == []
    assert run_record["settings"] == before


def test_saved_profile_stage_must_match_the_run_stage(run_record: dict) -> None:
    run_record["settings"]["stage"] = "verifier"
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$.settings.stage"


@pytest.mark.parametrize("stage", ["extractor", "verifier"])
def test_input_link_presence_must_match_the_stage(run_record: dict, stage: str) -> None:
    if stage == "extractor":
        run_record["input_run_id"] = "run_extract_0000"
    else:
        set_verifier(run_record)
        run_record["input_run_id"] = None
    assert validation.validate_run_record_structure(run_record)


@pytest.mark.parametrize("field", ["input_run_id", "retry_of_run_id"])
def test_run_links_cannot_point_to_the_current_run(run_record: dict, field: str) -> None:
    set_verifier(run_record)
    run_record[field] = run_record["run_id"]
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$." + field


def test_successful_input_and_failed_retry_target_cannot_be_the_same_run(run_record: dict) -> None:
    set_verifier(run_record)
    run_record["retry_of_run_id"] = run_record["input_run_id"]
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$.retry_of_run_id"


def test_distinct_retry_id_is_representable_without_resolving_files(run_record: dict) -> None:
    run_record["retry_of_run_id"] = "run_extract_0000"
    assert validation.validate_run_record(run_record, page_count=5) == []


@pytest.mark.parametrize("field", ["plan_id", "run_id", "input_run_id", "retry_of_run_id"])
@pytest.mark.parametrize("bad_id", ["../other", "other/run", "C:other", "."])
def test_run_identifiers_must_be_safe_path_components(run_record: dict, field: str, bad_id: str) -> None:
    set_verifier(run_record)
    run_record[field] = bad_id
    problems = validation.validate_run_record(run_record, page_count=5)
    assert any(problem.location == "$." + field and problem.category == "reference" for problem in problems)


@pytest.mark.parametrize("path", [
    "data/processed/plan_0001/preparation_02/preparation.json",
    "data/processed/plan_0099/preparation_00/preparation.json",
    "data/processed/plan_0099/preparation_02/pages.json",
    "../preparation.json", "/tmp/preparation.json", "C:/preparation.json",
])
def test_source_path_must_identify_this_plans_preserved_preparation(run_record: dict, path: str) -> None:
    run_record["source_path"] = path
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$.source_path"


@pytest.mark.parametrize("path", ["../prompt.md", "/tmp/prompt.md", "C:/prompt.md", "prompts\\extractor.md", ".", "prompts/\x00file.md"])
def test_prompt_paths_must_be_project_relative(run_record: dict, path: str) -> None:
    run_record["settings"]["prompt_paths"][0] = path
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$.settings.prompt_paths[0]"


@pytest.mark.parametrize("field", ["response_path", "tool_log_path"])
@pytest.mark.parametrize("path", [
    "runs/plan_0001/run_extract_0001/file.json",
    "runs/plan_0099/run_extract_0002/file.json",
    "runs/plan_0099/run_extract_0001",
    "runs/plan_0099/run_extract_0001/../other.json",
    "/tmp/file.json", "C:/file.json", "runs\\file.json",
])
def test_artifact_paths_cannot_escape_or_borrow_another_runs_files(run_record: dict, field: str, path: str) -> None:
    if field == "response_path":
        run_record["model_calls"][0][field] = path
        expected_location = "$.model_calls[0].response_path"
    else:
        run_record[field] = path
        expected_location = "$.tool_log_path"
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == expected_location


def test_accepts_tool_log_and_multiple_ordered_model_calls(run_record: dict) -> None:
    run_record["tool_log_path"] = "runs/plan_0099/run_extract_0001/tool_log.json"
    run_record["model_calls"].append(dict(run_record["model_calls"][0], response_path="runs/plan_0099/run_extract_0001/responses/response_02.json"))
    before = copy.deepcopy(run_record)
    assert validation.validate_run_record(run_record, page_count=5) == []
    assert run_record == before


@pytest.mark.parametrize("status", ["running", "succeeded"])
def test_reported_truncation_prevents_a_nonfailed_run(run_record: dict, status: str) -> None:
    run_record["status"] = status
    if status == "running":
        run_record["ended_at"] = None
    run_record["model_calls"][0]["truncated"] = True
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$.model_calls[0].truncated"


def test_failed_run_can_preserve_valid_content_and_reported_truncation(run_record: dict) -> None:
    run_record.update(status="failed", error="Provider reported output truncation.")
    run_record["model_calls"][0]["truncated"] = True
    before = copy.deepcopy(run_record)
    assert validation.validate_run_record(run_record, page_count=5) == []
    assert run_record == before


@pytest.mark.parametrize("status", ["running", "failed"])
def test_record_without_content_can_be_validated_without_page_count(run_record: dict, status: str) -> None:
    set_status(run_record, status)
    assert validation.validate_run_record(run_record) == []


@pytest.mark.parametrize("page_count", [None, 0, -1, True, 5.0, "5"])
def test_retained_content_requires_a_known_positive_source_page_count(run_record: dict, page_count: object) -> None:
    problems = validation.validate_run_record(run_record, page_count=page_count)
    assert len(problems) == 1 and problems[0].category == "other"
    assert problems[0].location == "page_count"


def test_failed_run_can_retain_valid_content_without_review(run_record: dict) -> None:
    run_record.update(status="failed", error="Final review could not be validated.", review=None)
    assert validation.validate_run_record(run_record, page_count=5) == []


def test_failed_run_without_content_can_retain_unlinked_source_issues(run_record: dict) -> None:
    set_status(run_record, "failed")
    run_record["review"] = {"issues": [issue(related_record_id=None)]}
    assert validation.validate_run_record(run_record) == []


def test_retained_issue_cannot_link_to_a_record_absent_from_content(run_record: dict) -> None:
    set_status(run_record, "failed")
    run_record["review"] = {"issues": [issue()]}
    problems = validation.validate_run_record(run_record)
    assert len(problems) == 1 and problems[0].location == "$.review.issues[0].related_record_id"


@pytest.mark.parametrize("problem_kind", ["page", "link", "duplicate-id", "issue-stage"])
def test_embedded_response_uses_the_existing_relationship_checks(run_record: dict, problem_kind: str) -> None:
    action = run_record["content"]["plan_actions"][0]
    if problem_kind == "page":
        action["evidence"][0]["page_numbers"] = [6]
        expected = "$.content.plan_actions[0].evidence[0].page_numbers[0]"
    elif problem_kind == "link":
        action["related_goal_ids"] = ["missing-goal"]
        expected = "$.content.plan_actions[0].related_goal_ids[0]"
    elif problem_kind == "duplicate-id":
        run_record["content"]["plan_actions"].append(copy.deepcopy(action))
        expected = "$.content.plan_actions[1].action_id"
    else:
        run_record["review"]["issues"] = [dict(issue(), origin_stage="verifier")]
        expected = "$.review.issues[0].origin_stage"
    before = copy.deepcopy(run_record)
    data, problems = validation.parse_run_record_json(json.dumps(run_record), page_count=5)
    assert data is None and len(problems) == 1 and problems[0].category == "reference"
    assert problems[0].location == expected
    assert run_record == before


@pytest.mark.parametrize("text", [
    '{"unfinished":', '{"schema_version": 1, "schema_version": 2}',
    '{"settings": {"name": "a", "name": "b"}}', "NaN", "Infinity",
    "-Infinity", '```json\n{}\n```', '{"status": "failed",}',
])
def test_run_parser_rejects_bad_json_without_repairs(text: str) -> None:
    data, problems = validation.parse_run_record_json(text)
    assert data is None and len(problems) == 1 and problems[0].category == "syntax"


@pytest.mark.parametrize("data", [None, [], "a run", 1])
def test_wrong_run_shapes_are_reported_without_crashing(data: object) -> None:
    problems = validation.validate_run_record(data)
    assert problems and all(problem.category == "structure" for problem in problems)


@pytest.mark.parametrize("path_attribute", ["_RUN_SCHEMA_PATH", "_CONTENT_SCHEMA_PATH", "_AGENT_RESPONSE_SCHEMA_PATH"])
@pytest.mark.parametrize("schema_text", [None, '{"type":', '{"type": "invalid"}'])
def test_missing_or_invalid_run_schema_dependencies_stop_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_record: dict,
    path_attribute: str, schema_text: str | None,
) -> None:
    path = tmp_path / "broken.schema.json"
    if schema_text is not None:
        path.write_text(schema_text, encoding="utf-8")
    monkeypatch.setattr(validation, path_attribute, path)
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].category == "other"
    assert problems[0].location == str(path)


@pytest.mark.parametrize("format_name", ["date", "date-time"])
def test_run_validation_requires_its_format_checkers(
    monkeypatch: pytest.MonkeyPatch, run_record: dict, format_name: str
) -> None:
    checker = validation.FormatChecker()
    del checker.checkers[format_name]
    monkeypatch.setattr(validation, "FormatChecker", lambda: checker)
    problems = validation.validate_run_record(run_record, page_count=5)
    assert len(problems) == 1 and problems[0].category == "other"
    assert "required format checkers are unavailable" in problems[0].message
