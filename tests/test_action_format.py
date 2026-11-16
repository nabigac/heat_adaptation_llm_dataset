"""Check the single current plan dataset contract.

These checks establish format and value preservation. They do not assess how a
model groups activities or whether its descriptions are supported by a source.
"""

import copy
import json

import pytest
from jsonschema import Draft202012Validator

import models
import validation


@pytest.fixture
def response(run_record):
    return copy.deepcopy({key: run_record[key] for key in ("plan_data", "plan_issues")})


def review_issue(**changes):
    issue = {
        "issue_id": "issue_0001",
        "related_action_id": "action_0001",
        "issue_description": "Check the reported quantity against the source.",
        "issue_type": "unclear_meaning",
        "issue_origin": "extractor",
        "issue_status": "open",
        "resolved_by": None,
        "resolution": None,
    }
    issue.update(changes)
    return issue


def test_current_parser_preserves_grouped_phase_details(response):
    action = response["plan_data"]["actions"][0]
    action.update(
        action="Tree planting: 100 completed in North Ward in 2025; 200 planned in South Ward in 2027.",
        action_status="unspecified", action_location="North Ward; South Ward",
        action_cost="A shared USD 30,000 allocation covers both phases.",
        action_benefit="Expected shade improvement, with no observed quantity stated.",
    )
    before = copy.deepcopy(response)
    parsed, problems = validation.parse_agent_response_json(
        json.dumps(response), page_count=3, stage="extractor"
    )
    assert problems == []
    assert parsed == before
    assert response == before
    assert set(parsed) == {"plan_data", "plan_issues"}
    assert set(parsed["plan_data"]) == {"metadata", "actions"}
    assert len(parsed["plan_data"]["actions"]) == 1


@pytest.mark.parametrize("field", [
    "action_id", "action", "action_type", "action_status", "action_location",
    "action_recipient", "action_cost", "action_benefit", "evidence",
])
def test_all_nine_action_fields_are_required(response, field):
    del response["plan_data"]["actions"][0][field]
    assert validation.validate_agent_response(response, page_count=3, stage="extractor")


@pytest.mark.parametrize("status", ["planned", "underway", "completed", "unspecified"])
def test_current_status_options(response, status):
    response["plan_data"]["actions"][0]["action_status"] = status
    assert validation.validate_agent_response(response, page_count=3, stage="extractor") == []


@pytest.mark.parametrize("status", ["in_progress", "not_specified", "discontinued"])
def test_current_format_rejects_unsupported_status_values(response, status):
    response["plan_data"]["actions"][0]["action_status"] = status
    assert validation.validate_agent_response_structure(response)


@pytest.mark.parametrize("types,valid", [
    (["nature-based", "infrastructural"], True),
    (["institutional", "behavioral/cultural"], True),
    (["nature-based", "nature-based"], False),
    (["other"], False),
    ("nature-based", False),
])
def test_types_are_unique_supported_values(response, types, valid):
    response["plan_data"]["actions"][0]["action_type"] = types
    assert (not validation.validate_agent_response(response, page_count=3, stage="extractor")) == valid


@pytest.mark.parametrize("field", ["action_type", "evidence"])
def test_empty_types_or_evidence_require_an_issue_linked_to_the_action(response, field):
    response["plan_data"]["actions"][0][field] = []
    assert validation.validate_agent_response(response, page_count=3, stage="extractor")
    response["plan_issues"]["issues"] = [review_issue()]
    assert validation.validate_agent_response(response, page_count=3, stage="extractor") == []
    response["plan_issues"]["issues"][0]["related_action_id"] = None
    assert validation.validate_agent_response(response, page_count=3, stage="extractor")


@pytest.mark.parametrize("field", ["action_location", "action_recipient", "action_cost", "action_benefit"])
def test_missing_descriptive_details_are_null_not_blank_strings(response, field):
    response["plan_data"]["actions"][0][field] = None
    assert validation.validate_agent_response(response, page_count=3, stage="extractor") == []
    response["plan_data"]["actions"][0][field] = "  "
    assert validation.validate_agent_response_structure(response)


@pytest.mark.parametrize("damage", ["duplicate_actions", "duplicate_issues", "duplicate_links", "unknown_action", "page_range"])
def test_action_and_issue_references_are_checked(response, damage):
    response["plan_issues"]["issues"] = [review_issue()]
    if damage == "duplicate_actions":
        actions = response["plan_data"]["actions"]
        actions.append(copy.deepcopy(actions[0]))
    elif damage == "duplicate_issues":
        response["plan_issues"]["issues"].append(review_issue(related_action_id=None))
    elif damage == "duplicate_links":
        response["plan_issues"]["issues"].append(review_issue(issue_id="issue_0002"))
    elif damage == "unknown_action":
        response["plan_issues"]["issues"][0]["related_action_id"] = "missing"
    else:
        response["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [4]
    assert validation.validate_agent_response(response, page_count=3, stage="extractor")


def test_expert_resolution_is_valid_in_curated_answers_and_rejected_in_model_answers(response):
    response["plan_issues"]["issues"] = [review_issue(
        issue_status="resolved", resolved_by="expert",
        resolution="The expert checked the original table and corrected the quantity.",
    )]
    assert validation.validate_curated_dataset(response, page_count=3) == []
    for stage in ("extractor", "verifier"):
        assert validation.validate_agent_response(response, page_count=3, stage=stage)
    provider = Draft202012Validator(models.prepare_ollama_response_schema())
    assert not provider.is_valid(response)




@pytest.mark.parametrize("old_name,new_name", [
    ("extra_data", "plan_data"), ("extra_issues", "plan_issues"),
])
def test_answers_reject_unexpected_section_names_instead_of_rewriting_them(response, old_name, new_name):
    response[old_name] = response.pop(new_name)
    parsed, problems = validation.parse_agent_response_json(
        json.dumps(response), page_count=3, stage="extractor"
    )
    assert parsed is None and problems
    assert old_name in response and new_name not in response


def test_page_number_repair_uses_the_current_data_path_and_preserves_quoted_words(response):
    evidence = response["plan_data"]["actions"][0]["evidence"][0]
    evidence.update(quote="The source uses the words content and review.", page_numbers=1)
    result = validation.validate_and_repair_agent_response(
        json.dumps(response), page_count=3, stage="extractor", completion_status="normal",
        raw_response_path="runs/plan_0099/run_extract_0001/responses/response_01.txt",
    )
    assert result.report["valid"]
    assert result.report["repairs"][0]["location"] == "$.plan_data.actions[0].evidence[0].page_numbers"
    repaired = result.response["plan_data"]["actions"][0]["evidence"][0]
    assert repaired == {"quote": evidence["quote"], "page_numbers": [1]}






@pytest.mark.parametrize("damage", ["missing_issue", "changed_origin", "wrong_resolver", "new_extractor_issue"])
def test_verifier_preserves_issue_identity_and_resolution_authorship(run_record, damage):
    baseline = copy.deepcopy(run_record)
    baseline["plan_issues"]["issues"] = [review_issue()]
    revised = copy.deepcopy(baseline)
    revised.update(stage="verifier", run_id="run_verify_0001", input_run_id=baseline["run_id"])
    revised["settings"]["stage"] = "verifier"
    assert validation.validate_run_links(revised, input_run=baseline) == []
    if damage == "missing_issue":
        revised["plan_issues"]["issues"] = []
    elif damage == "changed_origin":
        revised["plan_issues"]["issues"][0]["issue_origin"] = "verifier"
    elif damage == "wrong_resolver":
        revised["plan_issues"]["issues"][0].update(
            issue_status="resolved", resolved_by="extractor", resolution="A new verifier fix."
        )
    else:
        revised["plan_issues"]["issues"].append(review_issue(
            issue_id="issue_0002", related_action_id=None
        ))
    assert validation.validate_run_links(revised, input_run=baseline)
