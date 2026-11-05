"""Check profile selection and exact prompt snapshots without starting models.

All configurable settings in fixtures are fictional. The repository's starter
profile is also loaded as a file-format check, not a model capability test.
"""
# The fixtures create a small temporary project. Tests modify only its files,
# then check user-visible loading failures and preservation of loaded settings.

import copy
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

import agents
import validation


@pytest.fixture
def configuration(run_record: dict) -> dict:
    # Editable profiles contain the model choices but not prompt text copies or
    # detected environment. Shared document tools live once outside the list.
    profile = copy.deepcopy(run_record["settings"])
    document_tools = profile.pop("document_tools")
    profile.pop("prompt_texts")
    profile.pop("environment")
    return {"schema_version": 1, "document_tools": document_tools, "profiles": [profile]}


@pytest.fixture
def project(tmp_path: Path, configuration: dict) -> Path:
    root = tmp_path / "project"
    (root / "configs").mkdir(parents=True)
    (root / "prompts").mkdir()
    save_configuration(root, configuration)
    # Deliberate CRLF, leading spaces, Unicode, and trailing newlines expose any
    # accidental newline conversion or stripping in the prompt loader.
    (root / "prompts/extractor.md").write_bytes("  Extract exact £ values.\r\n\r\n".encode("utf-8"))
    (root / "prompts/shared.md").write_bytes(b"\nKeep exact quotations.\n")
    return root


def save_configuration(root: Path, configuration: dict, name: str = "profiles.json") -> None:
    (root / "configs" / name).write_text(
        json.dumps(configuration, ensure_ascii=False, allow_nan=False), encoding="utf-8"
    )


def snapshot(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def select_path(data: object, path: tuple):
    # A tuple identifies dictionary keys/list positions for the invalid-input
    # cases below. Each case changes one value in an otherwise valid config.
    for part in path:
        data = data[part]
    return data


def test_profiles_schema_is_valid() -> None:
    path = Path(__file__).resolve().parents[1] / "schemas/profiles.schema.json"
    Draft202012Validator.check_schema(json.loads(path.read_text(encoding="utf-8")))


def test_strict_configuration_parsing_preserves_values(configuration: dict) -> None:
    before = copy.deepcopy(configuration)
    parsed, problems = validation.parse_profiles_json(json.dumps(configuration))
    assert parsed == configuration == before
    assert problems == []


def test_loads_exact_ordered_prompts_and_shared_tools_without_writes(project: Path, configuration: dict) -> None:
    before_files = snapshot(project)
    settings = agents.load_profile(project, "fictional_extractor", stage="extractor")
    expected = copy.deepcopy(configuration["profiles"][0])
    expected["document_tools"] = configuration["document_tools"]
    expected["prompt_texts"] = ["  Extract exact £ values.\r\n\r\n", "\nKeep exact quotations.\n"]
    assert settings == expected
    assert snapshot(project) == before_files
    assert "environment" not in settings  # Observation belongs to a later runner.
    assert agents.load_profiles(project) == configuration


def test_loaded_settings_fit_existing_run_contract_once_observed_environment_is_supplied(
    project: Path, run_record: dict,
) -> None:
    settings = agents.load_profile(project, "fictional_extractor", stage="extractor")
    # The environment here is explicitly fictional test data from conftest.py.
    # Actual execution must detect these values rather than copy this fixture.
    settings["environment"] = copy.deepcopy(run_record["settings"]["environment"])
    run_record["settings"] = settings
    assert validation.validate_run_record(run_record, page_count=5) == []


def test_loading_is_independent_of_current_working_directory(project: Path, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    settings = agents.load_profile(project, "fictional_extractor", stage="extractor")
    assert settings["prompt_texts"][0] == "  Extract exact £ values.\r\n\r\n"


def test_selects_explicit_alternate_config_without_falling_back(project: Path, configuration: dict) -> None:
    configuration["profiles"][0]["name"] = "alternate"
    save_configuration(project, configuration, "alternate.json")
    settings = agents.load_profile(project, "alternate", stage="extractor", config_path="configs/alternate.json")
    assert settings["name"] == "alternate"
    with pytest.raises(agents.ProfileValidationError, match="No profile named"):
        agents.load_profile(project, "alternate", stage="extractor")


def test_loaded_snapshot_survives_file_edits_and_deletion(project: Path, configuration: dict) -> None:
    settings = agents.load_profile(project, "fictional_extractor", stage="extractor")
    before = copy.deepcopy(settings)
    configuration["profiles"][0]["generation"]["max_output_tokens"] = 2048
    configuration["document_tools"]["image_render_dpi"] = 300
    save_configuration(project, configuration)
    (project / "prompts/extractor.md").write_text("New instructions.\n", encoding="utf-8")
    updated = agents.load_profile(project, "fictional_extractor", stage="extractor")
    assert updated["generation"]["max_output_tokens"] == 2048
    assert updated["document_tools"]["image_render_dpi"] == 300
    assert updated["prompt_texts"][0] == "New instructions.\n"
    assert settings == before
    (project / "prompts/extractor.md").unlink()
    (project / "configs/profiles.json").unlink()
    assert settings == before


def test_mutating_a_loaded_dictionary_does_not_change_files_or_future_loads(project: Path) -> None:
    before_files = snapshot(project)
    first = agents.load_profile(project, "fictional_extractor", stage="extractor")
    expected = copy.deepcopy(first)
    first["generation"]["max_output_tokens"] = 1
    first["document_tools"]["image_render_dpi"] = 1
    first["prompt_paths"].clear()
    first["prompt_texts"].clear()
    assert agents.load_profile(project, "fictional_extractor", stage="extractor") == expected
    assert snapshot(project) == before_files


def test_repeated_prompt_paths_keep_their_order_and_repetition(project: Path, configuration: dict) -> None:
    configuration["profiles"][0]["prompt_paths"] = ["prompts/shared.md", "prompts/extractor.md", "prompts/shared.md"]
    save_configuration(project, configuration)
    settings = agents.load_profile(project, "fictional_extractor", stage="extractor")
    assert settings["prompt_paths"] == configuration["profiles"][0]["prompt_paths"]
    assert settings["prompt_texts"] == ["\nKeep exact quotations.\n", "  Extract exact £ values.\r\n\r\n", "\nKeep exact quotations.\n"]


@pytest.mark.parametrize("name", ["unknown", "Fictional_extractor", "", None])
def test_requires_an_exact_explicit_profile_name(project: Path, name: object) -> None:
    with pytest.raises(agents.ProfileValidationError, match="No profile named") as caught:
        agents.load_profile(project, name, stage="extractor")
    assert caught.value.problems[0].category == "reference"


@pytest.mark.parametrize("stage", ["expert", "", None])
def test_rejects_undefined_roles(project: Path, stage: object) -> None:
    with pytest.raises(agents.ProfileValidationError, match="Select stage"):
        agents.load_profile(project, "fictional_extractor", stage=stage)


def test_wrong_role_is_reported_before_opening_prompts(project: Path) -> None:
    (project / "prompts/extractor.md").unlink()
    with pytest.raises(agents.ProfileValidationError, match="is for extractor, not verifier"):
        agents.load_profile(project, "fictional_extractor", stage="verifier")


def test_only_selected_profile_prompts_are_opened(project: Path, configuration: dict) -> None:
    verifier = copy.deepcopy(configuration["profiles"][0])
    verifier.update(name="later_verifier", stage="verifier", prompt_paths=["prompts/not_created.md"])
    configuration["profiles"].append(verifier)
    save_configuration(project, configuration)
    assert agents.load_profile(project, "fictional_extractor", stage="extractor")["name"] == "fictional_extractor"
    with pytest.raises(agents.ProfileValidationError, match="Cannot read prompt"):
        agents.load_profile(project, "later_verifier", stage="verifier")


def test_verifier_configuration_can_be_selected_without_implementing_its_workflow(project: Path, configuration: dict) -> None:
    configuration["profiles"][0].update(name="fictional_verifier", stage="verifier")
    save_configuration(project, configuration)
    settings = agents.load_profile(project, "fictional_verifier", stage="verifier")
    assert settings["stage"] == "verifier"
    assert settings["document_tools"] == configuration["document_tools"]


def test_empty_profile_list_is_valid_but_cannot_select_a_run(project: Path, configuration: dict) -> None:
    configuration["profiles"] = []
    assert validation.validate_profiles(configuration) == []
    save_configuration(project, configuration)
    with pytest.raises(agents.ProfileValidationError, match="No profile named"):
        agents.load_profile(project, "fictional_extractor", stage="extractor")


@pytest.mark.parametrize("different_role", [False, True])
def test_profile_names_are_unique_across_roles(configuration: dict, different_role: bool) -> None:
    repeated = copy.deepcopy(configuration["profiles"][0])
    if different_role:
        repeated["stage"] = "verifier"
    configuration["profiles"].append(repeated)
    problems = validation.validate_profiles(configuration)
    assert len(problems) == 1
    assert problems[0].category == "reference" and problems[0].location == "$.profiles[1].name"


@pytest.mark.parametrize("path,value", [
    (("schema_version",), 2), (("schema_version",), True), (("profiles",), {}),
    (("document_tools", "ocr_enabled"), "true"),
    (("document_tools", "image_render_dpi"), 0), (("document_tools", "image_render_dpi"), True),
    (("document_tools", "tool_timeout_seconds"), 0),
    (("profiles", 0, "name"), " \t"), (("profiles", 0, "stage"), "expert"),
    (("profiles", 0, "context_limit"), 0), (("profiles", 0, "context_limit"), True),
    (("profiles", 0, "model", "name"), ""), (("profiles", 0, "model", "execution_mode"), "remote"),
    (("profiles", 0, "model", "endpoint"), ""),
    (("profiles", 0, "generation", "temperature"), -0.1),
    (("profiles", 0, "generation", "top_p"), 0), (("profiles", 0, "generation", "top_p"), 1.1),
    (("profiles", 0, "generation", "seed"), True), (("profiles", 0, "generation", "seed"), 1.5),
    (("profiles", 0, "generation", "max_output_tokens"), 0),
    (("profiles", 0, "max_tool_calls"), 0), (("profiles", 0, "max_tool_calls"), 1.5),
    (("profiles", 0, "model_timeout_seconds"), 0),
    (("profiles", 0, "image_input_enabled"), "false"),
    (("profiles", 0, "prompt_paths"), []), (("profiles", 0, "prompt_paths"), [None]),
])
def test_invalid_settings_are_rejected_without_mutation(configuration: dict, path: tuple, value: object) -> None:
    select_path(configuration, path[:-1])[path[-1]] = value
    before = copy.deepcopy(configuration)
    assert validation.validate_profiles(configuration)
    assert configuration == before


@pytest.mark.parametrize("path", [(), ("document_tools",), ("profiles", 0), ("profiles", 0, "model"), ("profiles", 0, "generation")])
def test_missing_fields_are_not_filled_from_defaults(configuration: dict, path: tuple) -> None:
    container = select_path(configuration, path)
    for field in list(container):
        candidate = copy.deepcopy(configuration)
        del select_path(candidate, path)[field]
        before = copy.deepcopy(candidate)
        problems = validation.validate_profiles(candidate)
        assert problems and any(field in problem.message for problem in problems)
        assert candidate == before


@pytest.mark.parametrize("path", [(), ("profiles", 0), ("profiles", 0, "model"), ("document_tools",)])
def test_undeclared_fields_including_inline_credentials_are_rejected(configuration: dict, path: tuple) -> None:
    select_path(configuration, path)["api_key"] = "fictional-not-a-secret"
    assert validation.validate_profiles(configuration)


def test_per_model_tool_overrides_and_saved_observations_do_not_belong_in_profiles(configuration: dict) -> None:
    for field, value in (("document_tools", {}), ("prompt_texts", ["Inline text"]), ("environment", {})):
        candidate = copy.deepcopy(configuration)
        candidate["profiles"][0][field] = value
        assert validation.validate_profiles(candidate)


@pytest.mark.parametrize("enabled", [False, True])
def test_ocr_switch_and_nullable_fields_agree(configuration: dict, enabled: bool) -> None:
    tools = configuration["document_tools"]
    tools.update(ocr_enabled=enabled, ocr_engine="easyocr" if enabled else None, ocr_language="en" if enabled else None)
    assert validation.validate_profiles(configuration) == []
    tools["ocr_engine"] = None if enabled else "easyocr"
    assert validation.validate_profiles(configuration)


def test_hosted_configuration_requires_service_and_provider(configuration: dict) -> None:
    model = configuration["profiles"][0]["model"]
    model.update(execution_mode="hosted_api", endpoint="https://example.org/api")
    assert validation.validate_profiles(configuration)
    model.update(api_service="fictional-service", provider="fictional-provider")
    assert validation.validate_profiles(configuration) == []


@pytest.mark.parametrize("path", [
    ("document_tools", "tool_timeout_seconds"),
    ("profiles", 0, "model_timeout_seconds"),
    ("profiles", 0, "generation", "temperature"),
])
@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_nonfinite_settings_are_rejected(configuration: dict, path: tuple, value: float) -> None:
    select_path(configuration, path[:-1])[path[-1]] = value
    assert validation.validate_profiles(configuration)


@pytest.mark.parametrize("path", ["/tmp/prompt.md", "../prompt.md", "prompts/../../prompt.md", "C:/prompt.md", "prompts\\file.md", ".", "prompts/a\x00.md"])
def test_prompt_paths_must_be_portable_and_project_relative(configuration: dict, path: str) -> None:
    configuration["profiles"][0]["prompt_paths"] = [path]
    problems = validation.validate_profiles(configuration)
    assert problems and problems[0].category == "reference"


@pytest.mark.parametrize("damage", ["duplicate-field", "trailing-comma", "code-fence", "NaN", "overflow"])
def test_configuration_json_is_strict_and_never_repaired(configuration: dict, damage: str) -> None:
    text = json.dumps(configuration)
    if damage == "duplicate-field":
        text = text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
    elif damage == "trailing-comma":
        text = text[:-1] + ",}"
    elif damage == "code-fence":
        text = "```json\n" + text + "\n```"
    else:
        text = text.replace('"temperature": 0', '"temperature": ' + ("NaN" if damage == "NaN" else "1e400"))
    parsed, problems = validation.parse_profiles_json(text)
    assert parsed is None and problems
    assert problems[0].category == ("structure" if damage == "overflow" else "syntax")


@pytest.mark.parametrize("damage", ["missing", "directory", "blank", "invalid-utf8"])
def test_prompt_read_failures_are_visible_without_partial_results(project: Path, damage: str) -> None:
    path = project / "prompts/extractor.md"
    if damage in ("missing", "directory"):
        path.unlink()
        if damage == "directory":
            path.mkdir()
    else:
        path.write_bytes(b" \r\n\t" if damage == "blank" else b"\xff")
    before = snapshot(project)
    with pytest.raises(agents.ProfileValidationError, match="prompt|Prompt") as caught:
        agents.load_profile(project, "fictional_extractor", stage="extractor")
    assert caught.value.problems[0].location == "$.prompt_paths[0]"
    assert snapshot(project) == before


def test_config_read_failure_and_json_errors_keep_structured_problems(project: Path) -> None:
    path = project / "configs/profiles.json"
    for contents in (b"\xff", b"{", None):
        if contents is None:
            path.unlink()
        else:
            path.write_bytes(contents)
        with pytest.raises(agents.ProfileValidationError) as caught:
            agents.load_profiles(project)
        assert caught.value.problems and str(caught.value)


@pytest.mark.parametrize("config_path", ["../outside.json", "/tmp/outside.json", "C:/outside.json"])
def test_configuration_path_cannot_escape_the_project(project: Path, config_path: str) -> None:
    with pytest.raises(agents.ProfileValidationError, match="Cannot read profile configuration"):
        agents.load_profiles(project, config_path=config_path)


def test_prompt_symlink_outside_project_is_refused(project: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_text("External instructions.", encoding="utf-8")
    selected = project / "prompts/extractor.md"
    selected.unlink()
    selected.symlink_to(outside)
    with pytest.raises(agents.ProfileValidationError, match="outside the project root"):
        agents.load_profile(project, "fictional_extractor", stage="extractor")


def test_configuration_symlink_outside_project_is_refused(project: Path, tmp_path: Path) -> None:
    selected = project / "configs/profiles.json"
    outside = tmp_path / "outside.json"
    outside.write_bytes(selected.read_bytes())
    selected.unlink()
    selected.symlink_to(outside)
    with pytest.raises(agents.ProfileValidationError, match="outside the project root"):
        agents.load_profiles(project)


def test_missing_shared_schema_is_a_visible_setup_failure(configuration: dict, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(validation, "_RUN_SCHEMA_PATH", tmp_path / "missing.schema.json")
    problems = validation.validate_profiles(configuration)
    assert problems and problems[0].category == "other"


def test_repository_starter_profile_loads_but_does_not_claim_environment_observations() -> None:
    root = Path(__file__).resolve().parents[1]
    settings = agents.load_profile(root, "qwen35_27b_extractor_development", stage="extractor")
    assert settings["stage"] == "extractor"
    assert len(settings["prompt_paths"]) == len(settings["prompt_texts"]) == 3
    assert all(text.strip() for text in settings["prompt_texts"])
    assert settings["image_input_enabled"] is False
    assert "environment" not in settings
