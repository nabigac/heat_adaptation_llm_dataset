"""Check durable execution using the coordinator's isolated fictional fixtures.

The real storage functions publish files. MCP/model replies and startup facts are
controlled here; metadata HTTP and received-byte behavior have separate tests.
These are failure/preservation checks, not research extraction assessments.
"""

import asyncio
import copy
import json
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

import agents
import models
import huggingface_api as hf
import storage
import test_agent_loop as loop

# Reuse the same prepared source and controlled model/MCP setup as loop tests.
project = loop.project
scripted = loop.scripted




@pytest.fixture
def facts(monkeypatch, run_record):
    environment = copy.deepcopy(run_record["settings"]["environment"])
    environment.update(runtime="huggingface_inference_providers", code_commit="fixture-commit", code_dirty=True,
                       python_version="fixture-python", preparation_version="v3", model_revision=None,
                       runtime_version=None, quantization=None, hardware=None, model_loaded_at_start=None)
    monkeypatch.setattr(agents, "_execution_environment", lambda packet, prep: copy.deepcopy(environment))
    monkeypatch.setattr(agents, "_code_snapshot", lambda: {"src/fixture.py": b"# fictional code snapshot\n"})
    return environment


def execute(root, scripted, **options):
    return asyncio.run(agents.run_extractor(root, loop.PLAN_ID, source_path=loop.SOURCE,
        profile_name=loop.PROFILE, purpose="development", _transport=scripted.transport, **options))


def folder(root, saved):
    return (root / saved.record_path).parent


def test_success_is_saved_incrementally_and_loads_with_all_evidence(project, scripted, facts, run_record):
    expected = project / f"runs/{loop.PLAN_ID}/run_extract_0001"
    def first_request(body):
        active = json.loads((expected / "output.json").read_text())
        assert active["status"] == "running" and active["model_calls"] == []
        assert active["settings"]["environment"]["model_revision"] is None
        assert json.loads((expected / "responses/attempt_01/request.json").read_text())["body"] == body
        assert (expected / "responses/attempt_01/token_budget.json").is_file()
    def second_request(body):
        active = storage.load_run_record(project, f"runs/{loop.PLAN_ID}/run_extract_0001/output.json")
        assert active["status"] == "running" and len(active["model_calls"]) == 1
        assert active["model_calls"][0]["input_tokens"] == 21
        assert active["tool_log_path"] is not None
        assert (expected / "responses/response_01.json").is_file()
    scripted.replies = [loop.message(calls=[loop.call()]), loop.message(agents.FINAL_READY_SIGNAL),
                        loop.message(loop.answer(run_record))]
    scripted.hooks = [first_request, second_request]
    saved = execute(project, scripted)
    assert saved.persistence_error is None
    assert saved.record["status"] == "succeeded" and saved.execution.status == "succeeded"
    assert storage.load_run_record(project, saved.record_path) == saved.record
    assert len(saved.record["model_calls"]) == 3
    assert saved.record["elapsed_seconds"] >= saved.execution.elapsed_seconds > 0
    assert saved.record["ended_at"] is not None
    env = saved.record["settings"]["environment"]
    assert env["code_commit"] == "fixture-commit" and env["model_loaded_at_start"] is None
    assert env["runtime_version"] is None and env["quantization"] is None
    assert (expected / "artifacts/code/src/fixture.py").read_bytes() == b"# fictional code snapshot\n"
    assert (expected / "artifacts/extractor_input.json").is_file()
    assert (expected / "artifacts/mcp_catalogue.json").is_file()
    assert (expected / "artifacts/tool_requests/tool_0001.json").is_file()
    chunks = sorted((expected / "responses/attempt_01/chunks").glob("*.bin"))
    assert b"".join(path.read_bytes() for path in chunks) == (expected / "responses/response_01.json").read_bytes()
    report = json.loads((expected / "validation_report.json").read_text())
    assert report["raw_response_path"] == f"runs/{loop.PLAN_ID}/run_extract_0001/responses/response_03.txt"
    diagnostic = json.loads((expected / agents.QUOTATION_PAGE_REPORT_PATH).read_text())
    assert diagnostic == saved.execution.quotation_diagnostics
    assert diagnostic["source_path"] == loop.SOURCE
    assert diagnostic["source_fingerprint"] == saved.execution.extractor_input.source_fingerprint
    assert diagnostic["summary"]["checked"] == diagnostic["summary"]["matched"] == 1
    assert diagnostic["findings"] == []
    assert saved.record["settings"]["prompt_texts"] == saved.execution.extractor_input.settings["prompt_texts"]


def test_permitted_repairs_preserve_raw_assistant_and_candidate_separately(project, scripted, facts, run_record):
    raw = "```json\n" + loop.answer(run_record) + "\n```"
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(raw)]
    saved = execute(project, scripted)
    root = folder(project, saved)
    assert saved.record["status"] == "succeeded" and saved.persistence_error is None
    assert (root / "responses/response_02.txt").read_text() == raw
    assert json.loads((root / "responses/repaired_final.txt").read_text())["plan_data"] == run_record["plan_data"]
    assert json.loads((root / "validation_report.json").read_text())["repairs"]
    assert len(scripted.requests) == 2


@pytest.mark.parametrize("prose", [False, True])
def test_investigation_reply_is_preserved_but_only_the_strict_final_answer_is_saved(
    project, scripted, facts, run_record, prose,
):
    draft = json.loads(loop.answer(run_record))
    draft["plan_data"]["metadata"]["draft_only"] = True
    raw_draft = json.dumps(draft)
    if prose:
        raw_draft = "I have enough to report. Compiling findings now."
    scripted.replies = [loop.message(raw_draft), loop.message(loop.answer(run_record))]
    result = execute(project, scripted)
    root = folder(project, result)
    assert result.record["status"] == "succeeded" and result.record["plan_data"] == run_record["plan_data"]
    assert (root / "responses/response_01.txt").read_text() == raw_draft
    first_request = json.loads((root / "responses/attempt_01/request.json").read_text())
    final_request = json.loads((root / "responses/attempt_02/request.json").read_text())
    assert first_request["phase"] == "tool_use" and "response_format" not in first_request["body"]
    assert final_request["phase"] == "final" and final_request["body"]["response_format"]["type"] == "json_schema"
    assert "tools" not in final_request["body"]
    assert any(m["role"] == "assistant" and m["content"] == raw_draft for m in final_request["body"]["messages"])
    report = json.loads((root / "validation_report.json").read_text())
    assert report["raw_response_path"].endswith("responses/response_02.txt")
    assert report["valid"] is True and report["repairs"] == []
    assert json.loads((root / agents.QUOTATION_PAGE_REPORT_PATH).read_text())["summary"]["checked"] == 1
    assert storage.load_run_record(project, result.record_path) == result.record
    assert len(scripted.requests) == len(result.record["model_calls"]) == 2


def test_format_and_page_corrections_share_the_audit_but_preserve_the_raw_answer(
    project, scripted, facts, run_record,
):
    pages_path = project / loop.SOURCE.replace("preparation.json", "pages.json")
    pages = json.loads(pages_path.read_text())
    pages[1]["text"] = "Other activity on page 2."
    pages_path.write_text(json.dumps(pages))
    response = json.loads(loop.answer(run_record))
    response["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [2]
    raw = "```json\n" + json.dumps(response) + "\n```"
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(raw)]
    result = execute(project, scripted)
    assert result.record["status"] == "succeeded"
    root = folder(project, result)
    assert (root / "responses/response_02.txt").read_text() == raw
    candidate = json.loads((root / "responses/repaired_final.txt").read_text())
    assert candidate["plan_data"] == result.record["plan_data"]
    assert candidate["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] == [1]
    report = json.loads((root / "validation_report.json").read_text())
    assert [change["rule"] for change in report["repairs"]] == ["json_code_fence", "quotation_page_number"]
    assert report["valid"] is True and report["initial_errors"] and report["remaining_errors"] == []
    assert storage.load_run_record(project, result.record_path) == result.record
    assert len(scripted.requests) == 2


@pytest.mark.parametrize("bad_page", [0, 99])
def test_invalid_page_range_fails_before_source_based_correction(
    project, scripted, facts, run_record, bad_page,
):
    response = json.loads(loop.answer(run_record))
    response["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [bad_page]
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(json.dumps(response))]
    result = execute(project, scripted)
    assert result.record["status"] == "failed" and result.record["plan_data"] is None
    assert result.execution.quotation_diagnostics is None
    report = json.loads((folder(project, result) / "validation_report.json").read_text())
    assert report["valid"] is False and report["repairs"] == []
    assert not (folder(project, result) / "responses/repaired_final.txt").exists()
    assert len(scripted.requests) == 2


@pytest.mark.parametrize("failure", ["invalid-final", "truncated-final", "model-connection"])
def test_failed_attempts_save_available_evidence_without_retry(project, scripted, facts, run_record, failure):
    if failure == "model-connection":
        scripted.replies = [httpx.ConnectError("Controlled unavailable model.")]
    else:
        final = loop.message("not JSON" if failure == "invalid-final" else loop.answer(run_record))
        if failure == "truncated-final": final["choices"][0]["finish_reason"] = "length"
        scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), final]
    saved = execute(project, scripted)
    assert saved.persistence_error is None and saved.record["status"] == "failed"
    assert saved.record["plan_data"] is None and saved.record["plan_issues"] is None
    assert saved.execution.quotation_diagnostics is None
    assert storage.load_run_record(project, saved.record_path) == saved.record
    assert len(scripted.requests) == (1 if failure == "model-connection" else 2)
    assert len(saved.record["model_calls"]) == len(scripted.requests)
    assert (project / saved.record["model_calls"][-1]["response_path"]).is_file()
    if failure == "invalid-final":
        assert json.loads((folder(project, saved) / "validation_report.json").read_text())["valid"] is False
    if failure == "truncated-final":
        assert saved.record["model_calls"][-1]["truncated"] is True


def test_blocked_preflight_is_preserved_without_inventing_generation_usage(project, scripted, facts, monkeypatch):
    def blocked(request):
        return models.TokenBudgetResult({"fits": False, "error": "Controlled overflow.", "input_tokens": None}, {})
    monkeypatch.setattr(hf, "estimate_huggingface_budget", blocked)
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.record["model_calls"] == []
    assert not scripted.requests
    report = json.loads((folder(project, saved) / "responses/attempt_01/token_budget.json").read_text())
    assert report["input_tokens"] is None and not report["fits"]
    assert not (folder(project, saved) / "responses/response_01.json").exists()


@pytest.mark.parametrize("field,value", [
    ("finish_reason", False), ("finish_reason", {}), ("content", {"invalid": "content"}),
])
def test_malformed_provider_metadata_preserves_a_valid_failed_record(project, scripted, facts, field, value):
    response = loop.message(agents.FINAL_READY_SIGNAL)
    target = response["choices"][0]
    if field == "content":
        target = target["message"]
    target[field] = value
    scripted.replies = [response]
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.persistence_error is None
    assert len(scripted.requests) == 1
    call = saved.record["model_calls"][0]
    assert call["input_tokens"] == 21 and call["output_tokens"] == 7
    assert json.loads((project / call["response_path"]).read_text()) == response
    assert storage.load_run_record(project, saved.record_path) == saved.record


def test_request_save_failure_prevents_model_call_and_saves_failed_status(project, scripted, facts, monkeypatch):
    real = agents.save_run_file
    def fail(root, record_path, relative, data):
        if relative.endswith("request.json"):
            raise OSError("Controlled request-write failure.")
        return real(root, record_path, relative, data)
    monkeypatch.setattr(agents, "save_run_file", fail)
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.persistence_error
    assert saved.record["model_calls"] == [] and not scripted.requests
    assert scripted.client.closed


def test_received_bytes_survive_a_chunk_write_failure_and_execution_stops(project, scripted, facts, run_record, monkeypatch):
    real = agents.save_run_file
    def fail(root, record_path, relative, data):
        if relative.endswith(".bin"):
            raise OSError("Controlled chunk-write failure.")
        return real(root, record_path, relative, data)
    monkeypatch.setattr(agents, "save_run_file", fail)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL)]
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.persistence_error
    assert len(scripted.requests) == 1 and len(saved.record["model_calls"]) == 1
    raw = (project / saved.record["model_calls"][0]["response_path"]).read_bytes()
    assert json.loads(raw)["choices"][0]["message"]["content"] == agents.FINAL_READY_SIGNAL


def test_unwritable_final_status_reports_the_actual_still_running_record(project, scripted, facts, run_record, monkeypatch):
    real = agents.save_run_record
    def fail(root, record):
        if record["status"] != "running":
            raise OSError("Controlled final-status failure.")
        return real(root, record)
    monkeypatch.setattr(agents, "save_run_record", fail)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    saved = execute(project, scripted)
    assert saved.execution.status == "succeeded"
    assert saved.record["status"] == "running" and saved.persistence_error
    assert saved.record == storage.load_run_record(project, saved.record_path)
    assert (folder(project, saved) / "validation_report.json").is_file()


def test_manual_retries_allocate_new_ids_and_never_change_completed_files(project, scripted, facts, run_record):
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message("bad final")]
    first = execute(project, scripted)
    original = loop.snapshot(folder(project, first))
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    second = execute(project, scripted, retry_of_run_id=first.record["run_id"])
    assert first.record["run_id"] == "run_extract_0001" and second.record["run_id"] == "run_extract_0002"
    assert second.record["retry_of_run_id"] == first.record["run_id"]
    assert second.record["status"] == "succeeded"
    assert loop.snapshot(folder(project, first)) == original


def test_cancelled_partial_response_is_saved_and_cancellation_propagates(project, scripted, facts):
    async def exercise():
        received = asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"message":{"role":"assistant","content":"partial'
                received.set()
                await asyncio.sleep(60)
        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))
        task = asyncio.create_task(agents.run_extractor(project, loop.PLAN_ID, source_path=loop.SOURCE,
            profile_name=loop.PROFILE, purpose="development", _transport=transport))
        await received.wait()
        task.cancel()
        with pytest.raises(agents.SavedExtractorCancelled) as stopped:
            await task
        saved = stopped.value.result
        assert saved.record["status"] == "failed" and saved.persistence_error is None
        call = saved.record["model_calls"][0]
        assert call["input_tokens"] is None and call["output_tokens"] is None
        assert (project / call["response_path"]).read_bytes().endswith(b'"partial')
        assert scripted.client.closed and saved.record["elapsed_seconds"] > 0
    asyncio.run(exercise())


def test_source_loss_still_allows_failed_record_and_raw_evidence_to_be_saved(project, scripted, facts):
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL)]
    def lose_source(_):
        (project / loop.SOURCE).unlink()
    scripted.hooks = [lose_source]
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.record["plan_data"] is None
    assert saved.record["model_calls"]
    assert (project / saved.record["model_calls"][0]["response_path"]).is_file()


@pytest.mark.parametrize("dirty", [False, True])
def test_formal_comparison_stays_blocked_until_workflow_is_ready(project, scripted, facts, dirty):
    facts["code_dirty"] = dirty
    with pytest.raises(ValueError, match="not yet enabled"):
        asyncio.run(agents.run_extractor(project, loop.PLAN_ID, source_path=loop.SOURCE,
            profile_name=loop.PROFILE, purpose="comparison", _transport=scripted.transport))
    assert not (project / "runs").exists() and not scripted.requests


def test_credentials_are_rejected_before_settings_are_saved(project, scripted, facts):
    path = project / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["profiles"][0]["model"]["endpoint"] = "http://user:secret@localhost:11434"
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError, match="endpoint"):
        execute(project, scripted)
    assert not (project / "runs").exists()


def test_unknown_startup_details_remain_null(project, scripted, facts, run_record):
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    saved = execute(project, scripted)
    assert saved.record["status"] == "succeeded"
    environment = saved.record["settings"]["environment"]
    for name in ("model_loaded_at_start", "quantization", "runtime_version", "model_revision", "hardware"):
        assert environment[name] is None


def test_active_run_uses_frozen_settings_when_profile_files_change(project, scripted, facts, run_record, monkeypatch):
    def changed(body):
        path = project / "configs/profiles.json"
        config = json.loads(path.read_text())
        config["profiles"][0]["generation"]["max_output_tokens"] = 99
        path.write_text(json.dumps(config))
        (project / "prompts/shared.md").write_text("Changed after settings were frozen.")
    scripted.hooks = [changed]
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    saved = execute(project, scripted)
    assert saved.record["status"] == "succeeded"
    assert saved.record["settings"]["generation"]["max_output_tokens"] == 8192
    assert "Fictional shared" in saved.record["settings"]["prompt_texts"][0]
    assert scripted.requests[0]["max_tokens"] == 8192


def test_tool_timeout_preserves_request_and_completed_error_log(project, scripted, facts):
    path = project / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["document_tools"]["tool_timeout_seconds"] = 0.02
    path.write_text(json.dumps(config))
    async def slow(*args):
        await asyncio.sleep(60)
    scripted.client.call_tool = slow
    scripted.replies = [loop.message(calls=[loop.call()])]
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.persistence_error is None
    log = json.loads((project / saved.record["tool_log_path"]).read_text())
    assert len(log) == 1 and log[0]["error"] and log[0]["elapsed_seconds"] >= 0.02
    assert (folder(project, saved) / "artifacts/tool_requests/tool_0001.json").is_file()


def test_code_changes_prevent_acceptance_but_preserve_original_snapshot(project, scripted, facts, run_record, monkeypatch):
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    scripted.hooks = [lambda _: monkeypatch.setattr(agents, "_code_snapshot", lambda: {"src/fixture.py": b"changed"})]
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.persistence_error
    assert saved.record["plan_data"] is None
    assert (folder(project, saved) / "artifacts/code/src/fixture.py").read_bytes() == b"# fictional code snapshot\n"


def test_published_response_is_not_overwritten_after_a_postpublication_error(project, scripted, facts, monkeypatch):
    real = agents.save_run_file
    attempts = []
    def published_then_failed(root, record_path, relative, data):
        result = real(root, record_path, relative, data)
        if relative == "responses/response_01.json":
            attempts.append(relative)
            raise OSError("Controlled error after publication.")
        return result
    monkeypatch.setattr(agents, "save_run_file", published_then_failed)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL)]
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.persistence_error
    assert attempts == ["responses/response_01.json"] and len(scripted.requests) == 1
    assert json.loads((project / saved.record["model_calls"][0]["response_path"]).read_text())["choices"][0]["message"]["content"] == agents.FINAL_READY_SIGNAL


def test_unwritable_raw_response_keeps_known_usage_and_received_chunks(project, scripted, facts, monkeypatch):
    real = agents.save_run_file
    def fail(root, record_path, relative, data):
        if relative == "responses/response_01.json":
            raise OSError("Controlled raw-response publication failure.")
        return real(root, record_path, relative, data)
    monkeypatch.setattr(agents, "save_run_file", fail)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL)]
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.persistence_error
    assert len(scripted.requests) == 1
    call = saved.record["model_calls"][0]
    assert call["input_tokens"] == 21 and call["output_tokens"] == 7
    assert call["finish_reason"] == "stop" and call["truncated"] is False
    assert call["response_path"] is None  # Do not link a file that failed to publish.
    chunks = sorted((folder(project, saved) / "responses/attempt_01/chunks").glob("*.bin"))
    response = json.loads(b"".join(path.read_bytes() for path in chunks))
    assert response["choices"][0]["finish_reason"] == "stop"


def test_published_tool_log_is_not_duplicated_after_append_reports_an_error(project, scripted, facts, monkeypatch):
    real = agents.append_run_tool_log
    def published_then_failed(root, record_path, entry):
        real(root, record_path, entry)
        raise OSError("Controlled error after tool-log publication.")
    monkeypatch.setattr(agents, "append_run_tool_log", published_then_failed)
    scripted.replies = [loop.message(calls=[loop.call()])]
    saved = execute(project, scripted)
    assert saved.record["status"] == "failed" and saved.persistence_error
    entries = json.loads((project / saved.record["tool_log_path"]).read_text())
    assert len(entries) == 1 and len(scripted.requests) == 1


def test_unobservable_required_git_state_is_not_guessed(project, monkeypatch):
    packet = agents.build_extractor_input(project, loop.PLAN_ID, source_path=loop.SOURCE, profile_name=loop.PROFILE)
    _, preparation, _ = storage.load_plan_preparation(project, loop.PLAN_ID, loop.SOURCE)
    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(128, args[0])
    monkeypatch.setattr(agents.subprocess, "run", unavailable)
    with pytest.raises(subprocess.CalledProcessError):
        agents._execution_environment(packet, preparation)


def test_hard_termination_leaves_running_record_and_received_chunks(project, facts, tmp_path):
    # This child uses no real MCP/API process. It blocks after a received HTTP
    # chunk has been saved; SIGTERM then bypasses Python's graceful finalization.
    environment = tmp_path / "environment.json"
    environment.write_text(json.dumps(facts))
    program = '''
import asyncio,json,sys
from pathlib import Path
import httpx
from mcp.types import ListToolsResult,Tool
import agents,models
root=Path(sys.argv[1])
agents._execution_environment=lambda *args:json.loads(Path(sys.argv[2]).read_text())
agents._code_snapshot=lambda:{"src/fixture.py":b"fixture"}
class Client:
 async def __aenter__(self):return self
 async def __aexit__(self,*args):pass
 async def list_tools(self):return ListToolsResult(tools=[Tool(name=n,description="Fixture.",input_schema={"type":"object"}) for n in ["get_page_text","find_quote"]])
agents._document_client=lambda *args,**kwargs:Client()
class Body(httpx.AsyncByteStream):
 async def __aiter__(self):
  yield b'{"message":{"role":"assistant","content":"partial'
  await asyncio.sleep(60)
transport=httpx.MockTransport(lambda request:httpx.Response(200,stream=Body()))
asyncio.run(agents.run_extractor(root,"plan_0099",source_path="data/processed/plan_0099/preparation_02/preparation.json",profile_name="fictional_extractor",purpose="development",_transport=transport))
'''
    child = subprocess.Popen([sys.executable, "-c", program, str(project), str(environment)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    run_root = project / f"runs/{loop.PLAN_ID}/run_extract_0001"
    chunk = run_root / "responses/attempt_01/chunks/part_0001.bin"
    try:
        deadline = time.monotonic() + 20
        while not chunk.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                raise AssertionError(child.stderr.read().decode())
            time.sleep(0.05)
        assert chunk.is_file(), "Child did not reach its saved-response checkpoint."
        child.terminate()
        child.wait(timeout=5)
        assert child.poll() is not None  # Establish stopped state before inspecting it.
        record = storage.load_run_record(project, f"runs/{loop.PLAN_ID}/run_extract_0001/output.json")
        assert record["status"] == "running" and record["ended_at"] is None
        assert record["elapsed_seconds"] is None  # Do not reconstruct duration from recovery time.
        assert chunk.read_bytes().endswith(b'"partial')
        assert (run_root / "responses/attempt_01/request.json").is_file()
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
        child.stdout.close()
        child.stderr.close()


@pytest.mark.parametrize("damage", ["changed_text", "missing_snapshot"])
def test_loading_completed_action_run_checks_preserved_source(project, scripted, facts, run_record, damage):
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    saved = execute(project, scripted)
    assert saved.record["status"] == "succeeded"
    assert storage.load_run_record(project, saved.record_path) == saved.record
    if damage == "changed_text":
        pages_path = project / loop.SOURCE.replace("preparation.json", "pages.json")
        pages = json.loads(pages_path.read_text())
        pages[0]["text"] += " A later manual edit."
        pages_path.write_text(json.dumps(pages))
    else:
        (folder(project, saved) / "artifacts/extractor_input.json").unlink()
    with pytest.raises(storage.RunValidationError, match="fingerprint|preserved extractor input"):
        storage.load_run_record(project, saved.record_path)
