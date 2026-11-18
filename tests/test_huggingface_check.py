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
from test_huggingface_api import MODEL, TOKEN, envelope, hosted_project, project


def study_hashes(root):
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for name in ("data", "runs") for p in (root / name).rglob("*") if p.is_file()}


def test_current_profile_selects_only_hosted_inkling():
    root = Path(__file__).resolve().parents[1]
    selected = load_profile(root, check.DEFAULT_PROFILE, stage="extractor")
    config = json.loads((root / "configs/profiles.json").read_text())
    assert len(config["profiles"]) == 1
    assert selected["model"]["name"] == MODEL and selected["model"]["provider"] == "deepinfra"
    assert selected["model"]["execution_mode"] == "hosted_api"
    assert selected["generation"]["max_output_tokens"] == 32768
    assert selected["context_limit"] == 1048576


@pytest.mark.parametrize("model", [MODEL])
def test_diagnostic_saves_schema_usage_and_caps_without_changing_study(project, run_record, monkeypatch, model):
    hosted_project(project, "deepinfra", model)
    config_path = project / "configs/profiles.json"
    config = json.loads(config_path.read_text())
    config["profiles"][0]["generation"]["max_output_tokens"] = 32768
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
def test_diagnostic_stops_and_saves_failures_without_retry(project, monkeypatch, failure):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    data = envelope('{"unexpected": true}')
    if failure == "token-overrun":
        data = envelope('{"compatible": true}', usage={"prompt_tokens": 100, "completion_tokens": 2049})
    sent = []
    def handler(request):
        sent.append(request)
        return httpx.Response(200, json=data)
    path, report = asyncio.run(check.run_checks(project, PROFILE, _transport=httpx.MockTransport(handler)))
    assert not report["passed"] and len(sent) == 1
    assert report["checks"][0]["errors"]
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
