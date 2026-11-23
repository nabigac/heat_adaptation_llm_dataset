"""Check shared DeepInfra schema adaptation without contacting a model.

Compare acceptance decisions as well as request differences. Shared Python
validation remains authoritative, including rules omitted by every DeepInfra
generation copy. Live provider acceptance is tested separately.
"""

import asyncio
from copy import deepcopy
import itertools
import json

import httpx
import pytest
from jsonschema import Draft202012Validator

import huggingface_api as hf
import huggingface_check as check
from models import prepare_response_schema
from test_agent_loop import PROFILE, answer
from test_huggingface_api import (
    DEEPSEEK_MODEL, DEEPSEEK_ROUTER_MODEL, GLM_MODEL, GLM_ROUTER_MODEL, MODEL, TOKEN,
    envelope, hosted_project, project, settings,
)
from test_huggingface_check import schema_replies


def issue_items(schema):
    return schema["properties"]["plan_issues"]["properties"]["issues"]["items"]


def request_schema(settings, schema):
    request = hf.build_huggingface_request(
        settings, [{"role": "user", "content": "Fictional plan."}], response_format=schema,
    )
    return request.body["response_format"]["json_schema"]["schema"]


@pytest.mark.parametrize("model,provider,flattened", [
    (GLM_MODEL, "deepinfra", True),
    (GLM_MODEL.lower(), "deepinfra", True),
    (MODEL, "deepinfra", True),
    (DEEPSEEK_MODEL, "deepinfra", True),
    ("zai-org/GLM-5.3", "deepinfra", True),
    ("zai-org/GLM-5.2-Flash", "deepinfra", True),
    (GLM_MODEL, "other-host", False),
    (MODEL, "other-host", False),
])
def test_all_deepinfra_models_share_representation_and_inputs_remain_intact(
    settings, model, provider, flattened,
):
    settings["model"].update(name=model, provider=provider)
    source = prepare_response_schema()
    before = deepcopy((settings, source))
    expected = (hf.prepare_deepinfra_response_schema(source)
                if provider == "deepinfra" else deepcopy(source))
    if flattened:
        # Preparing the standalone issue definition removes conditional rules
        # without encountering the whole-answer path used for flattening.
        merged = hf.prepare_deepinfra_response_schema(issue_items(source)["allOf"][0])
        merged["properties"]["resolved_by"]["enum"] = ["extractor", "verifier", None]
        expected["properties"]["plan_issues"]["properties"]["issues"]["items"] = merged

    actual = request_schema(settings, source)

    assert actual == expected
    Draft202012Validator.check_schema(actual)
    assert (settings, source) == before
    assert ("allOf" not in issue_items(actual)) is flattened


@pytest.mark.parametrize("model", [MODEL, DEEPSEEK_MODEL, GLM_MODEL])
def test_issue_acceptance_matches_unflattened_schema_across_valid_and_invalid_inputs(settings, model):
    settings["model"]["name"] = model
    source = prepare_response_schema()
    unflattened = {"allOf": [hf.prepare_deepinfra_response_schema(branch)
                             for branch in issue_items(source)["allOf"]]}
    original = Draft202012Validator(unflattened)
    flattened = Draft202012Validator(issue_items(request_schema(settings, source)))
    issue = {
        "issue_id": "issue_0001", "related_action_id": None,
        "issue_description": "The fictional source is unclear.",
        "issue_origin": "extractor", "issue_status": "open",
        "resolved_by": None, "resolution": None,
    }
    cases = []
    for origin, status, resolver, resolution in itertools.product(
        ["extractor", "verifier", "expert", "coordinator", None],
        ["open", "resolved", "other", None],
        [None, "extractor", "verifier", "expert", "coordinator", 0],
        ["Source checked.", None, "", 7],
    ):
        cases.append(dict(issue, issue_origin=origin, issue_status=status,
                          resolved_by=resolver, resolution=resolution))
    for required in issue:
        incomplete = deepcopy(issue)
        del incomplete[required]
        cases.append(incomplete)
    cases.extend([dict(issue, unexpected="extra field"), [], None, "not an object", 1])

    assert len(cases) == 492
    accepted = 0
    for candidate in cases:
        expected = original.is_valid(candidate)
        assert flattened.is_valid(candidate) == expected, candidate
        accepted += expected
    assert 0 < accepted < len(cases)


@pytest.mark.parametrize("variation", [
    "third_branch", "additional_restriction", "different_enum", "reversed_branches",
    "sibling_constraint", "narrower_base_enum", "missing_base_enum",
])
def test_unfamiliar_compositions_are_preserved_without_a_general_merge(settings, variation):
    settings["model"]["name"] = GLM_MODEL
    source = prepare_response_schema()
    items = issue_items(source)
    issue, restriction = items["allOf"]
    if variation == "third_branch":
        items["allOf"].append({"minProperties": 7})
    elif variation == "additional_restriction":
        restriction["properties"]["resolution"] = {"minLength": 5}
    elif variation == "different_enum":
        restriction["properties"]["resolved_by"]["enum"].append("expert")
    elif variation == "reversed_branches":
        items["allOf"].reverse()
    elif variation == "sibling_constraint":
        items["minProperties"] = 7
    elif variation == "narrower_base_enum":
        issue["properties"]["resolved_by"]["enum"] = ["verifier", None]
    else:
        del issue["properties"]["resolved_by"]["enum"]

    actual = issue_items(request_schema(settings, source))
    assert "allOf" in actual
    assert actual == hf.prepare_deepinfra_response_schema(items)


def test_three_model_requests_differ_only_in_routing_id(settings):
    source = prepare_response_schema()
    bodies = []
    for model in (MODEL, DEEPSEEK_MODEL, GLM_MODEL):
        chosen = deepcopy(settings)
        chosen["model"]["name"] = model
        body = hf.build_huggingface_request(
            chosen, [{"role": "user", "content": "Fictional plan."}], response_format=source,
        ).body
        assert body.pop("model") == model + ":deepinfra"
        bodies.append(body)
    assert bodies[0] == bodies[1] == bodies[2]


def test_shared_schema_preparation_is_idempotent_and_detached():
    source = prepare_response_schema()
    before = deepcopy(source)
    prepared = hf.prepare_deepinfra_response_schema(source)
    second = hf.prepare_deepinfra_response_schema(prepared)
    assert prepared == second and source == before
    second["properties"]["plan_issues"]["properties"]["issues"]["items"]["required"].append("extra")
    assert prepared == hf.prepare_deepinfra_response_schema(source)


@pytest.mark.parametrize("model,reported", [
    (MODEL, MODEL), (DEEPSEEK_MODEL, DEEPSEEK_ROUTER_MODEL), (GLM_MODEL, GLM_ROUTER_MODEL),
])
@pytest.mark.parametrize("failure", [None, "expert_resolver", "open_resolution", "duplicate_pages"])
def test_diagnostic_saves_exact_flattened_request_and_keeps_python_rules(
    project, run_record, monkeypatch, failure, model, reported,
):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    profile_before = (project / "configs/profiles.json").read_bytes()
    response = json.loads(answer(run_record))
    if failure == "duplicate_pages":
        response["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] *= 2
    elif failure is not None:
        response["plan_issues"]["issues"] = [{
            "issue_id": "issue_0001", "related_action_id": None,
            "issue_description": "Fictional uncertainty.", "issue_origin": "extractor",
            "issue_status": "resolved" if failure == "expert_resolver" else "open",
            "resolved_by": "expert" if failure == "expert_resolver" else "extractor",
            "resolution": "A claimed source clarification.",
        }]
    replies = schema_replies(run_record, reported)
    replies[1] = envelope(json.dumps(response), model=reported)
    if failure is not None:
        replies.pop()  # The standard diagnostic must stop after the invalid project answer.
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))

    path, report = asyncio.run(check.run_checks(
        project, PROFILE, model_name=model, _transport=httpx.MockTransport(handler),
    ))

    assert not replies and report["passed"] is (failure is None)
    assert len(sent) == (3 if failure is None else 2)
    saved = json.loads((path.parent / "project_schema_request.json").read_text())
    assert saved["body"] == sent[1]
    wire_schema = sent[1]["response_format"]["json_schema"]["schema"]
    assert "allOf" not in issue_items(wire_schema)
    assert sent[1]["response_format"]["json_schema"]["strict"] is True
    assert (project / "configs/profiles.json").read_bytes() == profile_before
    assert bool(report["checks"][1]["errors"]) is (failure is not None)
    for artifact in path.parent.iterdir():
        assert TOKEN.encode() not in artifact.read_bytes()
