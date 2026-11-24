"""Check curated E/V and C answers without permitting expert model claims.

These checks establish structural acceptance and workflow identity boundaries.
They do not establish source support or whether an expert actually made a fix.
"""

from copy import deepcopy
from itertools import product

import pytest
from jsonschema import Draft202012Validator

from collaboration_contracts import (
    CollaborationContractError,
    validate_collaboration_response,
)
import models
import validation


C_ACTORS = ("worker_1", "worker_2", "coordinator")
ORIGINS = ("extractor", "verifier", *C_ACTORS)
RESOLVERS = (*ORIGINS, "expert")


@pytest.fixture
def curated(run_record):
    answer = deepcopy({key: run_record[key] for key in ("plan_data", "plan_issues")})
    answer["plan_issues"]["issues"] = [{
        "issue_id": "issue_0001",
        "related_action_id": "action_0001",
        "issue_description": "Check the quantity in the original table.",
        "issue_type": "source_issue",
        "issue_origin": "worker_1",
        "issue_status": "open",
        "resolved_by": None,
        "resolution": None,
    }]
    return answer


@pytest.mark.parametrize("origin", ORIGINS)
def test_curated_answers_preserve_open_issues_from_either_workflow(curated, origin):
    curated["plan_issues"]["issues"][0]["issue_origin"] = origin
    original = deepcopy(curated)
    assert validation.validate_curated_dataset(curated, page_count=3) == []
    assert curated == original


@pytest.mark.parametrize("origin,resolver", tuple(product(ORIGINS, RESOLVERS)))
def test_curated_resolution_identities_stay_within_their_workflow(curated, origin, resolver):
    curated["plan_issues"]["issues"][0].update(
        issue_origin=origin, issue_status="resolved", resolved_by=resolver,
        resolution="The original table confirms the recorded quantity.",
    )
    # V follows E, while C workers and the coordinator can check each other.
    allowed = {
        "extractor": {"extractor", "verifier", "expert"},
        "verifier": {"verifier", "expert"},
        **{actor: {*C_ACTORS, "expert"} for actor in C_ACTORS},
    }
    original = deepcopy(curated)
    problems = validation.validate_curated_dataset(curated, page_count=3)
    assert (problems == []) == (resolver in allowed[origin])
    assert curated == original


@pytest.mark.parametrize("origin", ORIGINS)
def test_expert_resolutions_remain_curation_only(curated, origin):
    curated["plan_issues"]["issues"][0].update(
        issue_origin=origin, issue_status="resolved", resolved_by="expert",
        resolution="The expert checked the original PDF and corrected the quantity.",
    )
    assert validation.validate_curated_dataset(curated, page_count=3) == []
    for stage in ("extractor", "verifier"):
        assert validation.validate_agent_response(curated, page_count=3, stage=stage)
    assert not Draft202012Validator(models.prepare_response_schema()).is_valid(curated)
    assert not Draft202012Validator(
        models.prepare_collaboration_schema("collaboration_response.schema.json")
    ).is_valid(curated)
    with pytest.raises(CollaborationContractError):
        validate_collaboration_response(
            curated, page_count=3, source_metadata=curated["plan_data"]["metadata"],
        )


@pytest.mark.parametrize("origin", C_ACTORS)
def test_c_model_identities_still_cannot_enter_e_v_answers(curated, origin):
    curated["plan_issues"]["issues"][0]["issue_origin"] = origin
    validate_collaboration_response(
        curated, page_count=3, source_metadata=curated["plan_data"]["metadata"],
    )
    for stage in ("extractor", "verifier"):
        assert validation.validate_agent_response(curated, page_count=3, stage=stage)
    assert not Draft202012Validator(models.prepare_response_schema()).is_valid(curated)


@pytest.mark.parametrize("reverse", [False, True])
def test_curated_answer_cannot_mix_baseline_and_c_issue_origins(curated, reverse):
    issues = curated["plan_issues"]["issues"]
    issues[0]["related_action_id"] = None
    other = deepcopy(issues[0])
    other.update(issue_id="issue_0002", issue_origin="extractor")
    issues.append(other)
    if reverse:
        issues.reverse()
    assert validation.validate_curated_dataset(curated, page_count=3)


def test_invalid_c_resolver_identifies_the_field_requiring_correction(curated):
    curated["plan_issues"]["issues"][0].update(
        issue_status="resolved", resolved_by="verifier", resolution="Checked.",
    )
    problems = validation.validate_curated_dataset(curated, page_count=3)
    assert len(problems) == 1
    assert problems[0].location == "$.plan_issues.issues[0].resolved_by"


@pytest.mark.parametrize("origin", C_ACTORS)
@pytest.mark.parametrize("damage", [
    "unknown_origin", "unknown_resolver", "open_resolution", "missing_resolver",
    "missing_resolution", "blank_resolution", "missing_field", "extra_field",
    "unknown_action", "duplicate_issues", "duplicate_links", "bad_page",
    "empty_evidence", "empty_type",
])
def test_c_curation_retains_field_and_reference_guards(curated, origin, damage):
    issue = curated["plan_issues"]["issues"][0]
    issue["issue_origin"] = origin
    action = curated["plan_data"]["actions"][0]
    if damage == "unknown_origin":
        issue["issue_origin"] = "expert"
    elif damage == "unknown_resolver":
        issue.update(issue_status="resolved", resolved_by="worker_3", resolution="Checked.")
    elif damage == "open_resolution":
        issue.update(resolved_by="expert", resolution="Checked.")
    elif damage in ("missing_resolver", "missing_resolution", "blank_resolution"):
        issue.update(issue_status="resolved", resolved_by="expert", resolution="Checked.")
        issue["resolved_by" if damage == "missing_resolver" else "resolution"] = (
            "  " if damage == "blank_resolution" else None
        )
    elif damage == "missing_field":
        del issue["issue_description"]
    elif damage == "extra_field":
        issue["expert_approved"] = True
    elif damage == "unknown_action":
        issue["related_action_id"] = "missing"
    elif damage in ("duplicate_issues", "duplicate_links"):
        other = deepcopy(issue)
        if damage == "duplicate_issues":
            other["related_action_id"] = None
        else:
            other["issue_id"] = "issue_0002"
        curated["plan_issues"]["issues"].append(other)
    elif damage == "bad_page":
        action["evidence"][0]["page_numbers"] = [4]
    else:
        action["evidence" if damage == "empty_evidence" else "action_type"] = []
        issue["related_action_id"] = None
    assert validation.validate_curated_dataset(curated, page_count=3)


@pytest.mark.parametrize("page_count", [None, 0, -1, True, 1.5, "3"])
def test_c_curation_requires_the_original_pdf_page_count(curated, page_count):
    assert validation.validate_curated_dataset(curated, page_count=page_count)


def test_curated_answer_with_no_issues_remains_valid(curated):
    curated["plan_issues"]["issues"] = []
    assert validation.validate_curated_dataset(curated, page_count=3) == []
