"""Check mixed delegation/source replies without live model or document calls."""

from copy import deepcopy
import json

import pytest

from test_collaboration import (
    DOC_TOOLS, MODELS, ScriptedClient, answer, assignment, call, packet, reply, run,
)


SOURCE_TOOLS = DOC_TOOLS + [{"type": "function", "function": {
    "name": "find_quote", "description": "Find a passage in the saved source.",
    "parameters": {"type": "object", "properties": {"quote": {"type": "string"}},
                   "required": ["quote"], "additionalProperties": False},
}}]
OCR_TOOL = {"type": "function", "function": {
    "name": "run_ocr", "description": "Read a source page with OCR.",
    "parameters": DOC_TOOLS[0]["function"]["parameters"],
}}


def delegate(identifier="delegation"):
    return call("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}, identifier)


class MixedClient(ScriptedClient):
    def __init__(self, answer, calls, **options):
        super().__init__(answer, coordinator=[
            ("submit_draft", {"based_on_version": 0, "draft": answer}),
            ("finish_investigation", {}),
        ], **options)
        self.first_calls = deepcopy(calls)
        self.sent_first = False

    async def __call__(self, request):
        if request.model_name == MODELS["coordinator"] and not self.sent_first:
            self.sent_first = True
            self.requests.append(request.body)
            return reply(calls=self.first_calls)
        return await super().__call__(request)


@pytest.mark.parametrize("position", [0, 1, 2])
@pytest.mark.parametrize("source_tool", ["get_page_text", "find_quote", "run_ocr"])
def test_mixed_calls_follow_returned_order_with_parallel_workers_and_complete_history(
    packet, answer, position, source_tool,
):
    tools = deepcopy(SOURCE_TOOLS)
    if source_tool == "run_ocr":
        tools.append(OCR_TOOL)
        for profile in packet.profiles.values():
            profile["document_tools"].update(ocr_enabled=True, ocr_engine="easyocr", ocr_language="en")
    calls = [call(source_tool, {"quote": f"passage {n}"} if source_tool == "find_quote" else {"page_number": n},
                  f"source-{n}") for n in (1, 2)]
    calls.insert(position, delegate())
    original = deepcopy(calls)
    client = MixedClient(answer, calls, barrier=True)
    trace, submitted = [], []
    def observed(event, controller):
        if event["event"] == "task_completed":
            trace.append("worker")
        elif event["event"] == "document_tool_submitted":
            trace.append("source")
    async def document(actor, name, arguments):
        submitted.append((actor, name, arguments))
        return {"text": "Controlled source result."}
    result = run(packet, client, document_tools=tools, document_client=document,
                 document_source_fingerprint=packet.source_fingerprint, on_progress=observed)
    assert result.status == "succeeded", result.error
    assert trace == ["source"] * position + ["worker", "worker"] + ["source"] * (2 - position)
    assert client.arrived == {"worker_1", "worker_2"}
    assert len(submitted) == result.budget["document_tool_calls"]["coordinator"] == 2
    assert result.budget["model_requests"] == 8
    coordinator_requests = [r for r in client.requests if r["model"] == MODELS["coordinator"] + ":deepinfra"]
    responses = [m for m in coordinator_requests[1]["messages"] if m["role"] == "tool"]
    assert [m["tool_call_id"] for m in responses] == [c["id"] for c in calls]
    assert json.loads(responses[position]["content"])["results"][0]["worker_id"] == "worker_1"
    assert client.first_calls == original


@pytest.mark.parametrize("damage", [
    "unknown_tool", "invalid_arguments", "document_page", "task_page", "task_context", "duplicate_worker",
])
@pytest.mark.parametrize("delegation_first", [False, True])
def test_entire_batch_is_checked_before_any_worker_or_source_side_effect(
    packet, answer, damage, delegation_first,
):
    delegation = delegate()
    source = call("get_page_text", {"page_number": 1}, "source")
    if damage == "unknown_tool":
        source["function"]["name"] = "unknown_tool"
    elif damage == "invalid_arguments":
        source["function"]["arguments"]["page_number"] = "one"
    elif damage == "document_page":
        source["function"]["arguments"]["page_number"] = packet.page_count + 1
    else:
        tasks = delegation["function"]["arguments"]["assignments"]
        if damage == "task_page":
            tasks[0]["source_pages"] = [packet.page_count + 1]
        elif damage == "task_context":
            tasks[0].update(independent=False, context_task_ids=["task_9999"])
        else:
            tasks[1]["worker_id"] = tasks[0]["worker_id"]
    calls = [delegation, source] if delegation_first else [source, delegation]
    client, submitted = MixedClient(answer, calls), []
    async def document(*args):
        submitted.append(args)
        return {}
    result = run(packet, client, document_tools=SOURCE_TOOLS, document_client=document,
                 document_source_fingerprint=packet.source_fingerprint)
    assert result.status == "failed" and result.answer is None
    assert len(client.requests) == 1 and not result.tasks and not submitted
    assert sum(result.budget["document_tool_calls"].values()) == 0


@pytest.mark.parametrize("control", ["submit_draft", "finish_investigation", "two_delegations"])
def test_disallowed_control_combinations_fail_before_source_calls(packet, answer, control):
    if control == "two_delegations":
        calls = [delegate("first"), delegate("second")]
    else:
        arguments = {"based_on_version": 0, "draft": answer} if control == "submit_draft" else {}
        calls = [call(control, arguments, "control")]
    calls.insert(0, call("get_page_text", {"page_number": 1}, "source"))
    client, submitted = MixedClient(answer, calls), []
    async def document(*args):
        submitted.append(args)
        return {}
    result = run(packet, client, document_tools=SOURCE_TOOLS, document_client=document,
                 document_source_fingerprint=packet.source_fingerprint)
    assert result.status == "failed" and not submitted and not result.tasks
    assert "standalone" in result.error if control != "two_delegations" else "one coordination" in result.error
    assert len(client.requests) == 1


def test_mixed_source_calls_keep_shared_quotas_and_explicit_denials(packet, answer):
    packet.configuration["limits"]["max_document_tool_calls"] = 1
    calls = [delegate()] + [call("get_page_text", {"page_number": 1}, f"source-{n}") for n in range(3)]
    client, submitted = MixedClient(answer, calls), []
    async def document(*args):
        submitted.append(args)
        return {}
    result = run(packet, client, document_tools=SOURCE_TOOLS, document_client=document,
                 document_source_fingerprint=packet.source_fingerprint)
    assert result.status == "succeeded", result.error
    assert len(submitted) == sum(result.budget["document_tool_calls"].values()) == 1
    assert sum(e["event"] == "document_tool_denied" for e in result.events) == 2
    assert result.budget["model_requests"] == 8


def test_failed_worker_prevents_later_source_calls_in_the_same_reply(packet, answer):
    class BrokenWorker(MixedClient):
        async def __call__(self, request):
            if request.model_name == MODELS["worker_1"]:
                self.requests.append(request.body)
                return reply(error="Controlled worker failure.", status="failed")
            return await super().__call__(request)
    client = BrokenWorker(answer, [delegate(), call("get_page_text", {"page_number": 1}, "source")])
    submitted = []
    async def document(*args):
        submitted.append(args)
        return {}
    result = run(packet, client, document_tools=SOURCE_TOOLS, document_client=document,
                 document_source_fingerprint=packet.source_fingerprint)
    assert result.status == "failed" and "worker failure" in result.error
    assert not submitted and all(c["phase"] != "final" for c in result.model_calls)


def test_budget_denial_closes_only_unanswered_calls_in_a_partly_executed_mixed_reply(packet, answer):
    packet.configuration["limits"]["max_model_requests"] = 9
    mixed = [call("get_page_text", {"page_number": 1}, "before"), delegate("followup"),
             call("get_page_text", {"page_number": 2}, "after")]
    class FollowupClient(ScriptedClient):
        async def __call__(self, request):
            if (request.model_name == MODELS["coordinator"] and "response_format" not in request.body
                    and not self.coordinator):
                self.requests.append(request.body)
                return reply(calls=mixed)
            return await super().__call__(request)
    client = FollowupClient(answer, coordinator=[
        ("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}),
        ("submit_draft", {"based_on_version": 0, "draft": answer}),
    ])
    submitted = []
    async def document(actor, name, arguments):
        submitted.append(arguments["page_number"])
        return {"text": "Controlled source result."}
    result = run(packet, client, document_tools=SOURCE_TOOLS, document_client=document,
                 document_source_fingerprint=packet.source_fingerprint)
    assert result.status == "succeeded", result.error
    assert result.stop_reason == "investigation_budget_exhausted" and len(result.tasks) == 2
    responses = {m["tool_call_id"]: json.loads(m["content"]) for m in client.requests[-1]["messages"] if m["role"] == "tool"}
    assert submitted == [1] and result.budget["document_tool_calls"]["coordinator"] == 1
    assert responses["before"] == {"text": "Controlled source result."}
    assert responses["followup"]["submitted"] is responses["after"]["submitted"] is False
