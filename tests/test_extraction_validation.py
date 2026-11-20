"""Check metadata, evidence, strict parsing, and schema setup for plan datasets.

Action and issue coding boundaries are covered in test_action_format. These
checks establish format consistency, not source support or extraction quality.
"""

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import validation


@pytest.fixture
def response(run_record):
    return copy.deepcopy({key: run_record[key] for key in ("plan_data", "plan_issues")})


def test_schema_definitions_are_valid():
    for name in ("plan_data.schema.json", "agent_response.schema.json", "curated_dataset.schema.json"):
        path = Path(__file__).resolve().parents[1] / "schemas" / name
        Draft202012Validator.check_schema(json.loads(path.read_text()))


def test_parsers_preserve_the_complete_answer_and_metadata(response):
    before = copy.deepcopy(response)
    answer, problems = validation.parse_agent_response_json(
        json.dumps(response), page_count=5, stage="extractor"
    )
    data, data_problems = validation.parse_plan_data_json(json.dumps(response["plan_data"]), page_count=5)
    assert problems == data_problems == []
    assert answer == before and data == before["plan_data"] and response == before


def test_draft_recognition_does_not_validate_or_change_answer_fields(response):
    response["plan_data"]["metadata"]["draft_only"] = True
    raw = json.dumps(response)
    assert validation.is_agent_response_draft(raw) is True
    parsed, problems = validation.parse_agent_response_json(raw, page_count=5, stage="extractor")
    assert parsed is None and problems
    assert json.loads(raw) == response


def test_empty_answer_containers_are_recognizable_but_not_acceptable():
    raw = '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[]}}'
    assert validation.is_agent_response_draft(raw) is True
    assert validation.parse_agent_response_json(raw, page_count=5, stage="extractor")[1]


@pytest.mark.parametrize("text", [
    "", "ordinary prose", "{}", "[]", "null", '{"plan_data":{}}',
    '{"plan_data":{},"plan_issues":{}}',
    '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[]},"extra":0}',
    '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[]}',
    '```json\n{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[]}}\n```',
    '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[]}} trailing prose',
    '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[],"issues":[]}}',
    '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[{"value":NaN}]}}',
    '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[{"value":Infinity}]}}',
    '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[{"value":1e10000}]}}',
])
def test_ambiguous_incomplete_or_nonstandard_json_is_not_a_draft(text):
    assert validation.is_agent_response_draft(text) is False


@pytest.mark.parametrize("path,value", [
    (("plan_data",), None), (("plan_issues",), []),
    (("plan_data", "metadata"), []), (("plan_data", "actions"), {}),
    (("plan_data", "actions"), [None]), (("plan_issues", "issues"), "issues"),
    (("plan_issues", "issues"), [0]),
])
def test_draft_recognition_requires_answer_containers_and_object_records(response, path, value):
    target = response
    for name in path[:-1]:
        target = target[name]
    target[path[-1]] = value
    assert validation.is_agent_response_draft(json.dumps(response)) is False


@pytest.mark.parametrize("field", [
    "plan_title", "jurisdiction_name", "country", "plan_scale", "plan_type",
    "publication_year", "lead_agencies", "source_url", "date_accessed", "language",
])
def test_metadata_fields_are_required_even_when_nullable(response, field):
    del response["plan_data"]["metadata"][field]
    assert validation.validate_agent_response_structure(response)


@pytest.mark.parametrize("field", ["plan_title", "jurisdiction_name", "country"])
@pytest.mark.parametrize("value,valid", [(None, True), ("Source wording", True), ("  ", False), (5, False)])
def test_metadata_text_distinguishes_missing_from_blank(response, field, value, valid):
    response["plan_data"]["metadata"][field] = value
    problems = validation.validate_agent_response_structure(response)
    assert (problems == []) == valid


@pytest.mark.parametrize("field,value,valid", [
    ("plan_scale", "country", True), ("plan_scale", "city", True),
    ("plan_scale", "district", False), ("plan_type", "broader_climate_plan", True),
    ("plan_type", "other", False), ("publication_year", 2026, True),
    ("publication_year", True, False), ("lead_agencies", ["Council"], True),
    ("lead_agencies", [""], False), ("source_url", "", False),
    ("date_accessed", "2026-02-28", True), ("date_accessed", "2026-02-30", False),
    ("language", "English", True), ("language", "French", False),
])
def test_metadata_values_follow_the_contract(response, field, value, valid):
    response["plan_data"]["metadata"][field] = value
    assert (validation.validate_agent_response_structure(response) == []) == valid


@pytest.mark.parametrize("numbers,valid", [
    ([1, 2], True), ([], False), ([0], False), ([True], False),
    ([1, 1], False), ([1.5], False), (1, False),
])
def test_evidence_pages_are_nonempty_unique_positive_integers(response, numbers, valid):
    response["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = numbers
    assert (validation.validate_agent_response_structure(response) == []) == valid


@pytest.mark.parametrize("page_count", [None, 0, -1, True, 2.5, "5"])
def test_full_validation_requires_a_known_pdf_page_count(response, page_count):
    problems = validation.validate_agent_response(response, page_count=page_count, stage="extractor")
    assert problems and all(problem.category == "other" for problem in problems)


@pytest.mark.parametrize("text", [
    '{"unfinished":', '{"a": 1, "a": 2}', 'NaN', 'Infinity',
    '```json\n{}\n```', '{"field": 1,}',
])
def test_strict_parsers_reject_bad_json_without_repair(text):
    for parsed, problems in (
        validation.parse_plan_data_json(text, page_count=5),
        validation.parse_agent_response_json(text, page_count=5, stage="extractor"),
    ):
        assert parsed is None and problems[0].category == "syntax"


@pytest.mark.parametrize("data", [None, [], "a response", 1])
def test_wrong_input_shapes_are_reported_without_crashing(data):
    assert validation.validate_plan_data(data, page_count=5)[0].category == "structure"
    assert validation.validate_agent_response(data, page_count=5, stage="extractor")[0].category == "structure"


@pytest.mark.parametrize("schema_text", [None, '{"type":', '{"type": "invalid-type"}'])
def test_missing_or_invalid_shared_schema_is_a_setup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict, schema_text: str | None
) -> None:
    schema_path = tmp_path / "plan_data.schema.json"
    if schema_text is not None:
        schema_path.write_text(schema_text, encoding="utf-8")
    monkeypatch.setattr(validation, "_PLAN_DATA_SCHEMA_PATH", schema_path)
    for problems in (
        validation.validate_plan_data_structure(response["plan_data"]),
        validation.validate_agent_response_structure(response),
    ):
        assert len(problems) == 1 and problems[0].category == "other"
        assert problems[0].location == str(schema_path)


def test_response_reuses_the_loaded_content_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict
) -> None:
    # Changing one local schema must change both entry points' rules. This catches
    # accidentally maintaining a separate copy of the content definition.
    path = tmp_path / "plan_data.schema.json"
    path.write_text(json.dumps({"type": "object", "required": ["sentinel"]}), encoding="utf-8")
    monkeypatch.setattr(validation, "_PLAN_DATA_SCHEMA_PATH", path)
    for problems in (
        validation.validate_plan_data_structure(response["plan_data"]),
        validation.validate_agent_response_structure(response),
    ):
        assert len(problems) == 1 and problems[0].category == "structure"
        assert "sentinel" in problems[0].message


def test_unregistered_schema_reference_is_reported_without_network_access(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict
) -> None:
    path = tmp_path / "agent_response.schema.json"
    path.write_text(json.dumps({"$ref": "https://example.invalid/not-registered"}), encoding="utf-8")
    monkeypatch.setattr(validation, "_AGENT_RESPONSE_SCHEMA_PATH", path)
    problems = validation.validate_agent_response_structure(response)
    assert len(problems) == 1 and problems[0].category == "other"
    assert "Cannot resolve local schema reference" in problems[0].message


def test_missing_date_format_support_cannot_silently_accept_content(
    monkeypatch: pytest.MonkeyPatch, response: dict
) -> None:
    checker = validation.FormatChecker()
    del checker.checkers["date"]
    monkeypatch.setattr(validation, "FormatChecker", lambda: checker)
    for problems in (
        validation.validate_plan_data_structure(response["plan_data"]),
        validation.validate_agent_response_structure(response),
    ):
        assert len(problems) == 1 and problems[0].category == "other"
        assert "required format checkers are unavailable: date" in problems[0].message
