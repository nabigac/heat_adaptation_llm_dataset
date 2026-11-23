"""Check the diagnostic without credentials, network calls, or study changes."""

import asyncio
import hashlib
import json
from pathlib import Path

import httpx
import pytest

import huggingface_check as check
from agents import load_profile
from test_agent_loop import PROFILE, answer
from test_huggingface_api import (
    MODEL, TOKEN, DEEPSEEK_MODEL, DEEPSEEK_ROUTER_MODEL,
    GLM_MODEL, GLM_ROUTER_MODEL,
    envelope, hosted_project, project, tool_call,
)


def study_hashes(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for name in ("data", "runs") for p in (root / name).rglob("*") if p.is_file()}


def test_diagnostic_default_remains_hosted_inkling_with_a_verifier_profile_available():
    root = Path(__file__).resolve().parents[1]
    selected = load_profile(root, check.DEFAULT_PROFILE, stage="extractor")
    config = json.loads((root / "configs/profiles.json").read_text())
    assert {profile["stage"] for profile in config["profiles"]} == {"extractor", "verifier", "coordinator", "worker"}
    assert selected["model"]["name"] == MODEL and selected["model"]["provider"] == "deepinfra"
    assert selected["model"]["execution_mode"] == "hosted_api"
    assert selected["generation"]["max_output_tokens"] == 131072
    assert selected["context_limit"] == 1048576


@pytest.mark.parametrize("model", [MODEL])
def test_diagnostic_saves_schema_usage_and_caps_without_changing_study(project, run_record, monkeypatch, model):
    hosted_project(project, "deepinfra", model)
    config_path = project / "configs/profiles.json"
    config = json.loads(config_path.read_text())
    config["profiles"][0]["generation"]["max_output_tokens"] = 131072
    config_path.write_text(json.dumps(config))
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    before = study_hashes(project)
    replies = [envelope('{"compatible": true}', model=model), envelope(answer(run_record), model=model),
               envelope(None, finish="length", usage={"prompt_tokens": 100, "completion_tokens": 64}, model=model)]
    sent = []
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=replies.pop(0))
    path, report = asyncio.run(check.run_checks(project, PROFILE, _transport=httpx.MockTransport(handler)))
    assert report["passed"] and len(sent) == 3 and not replies
    assert path.parent.parent == project / "artifacts/huggingface_checks"
    assert study_hashes(project) == before
    assert all(body["response_format"]["json_schema"]["strict"] for body in sent)
    assert [body["max_tokens"] for body in sent] == [2048, 4096, 64]
    assert json.loads(path.read_text()) == report
    for file in path.parent.iterdir():
        assert TOKEN.encode() not in file.read_bytes()


@pytest.mark.parametrize("failure", ["schema", "token-overrun"])
@pytest.mark.parametrize("model,reported_model", [(MODEL, MODEL), (GLM_MODEL, GLM_ROUTER_MODEL)])
def test_diagnostic_stops_and_saves_failures_without_retry(project, monkeypatch, failure, model, reported_model):
    hosted_project(project, "deepinfra", model)
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    data = envelope('{"unexpected": true}', model=reported_model)
    if failure == "token-overrun":
        data = envelope('{"compatible": true}', model=reported_model,
                        usage={"prompt_tokens": 100, "completion_tokens": 2049})
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=data)
    path, report = asyncio.run(check.run_checks(project, PROFILE, _transport=httpx.MockTransport(handler)))
    assert not report["passed"] and len(sent) == 1
    assert report["checks"][0]["errors"]
    assert all("model identity" not in error for error in report["checks"][0]["errors"])
    assert (path.parent / "small_schema_response.json").exists()


def test_low_cap_without_reported_usage_is_inconclusive(project, run_record, monkeypatch):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    replies = [envelope('{"compatible": true}'), envelope(answer(run_record)),
               envelope('{"compatible": true}', usage=None)]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=replies.pop(0)))
    _, report = asyncio.run(check.run_checks(project, PROFILE, _transport=transport))
    assert not replies and not report["passed"]
    assert "did not report" in report["checks"][-1]["errors"][0]


def test_project_schema_check_rejects_unexpected_evidence_field(project, run_record, monkeypatch):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    run_record["plan_data"]["actions"][0]["evidence"][0]["unexpected"] = "Continuation of a quotation."
    replies = [envelope('{"compatible": true}'), envelope(answer(run_record))]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=replies.pop(0)))
    path, report = asyncio.run(check.run_checks(project, PROFILE, _transport=transport))
    assert not report["passed"] and len(report["checks"]) == 2
    assert report["checks"][-1]["errors"]
    assert not (path.parent / "short_output_limit_request.json").exists()


def test_diagnostic_cancellation_preserves_partial_response(project, monkeypatch):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"partial":'
            raise asyncio.CancelledError
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=InterruptedStream()))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(check.run_checks(project, PROFILE, _transport=transport))
    folder = next((project / "artifacts/huggingface_checks").iterdir())
    assert (folder / "small_schema_response.json").read_bytes() == b'{"partial":'
    report = json.loads((folder / "report.json").read_text())
    assert not report["passed"] and report["checks"][0]["errors"]


def test_diagnostic_missing_token_or_wrong_provider_creates_no_artifacts(project, monkeypatch):
    hosted_project(project, "deepinfra")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(ValueError, match="HF_TOKEN"):
        asyncio.run(check.run_checks(project, PROFILE))
    assert not (project / "artifacts").exists()
    hosted_project(project, "other-host")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    with pytest.raises(ValueError, match="DeepInfra"):
        asyncio.run(check.run_checks(project, PROFILE))
    assert not (project / "artifacts").exists()


def schema_replies(run_record, model=DEEPSEEK_MODEL):
    return [
        envelope('{"compatible": true}', model=model),
        envelope(answer(run_record), model=model),
        envelope(None, finish="length", model=model,
                 usage={"prompt_tokens": 100, "completion_tokens": 64}),
    ]


def successful_tool_reply(model=DEEPSEEK_MODEL):
    return envelope(None, calls=[tool_call(identifier="diagnostic-page-1")],
                    finish="tool_calls", model=model)


@pytest.mark.parametrize("model,reported_model", [
    (DEEPSEEK_MODEL, DEEPSEEK_MODEL), (DEEPSEEK_MODEL, DEEPSEEK_ROUTER_MODEL),
    (GLM_MODEL, GLM_MODEL), (GLM_MODEL, GLM_ROUTER_MODEL),
])
def test_model_override_and_tool_round_trip_preserve_profile_and_study(
    project, run_record, monkeypatch, model, reported_model,
):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    profile_before = (project / "configs/profiles.json").read_bytes()
    study_before = study_hashes(project)
    replies = schema_replies(run_record, reported_model) + [successful_tool_reply(reported_model)]
    sent = []

    def handler(request):
        body = json.loads(request.content)
        sent.append(body)
        if replies:
            return httpx.Response(200, json=replies.pop(0))
        tool_messages = [m for m in body["messages"] if m["role"] == "tool"]
        assert len(tool_messages) == 1
        supplied = json.loads(tool_messages[0]["content"])
        return httpx.Response(200, json=envelope(
            json.dumps({"confirmation_code": supplied["confirmation_code"]}), model=reported_model))

    path, report = asyncio.run(check.run_checks(
        project, PROFILE, model_name=model, check_tools=True,
        _transport=httpx.MockTransport(handler)))
    assert report["passed"] and not replies and len(sent) == 5
    assert report["model"]["name"] == report["model_override"] == model
    assert report["profile"] == PROFILE and report["tool_checks_requested"]
    assert report["planned_check_count"] == 5
    assert [body["max_tokens"] for body in sent] == [2048, 4096, 64, 2048, 2048]
    assert all(body["model"] == model + ":deepinfra" for body in sent)
    assert sent[3]["tools"] == check.FICTIONAL_TOOLS
    assert "response_format" not in sent[3] and "tools" not in sent[4]
    assistant = next(m for m in sent[4]["messages"] if m["role"] == "assistant")
    tool = next(m for m in sent[4]["messages"] if m["role"] == "tool")
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"] == "diagnostic-page-1"
    assert json.loads(assistant["tool_calls"][0]["function"]["arguments"]) == {"page_number": 1}
    code = json.loads((path.parent / "fictional_tool_result.json").read_text())["confirmation_code"]
    assert code not in json.dumps(sent[3])
    assert code not in json.dumps(sent[4]["response_format"])
    assert json.loads(path.read_text()) == report
    assert (project / "configs/profiles.json").read_bytes() == profile_before
    assert study_hashes(project) == study_before
    for file in path.parent.iterdir():
        assert TOKEN.encode() not in file.read_bytes()


@pytest.mark.parametrize("failure", ["no-call", "multiple-calls", "wrong-page", "wrong-code"])
def test_tool_failures_stop_without_retry_and_preserve_responses(project, run_record, monkeypatch, failure):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    tool_reply = successful_tool_reply()
    if failure == "no-call":
        tool_reply = envelope("Skipped the tool.", model=DEEPSEEK_MODEL)
    elif failure == "multiple-calls":
        tool_reply = envelope(None, calls=[tool_call(identifier="one"), tool_call(identifier="two")],
                              finish="tool_calls", model=DEEPSEEK_MODEL)
    elif failure == "wrong-page":
        tool_reply = envelope(None, calls=[tool_call(arguments='{"page_number":2}')],
                              finish="tool_calls", model=DEEPSEEK_MODEL)
    replies = schema_replies(run_record) + [tool_reply]
    if failure == "wrong-code":
        replies.append(envelope('{"confirmation_code":"guessed"}', model=DEEPSEEK_MODEL))
    sent = []

    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=replies.pop(0))

    path, report = asyncio.run(check.run_checks(
        project, PROFILE, model_name=DEEPSEEK_MODEL, check_tools=True,
        _transport=httpx.MockTransport(handler)))
    assert not report["passed"] and not replies
    assert len(sent) == len(report["checks"]) == (5 if failure == "wrong-code" else 4)
    assert report["checks"][-1]["errors"]
    assert (path.parent / (report["checks"][-1]["name"] + "_response.json")).exists()
    if failure == "wrong-code":
        assert "confirmation code" in report["checks"][-1]["errors"][0]
    else:
        assert not (path.parent / "tool_result_request.json").exists()


@pytest.mark.parametrize("phase", ["tool_call", "tool_result"])
def test_tool_check_cancellation_is_saved_before_propagation(project, run_record, monkeypatch, phase):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    replies = schema_replies(run_record)
    if phase == "tool_result":
        replies.append(successful_tool_reply())

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"partial":'
            raise asyncio.CancelledError

    def handler(request):
        if replies:
            return httpx.Response(200, json=replies.pop(0))
        return httpx.Response(200, stream=InterruptedStream())

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(check.run_checks(
            project, PROFILE, model_name=DEEPSEEK_MODEL, check_tools=True,
            _transport=httpx.MockTransport(handler)))
    folder = next((project / "artifacts/huggingface_checks").iterdir())
    report = json.loads((folder / "report.json").read_text())
    assert not report["passed"] and report["checks"][-1]["name"] == phase
    assert report["checks"][-1]["errors"]
    assert (folder / f"{phase}_response.json").read_bytes() == b'{"partial":'


@pytest.mark.parametrize("model", ["", "bad-model", DEEPSEEK_MODEL + ":deepinfra"])
def test_invalid_model_override_creates_no_artifacts_or_requests(project, monkeypatch, model):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    before = (project / "configs/profiles.json").read_bytes()

    def forbidden(request):
        pytest.fail("Invalid model overrides must fail before sending a request.")

    with pytest.raises(ValueError):
        asyncio.run(check.run_checks(
            project, PROFILE, model_name=model, check_tools=True,
            _transport=httpx.MockTransport(forbidden)))
    assert not (project / "artifacts").exists()
    assert (project / "configs/profiles.json").read_bytes() == before


def test_cli_passes_model_override_and_tool_flag(project, monkeypatch, capsys):
    monkeypatch.chdir(project)
    monkeypatch.setattr("sys.argv", ["huggingface_check", "--profile", PROFILE,
                                   "--model", DEEPSEEK_MODEL, "--check-tools"])
    received = []

    async def fake_checks(root, profile, **options):
        received.append((root, profile, options))
        return root / "artifacts/huggingface_checks/fictional/report.json", {"passed": True}

    monkeypatch.setattr(check, "run_checks", fake_checks)
    assert check.main() == 0
    assert received == [(project, PROFILE, {
        "model_name": DEEPSEEK_MODEL, "check_tools": True, "isolate_project_schema": False,
    })]
    assert "verifier quality remain untested" in capsys.readouterr().out
