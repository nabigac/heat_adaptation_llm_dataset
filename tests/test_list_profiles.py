"""Check profile discovery without authentication, inference, or research writes."""

import json
from pathlib import Path
import shutil

import pytest

import cli
import huggingface_api
from collaboration_contracts import DEFAULT_COLLABORATION_PROFILE


@pytest.fixture
def configured_profiles(tmp_path, monkeypatch):
    root = tmp_path / "project"
    repository = Path(__file__).resolve().parents[1]
    for name in ("configs", "prompts"):
        shutil.copytree(repository / name, root / name)
    monkeypatch.delenv("HF_TOKEN", raising=False)

    def unexpected_model_call(*args, **kwargs):
        pytest.fail("Profile discovery must not request authentication or inference.")

    monkeypatch.setattr(huggingface_api, "require_huggingface_token", unexpected_model_call)
    monkeypatch.setattr(huggingface_api, "request_huggingface_chat", unexpected_model_call)
    return root


def snapshot(root):
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_lists_selectable_modes_and_nested_models_without_writes(configured_profiles, capsys):
    before = snapshot(configured_profiles)
    assert cli.main(["list_profiles", "--project-root", str(configured_profiles)]) == 0
    output = capsys.readouterr()
    headings = [line for line in output.out.splitlines() if line.startswith(("E:", "V:", "C:"))]
    assert headings == [
        "E: inkling2_small_hf_extractor (run_extract_mode)",
        "V: deepseek_v4_1_flash_1017_hf_verifier (run_verify_mode)",
        "C: glm5_3_flash_hf_collaboration (run_collaboration_mode; development only)",
    ]
    assert "coordinator: zai-org/GLM-5.3-Flash" in output.out
    assert "worker_1: thinkingmachines/Inkling-2-Small" in output.out
    assert "worker_2: deepseek-ai/DeepSeek-V4.1-Flash-1017" in output.out
    assert output.out.count("Model requests: up to 25; document-tool calls: 25") == 2
    assert "Shared ceilings: 25 model requests; 75 document-tool calls; 90 min" in output.out
    assert "Context/request: 1,048,576; output/request: 131,072" in output.out
    assert "Aggregate estimated-token allowance: 31,457,280" in output.out
    assert "V subtracts its linked E duration" in output.out
    assert output.err == ""
    assert snapshot(configured_profiles) == before


def test_custom_configurations_determine_listing_instead_of_hardcoded_limits(configured_profiles, capsys):
    model_path = configured_profiles / "configs/alternate_models.json"
    models = json.loads((configured_profiles / "configs/profiles.json").read_text())
    models["profiles"][0].update(name="alternative_extractor", max_tool_calls=7, max_model_requests=5)
    model_path.write_text(json.dumps(models))
    binding_path = configured_profiles / "configs/alternate_collaboration.json"
    bindings = json.loads((configured_profiles / "configs/collaboration.json").read_text())
    bindings["profiles"][0]["name"] = "alternative_collaboration"
    bindings["profiles"][0]["limits"]["max_model_requests"] = 12
    binding_path.write_text(json.dumps(bindings))
    assert cli.main([
        "list_profiles", "--project-root", str(configured_profiles),
        "--config-path", "configs/alternate_models.json",
        "--collaboration-config-path", "configs/alternate_collaboration.json",
    ]) == 0
    output = capsys.readouterr()
    assert "E: alternative_extractor" in output.out
    assert "Model requests: up to 5; document-tool calls: 7" in output.out
    assert "C: alternative_collaboration" in output.out
    assert "Shared ceilings: 12 model requests" in output.out
    assert "E: inkling2_small_hf_extractor" not in output.out
    assert "C: glm5_3_flash_hf_collaboration" not in output.out


@pytest.mark.parametrize("damage", [
    "missing_models", "missing_bindings", "invalid_models", "invalid_bindings", "duplicate_binding", "unknown_worker", "missing_prompt",
])
def test_damaged_configuration_reports_error_without_partial_listing_or_writes(configured_profiles, capsys, damage):
    model_path = configured_profiles / "configs/profiles.json"
    binding_path = configured_profiles / "configs/collaboration.json"
    if damage == "missing_models":
        model_path.unlink()
    elif damage == "missing_bindings":
        binding_path.unlink()
    elif damage == "invalid_models":
        model_path.write_text("not JSON")
    elif damage == "invalid_bindings":
        binding_path.write_text("{}")
    elif damage in ("duplicate_binding", "unknown_worker"):
        bindings = json.loads(binding_path.read_text())
        if damage == "duplicate_binding":
            bindings["profiles"].append(bindings["profiles"][0])
        else:
            bindings["profiles"][0]["agents"]["worker_1"] = "missing-worker"
        binding_path.write_text(json.dumps(bindings))
    else:
        (configured_profiles / "prompts/extractor.md").unlink()
    before = snapshot(configured_profiles)
    assert cli.main(["list_profiles", "--project-root", str(configured_profiles)]) == 1
    output = capsys.readouterr()
    assert output.err and "Traceback" not in output.err
    assert output.out == ""
    assert snapshot(configured_profiles) == before


def test_default_project_is_current_directory(configured_profiles, monkeypatch, capsys):
    monkeypatch.chdir(configured_profiles)
    assert cli.main(["list_profiles"]) == 0
    assert "C: glm5_3_flash_hf_collaboration" in capsys.readouterr().out


def test_collaboration_cli_defaults_to_renamed_binding_and_remains_development_only():
    arguments = cli._build_parser().parse_args([
        "run_collaboration_mode", "plan_0001", "--source-path", "preparation.json", "--purpose", "development",
    ])
    assert arguments.profile == DEFAULT_COLLABORATION_PROFILE == "glm5_3_flash_hf_collaboration"
    with pytest.raises(SystemExit) as error:
        cli._build_parser().parse_args([
            "run_collaboration_mode", "plan_0001", "--source-path", "preparation.json", "--purpose", "comparison",
        ])
    assert error.value.code == 2
