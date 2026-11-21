"""Check the two diagnostic variants using controlled replies and no paid requests."""

import asyncio
from copy import deepcopy
import json

import httpx
import pytest

import huggingface_check as check
from test_agent_loop import PROFILE, answer
from test_huggingface_api import (
    GLM_MODEL, GLM_ROUTER_MODEL, TOKEN, envelope, hosted_project, project,
)
from test_huggingface_check import schema_replies, study_hashes


@pytest.fixture
def hosted(project, monkeypatch):
    hosted_project(project, "deepinfra")
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    return project


def _run(root, replies, *, isolate=True):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        reply = replies.pop(0)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

    path, report = asyncio.run(check.run_checks(
        root, PROFILE, model_name=GLM_MODEL, isolate_project_schema=isolate,
        _transport=httpx.MockTransport(handler),
    ))
    assert not replies
    return path, report, sent


def test_variants_change_only_schema_or_messages_from_standard_project_request(hosted, run_record):
    profile_before = (hosted / "configs/profiles.json").read_bytes()
    study_before = study_hashes(hosted)
    _, standard, baseline_requests = _run(
        hosted, schema_replies(run_record, GLM_ROUTER_MODEL), isolate=False,
    )
    path, report, requests = _run(hosted, [
        envelope('{"compatible":true}', model=GLM_ROUTER_MODEL),
        envelope(answer(run_record), model=GLM_ROUTER_MODEL),
    ])

    assert standard["passed"] and report["passed"]
    assert report["mode"] == "project_schema_isolation"
    assert report["planned_check_count"] == len(report["checks"]) == len(requests) == 2
    assert report["tool_checks_requested"] is False
    assert [item["name"] for item in report["checks"]] == [
        "small_schema_full_instructions", "project_schema_short_instructions",
    ]
    original = baseline_requests[1]
    assert {key for key in original if original[key] != requests[0][key]} == {"response_format"}
    assert {key for key in original if original[key] != requests[1][key]} == {"messages"}
    assert [message["role"] for message in requests[0]["messages"]] == ["system", "user", "system"]
    assert [message["role"] for message in requests[1]["messages"]] == ["user", "system"]
    assert check.FICTIONAL_INPUT in requests[1]["messages"][0]["content"]
    assert all(body["max_tokens"] == original["max_tokens"] == 4096 for body in requests)
    assert all(body["model"] == GLM_MODEL + ":deepinfra" and "tools" not in body for body in requests)
    assert all(body["response_format"]["json_schema"]["strict"] for body in requests)
    assert all(item["http_status_code"] == 200 for item in report["checks"])
    assert json.loads(path.read_text()) == report
    assert (hosted / "configs/profiles.json").read_bytes() == profile_before
    assert study_hashes(hosted) == study_before
    for file in path.parent.iterdir():
        assert TOKEN.encode() not in file.read_bytes()


@pytest.mark.parametrize("failure", ["http", "schema", "truncated", "usage"])
def test_first_failure_does_not_skip_second_or_disappear_from_report(hosted, run_record, failure):
    first = envelope('{"compatible":true}', model=GLM_ROUTER_MODEL)
    status = 200
    if failure == "http":
        first = {"error": {"message": "Provider returned error", "metadata": {
            "raw": '{"error":{"message":"Invalid request"}}', "provider_name": "DeepInfra",
        }}}
        status = 400
    elif failure == "schema":
        first = envelope('{"unexpected":true}', model=GLM_ROUTER_MODEL)
    elif failure == "truncated":
        first = envelope('{"compatible":', finish="length", model=GLM_ROUTER_MODEL)
    else:
        first["usage"] = {"prompt_tokens": 100, "completion_tokens": 4097}
    raw = json.dumps(first).encode()
    path, report, sent = _run(hosted, [
        httpx.Response(status, content=raw),
        envelope(answer(run_record), model=GLM_ROUTER_MODEL),
    ])

    assert len(sent) == len(report["checks"]) == 2
    assert [item["passed"] for item in report["checks"]] == [False, True]
    assert report["passed"] is False
    assert report["checks"][0]["http_status_code"] == status
    assert (path.parent / "small_schema_full_instructions_response.json").read_bytes() == raw
    assert json.loads(path.read_text()) == report
    assert (path.parent / "project_schema_short_instructions_response.json").exists()


def test_both_provider_failures_are_preserved_without_retries(hosted):
    failures = [{"error": {"message": "First request rejected"}},
                {"error": {"message": "Second request rejected"}}]
    raw = [json.dumps(failure).encode() for failure in failures]
    path, report, sent = _run(hosted, [httpx.Response(400, content=body) for body in raw])

    assert not report["passed"] and len(sent) == 2
    assert all(not item["passed"] and item["http_status_code"] == 400 for item in report["checks"])
    for item, expected in zip(report["checks"], raw):
        assert (path.parent / f"{item['name']}_response.json").read_bytes() == expected


@pytest.mark.parametrize("failure", ["page_range", "duplicate_action", "open_resolution", "extra_field"])
def test_short_instructions_keep_full_python_acceptance_checks(hosted, run_record, failure):
    response = json.loads(answer(run_record))
    action = response["plan_data"]["actions"][0]
    if failure == "page_range":
        action["evidence"][0]["page_numbers"] = [2]
    elif failure == "duplicate_action":
        response["plan_data"]["actions"].append(deepcopy(action))
    elif failure == "open_resolution":
        response["plan_issues"]["issues"] = [{
            "issue_id": "issue_0001", "related_action_id": action["action_id"],
            "issue_description": "Fictional uncertainty.", "issue_type": "unclear_meaning",
            "issue_origin": "extractor", "issue_status": "open",
            "resolved_by": "extractor", "resolution": "An open issue cannot claim a fix.",
        }]
    else:
        action["unexpected"] = "Not part of the contract."
    _, report, sent = _run(hosted, [
        envelope('{"compatible":true}', model=GLM_ROUTER_MODEL),
        envelope(json.dumps(response), model=GLM_ROUTER_MODEL),
    ])

    assert len(sent) == 2 and not report["passed"]
    assert [item["passed"] for item in report["checks"]] == [True, False]
    assert report["checks"][1]["completion_status"] == "normal"
    assert report["checks"][1]["errors"]


def test_both_variants_respect_lower_profile_output_limit(hosted, run_record):
    path = hosted / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["profiles"][0]["generation"]["max_output_tokens"] = 1024
    path.write_text(json.dumps(config))
    _, report, sent = _run(hosted, [
        envelope('{"compatible":true}', model=GLM_ROUTER_MODEL),
        envelope(answer(run_record), model=GLM_ROUTER_MODEL),
    ])

    assert report["passed"]
    assert [body["max_tokens"] for body in sent] == [1024, 1024]


@pytest.mark.parametrize("interrupted", [0, 1])
def test_cancellation_saves_partial_evidence_and_stops_further_requests(hosted, monkeypatch, interrupted):
    sent = []

    class InterruptedStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"partial":'
            raise asyncio.CancelledError

    def handler(request):
        index = len(sent)
        sent.append(request)
        if index == interrupted:
            return httpx.Response(200, stream=InterruptedStream())
        return httpx.Response(200, json=envelope('{"compatible":true}', model=GLM_ROUTER_MODEL))

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(check.run_checks(
            hosted, PROFILE, model_name=GLM_MODEL, isolate_project_schema=True,
            _transport=httpx.MockTransport(handler),
        ))

    folder = next((hosted / "artifacts/huggingface_checks").iterdir())
    report = json.loads((folder / "report.json").read_text())
    assert len(sent) == len(report["checks"]) == interrupted + 1
    assert report["passed"] is False
    final = report["checks"][-1]
    assert not final["passed"]
    assert (folder / f"{final['name']}_response.json").read_bytes() == b'{"partial":'


def test_incompatible_modes_are_rejected_before_artifacts_or_requests(hosted):
    def forbidden(request):
        pytest.fail("Conflicting modes must not make requests.")

    with pytest.raises(ValueError, match="either"):
        asyncio.run(check.run_checks(
            hosted, PROFILE, isolate_project_schema=True, check_tools=True,
            _transport=httpx.MockTransport(forbidden),
        ))
    assert not (hosted / "artifacts").exists()


def test_missing_token_creates_no_diagnostic(hosted, monkeypatch):
    monkeypatch.delenv("HF_TOKEN")
    with pytest.raises(ValueError, match="HF_TOKEN"):
        asyncio.run(check.run_checks(hosted, PROFILE, model_name=GLM_MODEL, isolate_project_schema=True))
    assert not (hosted / "artifacts").exists()


@pytest.mark.parametrize("passed", [False, True])
def test_cli_passes_isolation_mode_and_reports_its_limits(hosted, monkeypatch, capsys, passed):
    monkeypatch.chdir(hosted)
    monkeypatch.setattr("sys.argv", ["huggingface_check", "--profile", PROFILE,
                                   "--model", GLM_MODEL, "--isolate-project-schema"])
    received = []

    async def fake_checks(root, profile, **options):
        received.append((root, profile, options))
        return root / "artifacts/huggingface_checks/fictional/report.json", {"passed": passed}

    monkeypatch.setattr(check, "run_checks", fake_checks)
    assert check.main() == (0 if passed else 1)
    assert received == [(hosted, PROFILE, {
        "model_name": GLM_MODEL, "check_tools": False, "isolate_project_schema": True,
    })]
    assert "original request still needs the standard compatibility check" in capsys.readouterr().out


def test_cli_rejects_tools_and_isolation_together(monkeypatch):
    monkeypatch.setattr("sys.argv", ["huggingface_check", "--check-tools", "--isolate-project-schema"])
    with pytest.raises(SystemExit) as error:
        check.main()
    assert error.value.code == 2
