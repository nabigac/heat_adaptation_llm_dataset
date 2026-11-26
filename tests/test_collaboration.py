"""Exercise actual C control flow with fictional replies and no paid client."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import json

import pytest
import httpx

from agents import FINAL_READY_SIGNAL
from collaboration import CollaborationCancelled, run_collaboration_prototype
from collaboration_contracts import CollaborationContractError, CollaborationInput
from models import ModelCallResult, ModelRequestCancelled
from huggingface_api import request_huggingface_chat


MODELS = {"coordinator": "zai-org/GLM-5.3-Flash",
          "worker_1": "thinkingmachines/Inkling-2-Small",
          "worker_2": "deepseek-ai/DeepSeek-V4.1-Flash-1017"}
DOC_TOOLS = [{"type": "function", "function": {"name": "get_page_text", "description": "Read source page text.",
    "parameters": {"type": "object", "properties": {"page_number": {"type": "integer", "minimum": 1}},
                   "required": ["page_number"], "additionalProperties": False}}}]


def reply(content=None, *, calls=None, error=None, status="normal", usage=True):
    message = {"role": "assistant", "content": content or ""}
    if calls:
        message["tool_calls"] = calls
    return ModelCallResult(
        raw_response=json.dumps(message).encode(), response_text=content, assistant_message=message,
        input_tokens=100 if usage else None, output_tokens=10 if usage else None,
        finish_reason="tool_calls" if calls else "stop", truncated=False,
        completion_status=status, elapsed_seconds=0.01, status_code=200,
        provider_timings_ns={}, error=error, tool_calls=calls or [], generation_started=True,
    )


def call(name, arguments, identifier):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": arguments}}


def assignment(worker, *, independent=True, context=None, objective="Find or check heat activities."):
    return {"worker_id": worker, "objective": objective, "source_pages": [],
            "expected_findings": "Supported activities, evidence, and remaining concerns.",
            "independent": independent, "context_task_ids": context or []}


@pytest.fixture
def packet(run_record):
    profiles = {}
    for actor, model in MODELS.items():
        profile = deepcopy(run_record["settings"])
        profile.update(name=actor, stage="coordinator" if actor == "coordinator" else "worker",
                       context_limit=65536, max_tool_calls=2, model_timeout_seconds=1)
        profile["model"]["name"] = model
        profile["generation"]["max_output_tokens"] = 4096
        profile["prompt_texts"] = ["Fictional shared coding.", "Fictional fields.", "Fictional task."]
        profile["document_tools"]["tool_timeout_seconds"] = 1
        profiles[actor] = profile
    metadata = run_record["plan_data"]["metadata"]
    config = {"name": "fictional_pilot", "agents": {key: key for key in MODELS},
              "limits": {"max_model_requests": 21, "max_document_tool_calls": 6,
                         "max_elapsed_seconds": 10, "max_estimated_tokens": 21 * 65536}}
    return CollaborationInput("plan_0099", "data/prepared_plans/plan_0099/preparation_01/preparation.json",
        "fictional-source-fingerprint", 3, {"role": "user", "content": "Whole fictional plan. Plant 20 trees."},
        {key: metadata[key] for key in ("source_url", "date_accessed")}, config, profiles)


@pytest.fixture
def answer(run_record):
    return {"plan_data": deepcopy(run_record["plan_data"]), "plan_issues": {"issues": []}}


class ScriptedClient:
    def __init__(self, answer, *, coordinator=None, tools=False, barrier=False, bad_result=None):
        self.answer = answer
        self.coordinator = coordinator or [
            ("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}),
            ("submit_draft", {"based_on_version": 0, "draft": answer}),
            ("finish_investigation", {}),
        ]
        self.tools, self.barrier, self.bad_result = tools, barrier, bad_result
        self.requests, self.tasks, self.turns = [], {}, {}
        self.arrived = set()
        self.both_started = asyncio.Event()

    async def __call__(self, request):
        body = request.body
        self.requests.append(body)
        actor = next(key for key, model in MODELS.items() if body["model"] == model + ":deepinfra")
        if actor == "coordinator":
            if "response_format" in body:
                return reply(json.dumps(self.answer))
            name, arguments = self.coordinator.pop(0)
            return reply(calls=[call(name, arguments, f"coordinator-{len(self.requests)}")])
        context = next(json.loads(m["content"].split("\n", 1)[1]) for m in body["messages"]
                       if m["content"] and m["content"].startswith("ASSIGNMENT AND CHECKABLE DATA:\n"))
        task = context["task"]
        self.tasks[task["task_id"]] = context
        if "response_format" in body:
            result = {key: task[key] for key in ("task_id", "worker_id", "draft_version")}
            result.update(checked_pages=[1], findings=[{
                "description": "The fictional plan describes tree planting.", "related_action_id": None,
                "proposed_change": "Retain supported tree planting.",
                "evidence": [{"quote": "Plant 20 trees.", "page_numbers": [1]}], "unresolved": False,
            }])
            if self.bad_result:
                self.bad_result(result)
            return reply(json.dumps(result))
        turn = self.turns.get(task["task_id"], 0)
        self.turns[task["task_id"]] = turn + 1
        if self.barrier and turn == 0:
            self.arrived.add(actor)
            if len(self.arrived) == 2:
                self.both_started.set()
            await self.both_started.wait()
        if self.tools and turn == 0:
            return reply(calls=[call("get_page_text", {"page_number": 1}, task["task_id"] + suffix)
                                for suffix in ("-page-a", "-page-b")])
        return reply(FINAL_READY_SIGNAL)


def run(packet, client, **options):
    return asyncio.run(run_collaboration_prototype(packet, model_client=client, **options))


def test_two_workers_really_overlap_and_final_answer_is_schema_constrained(packet, answer):
    before = deepcopy(packet)
    client = ScriptedClient(answer, barrier=True)
    result = run(packet, client)
    assert result.status == "succeeded", result.error
    assert result.answer == answer and result.budget["model_requests"] == 8
    assert client.arrived == {"worker_1", "worker_2"}
    assert len(result.tasks) == 2 and [draft["version"] for draft in result.drafts] == [1, 2]
    assert result.budget["document_tool_calls"] == dict.fromkeys(MODELS, 0)
    assert "tools" not in client.requests[-1]
    assert client.requests[-1]["response_format"]["json_schema"]["strict"] is True
    assert result.model_calls[-1]["phase"] == "final"
    assert all("draft" not in context and "prior_findings" not in context for context in client.tasks.values())
    assert packet == before


def test_followup_can_assign_extraction_to_either_worker_with_selected_context(packet, answer):
    steps = [
        ("assign_tasks", {"assignments": [assignment("worker_1", objective="Check quotations."),
                                        assignment("worker_2", objective="Extract activities.")]}),
        ("submit_draft", {"based_on_version": 0, "draft": answer}),
        ("assign_tasks", {"assignments": [assignment("worker_1", independent=False,
                                    context=["task_0002"], objective="Extract any missing activity.")]}),
        ("submit_draft", {"based_on_version": 1, "draft": answer}),
        ("finish_investigation", {}),
    ]
    client = ScriptedClient(answer, coordinator=steps)
    result = run(packet, client)
    assert result.status == "succeeded", result.error
    assert result.budget["model_requests"] == 12
    context = client.tasks["task_0003"]
    assert context["task"]["worker_id"] == "worker_1" and context["task"]["draft_version"] == 1
    assert context["draft"] == answer
    assert [item["task_id"] for item in context["prior_findings"]] == ["task_0002"]


@pytest.mark.parametrize("kind", ["requests", "tokens"])
def test_parallel_batch_is_reserved_atomically_before_either_worker_starts(packet, answer, kind):
    packet.configuration["limits"]["max_model_requests"] = 5
    if kind == "tokens":
        packet.configuration["limits"]["max_estimated_tokens"] = 2 * 65536
    client = ScriptedClient(answer)
    result = run(packet, client)
    assert result.status == "failed" and result.answer is None
    assert len(client.requests) == 1 and result.tasks == []
    assert result.budget["model_requests"] == 1


def test_request_exhaustion_preserves_final_request_when_both_workers_and_draft_exist(packet, answer):
    packet.configuration["limits"]["max_model_requests"] = 7
    client = ScriptedClient(answer)
    result = run(packet, client)
    assert result.status == "succeeded", result.error
    assert result.stop_reason == "investigation_budget_exhausted"
    assert result.budget["model_requests"] == 7
    assert result.model_calls[-1]["phase"] == "final"


@pytest.mark.parametrize("failure", ["early_finish", "same_worker_twice", "bad_page", "independent_peer"])
def test_invalid_coordination_fails_without_starting_worker_requests(packet, answer, failure):
    assignments = [assignment("worker_1"), assignment("worker_2")]
    if failure == "same_worker_twice":
        assignments[1]["worker_id"] = "worker_1"
    elif failure == "bad_page":
        assignments[0]["source_pages"] = [99]
    elif failure == "independent_peer":
        assignments[0]["context_task_ids"] = ["task_9999"]
    steps = [("finish_investigation", {})] if failure == "early_finish" else [("assign_tasks", {"assignments": assignments})]
    client = ScriptedClient(answer, coordinator=steps)
    result = run(packet, client)
    assert result.status == "failed" and len(client.requests) == 1 and not result.tasks


@pytest.mark.parametrize("field,value", [("worker_id", "worker_2"), ("draft_version", 99), ("checked_pages", [99])])
def test_mismatched_worker_findings_fail_without_repair_or_retry(packet, answer, field, value):
    def damage(result):
        if result["worker_id"] == "worker_1":
            result[field] = value
    client = ScriptedClient(answer, bad_result=damage)
    result = run(packet, client)
    assert result.status == "failed" and result.answer is None
    assert all(item["phase"] != "final" for item in result.model_calls)
    assert any(event["event"] == "task_failed" for event in result.events)


def test_document_tools_share_global_quota_and_keep_separate_worker_counts(packet, answer):
    packet.configuration["limits"]["max_document_tool_calls"] = 1
    client = ScriptedClient(answer, tools=True)
    submitted = []
    async def document(actor, name, arguments):
        submitted.append((actor, name, arguments))
        await asyncio.sleep(0)
        return {"page_number": 1, "text": "Plant 20 trees."}
    result = run(packet, client, document_tools=DOC_TOOLS, document_client=document,
                 document_source_fingerprint=packet.source_fingerprint)
    assert result.status == "succeeded", result.error
    assert len(submitted) == sum(result.budget["document_tool_calls"].values()) == 1
    assert sum(event["event"] == "document_tool_denied" for event in result.events) == 3


def test_source_mismatch_is_rejected_before_any_model_request(packet, answer):
    client = ScriptedClient(answer)
    with pytest.raises(CollaborationContractError, match="fingerprint"):
        run(packet, client, document_tools=DOC_TOOLS, document_client=lambda *args: None,
            document_source_fingerprint="another-source")
    assert client.requests == []


@pytest.mark.parametrize("damage", ["provider", "worker_prompt"])
def test_mutated_binding_is_rejected_again_at_controller_start(packet, answer, damage):
    if damage == "provider":
        packet.profiles["worker_1"]["model"]["provider"] = "novita"
    else:
        packet.profiles["worker_2"]["prompt_texts"] = ["Different instructions."]
    client = ScriptedClient(answer)
    with pytest.raises(CollaborationContractError):
        run(packet, client)
    assert client.requests == []


def test_stale_draft_update_fails_with_available_findings_preserved(packet, answer):
    client = ScriptedClient(answer, coordinator=[
        ("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}),
        ("submit_draft", {"based_on_version": 1, "draft": answer}),
    ])
    result = run(packet, client)
    assert result.status == "failed" and "stale" in result.error
    assert sum(event["event"] == "task_completed" for event in result.events) == 2


def test_invalid_final_answer_fails_and_preserves_raw_response(packet, answer):
    class BadFinal(ScriptedClient):
        async def __call__(self, request):
            if request.body["model"].startswith(MODELS["coordinator"]) and "response_format" in request.body:
                self.requests.append(request.body)
                return reply('{"plan_data":{},"plan_issues":{"issues":[]}}')
            return await super().__call__(request)
    result = run(packet, BadFinal(answer))
    assert result.status == "failed" and result.answer is None
    assert result.model_calls[-1]["result"].response_text == '{"plan_data":{},"plan_issues":{"issues":[]}}'
    assert result.budget["model_requests"] == 8


def test_cancelled_request_retains_partial_bytes_and_unknown_usage(packet):
    async def cancelled(request):
        result = replace(reply(error="cancelled", status="failed", usage=False), raw_response=b'{"partial":')
        raise ModelRequestCancelled(result)
    with pytest.raises(CollaborationCancelled) as caught:
        run(packet, cancelled)
    result = caught.value.result
    assert result.status == "failed" and result.model_calls[0]["result"].raw_response == b'{"partial":'
    assert result.budget["reported_usage"] == {"input_tokens": None, "output_tokens": None}


def test_denied_followup_dispatch_closes_pending_tool_history_before_final(packet, answer):
    packet.configuration["limits"]["max_model_requests"] = 9
    client = ScriptedClient(answer, coordinator=[
        ("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}),
        ("submit_draft", {"based_on_version": 0, "draft": answer}),
        ("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}),
    ])
    result = run(packet, client)
    assert result.status == "succeeded", result.error
    assert result.stop_reason == "investigation_budget_exhausted" and len(result.tasks) == 2
    denied = [json.loads(message["content"]) for message in client.requests[-1]["messages"]
              if message["role"] == "tool"]
    assert denied[-1]["submitted"] is False


def test_investigation_time_exhaustion_uses_the_reserved_final_window(packet, answer):
    now = [0.0]
    class TimedClient(ScriptedClient):
        async def __call__(self, request):
            result = await super().__call__(request)
            if result.tool_calls and result.tool_calls[0]["function"]["name"] == "submit_draft":
                now[0] = 9.0
            return result
    result = run(packet, TimedClient(answer), clock=lambda: now[0])
    assert result.status == "succeeded", result.error
    assert result.stop_reason == "investigation_budget_exhausted"
    assert result.model_calls[-1]["phase"] == "final"


def test_answer_completed_after_total_elapsed_ceiling_is_not_accepted(packet, answer):
    now = [0.0]
    class LateFinal(ScriptedClient):
        async def __call__(self, request):
            result = await super().__call__(request)
            if request.model_name == MODELS["coordinator"] and "response_format" in request.body:
                now[0] = 11.0
            return result
    result = run(packet, LateFinal(answer), clock=lambda: now[0])
    assert result.status == "failed" and result.answer is None
    assert "elapsed" in result.error.lower()
    assert result.model_calls[-1]["result"].response_text == json.dumps(answer)


def test_required_worker_api_failure_stops_without_retry_and_retains_evidence(packet, answer):
    class BrokenWorker(ScriptedClient):
        async def __call__(self, request):
            if request.model_name == MODELS["worker_1"]:
                self.requests.append(request.body)
                return reply(error="Fictional HTTP 400", status="failed")
            return await super().__call__(request)
    result = run(packet, BrokenWorker(answer))
    assert result.status == "failed" and "HTTP 400" in result.error
    assert sum(item["actor"] == "worker_1" for item in result.model_calls) == 1
    assert all(item["phase"] != "final" for item in result.model_calls)
    assert any(item["result"] and item["result"].error == "Fictional HTTP 400" for item in result.model_calls)


def test_model_timeout_has_no_retry_and_does_not_report_unknown_usage_as_zero(packet):
    packet.profiles["coordinator"]["model_timeout_seconds"] = 0.01
    async def stalled(request):
        await asyncio.sleep(10)
    result = run(packet, stalled)
    assert result.status == "failed" and "TimeoutError" in result.error
    assert len(result.model_calls) == 1
    assert result.budget["reported_usage"] == {"input_tokens": None, "output_tokens": None}


@pytest.mark.parametrize("damage", ["retired_action", "issue_origin"])
def test_draft_revisions_preserve_identity_history(packet, answer, damage):
    first, second, third = deepcopy(answer), deepcopy(answer), deepcopy(answer)
    if damage == "retired_action":
        second["plan_data"]["actions"] = []
    else:
        issue = {"issue_id": "issue_0001", "related_action_id": None,
                 "issue_description": "Source uncertainty.", "issue_origin": "worker_1",
                 "issue_status": "open", "resolved_by": None, "resolution": None}
        first["plan_issues"]["issues"] = [issue]
        second["plan_issues"]["issues"] = [dict(issue, issue_origin="worker_2")]
    steps = [("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}),
             ("submit_draft", {"based_on_version": 0, "draft": first}),
             ("submit_draft", {"based_on_version": 1, "draft": second})]
    if damage == "retired_action":
        steps.append(("submit_draft", {"based_on_version": 2, "draft": third}))
    result = run(packet, ScriptedClient(answer, coordinator=steps))
    assert result.status == "failed"
    assert "retired" in result.error if damage == "retired_action" else "origins" in result.error


def test_controller_uses_the_real_http_adapter_with_mock_transport(packet, answer, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "fictional-c-test-token")
    scripted = ScriptedClient(answer)
    seen = []
    aliases = {MODELS["coordinator"]: "z-ai/glm-5.3-flash",
               MODELS["worker_2"]: "deepseek/deepseek-v4.1-flash-1017"}
    async def model(request):
        result = await scripted(request)
        message = deepcopy(result.assistant_message)
        for item in message.get("tool_calls", []):
            item["function"]["arguments"] = json.dumps(item["function"]["arguments"])
        payload = {"model": aliases.get(request.model_name, request.model_name),
                   "choices": [{"index": 0, "message": message, "finish_reason": result.finish_reason}],
                   "usage": {"prompt_tokens": 100, "completion_tokens": 10}}
        def handler(sent):
            seen.append(sent.content)
            return httpx.Response(200, json=payload)
        return await request_huggingface_chat(request, _transport=httpx.MockTransport(handler))
    result = run(packet, model)
    assert result.status == "succeeded", result.error
    assert len(seen) == result.budget["model_requests"] == 8
    assert all(b"fictional-c-test-token" not in value for value in seen)
