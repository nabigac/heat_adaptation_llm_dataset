"""Exercise orchestration and MCP lifecycle with controlled fictional inputs.

Most tests use fake MCP replies and mock hosted HTTP, while the subprocess case
uses our real document server. Capacity checks use the hosted request-size
estimate; no test sends a paid request.
No test downloads a model or sends a real model request.
"""

import asyncio
import copy
import hashlib
from itertools import count
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from mcp.types import CallToolResult, ImageContent, ListToolsResult, TextContent, Tool
from pypdf import PdfWriter

import agents
import document_tools
import models
import huggingface_api as hf
import storage
import validation


PLAN_ID = "plan_0099"
SOURCE = f"data/processed/{PLAN_ID}/preparation_02/preparation.json"
PROFILE = "fictional_extractor"
REAL_DOCUMENT_CLIENT = agents._document_client




@pytest.fixture
def project(tmp_path, run_record, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "fictional-test-token")
    root = tmp_path / "project"
    pdf = root / f"data/raw/{PLAN_ID}.pdf"
    pdf.parent.mkdir(parents=True)
    with PdfWriter() as writer:
        for _ in range(3):
            writer.add_blank_page(width=100, height=100)
        writer.write(pdf)
    prep = {
        "schema_version": 3, "plan_id": PLAN_ID, "pdf_path": f"data/raw/{PLAN_ID}.pdf",
        "document_sha256": hashlib.sha256(pdf.read_bytes()).hexdigest(),
        "source_url": "https://example.org/plan.pdf", "date_accessed": "2026-11-03",
        "prepared_at": "2026-11-06T12:00:00Z", "pages_path": SOURCE.replace("preparation.json", "pages.json"),
        "page_count": 3, "settings": {"ocr_enabled": False, "ocr_engine": None, "ocr_version": None,
            "ocr_language": None, "image_render_dpi": 150, "candidate_image_min_area": 0.1},
        "status": "ready", "problem": None,
    }
    pages = [{"page_number": n, "text": "Fictional source. We will plant 20 trees." if n == 1 else "",
              "text_source": "native", "readable": True, "image_available": False,
              "image_path": None, "image_regions": [], "problem": None} for n in range(1, 4)]
    storage.save_preparation(root, prep, pages)
    storage.save_registry(root, {"schema_version": 1, "plans": [{
        "plan_id": PLAN_ID, "plan_title": "Fictional plan", "pdf_path": prep["pdf_path"],
        "document_sha256": prep["document_sha256"], "source_url": prep["source_url"],
        "date_accessed": prep["date_accessed"], "study_set": "development", "prepared_source_path": SOURCE,
    }]})
    profile = copy.deepcopy(run_record["settings"])
    shared = profile.pop("document_tools")
    profile.pop("environment")
    profile.pop("prompt_texts")
    profile["prompt_paths"] = ["prompts/shared.md", "prompts/fields.md", "prompts/extractor.md"]
    profile["max_tool_calls"] = 2
    (root / "configs").mkdir()
    (root / "configs/profiles.json").write_text(json.dumps({
        "schema_version": 1, "document_tools": shared, "profiles": [profile],
    }))
    (root / "prompts").mkdir()
    for name in ("shared", "fields", "extractor"):
        (root / f"prompts/{name}.md").write_text(f"Fictional {name} instructions.\n")
    return root


def catalogue():
    return ListToolsResult(tools=[
        Tool(name="get_page_text", description="Read saved text.", input_schema={"type": "object",
             "properties": {"page_number": {"type": "integer", "minimum": 1}}, "required": ["page_number"]}),
        Tool(name="find_quote", description="Find exact text.", input_schema={"type": "object",
             "properties": {"quote": {"type": "string"}}, "required": ["quote"]}),
    ])


class FakeClient:
    def __init__(self):
        self.entered = self.closed = False
        self.calls = []
        self.result = CallToolResult(content=[TextContent(type="text", text="Fictional tool text.")],
                                    structured_content={"page_number": 1, "text": "We will plant 20 trees."})

    async def __aenter__(self):
        self.entered = True
        return self

    async def __aexit__(self, *error):
        self.closed = True

    async def list_tools(self):
        return catalogue()

    async def call_tool(self, name, arguments):
        self.calls.append((name, copy.deepcopy(arguments)))
        return copy.deepcopy(self.result)


@pytest.fixture
def scripted(monkeypatch):
    state = SimpleNamespace(client=FakeClient(), replies=[], requests=[], hooks=[])
    monkeypatch.setattr(agents, "_document_client", lambda root, packet, **options: state.client)

    def handle(request):
        body = json.loads(request.content)
        state.requests.append(body)
        if state.hooks:
            state.hooks.pop(0)(body)
        assert state.replies, "Unexpected model call: no scripted response remains."
        response = state.replies.pop(0)
        if isinstance(response, Exception):
            raise response
        return httpx.Response(200, json=response)
    state.transport = httpx.MockTransport(handle)
    return state


_call_numbers = count(1)


def message(content="", calls=None, *, finish=None):
    value = {"role": "assistant", "content": content, "reasoning_content": "Preserved thought.\r\n"}
    if calls is not None:
        value["tool_calls"] = [{"id": c["id"], "type": "function", "function": {
            "name": c["function"]["name"], "arguments": json.dumps(c["function"]["arguments"]),
        }} for c in calls]
    return {"model": "test-lab/fictional-model", "choices": [{"index": 0, "message": value,
            "finish_reason": finish or ("tool_calls" if calls else "stop")}],
            "usage": {"prompt_tokens": 21, "completion_tokens": 7}}


def call(number=1, *, name="get_page_text", identifier=None):
    return {"id": identifier or f"page_{next(_call_numbers)}", "function": {"index": 0, "name": name,
        "arguments": {"page_number": number} if name == "get_page_text" else {"quote": "trees"}}}


def answer(run_record):
    return json.dumps({"plan_data": run_record["plan_data"], "plan_issues": run_record["plan_issues"]})


def run(root, scripted, **options):
    return asyncio.run(agents.run_extractor_loop(root, PLAN_ID, source_path=SOURCE,
        profile_name=PROFILE, _transport=scripted.transport, **options))


def configure(root, **changes):
    path = root / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["profiles"][0].update(changes)
    path.write_text(json.dumps(config))


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def test_readiness_then_schema_final_preserves_inputs_and_closes_client(project, scripted, run_record):
    before = snapshot(project)
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded" and result.error is None
    assert result.final_validation.report["valid"] is True
    assert result.final_validation.response["plan_data"] == run_record["plan_data"]
    assert [attempt.phase for attempt in result.model_attempts] == ["tool_use", "final"]
    assert "response_format" not in scripted.requests[0] and len(scripted.requests[0]["tools"]) == 2
    assert scripted.requests[1]["response_format"]["json_schema"]["schema"] == hf.prepare_deepinfra_response_schema(result.extractor_input.response_format)
    assert "tools" not in scripted.requests[1]
    assert "2 total; 0 submitted; 2 remaining" in scripted.requests[0]["messages"][1]["content"]
    assert any("Final source-page check: compare every evidence quotation" in m["content"]
               for m in scripted.requests[-1]["messages"] if m["role"] == "system")
    assert result.messages[0] == result.extractor_input.messages[0]
    assert result.extractor_input.messages[-1] in result.messages
    assert result.tool_calls_started == 0 and result.tool_log == []
    assert scripted.client.entered and scripted.client.closed
    assert result.elapsed_seconds > 0 and snapshot(project) == before
    assert result.final_validation.report["raw_response_path"] == "responses/response_02.txt"


def test_automatic_tool_result_returns_in_history_before_readiness_and_final(project, scripted, run_record):
    scripted.replies = [message(calls=[call(identifier="page_1")]), message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded" and result.tool_calls_started == 1
    assert scripted.client.calls == [("get_page_text", {"page_number": 1})]
    returned = next(m for m in scripted.requests[1]["messages"] if m["role"] == "tool")
    assert returned["tool_call_id"] == "page_1" and returned["name"] == "get_page_text"
    assert json.loads(returned["content"])["result"]["text"] == "We will plant 20 trees."
    assert "thinking" not in scripted.requests[1]["messages"][-2]
    assert not validation.validate_tool_log(result.tool_log)
    assert result.tool_log[0]["result"]["structuredContent"]["page_number"] == 1


@pytest.mark.parametrize("use_tool_first", [False, True])
@pytest.mark.parametrize("wrap", [
    lambda body: body,
    lambda body: agents.FINAL_READY_SIGNAL + "\n\n" + body,
    lambda body: agents.FINAL_READY_SIGNAL + "\n\n```json\n" + body + "\n```",
    lambda body: agents.FINAL_READY_SIGNAL + "\r\n```\r\n" + body + "\r\n```",
    lambda body: "I have enough to report. Compiling findings now.",
])
def test_investigation_reply_transitions_to_one_strict_final_request(project, scripted, run_record, use_tool_first, wrap):
    draft = json.loads(answer(run_record))
    draft["plan_data"]["metadata"]["draft_only"] = True
    raw_draft = wrap(json.dumps(draft))
    scripted.replies = ([message(calls=[call()])] if use_tool_first else []) + [
        message(raw_draft), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded" and result.final_validation.report["valid"] is True
    assert result.final_validation.response["plan_data"] == run_record["plan_data"]
    assert [attempt.phase for attempt in result.model_attempts] == ["tool_use"] * (1 + use_tool_first) + ["final"]
    assert len(scripted.requests) == 2 + use_tool_first
    assert result.tool_calls_started == use_tool_first
    assert "tools" not in scripted.requests[-1] and scripted.requests[-1]["response_format"]["type"] == "json_schema"
    assert any(m["role"] == "assistant" and m["content"] == raw_draft for m in scripted.requests[-1]["messages"])
    assert any("unvalidated investigation reply" in m["content"] for m in scripted.requests[-1]["messages"] if m["role"] == "system")
    assert result.final_validation.report["raw_response_path"].endswith(f"response_{2 + use_tool_first:02d}.txt")
    assert scripted.client.closed


@pytest.mark.parametrize("reply_kind", ["json", "wrapped", "prose"])
def test_tool_calls_take_priority_over_handoff_text(project, scripted, run_record, reply_kind):
    draft = answer(run_record)
    if reply_kind == "wrapped":
        draft = agents.FINAL_READY_SIGNAL + "\n```json\n" + draft + "\n```"
    elif reply_kind == "prose":
        draft = "I have enough to report. Compiling findings now."
    scripted.replies = [message(draft, calls=[call()]),
                        message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded" and result.tool_calls_started == 1
    assert len(scripted.requests) == 3 and scripted.client.calls
    assert "tools" in scripted.requests[1]


@pytest.mark.parametrize("bad_final", ["not JSON", '{"plan_data":{},"plan_issues":{"issues":[]}}'])
@pytest.mark.parametrize("reply_kind", ["json", "wrapped", "prose"])
def test_investigation_reply_cannot_replace_a_failed_final_answer(project, scripted, run_record, bad_final, reply_kind):
    draft = answer(run_record)
    if reply_kind == "wrapped":
        draft = agents.FINAL_READY_SIGNAL + "\n```json\n" + draft + "\n```"
    elif reply_kind == "prose":
        draft = "I have enough to report. Compiling findings now."
    scripted.replies = [message(draft), message(bad_final)]
    result = run(project, scripted)
    assert result.status == "failed" and result.final_validation.report["valid"] is False
    assert result.final_validation.response is None and len(scripted.requests) == 2
    assert result.final_validation.raw_text == bad_final


@pytest.mark.parametrize("wrap", [
    lambda body: agents.FINAL_READY_SIGNAL + "\n```json\n" + body + "\n```\nextra prose",
    lambda body: agents.FINAL_READY_SIGNAL + "\n" + body + "\n{}",
    lambda body: agents.FINAL_READY_SIGNAL + "\n```json\n" + body[:-1] + "\n```",
    lambda body: agents.FINAL_READY_SIGNAL + "\n```json\n[]\n```",
    lambda body: agents.FINAL_READY_SIGNAL + "\n" + body.replace('"plan_data":', '"plan_data":{},"plan_data":', 1),
    lambda body: agents.FINAL_READY_SIGNAL + "\n" + body.replace('"plan_data":', '"nonfinite":NaN,"plan_data":', 1),
    lambda body: "Here is my answer:\n" + agents.FINAL_READY_SIGNAL + "\n" + body,
    lambda body: agents.FINAL_READY_SIGNAL + "\n```python\n" + body + "\n```",
    lambda body: "```json\n" + body + "\n```",
])
def test_investigation_text_needs_no_json_parsing_but_requires_final_generation(project, scripted, run_record, wrap):
    raw = wrap(answer(run_record))
    scripted.replies = [message(raw), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded" and result.final_validation.response["plan_data"] == run_record["plan_data"]
    assert len(scripted.requests) == 2 and result.model_attempts[0].result.response_text == raw
    assert any(m["role"] == "assistant" and m["content"] == raw for m in scripted.requests[-1]["messages"])
    assert scripted.requests[-1]["response_format"]["json_schema"]["strict"] is True


def test_investigation_wrapper_never_unwraps_a_final_answer(project, scripted, run_record):
    raw = agents.FINAL_READY_SIGNAL + "\n```json\n" + answer(run_record) + "\n```"
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(raw)]
    result = run(project, scripted)
    assert result.status == "failed" and result.final_validation.response is None
    assert result.final_validation.raw_text == raw and len(scripted.requests) == 2


@pytest.mark.parametrize("limit", [1, 20])
def test_budget_limits_actual_executions_and_denied_batch_calls_receive_error_results(project, scripted, run_record, limit):
    # The larger conversation needs headroom in this fictional test profile.
    configure(project, max_tool_calls=limit, context_limit=131072)
    calls = [call(identifier=f"request_{n}") for n in range(limit + 1)]
    scripted.replies = [message(calls=calls), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded" and result.tool_calls_started == limit
    assert len(scripted.client.calls) == limit and len(result.tool_log) == limit + 1
    assert result.tool_log[-1]["result"] is None and "not executed" in result.tool_log[-1]["error"]
    returned = [m for m in scripted.requests[-1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in returned] == [call["id"] for call in calls]
    assert json.loads(returned[-1]["content"])["is_error"] is True
    assert any("budget is exhausted" in m["content"] for m in scripted.requests[-1]["messages"])
    assert f"{limit} total; {limit} submitted; 0 remaining" in scripted.requests[-1]["messages"][1]["content"]
    # Updating the current allowance must not change earlier prepared requests.
    assert f"{limit} total; 0 submitted; {limit} remaining" in scripted.requests[0]["messages"][1]["content"]
    assert [a.phase for a in result.model_attempts] == ["tool_use", "final"]
    assert not validation.validate_tool_log(result.tool_log)


def test_multiple_calls_and_rounds_preserve_call_order(project, scripted, run_record):
    configure(project, max_tool_calls=3)
    scripted.replies = [message(calls=[call(identifier="one"), call(name="find_quote", identifier="two")]),
                        message(calls=[call(2, identifier="three")]), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded" and result.tool_calls_started == 3
    assert [name for name, _ in scripted.client.calls] == ["get_page_text", "find_quote", "get_page_text"]
    assert len(result.model_attempts) == 3
    assert "3 total; 0 submitted; 3 remaining" in scripted.requests[0]["messages"][1]["content"]
    assert "3 total; 2 submitted; 1 remaining" in scripted.requests[1]["messages"][1]["content"]
    assert "3 total; 3 submitted; 0 remaining" in scripted.requests[2]["messages"][1]["content"]


def test_recoverable_mcp_error_is_logged_and_returned_to_model(project, scripted, run_record):
    scripted.client.result = CallToolResult(is_error=True, content=[TextContent(type="text", text="Page is out of range.")])
    scripted.replies = [message(calls=[call(99)]), message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded"
    assert result.tool_log[0]["error"] == "Page is out of range."
    payload = json.loads(next(m for m in scripted.requests[1]["messages"] if m["role"] == "tool")["content"])
    assert payload == {"is_error": True, "messages": ["Page is out of range."]}
    assert "2 total; 1 submitted; 1 remaining" in scripted.requests[1]["messages"][1]["content"]


def test_nontext_result_is_preserved_but_not_forwarded_as_untested_image_input(project, scripted):
    scripted.client.result = CallToolResult(content=[ImageContent(type="image", data="AA==", mime_type="image/png")])
    scripted.replies = [message(calls=[call()])]
    result = run(project, scripted)
    assert result.status == "failed" and "text MCP results only" in result.error
    assert result.tool_log[0]["result"]["content"][0]["type"] == "image"
    assert len(scripted.requests) == 1 and scripted.client.closed


def test_mcp_protocol_failure_stops_attempt_and_retains_tool_log(project, scripted):
    async def broken(*args):
        raise RuntimeError("Controlled MCP connection failure.")
    scripted.client.call_tool = broken
    scripted.replies = [message(calls=[call()])]
    result = run(project, scripted)
    assert result.status == "failed" and "MCP connection failure" in result.error
    assert result.tool_log[0]["result"] is None and result.tool_log[0]["error"]
    assert result.tool_calls_started == 1 and len(scripted.requests) == 1


@pytest.mark.parametrize("content", ["", " \n\t "])
def test_empty_investigation_reply_fails_without_a_final_or_retry_call(project, scripted, content):
    scripted.replies = [message(content)]
    result = run(project, scripted)
    assert result.status == "failed" and "nonempty" in result.error
    assert len(scripted.requests) == 1 and scripted.client.closed
    assert result.model_attempts[0].result.response_text == content


def test_outer_whitespace_is_allowed_only_for_control_signal(project, scripted, run_record):
    scripted.replies = [message(" \n" + agents.FINAL_READY_SIGNAL + "\n"), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded"
    assert any(m["role"] == "assistant" and m["content"].startswith(" \n") for m in scripted.requests[-1]["messages"])


@pytest.mark.parametrize("final_text", ["not JSON", '{"plan_data": {}, "plan_issues": {"issues": []}}'])
def test_invalid_final_response_fails_without_model_repair_retry(project, scripted, final_text):
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(final_text)]
    result = run(project, scripted)
    assert result.status == "failed" and len(scripted.requests) == 2
    assert result.final_validation.raw_text == final_text
    assert result.final_validation.report["valid"] is False
    assert scripted.client.closed


def test_permitted_fence_repair_occurs_without_an_extra_model_call(project, scripted, run_record):
    raw = "```json\n" + answer(run_record) + "\n```"
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(raw)]
    result = run(project, scripted, response_directory=f"runs/{PLAN_ID}/run_extract_0001/responses")
    assert result.status == "succeeded" and len(scripted.requests) == 2
    assert result.final_validation.raw_text == raw
    assert result.final_validation.report["repairs"]
    assert result.final_validation.report["raw_response_path"].startswith(f"runs/{PLAN_ID}/")
    assert not (project / "runs").exists()


@pytest.mark.parametrize("phase", ["tool_use", "final"])
def test_model_output_truncation_stops_immediately_and_retains_available_bytes(project, scripted, run_record, phase):
    scripted.replies = ([] if phase == "tool_use" else [message(agents.FINAL_READY_SIGNAL)]) + [
        message(answer(run_record), finish="length")]
    result = run(project, scripted)
    assert result.status == "failed" and "truncation" in result.error
    assert result.model_attempts[-1].result.raw_response
    assert result.final_validation is None and scripted.client.closed


@pytest.mark.parametrize("content", [agents.FINAL_READY_SIGNAL,
    '{"plan_data":{"metadata":{},"actions":[]},"plan_issues":{"issues":[]}}',
    "I have enough to report. Compiling findings now."])
def test_unconfirmed_tool_phase_completion_cannot_trigger_execution(project, scripted, content):
    scripted.replies = [message(content, finish="unknown")]
    result = run(project, scripted)
    assert result.status == "failed" and "completion reason" in result.error
    assert scripted.client.calls == [] and len(scripted.requests) == 1


def test_unknown_final_completion_keeps_existing_validation_rules(project, scripted, run_record):
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(answer(run_record), finish="unknown")]
    assert run(project, scripted).status == "failed"


def test_model_failure_or_blocked_preflight_has_no_tool_execution_or_retry(project, scripted, monkeypatch):
    def blocked(request):
        return models.TokenBudgetResult({"fits": False, "input_tokens": None, "error": "Fictional overflow."}, {})
    monkeypatch.setattr(hf, "estimate_huggingface_budget", blocked)
    result = run(project, scripted)
    assert result.status == "failed" and "overflow" in result.error
    assert not scripted.requests and not scripted.client.calls
    assert result.model_attempts[0].result.token_budget.report["fits"] is False


def test_transport_failure_is_preserved_without_retry(project, scripted):
    scripted.replies = [httpx.ConnectError("Controlled disconnect.")]
    result = run(project, scripted)
    assert result.status == "failed" and "connection" in result.error
    assert len(scripted.requests) == 1 and scripted.client.closed


def test_unadvertised_tool_is_never_executed(project, scripted):
    scripted.replies = [message(calls=[call(name="write_file")])]
    result = run(project, scripted)
    assert result.status == "failed" and "undeclared" in result.error
    assert not scripted.client.calls and not result.tool_log


@pytest.mark.parametrize("point", ["startup", "catalogue", "tool"])
def test_mcp_timeout_fails_attempt_without_another_model_request(project, scripted, point):
    path = project / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["document_tools"]["tool_timeout_seconds"] = 0.02
    path.write_text(json.dumps(config))
    async def slow(*args):
        await asyncio.sleep(1)
    if point == "startup":
        @asynccontextmanager
        async def opening():
            await slow()
            yield scripted.client
        scripted.client = opening()
    elif point == "catalogue": scripted.client.list_tools = slow
    else:
        scripted.client.call_tool = slow
        scripted.replies = [message(calls=[call()])]
    result = run(project, scripted)
    assert result.status == "failed" and "Timeout" in result.error
    assert len(scripted.requests) == (1 if point == "tool" else 0)
    if point == "tool":
        assert result.tool_log[0]["result"] is None
        assert result.tool_log[0]["elapsed_seconds"] >= 0.02


def test_late_decoded_tool_reply_is_preserved_but_still_fails_the_deadline(project, scripted):
    path = project / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["document_tools"]["tool_timeout_seconds"] = 0.02
    path.write_text(json.dumps(config))
    async def slow_decode(*args):
        time.sleep(0.03)  # Deliberately blocks, as a synchronous SDK decoder can.
        return scripted.client.result
    scripted.client.call_tool = slow_decode
    scripted.replies = [message(calls=[call()])]
    result = run(project, scripted)
    assert result.status == "failed" and "Timeout" in result.error
    assert result.tool_log[0]["result"]["structuredContent"]["page_number"] == 1
    assert len(scripted.requests) == 1


@pytest.mark.parametrize("point", ["model", "tool"])
def test_cancellation_propagates_with_evidence_and_client_cleanup(project, scripted, monkeypatch, point):
    async def exercise():
        entered = asyncio.Event()
        if point == "tool":
            scripted.replies = [message(calls=[call()])]
            async def wait(*args):
                entered.set()
                await asyncio.sleep(60)
            scripted.client.call_tool = wait
        else:
            async def waiting(request):
                entered.set()
                await asyncio.sleep(60)
            scripted.transport = httpx.MockTransport(waiting)
        task = asyncio.create_task(agents.run_extractor_loop(project, PLAN_ID, source_path=SOURCE,
            profile_name=PROFILE, _transport=scripted.transport))
        await entered.wait()
        task.cancel()
        with pytest.raises(agents.ExtractorLoopCancelled) as cancelled:
            await task
        state = cancelled.value.result
        assert state.status == "failed" and state.elapsed_seconds > 0
        assert scripted.client.closed
        assert state.model_attempts[0].result is not None
        if point == "tool": assert "cancelled" in state.tool_log[-1]["error"]
    asyncio.run(exercise())


def test_unexpected_catalogue_prevents_success(project, scripted):
    async def wrong_catalogue():
        result = catalogue()
        result.tools.pop()
        return result
    scripted.client.list_tools = wrong_catalogue
    result = run(project, scripted)
    assert result.status == "failed" and "two supported" in result.error
    assert not scripted.requests and scripted.client.closed


def test_paginated_catalogue_cannot_silently_hide_additional_tools(project, scripted):
    async def paginated():
        result = catalogue()
        result.next_cursor = "more-tools"
        return result
    scripted.client.list_tools = paginated
    result = run(project, scripted)
    assert result.status == "failed" and "paginated" in result.error
    assert not scripted.requests and scripted.client.closed


def test_client_cleanup_failure_prevents_success_even_after_valid_answer(project, scripted, run_record):
    class BrokenCleanup(FakeClient):
        async def __aexit__(self, *error):
            self.closed = True
            raise RuntimeError("Controlled cleanup failure.")
    scripted.client = BrokenCleanup()
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "failed" and "cleanup failure" in result.error
    assert result.final_validation.report["valid"] is True and scripted.client.closed


@pytest.mark.parametrize("field,value", [("source_url", "https://example.org/wrong.pdf"), ("date_accessed", "2026-11-05")])
def test_wrong_collection_metadata_fails_without_silent_correction(project, scripted, run_record, field, value):
    payload = json.loads(answer(run_record))
    payload["plan_data"]["metadata"][field] = value
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(json.dumps(payload))]
    result = run(project, scripted)
    assert result.status == "failed" and "collection metadata" in result.error
    assert result.final_validation.response is None
    assert result.final_validation.report["remaining_errors"][0]["location"].endswith(field)
    assert not validation.validate_validation_report(result.final_validation.report)
    assert len(scripted.requests) == 2


def test_changed_source_before_final_acceptance_is_reported(project, scripted, run_record):
    def change(_):
        p = project / SOURCE.replace("preparation.json", "pages.json")
        pages = json.loads(p.read_text())
        pages[0]["text"] = "Changed source after startup."
        p.write_text(json.dumps(pages))
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    scripted.hooks = [lambda _: None, change]
    result = run(project, scripted)
    assert result.status == "failed" and "source changed" in result.error
    assert result.final_validation.report["valid"] is True


def test_source_fingerprint_is_stable_for_json_formatting_but_detects_text_and_notes(project):
    _, prep, pages = storage.load_plan_preparation(project, PLAN_ID, SOURCE)
    original = storage.preparation_text_fingerprint(prep, pages)
    assert original == storage.preparation_text_fingerprint(dict(reversed(list(prep.items()))), pages)
    changed = copy.deepcopy(pages)
    changed[0]["text"] += " "
    assert storage.preparation_text_fingerprint(prep, changed) != original
    changed = copy.deepcopy(prep)
    changed["problem"] = "New note."
    assert storage.preparation_text_fingerprint(changed, pages) != original
    with pytest.raises(document_tools.DocumentToolError, match="snapshot differs"):
        document_tools.create_document_tool_server(project, PLAN_ID, source_path=SOURCE,
                                                   expected_source_fingerprint="0" * 64)


def test_real_mcp_subprocess_is_used_by_coordinator_with_mock_hosted_api(project, scripted, run_record, monkeypatch):
    # Restore the real factory captured from the module implementation. Only the
    # HTTP model replies/counts are controlled; actual document tools run over pipes.
    monkeypatch.setattr(agents, "_document_client", REAL_DOCUMENT_CLIENT)
    configure(project, max_tool_calls=1)
    before = snapshot(project)
    scripted.replies = [message(calls=[call()]), message(answer(run_record))]
    result = run(project, scripted)
    assert result.status == "succeeded", result.error
    actual = result.tool_log[0]["result"]["structuredContent"]
    assert actual["plan_id"] == PLAN_ID and actual["page"]["text"].startswith("Fictional source.")
    assert result.tool_calls_started == 1 and snapshot(project) == before


def test_real_server_rejects_text_changed_between_input_assembly_and_startup(project, scripted, monkeypatch):
    def changed_client(root, packet):
        path = root / SOURCE.replace("preparation.json", "pages.json")
        pages = json.loads(path.read_text())
        pages[0]["text"] += " Changed before the subprocess loaded it."
        path.write_text(json.dumps(pages))
        return REAL_DOCUMENT_CLIENT(root, packet)
    monkeypatch.setattr(agents, "_document_client", changed_client)
    result = run(project, scripted)
    assert result.status == "failed" and not scripted.requests and not result.model_attempts
    _, prep, pages = storage.load_plan_preparation(project, PLAN_ID, SOURCE)
    assert result.extractor_input.source_fingerprint != storage.preparation_text_fingerprint(prep, pages)


def test_unsupported_image_profile_is_rejected_before_startup(project, scripted):
    configure(project, image_input_enabled=True)
    with pytest.raises(ValueError, match="image input"):
        run(project, scripted)
    assert not scripted.requests and not scripted.client.entered


@pytest.mark.parametrize("directory", ["../responses", "/tmp/responses", "runs/not-responses"])
def test_invalid_response_references_raise_before_processes_or_models(project, scripted, directory):
    with pytest.raises(ValueError):
        run(project, scripted, response_directory=directory)
    assert not scripted.client.entered and not scripted.requests
