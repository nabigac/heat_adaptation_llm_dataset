"""Check coordinator configuration without enabling collaboration execution."""

import copy
from pathlib import Path

import pytest

import agents
import huggingface_api as hf
from models import prepare_response_schema
from test_profiles import configuration, project, save_configuration, snapshot
from validation import validate_profiles, validate_run_record


PROFILE = "glm5_3_flash_hf_coordinator"


@pytest.fixture
def coordinator_project(project, configuration):
    configuration["profiles"][0].update(name="fictional_coordinator", stage="coordinator")
    save_configuration(project, configuration)
    return project


def test_editable_coordinator_profile_loads_without_writes(coordinator_project):
    before = snapshot(coordinator_project)
    config = agents.load_profiles(coordinator_project)
    assert validate_profiles(config) == []
    settings = agents.load_profile(coordinator_project, "fictional_coordinator", stage="coordinator")
    assert settings["stage"] == "coordinator"
    assert settings["document_tools"] == config["document_tools"]
    assert len(settings["prompt_texts"]) == len(settings["prompt_paths"])
    assert "environment" not in settings
    assert snapshot(coordinator_project) == before


@pytest.mark.parametrize("stage", ["extractor", "verifier"])
def test_coordinator_cannot_enter_existing_input_builders(coordinator_project, stage):
    before = snapshot(coordinator_project)
    with pytest.raises(agents.ProfileValidationError, match=f"is for coordinator, not {stage}"):
        if stage == "extractor":
            agents.build_extractor_input(
                coordinator_project, "plan_0001", source_path="not_opened.json",
                profile_name="fictional_coordinator",
            )
        else:
            agents.build_verifier_input(
                coordinator_project, "plan_0001", profile_name="fictional_coordinator",
                purpose="development",
            )
    assert snapshot(coordinator_project) == before


def test_coordinator_loading_does_not_extend_saved_ev_run_stages(coordinator_project, run_record):
    settings = agents.load_profile(coordinator_project, "fictional_coordinator", stage="coordinator")
    settings["environment"] = copy.deepcopy(run_record["settings"]["environment"])
    record = copy.deepcopy(run_record)
    record["settings"] = settings
    problems = validate_run_record(record, page_count=5)
    assert any(problem.location == "$.settings.stage" for problem in problems)


def test_repository_coordinator_prepares_routed_request_without_authentication(monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    root = Path(__file__).resolve().parents[1]
    settings = agents.load_profile(root, PROFILE, stage="coordinator")
    messages = [{"role": "system", "content": "\n\n".join(settings["prompt_texts"])},
                {"role": "user", "content": "Fictional plan for offline request assembly."}]
    request = hf.build_huggingface_request(settings, messages, response_format=prepare_response_schema())
    assert request.body["model"] == "zai-org/GLM-5.3-Flash:deepinfra"
    assert request.body["messages"][:2] == messages
    assert request.max_output_tokens == 131072 and request.context_limit == 1048576
    assert settings["prompt_paths"] == [
        "prompts/shared_coding.md", "prompts/field_definitions.md", "prompts/coordinator.md",
    ]
    assert settings["prompt_texts"] == [(root / path).read_bytes().decode("utf-8")
                                         for path in settings["prompt_paths"]]
    assert hf.estimate_huggingface_budget(request).report["fits"]
    # This exercises configuration/transport only. C's task, response and run
    # contracts are deliberately not enabled by profile loading.
