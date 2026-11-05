"""Check permitted text edits and refusal boundaries without calling a model.

The examples are fictional. These tests establish formatting and validation
behavior, not extraction accuracy, quotation fidelity, or model suitability.
"""
# Read the fixture and check_final helper first, then the four rule sections,
# then the refusal/report tests. Parameterized tests run one named case per input.

import copy
import json

import pytest

import repair
import validation


@pytest.fixture
def response(run_record: dict) -> dict:
    # Reuse only the fictional content/review, not the synthetic run's succeeded
    # label or measurements. Each test gets its own independently editable copy.
    return copy.deepcopy({"content": run_record["content"], "review": run_record["review"]})


def check_final(text: str, *, completion_status: str = "normal", stage: str = "extractor"):
    return validation.validate_and_repair_agent_response(
        text, page_count=5, stage=stage, completion_status=completion_status,
        raw_response_path="runs/plan_0099/run_extract_0001/responses/response_01.txt",
    )


@pytest.mark.parametrize("completion_status", ["normal", "unknown"])
@pytest.mark.parametrize("stage", ["extractor", "verifier"])
def test_valid_answer_is_accepted_with_exact_original_text(response: dict, completion_status: str, stage: str) -> None:
    text = " \n" + json.dumps(response, ensure_ascii=False, indent=2) + "\t\n"
    result = check_final(text, completion_status=completion_status, stage=stage)
    assert result.response == response
    assert result.raw_text == result.candidate_text == text
    assert result.report == {
        "raw_response_path": "runs/plan_0099/run_extract_0001/responses/response_01.txt",
        "repaired_response_path": None, "initial_errors": [], "remaining_errors": [],
        "repairs": [], "valid": True,
    }
    assert validation.validate_validation_report(result.report) == []


@pytest.mark.parametrize("opening,closing", [
    ("```json\n", "\n```"), ("```\n", "\n```"),
    (" \n```JSON\r\n", "\r\n```\t\r\n"),
])
@pytest.mark.parametrize("completion_status", ["normal", "unknown"])
def test_whole_response_fence_is_removed(response: dict, opening: str, closing: str, completion_status: str) -> None:
    body = json.dumps(response, ensure_ascii=False, indent=2)
    raw = opening + body + closing
    result = check_final(raw, completion_status=completion_status)
    assert result.response == response
    assert result.raw_text == raw
    assert result.candidate_text == body
    assert [change["rule"] for change in result.report["repairs"]] == ["json_code_fence"]
    assert result.report["initial_errors"][0]["category"] == "syntax"
    assert result.report["remaining_errors"] == []


@pytest.mark.parametrize("text", [
    'Here is the answer:\n```json\n{}\n```', '```json\n{}\n```\nThank you.',
    '```json\n{} {}\n```', '```json\n{}\n{}\n```',
    '```json\n{}\n```\n```json\n{}\n```',
    '```javascript\n{}\n```', '~~~json\n{}\n~~~',
    '```json\n{\'field\': 1}\n```', '```json\n{"field":}\n```',
])
def test_fence_rule_refuses_commentary_multiple_answers_and_unapproved_syntax(text: str) -> None:
    result = repair.repair_agent_response(text, completion_status="normal")
    assert result.candidate_text == text
    assert result.repairs == ()


@pytest.mark.parametrize("text", [
    'Commentary with ,} and ,] punctuation.', '{"quote": \'Preserve ,} exactly\',}',
    'Here is JSON: {"a":1,}', '{"a":1,} {"b":2,}',
    '{"a":1,"a":2,}', '{"a":,}', '{"a":"invalid\\q ,}",}',
])
def test_comma_rule_does_not_edit_ambiguous_non_json_or_invalid_quotations(text: str) -> None:
    result = repair.repair_agent_response(text, completion_status="normal")
    assert result.candidate_text == text
    assert result.repairs == ()


def test_trailing_commas_are_removed_but_quotation_characters_are_preserved(response: dict) -> None:
    quote = 'Keep ,} and ,] plus "quoted words", backslashes \\, and Unicode £–é.'
    response["content"]["plan_actions"][0]["evidence"][0]["quote"] = quote
    clean = json.dumps(response, ensure_ascii=False, indent=2)
    # Introduce one comma at each container ending. Comma-looking text inside
    # quote remains a string; it must not become an edit target.
    raw = clean.replace("\n  }", ",\n  }")[:-1] + ",\n}"
    result = check_final(raw)
    assert result.response == response
    assert result.response["content"]["plan_actions"][0]["evidence"][0]["quote"] == quote
    assert all(change["rule"] == "trailing_comma" for change in result.report["repairs"])
    assert all(change["before"] == "," and change["after"] == "" for change in result.report["repairs"])
    assert result.raw_text == raw


@pytest.mark.parametrize("text,expected", [
    ('{"a": [1, 2, \n\t],}', '{"a": [1, 2 \n\t]}'),
    ('{"a": ",}", "b": ",]",}', '{"a": ",}", "b": ",]"}'),
    ('{"a":"ends with a slash \\\\",}', '{"a":"ends with a slash \\\\"}'),
])
def test_comma_scanner_respects_strings_escapes_and_json_whitespace(text: str, expected: str) -> None:
    result = repair.repair_agent_response(text, completion_status="unknown")
    assert result.candidate_text == expected
    assert json.loads(expected) == json.loads(result.candidate_text)


@pytest.mark.parametrize("text,expected", [
    ('{"a": 12', '{"a": 12}'), ('{"a": -12.50e+2', '{"a": -12.50e+2}'),
    ('{"a": "complete"', '{"a": "complete"}'), ('{"a": true', '{"a": true}'),
    ('{"a": false', '{"a": false}'), ('{"a": null', '{"a": null}'),
    ('{"a": []', '{"a": []}'), ('{"a": {}', '{"a": {}}'),
    ('{"a": [{"b": 1', '{"a": [{"b": 1}]}'),
    ('[1, {"b": [2 \n', '[1, {"b": [2 \n]}]'),
])
def test_closers_are_appended_only_after_complete_values(text: str, expected: str) -> None:
    result = repair.repair_agent_response(text, completion_status="normal")
    assert result.candidate_text == expected
    assert [change.rule for change in result.repairs] == ["missing_closing_delimiters"]
    assert result.repairs[0].before == ""
    assert result.repairs[0].after == expected[len(text):]


@pytest.mark.parametrize("text", [
    "{", "[", '{"a":', '{"a": [', '{"a": {', '{"a"',
    '{"a": "unfinished', '{"a": "unfinished\\', '{"a": tru',
    '{"a": 1e', '{"a": 1.', '{"a": -', '{"a": [1,',
    '{"a": [1}', '{"a": 1}}', '{} {"a": 1',
    '{"a": 1 // commentary', '{"a": NaN', '{"a": 1, "a": 2',
])
def test_unfinished_values_ambiguous_nesting_and_duplicate_fields_are_not_completed(text: str) -> None:
    result = repair.repair_agent_response(text, completion_status="normal")
    assert result.candidate_text == text
    assert result.repairs == ()


def test_unknown_completion_never_appends_closers(response: dict) -> None:
    raw = json.dumps(response)[:-1]
    result = check_final(raw, completion_status="unknown")
    assert result.response is None
    assert result.raw_text == result.candidate_text == raw
    assert result.report["repairs"] == []
    assert result.report["valid"] is False
    assert result.report["remaining_errors"][0]["category"] == "syntax"


def test_unknown_completion_can_remove_a_comma_without_closing_an_unfinished_answer() -> None:
    raw = '{"a": [1,]'
    result = repair.repair_agent_response(raw, completion_status="unknown")
    assert result.candidate_text == '{"a": [1]'
    assert [change.rule for change in result.repairs] == ["trailing_comma"]


def test_comma_audit_positions_refer_to_the_candidate_before_the_rule() -> None:
    raw = '{\n  "a": [1,],\n}'
    result = repair.repair_agent_response(raw, completion_status="normal")
    assert result.candidate_text == '{\n  "a": [1]\n}'
    assert [change.location for change in result.repairs] == ["line 2, column 10", "line 2, column 12"]


@pytest.mark.parametrize("category", [
    "plan_goals", "plan_actions", "plan_mon_eval", "plan_benefits", "plan_costs",
])
def test_page_number_rule_targets_all_five_record_categories(category: str) -> None:
    # Minimal objects suffice for testing edit locations. They intentionally lack
    # required research fields, so a later full validation must still reject them.
    raw = '{"content":{"' + category + '":[{"evidence":[{"quote":"Exact.","page_numbers":12}]}]}}'
    result = repair.repair_agent_response(raw, completion_status="unknown")
    assert result.candidate_text == raw.replace('"page_numbers":12', '"page_numbers":[12]')
    assert len(result.repairs) == 1
    assert result.repairs[0].location == f"$.content.{category}[0].evidence[0].page_numbers"
    assert (result.repairs[0].before, result.repairs[0].after) == ("12", "[12]")


@pytest.mark.parametrize("value", ['"12"', "0", "-1", "true", "false", "null", "1.0", "1e0", "[]", "[1]"])
def test_page_number_rule_does_not_interpret_or_guess_other_values(response: dict, value: str) -> None:
    raw = json.dumps(response).replace('"page_numbers": [1]', '"page_numbers": ' + value)
    result = repair.repair_agent_response(raw, completion_status="normal")
    assert result.candidate_text == raw
    assert result.repairs == ()


def test_unknown_page_fields_and_numbers_inside_quotes_remain_unchanged(response: dict) -> None:
    response["content"]["plan_info"]["page_numbers"] = 3
    response["review"]["page_numbers"] = 2
    response["content"]["plan_actions"][0]["page_numbers"] = 4
    response["content"]["plan_actions"][0]["action"] = 'Keep "page_numbers": 12 in this text.'
    raw = json.dumps(response)
    result = check_final(raw)
    assert result.response is None
    assert result.candidate_text == raw
    assert result.report["repairs"] == []
    assert any(error["category"] == "structure" for error in result.report["remaining_errors"])


def test_all_four_repairs_are_ordered_and_preserve_original_values(response: dict) -> None:
    response["content"]["plan_actions"][0]["evidence"][0]["page_numbers"] = 2
    body = json.dumps(response, ensure_ascii=False)
    body = body.replace('"plan_costs": []', '"plan_costs": [ ]')
    body = body.replace('"issues": []', '"issues": [ ] ,')[:-1]
    raw = "```json\n" + body + "\n```"
    result = check_final(raw)
    expected = copy.deepcopy(response)
    expected["content"]["plan_actions"][0]["evidence"][0]["page_numbers"] = [2]
    assert result.response == expected
    assert result.raw_text == raw
    assert [change["rule"] for change in result.report["repairs"]] == [
        "json_code_fence", "trailing_comma", "missing_closing_delimiters", "single_page_number",
    ]
    assert result.report["valid"] is True
    assert result.report["repaired_response_path"].endswith("/responses/repaired_final.txt")
    assert validation.validate_validation_report(result.report) == []


def test_number_spelling_and_escaped_quote_spelling_are_not_reserialized() -> None:
    raw = r'{"content":{"plan_actions":[{"evidence":[{"quote":"\u00a3 1,000 \/ year","page_numbers":2}]}]},"number":1.2300e+04}'
    result = repair.repair_agent_response(raw, completion_status="normal")
    assert result.candidate_text == raw.replace('"page_numbers":2', '"page_numbers":[2]')


def test_multiple_page_number_edits_preserve_record_order_and_each_value(response: dict) -> None:
    first = response["content"]["plan_actions"][0]
    first["evidence"][0]["page_numbers"] = 2
    second = copy.deepcopy(first)
    second["action_id"] = "action_0002"
    second["evidence"] = [
        {"quote": "Another exact quotation.", "page_numbers": 3},
        {"quote": "A separate passage.", "page_numbers": 4},
    ]
    response["content"]["plan_actions"].append(second)
    raw = json.dumps(response, ensure_ascii=False, indent=2)
    result = check_final(raw, completion_status="unknown")
    expected = copy.deepcopy(response)
    for action in expected["content"]["plan_actions"]:
        for evidence in action["evidence"]:
            evidence["page_numbers"] = [evidence["page_numbers"]]
    assert result.response == expected
    assert len(result.report["repairs"]) == 3
    assert [change["before"] for change in result.report["repairs"]] == ["2", "3", "4"]
    assert result.candidate_text == raw.replace('"page_numbers": 2', '"page_numbers": [2]').replace(
        '"page_numbers": 3', '"page_numbers": [3]'
    ).replace('"page_numbers": 4', '"page_numbers": [4]')


@pytest.mark.parametrize("problem", ["missing-field", "unknown-field", "broken-link", "duplicate-id", "out-of-range", "wrong-stage"])
def test_formatting_repairs_do_not_hide_remaining_validation_errors(response: dict, problem: str) -> None:
    action = response["content"]["plan_actions"][0]
    action["evidence"][0]["page_numbers"] = 2
    if problem == "missing-field":
        del action["action_status"]
    elif problem == "unknown-field":
        action["extra"] = "Do not remove this field."
    elif problem == "broken-link":
        action["related_goal_ids"] = ["nonexistent_goal"]
    elif problem == "duplicate-id":
        response["content"]["plan_actions"].append(copy.deepcopy(action))
    elif problem == "out-of-range":
        action["evidence"][0]["page_numbers"] = 6
    else:
        response["review"]["issues"] = [{
            "issue_id": "issue_0001", "related_record_id": "action_0001",
            "description": "Wrong stage for an extractor.", "origin_stage": "verifier",
            "status": "open", "resolved_by": None, "resolution": None,
        }]
    before = copy.deepcopy(response)
    raw = json.dumps(response)
    result = check_final(raw)
    assert result.response is None
    assert result.report["repairs"]
    assert result.report["valid"] is False
    assert result.report["initial_errors"] and result.report["remaining_errors"]
    assert response == before  # No guessed fields, reference repairs, or caller mutation.
    assert validation.validate_validation_report(result.report) == []


@pytest.mark.parametrize("completion_status", ["truncated", "failed"])
@pytest.mark.parametrize("fenced", [False, True])
def test_operational_failure_prevents_acceptance_even_for_valid_json(response: dict, completion_status: str, fenced: bool) -> None:
    text = json.dumps(response)
    raw = "```json\n" + text + "\n```" if fenced else text
    result = check_final(raw, completion_status=completion_status)
    assert result.response is None
    assert result.raw_text == result.candidate_text == raw
    assert result.report["repairs"] == []
    assert result.report["valid"] is False
    assert result.report["remaining_errors"][0]["category"] == "other"
    assert repair.repair_agent_response(raw, completion_status=completion_status).repairs == ()
    assert validation.validate_validation_report(result.report) == []


@pytest.mark.parametrize("raw", [
    '{"a":1,"a":2}', '{"content":{"plan_actions":[{"evidence":[{"page_numbers":1,"page_numbers":2}]}]}}',
    '{"a":NaN}', '{"a":Infinity}', '{"a":-Infinity}', '{"a":1} {"b":2}',
    "", "   ", "None", "{\"a\": undefined}",
])
def test_unapproved_json_errors_are_preserved_and_reported(raw: str) -> None:
    result = check_final(raw)
    assert result.response is None
    assert result.candidate_text == result.raw_text == raw
    assert result.report["repairs"] == []
    assert result.report["remaining_errors"][0]["category"] == "syntax"


@pytest.mark.parametrize("status", ["stop", "length", "", None])
def test_completion_state_must_be_explicitly_normalized(status: object) -> None:
    # Provider strings belong to models.py's future adapter. The repair module
    # must not guess their meaning from labels that differ between providers.
    with pytest.raises(ValueError, match="Completion status"):
        repair.repair_agent_response("{}", completion_status=status)
    with pytest.raises(ValueError, match="Completion status"):
        check_final("{}", completion_status=status)


@pytest.mark.parametrize("path", [
    "/tmp/responses/raw.txt", "../responses/raw.txt", "runs/raw.txt",
    "runs/x/responses/repaired_final.txt", "C:/responses/raw.txt",
])
def test_report_paths_cannot_replace_raw_with_repaired_text(path: str) -> None:
    with pytest.raises(ValueError, match="raw response"):
        validation.validate_and_repair_agent_response(
            "{}", page_count=5, stage="extractor", completion_status="normal", raw_response_path=path,
        )


def test_strict_parser_still_does_not_apply_repairs(response: dict) -> None:
    raw = "```json\n" + json.dumps(response) + "\n```"
    parsed, problems = validation.parse_agent_response_json(raw, page_count=5, stage="extractor")
    assert parsed is None and problems[0].category == "syntax"
    assert check_final(raw).response == response
