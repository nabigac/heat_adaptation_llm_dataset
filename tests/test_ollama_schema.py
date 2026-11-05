"""Check the provider copy against our authoritative response contract.

These tests exercise conversion and validation without contacting Ollama. Live
synthetic probes check the serving setup separately; neither proves extraction
accuracy, source support, or completeness on research documents.
"""

import copy
import itertools
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

import models
from validation import validate_agent_response, validate_agent_response_structure


ROOT = Path(__file__).resolve().parents[1]
CONTENT_URI = "urn:heat-adaptation:content"
RESPONSE_URI = "urn:heat-adaptation:agent-response"
DIALECT = "https://json-schema.org/draft/2020-12/schema"


@pytest.fixture
def response(run_record: dict) -> dict:
    """Populate every record type and both issue states with fictional data."""
    data = copy.deepcopy({key: run_record[key] for key in ("content", "review")})
    content = data["content"]
    evidence = [{"quote": "Fictional source passage.\nContinued here.", "page_numbers": [1, 2]}]
    content["plan_goals"] = [{
        "goal_id": "goal_0001", "goal": "Reduce heat exposure.",
        "targets": [{"target": "Provide shade for 20 stops.", "deadline": None}],
        "evidence": copy.deepcopy(evidence),
    }]
    content["plan_actions"][0]["related_goal_ids"] = ["goal_0001"]
    for category, prefix, description in (
        ("plan_mon_eval", "mon_eval", "Inspect shade annually."),
        ("plan_benefits", "benefit", "Expected reduction in exposure."),
        ("plan_costs", "cost", "Estimated £500,000 for shade."),
    ):
        content[category] = [{
            prefix + "_id": prefix + "_0001", prefix: description, "scope": "linked",
            "related_goal_ids": ["goal_0001"], "related_action_ids": ["action_0001"],
            "evidence": copy.deepcopy(evidence),
        }]
    data["review"]["issues"] = [
        {"issue_id": "issue_0001", "related_record_id": "action_0001",
         "description": "A fictional chart remains unclear.", "type": "source_issue",
         "origin_stage": "extractor", "status": "open", "resolved_by": None, "resolution": None},
        {"issue_id": "issue_0002", "related_record_id": "cost_0001",
         "description": "A fictional budget needed clarification.", "type": "conflicting_evidence",
         "origin_stage": "extractor", "status": "resolved", "resolved_by": "extractor",
         "resolution": "The footnote distinguishes the first phase from the total."},
    ]
    assert validate_agent_response(data, page_count=5, stage="extractor") == []
    return data


@pytest.fixture(scope="module")
def prepared_validator():
    return Draft202012Validator(models.prepare_ollama_response_schema(), format_checker=FormatChecker())


def assert_agreement(data, prepared_validator, expected: bool) -> None:
    """Compare real acceptance decisions, not just converted dictionary shapes."""
    assert (not validate_agent_response_structure(data)) is expected
    assert prepared_validator.is_valid(data) is expected


def nodes(value, path=()):
    """Enumerate instance locations so required-field checks cover every record."""
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from nodes(child, path + (key,))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from nodes(child, path + (index,))


def at(data, path):
    for part in path:
        data = data[part]
    return data


def test_every_required_field_and_unknown_field_still_rejected(response, prepared_validator):
    assert_agreement(response, prepared_validator, True)
    for path, value in nodes(response):
        if not isinstance(value, dict):
            continue
        # Issue type is the only optional field in this complete fixture.
        for key in value:
            damaged = copy.deepcopy(response)
            del at(damaged, path)[key]
            assert_agreement(damaged, prepared_validator, key == "type")
        damaged = copy.deepcopy(response)
        at(damaged, path)["unexpected"] = "must not be silently accepted"
        assert_agreement(damaged, prepared_validator, False)


@pytest.mark.parametrize("text", [
    "", " ", "\t\r\n", "\u2003", "\u2028", "A", "AB", " a ", "\na\n",
    "Plant 20 trees.", "£500,000", "Line one.\nLine two.", "x\u2003", "\u2028A", "\x00", "😀",
])
def test_nonblank_rule_preserves_multiline_and_unicode_acceptance(response, prepared_validator, text):
    for path in (
        ("content", "plan_actions", 0, "action"),
        ("content", "plan_info", "country"),
        ("content", "plan_goals", 0, "targets", 0, "deadline"),
        ("content", "plan_mon_eval", 0, "evidence", 0, "quote"),
        ("review", "issues", 1, "resolution"),
    ):
        changed = copy.deepcopy(response)
        at(changed, path[:-1])[path[-1]] = text
        assert_agreement(changed, prepared_validator, bool(text.strip()))


@pytest.mark.parametrize("path,value,expected", [
    (("content", "plan_info", "country"), None, True),
    (("content", "plan_info", "country"), 3, False),
    (("content", "plan_info", "plan_scale"), "city", True),
    (("content", "plan_info", "plan_scale"), "district", False),
    (("content", "plan_info", "plan_type"), "broader_climate_plan", True),
    (("content", "plan_info", "plan_type"), "other", False),
    (("content", "plan_info", "language"), "French", False),
    (("content", "plan_info", "publication_year"), True, False),
    (("content", "plan_info", "publication_year"), 2026, True),
    (("content", "plan_info", "date_accessed"), "2026-02-30", False),
    (("content", "plan_info", "date_accessed"), "2024-02-29", True),
    (("content", "plan_info", "lead_agencies"), [""], False),
    (("content", "plan_actions", 0, "action_status"), "not_specified", True),
    (("content", "plan_actions", 0, "action_status"), "unknown", False),
    (("content", "plan_benefits", 0, "scope"), "unspecified", True),
    (("content", "plan_costs", 0, "scope"), "national", False),
    (("content", "plan_goals", 0, "evidence"), [], True),
    (("content", "plan_goals", 0, "evidence", 0, "page_numbers"), [], False),
    (("content", "plan_goals", 0, "evidence", 0, "page_numbers"), [0], False),
    (("content", "plan_goals", 0, "evidence", 0, "page_numbers"), [1, 1], False),
    (("content", "plan_goals", 0, "evidence", 0, "page_numbers"), [True], False),
    (("content", "plan_goals", 0, "evidence", 0, "page_numbers"), 1, False),
    (("review", "issues", 0, "type"), None, True),
    (("review", "issues", 0, "type"), "invented_type", False),
    (("review", "issues", 0, "origin_stage"), "verifier", True),
    (("review", "issues", 0, "origin_stage"), "expert", False),
])
def test_field_types_values_and_bounds_agree(response, prepared_validator, path, value, expected):
    at(response, path[:-1])[path[-1]] = value
    assert_agreement(response, prepared_validator, expected)


@pytest.mark.parametrize("status,resolver,resolution", list(itertools.product(
    ("open", "resolved"), (None, "extractor", "verifier", "expert"), (None, "", "Clarified by a footnote.")
)))
def test_issue_conditional_rules_are_preserved(response, prepared_validator, status, resolver, resolution):
    response["review"]["issues"][0].update(status=status, resolved_by=resolver, resolution=resolution)
    expected = ((resolver is None and resolution is None) if status == "open" else
                (resolver in ("extractor", "verifier") and bool(resolution)))
    assert_agreement(response, prepared_validator, expected)


@pytest.mark.parametrize("damage", ["duplicate_ids", "unknown_link", "page_outside_document", "wrong_stage"])
def test_schema_mode_does_not_replace_semantic_validation(response, prepared_validator, damage):
    if damage == "duplicate_ids":
        response["review"]["issues"][1]["issue_id"] = "issue_0001"
    elif damage == "unknown_link":
        response["content"]["plan_actions"][0]["related_goal_ids"] = ["missing_goal"]
    elif damage == "page_outside_document":
        response["content"]["plan_goals"][0]["evidence"][0]["page_numbers"] = [6]
    else:
        response["review"]["issues"][0]["origin_stage"] = "verifier"
    assert_agreement(response, prepared_validator, True)
    assert validate_agent_response(response, page_count=5, stage="extractor")


def test_prepared_copy_is_self_contained_fresh_and_explicit(run_record):
    sources = {path: path.read_bytes() for path in (ROOT / "schemas").glob("*.schema.json")}
    first = models.prepare_ollama_response_schema()
    second = models.prepare_ollama_response_schema()
    assert first == second
    assert first["$schema"] == DIALECT
    assert not any(isinstance(value, dict) and {"$id", "$defs", "$ref"} & value.keys()
                   for _, value in nodes(first))
    assert sources == {path: path.read_bytes() for path in sources}
    settings = run_record["settings"]
    messages = [{"role": "user", "content": "Fictional test only."}]
    _, body, _ = models.build_ollama_request(settings, messages, response_format=first)
    assert body["format"] == first
    body["format"]["properties"].clear()
    first["properties"]["content"]["properties"].clear()
    assert second == models.prepare_ollama_response_schema()
    assert "format" not in models.build_ollama_request(settings, messages)[1]


@pytest.fixture
def schema_files(tmp_path, monkeypatch):
    """Use tiny local schema files to isolate errors without editing real files."""
    monkeypatch.setattr(models, "_SCHEMA_DIRECTORY", tmp_path)

    def write(content=None, response=None):
        documents = {
            "content.schema.json": {"$schema": DIALECT, "$id": CONTENT_URI, **(content or {})},
            "agent_response.schema.json": {"$schema": DIALECT, "$id": RESPONSE_URI,
                **(response if response is not None else {"type": "object", "properties": {"content": {"$ref": CONTENT_URI}}})},
        }
        for filename, document in documents.items():
            (tmp_path / filename).write_text(json.dumps(document), encoding="utf-8")
        return tmp_path

    return write


@pytest.mark.parametrize("damage", ["missing", "invalid_utf8", "invalid_json", "duplicate", "nan", "invalid_schema", "wrong_id", "wrong_dialect"])
def test_bad_source_files_fail_visibly(schema_files, damage):
    folder = schema_files()
    path = folder / "content.schema.json"
    if damage == "missing":
        path.unlink()
    elif damage == "invalid_utf8":
        path.write_bytes(b"\xff")
    elif damage == "invalid_json":
        path.write_text("{unfinished")
    elif damage == "duplicate":
        path.write_text('{"$id":"' + CONTENT_URI + '","type":"object","type":"string"}')
    elif damage == "nan":
        path.write_text('{"$id":"' + CONTENT_URI + '","default":NaN}')
    elif damage == "invalid_schema":
        schema_files(content={"type": 42})
    elif damage == "wrong_id":
        schema_files(content={"$id": "urn:unknown"})
    else:
        schema_files(content={"$schema": "http://json-schema.org/draft-07/schema#"})
    with pytest.raises(models.OllamaSchemaError):
        models.prepare_ollama_response_schema()


@pytest.mark.parametrize("reference", [
    "https://example.org/never-fetch.json", "file:///never-read.json", "urn:unknown",
    "#/$defs/missing", "#anchor", "#/$defs/bad~2escape", "#/$defs/end~", "#/%FF",
    "#/allOf/01", "#/allOf/-1", "#/allOf/9", "#/allOf/x", "#/title",
])
def test_unknown_or_unsupported_references_fail_locally(schema_files, reference):
    schema_files(content={"title": "Literal title, not a schema.", "allOf": [{"type": "object"}],
                          "properties": {"value": {"$ref": reference}}})
    with pytest.raises(models.OllamaSchemaError, match="reference|Pointer|Expected a schema"):
        models.prepare_ollama_response_schema()


@pytest.mark.parametrize("cross_document", [False, True])
def test_recursive_references_fail_instead_of_recursing_forever(schema_files, cross_document):
    target = RESPONSE_URI + "#/$defs/back" if cross_document else "#/$defs/loop"
    schema_files(content={"$defs": {"loop": {"$ref": target}},
                          "properties": {"value": {"$ref": "#/$defs/loop"}}},
                 response={"$defs": {"back": {"$ref": CONTENT_URI + "#/$defs/loop"}},
                           "properties": {"content": {"$ref": CONTENT_URI}}})
    with pytest.raises(models.OllamaSchemaError, match="Recursive"):
        models.prepare_ollama_response_schema()


@pytest.mark.parametrize("fragment", [
    {"$id": "urn:nested", "type": "string"},
    {"$ref": "#/$defs/text", "minLength": 10},
    {"$ref": "#/$defs/text", "$schema": DIALECT},
    {"$ref": "#/$defs/no", "description": "Boolean annotation not supported."},
    {"pattern": "^other$"}, {"$dynamicRef": "#/$defs/text"},
    {"unevaluatedProperties": False}, {"patternProperties": {"x": {"type": "string"}}},
])
def test_unsupported_rules_are_rejected_rather_than_dropped(schema_files, fragment):
    schema_files(content={"$defs": {"text": {"type": "string"}, "no": False},
                          "properties": {"value": fragment}})
    with pytest.raises(models.OllamaSchemaError):
        models.prepare_ollama_response_schema()


def test_pointer_escapes_array_targets_and_repeated_refs(schema_files):
    schema_files(content={
        "$defs": {"slash/name~": {"type": "string", "description": "Original wording."}},
        "allOf": [{"type": "object"}],
        "properties": {
            "first": {"$ref": "#/$defs/slash~1name~0", "description": "Additional guidance."},
            "second": {"$ref": "#/$defs/slash~1name~0"},
            "array_target": {"$ref": "#/allOf/0"},
        },
    })
    properties = models.prepare_ollama_response_schema()["properties"]["content"]["properties"]
    assert properties["first"]["description"] == "Original wording.\nAdditional guidance."
    assert properties["second"]["description"] == "Original wording."
    assert properties["array_target"] == {"type": "object"}
    properties["first"]["type"] = "integer"
    assert properties["second"]["type"] == "string"


def test_literal_values_and_property_names_are_never_treated_as_schema_keywords(schema_files):
    literal = {"$ref": "https://example.org/literal", "pattern": "leave exactly as written", "$defs": {}}
    schema_files(content={"type": "object", "properties": {
        name: {"const": literal, "examples": [literal], "default": literal}
        for name in ("$ref", "$id", "$schema", "$defs", "pattern")
    }})
    properties = models.prepare_ollama_response_schema()["properties"]["content"]["properties"]
    assert set(properties) == {"$ref", "$id", "$schema", "$defs", "pattern"}
    assert all(value == {"const": literal, "examples": [literal], "default": literal} for value in properties.values())


def test_compositions_and_boolean_schemas_keep_their_constraints(schema_files):
    content = {"type": "array", "prefixItems": [True], "items": {"$ref": "#/$defs/text"},
               "contains": {"$ref": "#/$defs/text"}, "minContains": 1, "maxContains": 2,
               "$defs": {"text": {"type": "string", "pattern": r"\S"}},
               "allOf": [{"not": {"type": "null"}}],
               "anyOf": [{"minItems": 2}, {"maxItems": 0}],
               "oneOf": [{"uniqueItems": True}, False]}
    schema_files(content=content)
    prepared = models.prepare_ollama_response_schema()["properties"]["content"]
    original = Draft202012Validator(content)
    converted = Draft202012Validator(prepared)
    for value in ([], ["text"], [1, "text"], [None, "text"], None):
        assert original.is_valid(value) == converted.is_valid(value)
    assert converted.is_valid([1, "text"])
    assert not converted.is_valid([1, "   "])
    assert prepared["prefixItems"] == [True]
    assert prepared["oneOf"][1] is False
