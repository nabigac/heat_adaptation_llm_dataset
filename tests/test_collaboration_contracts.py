"""Exercise separate C contracts and source-only loading with fictional PDFs."""

from copy import deepcopy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from collaboration_contracts import (
    CollaborationContractError, DEFAULT_COLLABORATION_PROFILE, build_collaboration_input,
    load_collaboration_configuration, validate_collaboration_response,
    validate_task, validate_worker_result,
)
from models import prepare_collaboration_schema
from test_agent_loop import PLAN_ID, SOURCE, project
from test_collaboration import MODELS, answer, assignment, packet
from validation import validate_agent_response
from storage import PreparationValidationError


@pytest.fixture
def configured(project):
    config_file = project / "configs/profiles.json"
    config = json.loads(config_file.read_text())
    base = config["profiles"][0]
    for actor, model in MODELS.items():
        profile = deepcopy(base)
        profile.update(name=actor, stage="coordinator" if actor == "coordinator" else "worker")
        profile["model"]["name"] = model
        config["profiles"].append(profile)
    config_file.write_text(json.dumps(config))
    (project / "configs/collaboration.json").write_text(json.dumps({"schema_version": 1, "profiles": [{
        "name": DEFAULT_COLLABORATION_PROFILE, "agents": {actor: actor for actor in MODELS},
        "limits": {"max_model_requests": 21, "max_document_tool_calls": 60,
                   "max_elapsed_seconds": 5400, "max_estimated_tokens": 22020096},
    }]}))
    return project


def test_source_builder_ignores_baseline_and_expert_files_and_writes_nothing(configured):
    for name in (f"runs/{PLAN_ID}/run_extract_0001/output.json",
                 f"data/expert_references/{PLAN_ID}/expert_reference.json"):
        path = configured / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('not valid JSON; must never be read')
    before = {str(path): path.read_bytes() for path in configured.rglob('*') if path.is_file()}
    data = build_collaboration_input(configured, PLAN_ID, source_path=SOURCE)
    assert data.page_count == 3 and "We will plant 20 trees." in data.source_message["content"]
    assert data.source_metadata["source_url"] == "https://example.org/plan.pdf"
    assert set(data.profiles) == set(MODELS)
    assert before == {str(path): path.read_bytes() for path in configured.rglob('*') if path.is_file()}


@pytest.mark.parametrize("damage", ["same_model", "wrong_worker_role", "different_prompts", "no_final_time", "no_final_tokens", "unknown_name"])
def test_invalid_binding_and_limits_fail_before_source_assembly(configured, damage):
    path = configured / "configs/profiles.json"
    config = json.loads(path.read_text())
    cpath = configured / "configs/collaboration.json"
    collaboration = json.loads(cpath.read_text())
    if damage == "same_model":
        config["profiles"][-1]["model"]["name"] = MODELS["worker_1"]
    elif damage == "wrong_worker_role":
        config["profiles"][-1]["stage"] = "verifier"
    elif damage == "different_prompts":
        config["profiles"][-1]["prompt_paths"] = ["prompts/shared.md"]
    elif damage == "no_final_time":
        collaboration["profiles"][0]["limits"]["max_elapsed_seconds"] = 1
    elif damage == "no_final_tokens":
        collaboration["profiles"][0]["limits"]["max_estimated_tokens"] = 1
    else:
        collaboration["profiles"][0]["agents"]["worker_1"] = "missing-profile"
    path.write_text(json.dumps(config))
    cpath.write_text(json.dumps(collaboration))
    with pytest.raises(ValueError):
        load_collaboration_configuration(configured)


def test_comparison_input_remains_disabled(configured):
    path = configured / 'data/registry/plans.json'
    registry = json.loads(path.read_text())
    registry['plans'][0]['study_set'] = 'comparison'
    path.write_text(json.dumps(registry))
    with pytest.raises(CollaborationContractError, match="development"):
        build_collaboration_input(configured, PLAN_ID, source_path=SOURCE)


def test_changed_original_pdf_is_rejected_by_the_shared_source_checks(configured):
    with (configured / f"data/raw/{PLAN_ID}.pdf").open("ab") as source:
        source.write(b"changed after preparation")
    with pytest.raises(PreparationValidationError):
        build_collaboration_input(configured, PLAN_ID, source_path=SOURCE)


@pytest.mark.parametrize("origin", ["worker_1", "worker_2", "coordinator"])
def test_c_issue_identities_are_valid_only_in_the_separate_c_contract(packet, answer, origin):
    answer["plan_issues"]["issues"] = [{
        "issue_id": "issue_0001", "related_action_id": answer['plan_data']['actions'][0]['action_id'],
        "issue_description": "Fictional uncertainty.", "issue_origin": origin,
        "issue_status": "open", "resolved_by": None, "resolution": None,
    }]
    validate_collaboration_response(answer, page_count=3, source_metadata=packet.source_metadata)
    assert validate_agent_response(answer, page_count=3, stage="extractor")


@pytest.mark.parametrize("damage", ["baseline_role", "expert_resolution", "open_resolution", "duplicate_pages", "bad_page", "source_metadata", "empty_evidence", "duplicate_action"])
def test_c_retains_strict_acceptance_and_source_rules(packet, answer, damage):
    action = answer['plan_data']['actions'][0]
    issue = {'issue_id':'issue_0001','related_action_id':action['action_id'],
             'issue_description':'Fictional uncertainty.','issue_origin':'worker_1','issue_status':'open',
             'resolved_by':None,'resolution':None}
    if damage == 'baseline_role':
        issue['issue_origin'] = 'extractor'
        answer['plan_issues']['issues'] = [issue]
    elif damage in ('expert_resolution','open_resolution'):
        issue.update(resolved_by='expert' if damage=='expert_resolution' else 'worker_2', resolution='Claimed fix.')
        answer['plan_issues']['issues']=[issue]
    elif damage == 'duplicate_pages':
        action['evidence'][0]['page_numbers'] *= 2
    elif damage == 'bad_page':
        action['evidence'][0]['page_numbers']=[99]
    elif damage == 'source_metadata':
        answer['plan_data']['metadata']['source_url']='https://example.org/other.pdf'
    elif damage == 'empty_evidence':
        action['evidence']=[]
    else:
        answer['plan_data']['actions'].append(deepcopy(action))
    with pytest.raises(CollaborationContractError):
        validate_collaboration_response(answer,page_count=3,source_metadata=packet.source_metadata)


def test_independent_task_cannot_receive_even_a_completed_peer_result():
    task={'task_id':'task_0002','draft_version':0,**assignment('worker_2',context=['task_0001'])}
    with pytest.raises(CollaborationContractError,match='Independent'):
        validate_task(task,page_count=3,completed_tasks={'task_0001'})


@pytest.mark.parametrize("page_count", [0, -1, True, 1.5, None])
def test_c_validation_requires_a_real_source_page_count(packet, answer, page_count):
    with pytest.raises(CollaborationContractError, match="page count"):
        validate_collaboration_response(answer, page_count=page_count, source_metadata=packet.source_metadata)


@pytest.mark.parametrize("origin,resolver", [
    ("worker_1", "worker_2"), ("worker_2", "worker_1"), ("coordinator", "worker_1"),
])
def test_c_allows_supported_cross_worker_resolution_claims(packet, answer, origin, resolver):
    answer["plan_issues"]["issues"] = [{
        "issue_id": "issue_0001", "related_action_id": None,
        "issue_description": "An ambiguity needed a source check.", "issue_origin": origin,
        "issue_status": "resolved", "resolved_by": resolver, "resolution": "The source footnote clarifies the scope.",
    }]
    validate_collaboration_response(answer, page_count=3, source_metadata=packet.source_metadata)


def test_original_and_expanded_worker_contracts_reject_missing_result_fields():
    schema=prepare_collaboration_schema('collaboration_result.schema.json')
    Draft202012Validator.check_schema(schema)
    assert not Draft202012Validator(schema).is_valid({'task_id':'task_0001'})


def test_c_keeps_the_baseline_issue_rules_apart_from_agent_identities():
    root = Path(__file__).resolve().parents[1] / "schemas"
    baseline = json.loads((root / "agent_response.schema.json").read_text())
    collaboration = json.loads((root / "collaboration_response.schema.json").read_text())
    issue = deepcopy(collaboration["$defs"]["issue"])
    for field in ("issue_origin", "resolved_by"):
        issue["properties"][field]["enum"] = baseline["$defs"]["issue"]["properties"][field]["enum"]
    assert issue == baseline["$defs"]["issue"]
    assert collaboration["properties"]["plan_data"] == baseline["properties"]["plan_data"]


def test_repository_binding_uses_shared_25_request_allowance_and_common_worker_prompts():
    config,profiles=load_collaboration_configuration(Path(__file__).resolve().parents[1])
    assert config['name']=='glm5_3_flash_hf_collaboration'
    assert config['limits']['max_model_requests']==25
    assert config['limits']['max_document_tool_calls']==75
    assert config['limits']['max_elapsed_seconds']==5400
    assert config['limits']['max_estimated_tokens']==31457280
    assert config['limits']['final_generation_seconds']==1800
    assert all(profile['max_tool_calls']==25 for profile in profiles.values())
    assert profiles['worker_1']['prompt_paths']==profiles['worker_2']['prompt_paths']
    assert profiles['worker_1']['prompt_paths'][-1]=='prompts/worker.md'
