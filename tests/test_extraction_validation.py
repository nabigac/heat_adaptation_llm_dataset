"""Check the Appendix B/C response contract without models or research-file writes.

The fictional examples exercise field rules and relationships. They do not test
whether an LLM extracts faithfully, whether a quotation supports a claim, or
whether the returned records cover all relevant source information.
"""
# Read the valid content/response fixtures first, then the field tests, then
# ID/link/issue tests and parser/setup failures. No files named by the fictional
# metadata need to exist because these validators check supplied data in memory.

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import validation


RECORD_LISTS = (
    ("plan_goals", "goal_id"),
    ("plan_actions", "action_id"),
    ("plan_mon_eval", "mon_eval_id"),
    ("plan_benefits", "benefit_id"),
    ("plan_costs", "cost_id"),
)
SCOPED_LISTS = ("plan_mon_eval", "plan_benefits", "plan_costs")


@pytest.fixture
def content() -> dict:
    """Include every record type, nullable timing, and both linked/unlinked scope."""
    # Use all five record categories so shared rules are exercised through every
    # list. Linked, plan-wide, and unspecified scopes appear deliberately; the
    # quotations are fictional examples, not validated research evidence.
    return {
        "plan_info": {
            "plan_title": "Example City Heat Plan",
            "jurisdiction_name": "Example City",
            "country": "Example Country",
            "plan_scale": "city",
            "plan_type": "heat_specific_plan",
            "publication_year": 2026,
            "lead_agencies": ["Example City Council"],
            "source_url": "https://example.org/heat-plan.pdf",
            "date_accessed": "2026-11-03",
            "language": "English",
        },
        "plan_goals": [{
            "goal_id": "goal_0001",
            "goal": "Increase shade at schools to reduce heat exposure.",
            "targets": [
                {"target": "Shade 20 schools", "deadline": "by 2030"},
                {"target": "Improve school shade", "deadline": None},
            ],
            "evidence": [{"quote": "Our goal is to shade 20 schools by 2030.", "page_numbers": [1]}],
        }],
        "plan_actions": [{
            "action_id": "action_0001",
            "action": "Plant trees at 20 schools to deliver the school shade goal.",
            "action_status": "planned",
            "related_goal_ids": ["goal_0001"],
            "evidence": [{"quote": "We will plant trees at 20 schools.", "page_numbers": [2, 3]}],
        }],
        "plan_mon_eval": [{
            "mon_eval_id": "mon_eval_0001",
            "mon_eval": "Count surviving school trees annually.",
            "scope": "linked",
            "related_goal_ids": ["goal_0001"],
            "related_action_ids": ["action_0001"],
            "evidence": [{"quote": "Count surviving school trees annually.", "page_numbers": [3]}],
        }],
        "plan_benefits": [{
            "benefit_id": "benefit_0001",
            "benefit": "The overall programme is expected to reduce heat exposure.",
            "scope": "plan_wide",
            "related_goal_ids": [],
            "related_action_ids": [],
            "evidence": [{"quote": "The programme is expected to reduce heat exposure.", "page_numbers": [4]}],
        }],
        "plan_costs": [{
            "cost_id": "cost_0001",
            "cost": "An estimated £10,000 is needed; the source does not specify allocation.",
            "scope": "unspecified",
            "related_goal_ids": [],
            "related_action_ids": [],
            "evidence": [{"quote": "Estimated resources: £10,000.", "page_numbers": [5]}],
        }],
    }


@pytest.fixture
def response(content: dict) -> dict:
    # The complete model-answer wrapper adds review to the shared content.
    # The issue points to an existing action so later tests can change one link or
    # status field and isolate the resulting error.
    return {
        "content": content,
        "review": {"issues": [{
            "issue_id": "issue_0001",
            "related_record_id": "action_0001",
            "description": "Check conflicting statements about when planting begins on PDF pages 2–3.",
            "type": "conflicting_evidence",
            "origin_stage": "extractor",
            "status": "open",
            "resolved_by": None,
            "resolution": None,
        }]},
    }


def select_path(data: object, path: tuple):
    """Select a nested test value without duplicating navigation in each case."""
    # The path tuple contains dictionary keys and list positions. For example,
    # ("content", "plan_actions", 0) selects the first action. This helper only
    # navigates the fixture; it does not change or normalize any values.
    for part in path:
        data = data[part]
    return data


def test_schema_definitions_are_valid() -> None:
    for filename in ("content.schema.json", "agent_response.schema.json"):
        path = Path(__file__).resolve().parents[1] / "schemas" / filename
        Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_parses_complete_content_and_response_without_changes(content: dict, response: dict) -> None:
    before = copy.deepcopy(response)
    parsed_content, content_problems = validation.parse_content_json(
        json.dumps(content, ensure_ascii=False), page_count=5
    )
    parsed_response, response_problems = validation.parse_agent_response_json(
        json.dumps(response, ensure_ascii=False), page_count=5, stage="extractor"
    )
    assert parsed_content == content
    assert parsed_response == response
    assert content_problems == response_problems == []
    assert response == before


def test_content_is_valid_without_the_agent_review_wrapper(content: dict) -> None:
    assert validation.validate_content(content, page_count=5) == []
    problems = validation.validate_agent_response_structure({"content": content})
    assert problems and "review" in problems[0].message


def test_empty_categories_and_unknown_nullable_metadata_are_preserved(response: dict) -> None:
    content = response["content"]
    for name, _ in RECORD_LISTS:
        content[name] = []
    for name in ("plan_title", "jurisdiction_name", "country", "plan_scale", "plan_type", "publication_year"):
        content["plan_info"][name] = None
    content["plan_info"]["lead_agencies"] = []
    response["review"]["issues"] = []
    before = copy.deepcopy(response)
    assert validation.validate_agent_response(response, page_count=5, stage="extractor") == []
    assert response == before


@pytest.mark.parametrize("name", [name for name, _ in RECORD_LISTS])
def test_empty_evidence_is_representable_without_inventing_a_quote(content: dict, name: str) -> None:
    # An empty evidence list must remain visible for review. Structural acceptance
    # does not supply a missing quotation or establish that the record is supported.
    content[name][0]["evidence"] = []
    assert validation.validate_content(content, page_count=5) == []
    assert content[name][0]["evidence"] == []


# Each object must reject unknown fields and retain all required fields, including
# fields whose values may legitimately be null. Issue type is tested separately.
OBJECT_PATHS = (
    (), ("content",), ("content", "plan_info"), ("review",), ("review", "issues", 0),
    *(("content", name, 0) for name, _ in RECORD_LISTS),
    ("content", "plan_goals", 0, "targets", 0),
    ("content", "plan_actions", 0, "evidence", 0),
)


@pytest.mark.parametrize("path", OBJECT_PATHS)
def test_required_fields_are_reported_without_being_filled(response: dict, path: tuple) -> None:
    for field in select_path(response, path):
        if path == ("review", "issues", 0) and field == "type":
            continue  # The design explicitly makes only this issue field optional.
        candidate = copy.deepcopy(response)
        del select_path(candidate, path)[field]
        before = copy.deepcopy(candidate)
        problems = validation.validate_agent_response(candidate, page_count=5, stage="extractor")
        assert problems, (path, field)
        assert all(problem.category == "structure" for problem in problems)
        assert any(field in problem.message for problem in problems)
        assert candidate == before


@pytest.mark.parametrize("path", OBJECT_PATHS)
def test_unknown_fields_are_rejected_at_each_object_level(response: dict, path: tuple) -> None:
    select_path(response, path)["unexpected"] = "Keep this visible as an error."
    problems = validation.validate_agent_response_structure(response)
    assert problems and all(problem.category == "structure" for problem in problems)
    assert any("unexpected" in problem.message for problem in problems)


@pytest.mark.parametrize(("path", "value"), [
    (("content", "plan_info", "publication_year"), True),
    (("content", "plan_info", "publication_year"), "2026"),
    (("content", "plan_info", "publication_year"), 2026.5),
    (("content", "plan_info", "date_accessed"), "2026-02-29"),
    (("content", "plan_info", "date_accessed"), "03-11-2026"),
    (("content", "plan_info", "language"), "French"),
    (("content", "plan_info", "lead_agencies"), [None]),
    (("content", "plan_info", "plan_scale"), "district"),
    (("content", "plan_info", "plan_type"), "draft"),
    (("content", "plan_actions", 0, "action_status"), "ongoing"),
    (("content", "plan_actions", 0, "related_goal_ids"), [None]),
    (("content", "plan_goals", 0, "targets", 0, "deadline"), 2030),
    (("content", "plan_costs", 0, "scope"), "unknown"),
    (("content", "plan_actions", 0, "action"), " \n\t"),
    (("content", "plan_actions", 0, "action_id"), ""),
    (("content", "plan_actions", 0, "evidence", 0, "quote"), "  "),
    (("content", "plan_actions", 0, "evidence", 0, "page_numbers"), []),
    (("content", "plan_actions", 0, "evidence", 0, "page_numbers"), [2, 2]),
    (("content", "plan_actions", 0, "evidence", 0, "page_numbers"), [0]),
    (("content", "plan_actions", 0, "evidence", 0, "page_numbers"), [-1]),
    (("content", "plan_actions", 0, "evidence", 0, "page_numbers"), [True]),
    (("content", "plan_actions", 0, "evidence", 0, "page_numbers"), [2.5]),
    (("content", "plan_actions", 0, "evidence", 0, "page_numbers"), ["2"]),
    (("content", "plan_actions", 0, "evidence", 0, "page_numbers"), 2),
    (("review", "issues", 0, "type"), "confidence_low"),
    (("review", "issues", 0, "status"), "pending"),
    (("review", "issues", 0, "origin_stage"), "expert"),
])
def test_invalid_field_values_are_structure_errors(response: dict, path: tuple, value: object) -> None:
    select_path(response, path[:-1])[path[-1]] = value
    problems = validation.validate_agent_response_structure(response)
    assert problems and all(problem.category == "structure" for problem in problems)


@pytest.mark.parametrize("status", ["planned", "in_progress", "completed", "discontinued", "not_specified"])
def test_accepts_each_defined_action_status(content: dict, status: str) -> None:
    content["plan_actions"][0]["action_status"] = status
    assert validation.validate_content(content, page_count=5) == []


@pytest.mark.parametrize("scale", ["city", "county", "region", "state", "country", None])
def test_accepts_each_defined_plan_scale(content: dict, scale: str | None) -> None:
    content["plan_info"]["plan_scale"] = scale
    assert validation.validate_content(content, page_count=5) == []


@pytest.mark.parametrize("plan_type", ["heat_specific_plan", "broader_climate_plan", None])
def test_accepts_each_defined_plan_type(content: dict, plan_type: str | None) -> None:
    content["plan_info"]["plan_type"] = plan_type
    assert validation.validate_content(content, page_count=5) == []


@pytest.mark.parametrize(("list_name", "id_field"), RECORD_LISTS)
def test_rejects_duplicate_ids_within_each_record_list(content: dict, list_name: str, id_field: str) -> None:
    content[list_name].append(copy.deepcopy(content[list_name][0]))
    before = copy.deepcopy(content)
    problems = validation.validate_content(content, page_count=5)
    assert len(problems) == 1
    assert problems[0].category == "reference"
    assert problems[0].location == f"$.{list_name}[1].{id_field}"
    assert content == before


def test_record_ids_must_be_unique_across_categories(content: dict) -> None:
    # Issue links use one related_record_id field, so reusing the same ID in two
    # content categories would make that link ambiguous even if each list alone
    # contained no duplicate.
    content["plan_costs"][0]["cost_id"] = "action_0001"
    problems = validation.validate_content(content, page_count=5)
    assert len(problems) == 1 and problems[0].location == "$.plan_costs[0].cost_id"


def test_ids_are_not_forced_into_example_prefixes_or_renamed(content: dict) -> None:
    content["plan_goals"][0]["goal_id"] = "school-shade-goal"
    content["plan_actions"][0]["related_goal_ids"] = ["school-shade-goal"]
    content["plan_mon_eval"][0]["related_goal_ids"] = ["school-shade-goal"]
    before = copy.deepcopy(content)
    assert validation.validate_content(content, page_count=5) == []
    assert content == before


LINK_FIELDS = (
    ("plan_actions", "related_goal_ids", "action_0001"),
    *((name, "related_goal_ids", "action_0001") for name in SCOPED_LISTS),
    *((name, "related_action_ids", "goal_0001") for name in SCOPED_LISTS),
)


@pytest.mark.parametrize(("list_name", "field", "wrong_category_id"), LINK_FIELDS)
@pytest.mark.parametrize("missing", [False, True], ids=["wrong-category", "missing-record"])
def test_links_must_resolve_to_the_correct_record_category(
    content: dict, list_name: str, field: str, wrong_category_id: str, missing: bool
) -> None:
    record = content[list_name][0]
    record[field] = ["nonexistent" if missing else wrong_category_id]
    if "scope" in record:
        record["scope"] = "linked"
    problems = validation.validate_content(content, page_count=5)
    assert len(problems) == 1 and problems[0].category == "reference"
    assert problems[0].location == f"$.{list_name}[0].{field}[0]"


@pytest.mark.parametrize("list_name", SCOPED_LISTS)
@pytest.mark.parametrize(("scope", "goal_links", "action_links"), [
    ("linked", [], []),
    ("plan_wide", ["goal_0001"], []),
    ("unspecified", [], ["action_0001"]),
])
def test_scope_must_agree_with_links(
    content: dict, list_name: str, scope: str, goal_links: list, action_links: list
) -> None:
    content[list_name][0].update(scope=scope, related_goal_ids=goal_links, related_action_ids=action_links)
    problems = validation.validate_content(content, page_count=5)
    assert len(problems) == 1 and problems[0].location == f"$.{list_name}[0].scope"


@pytest.mark.parametrize("list_name", SCOPED_LISTS)
@pytest.mark.parametrize(("scope", "goal_links", "action_links"), [
    ("linked", ["goal_0001"], []),
    ("linked", [], ["action_0001"]),
    ("plan_wide", [], []),
    ("unspecified", [], []),
])
def test_accepts_defined_scope_and_link_combinations(
    content: dict, list_name: str, scope: str, goal_links: list, action_links: list
) -> None:
    content[list_name][0].update(scope=scope, related_goal_ids=goal_links, related_action_ids=action_links)
    assert validation.validate_content(content, page_count=5) == []


@pytest.mark.parametrize(("list_name", "_"), RECORD_LISTS)
def test_citations_are_checked_in_every_record_category(content: dict, list_name: str, _: str) -> None:
    content[list_name][0]["evidence"][0]["page_numbers"] = [1, 6]
    problems = validation.validate_content(content, page_count=5)
    assert len(problems) == 1 and problems[0].category == "reference"
    assert problems[0].location == f"$.{list_name}[0].evidence[0].page_numbers[1]"
    assert "1 to 5" in problems[0].message


def test_preserves_separate_passages_exact_wording_and_page_boundaries(content: dict) -> None:
    content["plan_actions"][0]["evidence"] = [
        {"quote": '  “Plant 20 trees.”\nKeep punctuation and £1,000.  ', "page_numbers": [1, 5]},
        {"quote": "A separate footnote.", "page_numbers": [5]},
    ]
    before = copy.deepcopy(content)
    assert validation.validate_content(content, page_count=5) == []
    assert content == before


@pytest.mark.parametrize("page_count", [None, 0, -1, True, 5.0, "5"])
def test_invalid_source_page_count_is_a_setup_error(content: dict, response: dict, page_count: object) -> None:
    for problems in (
        validation.validate_content(content, page_count=page_count),
        validation.validate_agent_response(response, page_count=page_count, stage="extractor"),
    ):
        assert len(problems) == 1 and problems[0].category == "other"
        assert problems[0].location == "page_count"


@pytest.mark.parametrize("stage", [None, "expert", [], 1])
def test_invalid_executing_stage_is_a_setup_error(response: dict, stage: object) -> None:
    problems = validation.validate_agent_response(response, page_count=5, stage=stage)
    assert len(problems) == 1 and problems[0].category == "other"
    assert problems[0].location == "stage"


def test_issue_ids_must_be_unique(response: dict) -> None:
    other = dict(response["review"]["issues"][0], related_record_id=None)
    response["review"]["issues"].append(other)
    problems = validation.validate_agent_response(response, page_count=5, stage="extractor")
    assert len(problems) == 1 and problems[0].location == "$.review.issues[1].issue_id"


def test_issue_record_links_must_exist(response: dict) -> None:
    response["review"]["issues"][0]["related_record_id"] = "missing-record"
    problems = validation.validate_agent_response(response, page_count=5, stage="extractor")
    assert len(problems) == 1 and problems[0].location == "$.review.issues[0].related_record_id"


def test_grouped_problems_use_one_issue_per_affected_record(response: dict) -> None:
    response["review"]["issues"].append(dict(response["review"]["issues"][0], issue_id="issue_0002"))
    problems = validation.validate_agent_response(response, page_count=5, stage="extractor")
    assert len(problems) == 1 and problems[0].location == "$.review.issues[1].related_record_id"


def test_multiple_unlinked_source_or_omission_issues_are_allowed(response: dict) -> None:
    issue = response["review"]["issues"][0]
    issue.update(related_record_id=None, type="source_issue")
    response["review"]["issues"].append(dict(issue, issue_id="issue_0002", type="no_records_found"))
    assert validation.validate_agent_response(response, page_count=5, stage="extractor") == []


@pytest.mark.parametrize("issue_type", [
    None, "unclear_meaning", "conflicting_evidence", "source_issue",
    "extraction_process_issue", "no_records_found",
])
def test_accepts_each_optional_issue_type(response: dict, issue_type: str | None) -> None:
    response["review"]["issues"][0]["type"] = issue_type
    assert validation.validate_agent_response(response, page_count=5, stage="extractor") == []


def test_omitted_issue_type_is_not_inserted(response: dict) -> None:
    del response["review"]["issues"][0]["type"]
    assert validation.validate_agent_response(response, page_count=5, stage="extractor") == []
    assert "type" not in response["review"]["issues"][0]


@pytest.mark.parametrize(("status", "resolved_by", "resolution"), [
    ("open", "extractor", None),
    ("open", None, "Already fixed."),
    ("resolved", None, "Checked the source."),
    ("resolved", "extractor", None),
    ("resolved", "extractor", "   "),
])
def test_issue_resolution_fields_must_agree_with_status(
    response: dict, status: str, resolved_by: str | None, resolution: str | None
) -> None:
    response["review"]["issues"][0].update(status=status, resolved_by=resolved_by, resolution=resolution)
    problems = validation.validate_agent_response_structure(response)
    assert problems and all(problem.category == "structure" for problem in problems)


@pytest.mark.parametrize(("stage", "origin", "resolved_by"), [
    ("extractor", "extractor", "extractor"),
    ("verifier", "extractor", "extractor"),
    ("verifier", "extractor", "verifier"),
    ("verifier", "verifier", "verifier"),
])
def test_accepts_consistent_issue_resolution_stages(response: dict, stage: str, origin: str, resolved_by: str) -> None:
    response["review"]["issues"][0].update(
        status="resolved", origin_stage=origin, resolved_by=resolved_by,
        resolution="Source checking established that no correction was necessary."
    )
    assert validation.validate_agent_response(response, page_count=5, stage=stage) == []


@pytest.mark.parametrize(("stage", "origin", "resolved_by", "field"), [
    ("extractor", "verifier", None, "origin_stage"),
    ("extractor", "extractor", "verifier", "resolved_by"),
    ("verifier", "verifier", "extractor", "resolved_by"),
])
def test_rejects_impossible_issue_stages(
    response: dict, stage: str, origin: str, resolved_by: str | None, field: str
) -> None:
    issue = response["review"]["issues"][0]
    issue["origin_stage"] = origin
    if resolved_by is not None:
        issue.update(status="resolved", resolved_by=resolved_by, resolution="Claimed resolution.")
    problems = validation.validate_agent_response(response, page_count=5, stage=stage)
    assert len(problems) == 1 and problems[0].category == "reference"
    assert problems[0].location == "$.review.issues[0]." + field


@pytest.mark.parametrize("reader_name", ["content", "agent_response"])
@pytest.mark.parametrize("text", [
    '{"unfinished":', '{"x": 1, "x": 2}', '{"nested": {"x": 1, "x": 2}}',
    "NaN", "Infinity", "-Infinity", '```json\n{}\n```', '{"x": 1,}',
])
def test_readers_reject_bad_json_without_repairs(reader_name: str, text: str) -> None:
    if reader_name == "content":
        data, problems = validation.parse_content_json(text, page_count=5)
    else:
        data, problems = validation.parse_agent_response_json(text, page_count=5, stage="extractor")
    assert data is None and len(problems) == 1
    assert problems[0].category == "syntax"


@pytest.mark.parametrize("data", [None, [], "a response", 1])
def test_wrong_input_shapes_are_reported_without_crashing(data: object) -> None:
    assert validation.validate_content(data, page_count=5)[0].category == "structure"
    assert validation.validate_agent_response(data, page_count=5, stage="extractor")[0].category == "structure"


def test_parser_withholds_response_when_a_record_link_is_invalid(response: dict) -> None:
    response["content"]["plan_actions"][0]["related_goal_ids"] = ["missing-goal"]
    data, problems = validation.parse_agent_response_json(json.dumps(response), page_count=5, stage="extractor")
    assert data is None and len(problems) == 1
    assert problems[0].category == "reference"
    assert problems[0].location == "$.content.plan_actions[0].related_goal_ids[0]"


@pytest.mark.parametrize("schema_text", [None, '{"type":', '{"type": "invalid-type"}'])
def test_missing_or_invalid_shared_schema_is_a_setup_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict, schema_text: str | None
) -> None:
    schema_path = tmp_path / "content.schema.json"
    if schema_text is not None:
        schema_path.write_text(schema_text, encoding="utf-8")
    monkeypatch.setattr(validation, "_CONTENT_SCHEMA_PATH", schema_path)
    for problems in (
        validation.validate_content_structure(response["content"]),
        validation.validate_agent_response_structure(response),
    ):
        assert len(problems) == 1 and problems[0].category == "other"
        assert problems[0].location == str(schema_path)


def test_response_reuses_the_loaded_content_schema(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, response: dict
) -> None:
    # Changing one local schema must change both entry points' rules. This catches
    # accidentally maintaining a separate copy of the content definition.
    path = tmp_path / "content.schema.json"
    path.write_text(json.dumps({"type": "object", "required": ["sentinel"]}), encoding="utf-8")
    monkeypatch.setattr(validation, "_CONTENT_SCHEMA_PATH", path)
    for problems in (
        validation.validate_content_structure(response["content"]),
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
        validation.validate_content_structure(response["content"]),
        validation.validate_agent_response_structure(response),
    ):
        assert len(problems) == 1 and problems[0].category == "other"
        assert "required format checkers are unavailable: date" in problems[0].message
