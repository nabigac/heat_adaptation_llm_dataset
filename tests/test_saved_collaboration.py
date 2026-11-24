"""Exercise real C orchestration/storage through mock HTTP and source tools.

The HTTP mock serves all three identities, including concurrent worker calls.
Fictional PDFs and replies establish lifecycle behavior, not extraction quality.
"""

import asyncio
from copy import deepcopy
import json
import time
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

import agents
import cli
import collaboration_runner as runner
import collaboration_storage as saved_storage
import document_tools
import storage
from test_agent_loop import PLAN_ID, SOURCE, FakeClient, project
from test_collaboration import MODELS, assignment
from test_collaboration_contracts import configured
from test_saved_extractor import facts
from test_mcp_ocr import recognition


class ModelHTTP:
    def __init__(self, answer):
        self.answer = deepcopy(answer)
        self.calls, self.turns = [], dict.fromkeys(MODELS, 0)
        self.arrived, self.both_started = set(), asyncio.Event()
        self.failure = self.hook = None

    async def __call__(self, request):
        body = json.loads(request.content)
        actor = next(actor for actor, model in MODELS.items() if body["model"] == model + ":deepinfra")
        self.calls.append((actor, body))
        self.turns[actor] += 1
        number = self.turns[actor]
        if self.hook:
            self.hook(actor, body)
        if self.failure == "http":
            return httpx.Response(400, json={"error": {"message": "Controlled hosted failure"}})
        if actor == "coordinator":
            if "response_format" in body:
                message = {"role": "assistant", "content": json.dumps(self.answer)}
            elif number == 1:
                message = self.tool("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}, actor, number)
            elif number == 2:
                message = self.tool("submit_draft", {"based_on_version": 0, "draft": self.answer}, actor, number)
            else:
                message = self.tool("finish_investigation", {}, actor, number)
        elif "response_format" in body:
            context = next(json.loads(m["content"].split("\n", 1)[1]) for m in body["messages"]
                           if m["content"].startswith("ASSIGNMENT AND CHECKABLE DATA:\n"))
            task = context["task"]
            result = {**{k: task[k] for k in ("task_id", "worker_id", "draft_version")}, "checked_pages": [1],
                      "findings": [{"description": "Tree planting is proposed.", "related_action_id": None,
                                    "proposed_change": "Include tree planting.", "unresolved": False,
                                    "evidence": [{"quote": "We will plant 20 trees.", "page_numbers": [1]}]}]}
            message = {"role": "assistant", "content": json.dumps(result)}
        elif number == 1:
            self.arrived.add(actor)
            if len(self.arrived) == 2:
                self.both_started.set()
            await asyncio.wait_for(self.both_started.wait(), 2)
            message = self.tool("get_page_text", {"page_number": 1}, actor, number)
        else:
            message = {"role": "assistant", "content": agents.FINAL_READY_SIGNAL}
        finish = "tool_calls" if "tool_calls" in message else "stop"
        if self.failure == "truncated" and actor == "coordinator" and "response_format" in body:
            finish = "length"
        return httpx.Response(200, json={"model": MODELS[actor],
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}})

    @staticmethod
    def tool(name, arguments, actor, number):
        return {"role": "assistant", "content": "", "tool_calls": [{
            "id": f"{actor}_{number}", "type": "function",
            "function": {"name": name, "arguments": json.dumps(arguments)},
        }]}


@pytest.fixture
def ready(configured, facts, run_record, monkeypatch):
    path = configured / "configs/profiles.json"
    profiles = json.loads(path.read_text())
    for profile in profiles["profiles"]:
        profile["context_limit"] = 1048576
    path.write_text(json.dumps(profiles))
    monkeypatch.setenv("HF_TOKEN", "hf-fictional-c-run-token")
    client = FakeClient()
    monkeypatch.setattr(agents, "_document_client", lambda *args, **kwargs: client)
    answer = {k: deepcopy(run_record[k]) for k in ("plan_data", "plan_issues")}
    return SimpleNamespace(root=configured, client=client, http=ModelHTTP(answer))


def run(ready, **options):
    return asyncio.run(runner.run_collaboration(ready.root, PLAN_ID, source_path=SOURCE,
        _transport=httpx.MockTransport(ready.http), **options))


@pytest.mark.parametrize("late_reply", [False, True])
@pytest.mark.parametrize("actor", ["worker", "coordinator"])
def test_submitted_tool_timeout_fails_and_preserves_evidence_without_new_requests(ready, late_reply, actor):
    config_path = ready.root / "configs/profiles.json"
    config = json.loads(config_path.read_text())
    config["document_tools"]["tool_timeout_seconds"] = 0.05
    config_path.write_text(json.dumps(config))

    async def delayed(*args):
        if late_reply:
            time.sleep(0.10)  # Model synchronous SDK decoding that misses its deadline.
            return ready.client.result
        await asyncio.sleep(1)
    ready.client.call_tool = delayed
    if actor == "coordinator":
        original = ready.http
        async def coordinator_tool(request):
            body = json.loads(request.content)
            return httpx.Response(200, json={"model": MODELS["coordinator"],
                "choices": [{"index": 0, "message": original.tool(
                    "get_page_text", {"page_number": 1}, "coordinator", 1), "finish_reason": "tool_calls"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20}})
        ready.http = coordinator_tool

    saved = run(ready)

    assert saved.record["status"] == "failed"
    assert "MCPRequestTimeout" in saved.record["error"]
    assert saved.persistence_error is None and ready.client.closed
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record
    # Initial parallel requests may already be in flight; no follow-up or final
    # request may start after the missed tool deadline is observed.
    calls = saved.record["model_calls"]
    assert len(calls) <= (3 if actor == "worker" else 1)
    assert all(call["phase"] == "investigation" for call in calls)
    folder = ready.root / Path(saved.record_path).parent
    controller = json.loads((folder / "artifacts/controller_result.json").read_text())
    timeouts = [event for event in controller["events"]
                if event["event"] == "document_tool_result" and "MCPRequestTimeout" in event.get("error", "")]
    assert timeouts
    first_timeout = controller["events"].index(timeouts[0])
    assert all(event["event"] != "model_request" for event in controller["events"][first_timeout + 1:])
    log = json.loads((ready.root / saved.record["tool_log_path"]).read_text())
    assert log and all(row["error"] for row in log)
    assert len(list((folder / "artifacts/tool_results").glob("*.json"))) == len(log)
    if late_reply:
        assert log[0]["result"]["structuredContent"]["page_number"] == 1
        assert timeouts[0]["result"]["structuredContent"]["page_number"] == 1
    else:
        assert all(row["result"] is None for row in log)


@pytest.mark.parametrize("tool_name", ["get_page_text", "run_ocr"])
def test_ordinary_unreadable_source_reply_remains_recoverable_in_saved_c(ready, tool_name):
    from mcp.types import CallToolResult, TextContent
    if tool_name == "run_ocr":
        config_path = ready.root / "configs/profiles.json"
        config = json.loads(config_path.read_text())
        config["document_tools"].update(ocr_enabled=True, ocr_engine="easyocr", ocr_language="en")
        config_path.write_text(json.dumps(config))
        original_catalogue = ready.client.list_tools
        async def catalogue():
            from mcp.types import Tool
            result = await original_catalogue()
            result.tools.append(Tool(name="run_ocr", description="Read source with OCR.", input_schema={
                "type": "object", "properties": {"page_number": {"type": "integer", "minimum": 1}},
                "required": ["page_number"]}))
            return result
        ready.client.list_tools = catalogue
        original_tool = ready.http.tool
        def ocr_tool(name, arguments, actor, number):
            return original_tool(tool_name if name == "get_page_text" else name, arguments, actor, number)
        ready.http.tool = ocr_tool
    async def unreadable(*args):
        return CallToolResult(is_error=True, content=[TextContent(
            type="text", text="OCR could not read this page; source text is unavailable.")])
    ready.client.call_tool = unreadable

    saved = run(ready)

    assert saved.record["status"] == "succeeded", saved.record["error"]
    assert saved.persistence_error is None and len(ready.http.calls) == 10
    log = json.loads((ready.root / saved.record["tool_log_path"]).read_text())
    assert len(log) == 2 and all("OCR could not read" in row["error"] for row in log)
    assert all(row["tool"] == tool_name for row in log)
    assert all(row["result"]["isError"] for row in log)


def test_live_clients_parallel_workers_and_preserved_saved_output(ready):
    folder = ready.root / f"runs/{PLAN_ID}/run_collaboration_0001"
    def observed(actor, body):
        active = json.loads((folder / "output.json").read_text())
        assert active["status"] == "running"
        assert any(json.loads((ready.root / call["request_path"]).read_text())["body"] == body
                   for call in active["model_calls"])
    ready.http.hook = observed
    saved = run(ready)
    assert saved.persistence_error is None
    assert saved.record["status"] == "succeeded", saved.record["error"]
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record
    assert len(ready.http.calls) == saved.record["budget"]["model_requests"] == 10
    assert ready.http.arrived == {"worker_1", "worker_2"}
    assert ready.client.closed and len(ready.client.calls) == 2
    assert saved.record["budget"]["reported_usage"] == {"input_tokens": 1000, "output_tokens": 200}
    assert saved.quotation_diagnostics["summary"]["matched"] == 1
    assert saved.validation_report["valid"]
    logs = json.loads((ready.root / saved.record["tool_log_path"]).read_text())
    assert {row["actor"] for row in logs} == {"worker_1", "worker_2"}
    for index, call in enumerate(saved.record["model_calls"], 1):
        stem = folder / f"responses/attempt_{index:04d}"
        assert (stem / "token_budget.json").exists()
        assert b"".join(p.read_bytes() for p in sorted((stem / "chunks").glob('*.bin'))) == (ready.root / call["response_path"]).read_bytes()
    controller = json.loads((folder / "artifacts/controller_result.json").read_text())
    assert len(controller["tasks"]) == len(controller["drafts"]) == 2
    assert len(list((folder / "artifacts/events").glob('*.json'))) == len(controller["events"])
    assert not list((ready.root / "expert_references").glob('**/*'))
    assert not list((ready.root / "data/expert_references").glob('**/*'))
    for path in folder.rglob('*'):
        if path.is_file():
            assert b"hf-fictional-c-run-token" not in path.read_bytes()


def test_page_correction_changes_only_citation_and_keeps_raw_final(ready):
    # Page 2 has readable text, making a wrong citation demonstrable. Page 1
    # remains the sole exact location for this quotation.
    pages_path = ready.root / SOURCE.replace('preparation.json', 'pages.json')
    pages = json.loads(pages_path.read_text())
    pages[1].update(text="A different readable page.", readable=True, text_source="native")
    pages_path.write_text(json.dumps(pages))
    ready.http.answer["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [2]
    saved = run(ready)
    assert saved.record["status"] == "succeeded", saved.record['error']
    assert saved.record["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] == [1]
    assert saved.quotation_diagnostics["summary"]["corrected"] == 1
    raw = json.loads((ready.root / saved.validation_report["raw_response_path"]).read_text())
    assert raw["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] == [2]
    assert saved.validation_report["repairs"][0]["rule"] == "quotation_page_number"
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record


def test_unmatched_quotation_is_flagged_without_rewriting_text(ready):
    quote = "Not present in the source."
    ready.http.answer['plan_data']['actions'][0]['evidence'][0]['quote'] = quote
    saved = run(ready)
    assert saved.record['status'] == 'succeeded'
    assert saved.quotation_diagnostics['summary']['unmatched_quote'] == 1
    assert saved.record['plan_data']['actions'][0]['evidence'][0]['quote'] == quote


@pytest.mark.parametrize('failure', ['http', 'truncated'])
def test_failed_http_or_truncated_final_is_preserved_without_retry(ready, failure):
    ready.http.failure = failure
    saved = run(ready)
    assert saved.record['status'] == 'failed'
    assert saved.record['plan_data'] is saved.record['plan_issues'] is None
    assert len(ready.http.calls) == (1 if failure == 'http' else 10)
    assert ready.client.closed
    assert (ready.root / saved.record['model_calls'][-1]['response_path']).is_file()
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record


@pytest.mark.parametrize('damage', ['source', 'code'])
def test_changed_source_or_application_prevents_success(ready, monkeypatch, damage):
    def change(actor, body):
        if actor != 'coordinator' or 'response_format' not in body:
            return
        if damage == 'source':
            pages = ready.root / SOURCE.replace('preparation.json', 'pages.json')
            data = json.loads(pages.read_text()); data[0]['text'] += ' Changed.'; pages.write_text(json.dumps(data))
        else:
            monkeypatch.setattr(agents, '_code_snapshot', lambda: {'src/fixture.py': b'changed'})
    ready.http.hook = change
    saved = run(ready)
    assert saved.record['status'] == 'failed'
    assert saved.record['plan_data'] is None
    assert 'changed' in saved.record['error']


def test_no_overwrite_and_explicit_retry_link(ready):
    ready.http.failure = 'http'
    first = run(ready)
    before = {p: p.read_bytes() for p in (ready.root / first.record_path).parent.rglob('*') if p.is_file()}
    ready.http = ModelHTTP(ready.http.answer)
    second = run(ready, retry_of_run_id=first.record['run_id'])
    assert second.record['run_id'] == 'run_collaboration_0002'
    assert second.record['retry_of_run_id'] == first.record['run_id']
    assert second.record['status'] == 'succeeded'
    assert all(p.read_bytes() == raw for p, raw in before.items())
    with pytest.raises(ValueError, match='Completed runs'):
        saved_storage.save_collaboration_file(ready.root, first.record_path, 'artifacts/new.txt', b'no')
    with pytest.raises(ValueError, match='failed C'):
        run(ready, retry_of_run_id=second.record['run_id'])


@pytest.mark.parametrize('target', ['request.json', 'response.json'])
def test_saving_failure_stops_new_requests_and_never_claims_success(ready, monkeypatch, target):
    original = saved_storage.save_collaboration_file
    def fail(root, path, relative, raw):
        if relative.endswith('/' + target):
            raise OSError('Controlled evidence saving failure')
        return original(root, path, relative, raw)
    monkeypatch.setattr(saved_storage, 'save_collaboration_file', fail)
    saved = run(ready)
    assert saved.record['status'] != 'succeeded'
    assert len(ready.http.calls) == (0 if target == 'request.json' else 1)
    assert saved.persistence_error


def test_partial_cancel_preserves_bytes_and_returns_cancellation_result(ready):
    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"partial":'
            raise asyncio.CancelledError
    async def cancelled(request):
        return httpx.Response(200, stream=Partial())
    ready.http = cancelled
    with pytest.raises(runner.SavedCollaborationCancelled) as caught:
        run(ready)
    saved = caught.value.result
    assert saved.record['status'] == 'failed'
    assert (ready.root / saved.record['model_calls'][0]['response_path']).read_bytes() == b'{"partial":'
    assert ready.client.closed


@pytest.mark.parametrize('target', ['input', 'source', 'code'])
def test_strict_load_rejects_missing_or_changed_saved_evidence(ready, target):
    saved = run(ready)
    folder = (ready.root / saved.record_path).parent
    if target == 'input':
        (folder / 'artifacts/collaboration_input.json').unlink()
    elif target == 'source':
        page_file = ready.root / SOURCE.replace('preparation.json', 'pages.json')
        pages = json.loads(page_file.read_text()); pages[0]['text'] += ' Changed.'; page_file.write_text(json.dumps(pages))
    else:
        (folder / 'artifacts/code/src/fixture.py').write_bytes(b'changed')
    with pytest.raises((OSError, ValueError)):
        storage.load_run_record(ready.root, saved.record_path)


def test_missing_token_and_non_development_plans_start_no_run(ready, monkeypatch):
    monkeypatch.delenv('HF_TOKEN')
    with pytest.raises(ValueError, match='HF_TOKEN'):
        run(ready)
    assert not (ready.root / 'runs').exists()
    with pytest.raises(ValueError, match='development'):
        run(ready, purpose='comparison')


def test_cli_dispatch_and_published_status(ready, monkeypatch, capsys):
    transport = httpx.MockTransport(ready.http)
    original = runner.run_collaboration
    async def offline(*args, **kwargs):
        return await original(*args, **kwargs, _transport=transport)
    monkeypatch.setattr(runner, 'run_collaboration', offline)
    result = cli.main(['run_collaboration_mode', PLAN_ID, '--source-path', SOURCE, '--purpose', 'development',
                       '--project-root', str(ready.root)])
    assert result == 0
    printed = capsys.readouterr().out
    assert 'Status: succeeded' in printed and 'run_collaboration_0001' in printed
    assert 'Quotation/page diagnostic:' in printed and 'Model requests: 10' in printed


def test_real_mcp_subprocess_is_bound_to_the_c_record(ready, monkeypatch):
    # Model requests still use MockTransport; only the document MCP subprocess
    # is real. No OCR weights or paid network calls are used.
    from test_agent_loop import REAL_DOCUMENT_CLIENT
    monkeypatch.setattr(agents, '_document_client', REAL_DOCUMENT_CLIENT)
    saved = run(ready)
    assert saved.record['status'] == 'succeeded', saved.record['error']
    folder = (ready.root / saved.record_path).parent
    assert (folder / 'artifacts/mcp_stderr.log').is_file()
    assert saved.record['budget']['document_tool_calls'] == {'coordinator': 0, 'worker_1': 1, 'worker_2': 1}
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record


def test_run_bound_ocr_preserves_files_only_in_the_active_c_attempt(ready, recognition, monkeypatch):
    path = ready.root / 'configs/profiles.json'
    profiles = json.loads(path.read_text())
    profiles['document_tools'].update(ocr_enabled=True, ocr_engine='easyocr', ocr_language='en')
    path.write_text(json.dumps(profiles))
    observed = []
    def opening(root, packet, *, run_record_path):
        document = document_tools.RunDocumentTools(root, PLAN_ID, source_path=SOURCE,
            run_record_path=run_record_path, expected_source_fingerprint=packet.source_fingerprint)
        # Exercise the same storage dispatch used by the subprocess, including
        # rendering and OCR report files; recognition itself remains controlled.
        observed.append(document.run_ocr(1))
        client = FakeClient()
        original = client.list_tools
        async def catalogue():
            from mcp.types import Tool
            result = await original()
            result.tools.append(Tool(name='run_ocr', description='Read source with OCR.', input_schema={
                'type': 'object', 'properties': {'page_number': {'type': 'integer', 'minimum': 1}},
                'required': ['page_number']}))
            return result
        client.list_tools = catalogue
        return client
    monkeypatch.setattr(agents, '_document_client', opening)
    saved = run(ready)
    assert saved.record['status'] == 'succeeded', saved.record['error']
    assert len(observed) == 1
    for key in ['image_path', 'text_path', 'report_path']:
        assert observed[0][key].startswith(str(Path(saved.record_path).parent) + '/')
        assert (ready.root / observed[0][key]).is_file()
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record


def test_late_wrapper_completion_cannot_publish_success(ready, monkeypatch):
    now = runner.time.monotonic
    def late(actor, body):
        if actor == 'coordinator' and 'response_format' in body:
            monkeypatch.setattr(runner, 'time', SimpleNamespace(monotonic=lambda: now() + 5401))
    ready.http.hook = late
    saved = run(ready)
    assert saved.execution.status == 'succeeded'
    assert saved.record['status'] == 'failed' and saved.record['plan_data'] is None
    assert 'elapsed-time limit' in saved.record['error']


def test_final_saving_failure_keeps_published_running_status_and_cli_fails(ready, monkeypatch, capsys):
    original = saved_storage.save_collaboration_record
    def failing(root, record):
        if record['status'] != 'running':
            raise OSError('Controlled final publication failure')
        return original(root, record)
    monkeypatch.setattr(saved_storage, 'save_collaboration_record', failing)
    saved = run(ready)
    assert saved.execution.status == 'succeeded'
    assert saved.record['status'] == 'running' and saved.persistence_error
    async def returned(*args, **kwargs):
        return saved
    monkeypatch.setattr(runner, 'run_collaboration', returned)
    result = cli.main(['run_collaboration_mode', PLAN_ID, '--source-path', SOURCE, '--purpose', 'development',
                       '--project-root', str(ready.root)])
    assert result == 1 and 'Status: running' in capsys.readouterr().out


def test_mcp_protocol_failure_stops_new_requests_but_preserves_inflight_evidence(ready):
    async def broken(*args):
        from mcp.shared.exceptions import MCPError
        raise MCPError(code=-32603, message='Controlled OCR artifact publication failure')
    ready.client.call_tool = broken
    saved = run(ready)
    assert saved.record['status'] == 'failed'
    assert 'OCR artifact publication failure' in saved.record['error']
    assert ready.http.turns['coordinator'] == 1
    assert ready.http.turns['worker_1'] <= 1 and ready.http.turns['worker_2'] <= 1
    assert ready.client.closed
    assert saved.record['tool_log_path']


def test_saved_runner_preserves_mixed_delegation_and_three_quote_lookups(ready):
    profile_file = ready.root / 'configs/profiles.json'
    profiles = json.loads(profile_file.read_text())
    for profile in profiles['profiles']:
        profile['max_tool_calls'] = 20
    profile_file.write_text(json.dumps(profiles))
    original = ready.http
    async def mixed(request):
        response = await original(request)
        body = json.loads(request.content)
        if body['model'] == MODELS['coordinator'] + ':deepinfra' and original.turns['coordinator'] == 1:
            payload = response.json()
            calls = payload['choices'][0]['message']['tool_calls']
            for number in range(3):
                calls.append({'id': f'quote-{number}', 'type': 'function', 'function': {
                    'name': 'find_quote', 'arguments': json.dumps({'quote': 'We will plant 20 trees.'}),
                }})
            return httpx.Response(200, json=payload)
        return response
    ready.http = mixed
    saved = run(ready)
    assert saved.record['status'] == 'succeeded', saved.record['error']
    assert saved.persistence_error is None
    assert saved.record['budget']['document_tool_calls'] == {'coordinator': 3, 'worker_1': 1, 'worker_2': 1}
    assert saved.record['budget']['model_requests'] == 10
    log = json.loads((ready.root / saved.record['tool_log_path']).read_text())
    assert [row['tool'] for row in log if row['actor'] == 'coordinator'] == ['find_quote'] * 3
    next_request = [body for actor, body in original.calls if actor == 'coordinator'][1]
    replies = [m['tool_call_id'] for m in next_request['messages'] if m['role'] == 'tool']
    assert replies == ['coordinator_1', 'quote-0', 'quote-1', 'quote-2']
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record


def test_saved_budget_handoff_publishes_first_answer_within_twenty_one_requests(ready):
    profile_file = ready.root / 'configs/profiles.json'
    profiles = json.loads(profile_file.read_text())
    for profile in profiles['profiles']:
        profile['max_tool_calls'] = 20
    profile_file.write_text(json.dumps(profiles))
    original = ready.http
    async def busy(request):
        body = json.loads(request.content)
        if body['model'] == MODELS['coordinator'] + ':deepinfra' or 'response_format' in body:
            return await original(request)
        actor = next(actor for actor, model in MODELS.items() if body['model'] == model + ':deepinfra')
        original.calls.append((actor, body))
        original.turns[actor] += 1
        number = original.turns[actor]
        if number == 1:
            original.arrived.add(actor)
            if len(original.arrived) == 2:
                original.both_started.set()
            await asyncio.wait_for(original.both_started.wait(), 2)
        message = original.tool('get_page_text', {'page_number': 1}, actor, number)
        return httpx.Response(200, json={'model': MODELS[actor],
            'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls'}],
            'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
    ready.http = busy
    saved = run(ready)
    assert saved.record['status'] == 'succeeded', saved.record['error']
    assert saved.persistence_error is None and saved.validation_report['valid']
    assert saved.record['budget']['model_requests'] == len(saved.record['model_calls']) == 21
    assert saved.record['stop_reason'] == 'investigation_budget_exhausted'
    assert [c['phase'] for c in saved.record['model_calls'] if c['actor'] == 'coordinator'] == ['investigation', 'final']
    folder = (ready.root / saved.record_path).parent
    controller = json.loads((folder / 'artifacts/controller_result.json').read_text())
    assert len(controller['drafts']) == 1 and len(controller['tasks']) == 2
    handoff = next(e for e in controller['events'] if e['event'] == 'final_handoff')
    assert handoff['draft_version'] == 0
    assert saved.quotation_diagnostics['summary']['matched'] == 1
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record
