"""Check the application-facing registry validation functions.

The schema tests cover the detailed field rules separately. These tests focus on
reading JSON, reporting problems, preserving input, and handling unusable schemas.
"""
# Start with accepted registry values, then syntax/field errors and unusable
# schemas. The validators return structured problems; tests also verify that
# rejection does not rewrite inputs or invent defaults.

import copy
import json
from dataclasses import asdict
from pathlib import Path

import pytest

# pytest's pythonpath setting makes src/validation.py available as this module.
import validation


@pytest.fixture
def valid_registry() -> dict:
    """Supply fresh fictional data; none of these tests needs an actual PDF."""
    # Use Unicode punctuation and nullable metadata to expose accidental text
    # normalization or replacement. The fictional fingerprint is not checked
    # against a PDF by these field-only validation functions.
    return {
        "schema_version": 1,
        "plans": [
            {
                "plan_id": "plan_0001",
                "plan_title": 'Heat, "Adaptation" — Example City',
                "pdf_path": "data/raw/plan_0001.pdf",
                "document_sha256": "a" * 64,
                "source_url": "https://example.org/heat-plan.pdf",
                "date_accessed": "2026-11-01",
                "study_set": "development",
                "prepared_source_path": None,
            }
        ],
    }


def test_accepts_valid_decoded_registry(valid_registry: dict) -> None:
    assert validation.validate_registry_structure(valid_registry) == []


def test_parses_empty_registry() -> None:
    data, problems = validation.parse_registry_json('{"schema_version": 1, "plans": []}')

    assert data == {"schema_version": 1, "plans": []}
    assert problems == []


def test_preserves_values_when_parsing(valid_registry: dict) -> None:
    # Include punctuation, Unicode text, and null so accidental rewriting is visible.
    text = json.dumps(valid_registry, ensure_ascii=False)

    data, problems = validation.parse_registry_json(text)

    assert data == valid_registry
    assert problems == []


def test_reports_multiple_structure_problems(valid_registry: dict) -> None:
    valid_registry["plans"][0]["date_accessed"] = "2026-02-29"
    valid_registry["plans"][0]["study_set"] = "pilot"

    problems = validation.validate_registry_structure(valid_registry)

    assert len(problems) == 2
    assert all(problem.category == "structure" for problem in problems)
    assert [problem.location for problem in problems] == [
        "$.plans[0].date_accessed",
        "$.plans[0].study_set",
    ]
    assert all(problem.message for problem in problems)


def test_reports_missing_field_without_inserting_it(valid_registry: dict) -> None:
    del valid_registry["plans"][0]["plan_title"]
    # A deep copy preserves nested dictionaries too, giving an independent baseline.
    before = copy.deepcopy(valid_registry)

    problems = validation.validate_registry_structure(valid_registry)

    assert valid_registry == before
    assert len(problems) == 1
    assert problems[0].category == "structure"
    assert problems[0].location == "$.plans[0]"
    assert "plan_title" in problems[0].message


def test_problems_use_the_designs_report_fields() -> None:
    problems = validation.validate_registry_structure({})

    # Convert the dataclass record to the three-field dictionary used in saved reports.
    report_item = asdict(problems[0])
    assert set(report_item) == {"category", "location", "message"}
    assert report_item["category"] == "structure"
    assert report_item["location"] == "$"
    assert isinstance(report_item["message"], str)


def test_reports_syntax_error_with_line_and_column() -> None:
    text = '{\n  "schema_version": 1,\n  "plans": [],\n}'

    data, problems = validation.parse_registry_json(text)

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "syntax"
    assert problems[0].location == "line 4, column 1"


@pytest.mark.parametrize(
    "text",
    [
        pytest.param(
            '{"schema_version": 1, "schema_version": 2, "plans": []}',
            id="duplicate-registry-field",
        ),
        pytest.param(
            '{"schema_version": 1, "plans": [{"plan_id": "first", "plan_id": "second"}]}',
            id="duplicate-nested-field",
        ),
        pytest.param("NaN", id="nan"),
        pytest.param("Infinity", id="positive-infinity"),
        pytest.param("-Infinity", id="negative-infinity"),
    ],
)
def test_rejects_ambiguous_or_nonstandard_json(text: str) -> None:
    # Python normally keeps the last duplicate JSON key. These cases require
    # explicit rejection, so an earlier value cannot disappear silently when
    # a saved document or response is parsed.
    data, problems = validation.parse_registry_json(text)

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "syntax"
    # Decoder hooks do not expose an exact position; do not invent one.
    assert problems[0].location is None
    assert problems[0].message


@pytest.mark.parametrize("text", ["null", "[]", '"a registry"'])
def test_readable_json_must_still_match_the_registry_schema(text: str) -> None:
    data, problems = validation.parse_registry_json(text)

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "structure"
    assert problems[0].location == "$"


def test_invalid_registry_is_not_returned_as_usable_data(valid_registry: dict) -> None:
    valid_registry["plans"][0]["date_accessed"] = "2026-02-29"

    data, problems = validation.parse_registry_json(json.dumps(valid_registry))

    assert data is None
    assert problems[0].category == "structure"
    assert problems[0].location == "$.plans[0].date_accessed"


def test_registry_reader_does_not_apply_model_response_repairs() -> None:
    text = '```json\n{"schema_version": 1, "plans": []}\n```'

    data, problems = validation.parse_registry_json(text)

    assert data is None
    assert problems[0].category == "syntax"


@pytest.mark.parametrize(
    "schema_text",
    [
        pytest.param(None, id="missing-file"),
        pytest.param('{"type":', id="unreadable-json"),
        pytest.param('{"type": "unknown_type"}', id="invalid-schema"),
    ],
)
def test_unusable_schema_is_reported_as_a_setup_problem(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, schema_text: str | None
) -> None:
    # tmp_path is an isolated temporary directory supplied by pytest.
    schema_path = tmp_path / "registry.schema.json"
    if schema_text is not None:
        schema_path.write_text(schema_text, encoding="utf-8")

    # Temporarily redirect schema loading; pytest restores the real path afterward.
    monkeypatch.setattr(validation, "_REGISTRY_SCHEMA_PATH", schema_path)

    problems = validation.validate_registry_structure({"schema_version": 1, "plans": []})

    assert len(problems) == 1
    assert problems[0].category == "other"
    assert problems[0].location == str(schema_path)
    assert "Cannot load the registry schema" in problems[0].message
