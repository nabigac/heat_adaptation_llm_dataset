"""Check task-bound generation and budget handoff with controlled model replies."""

from copy import deepcopy
from dataclasses import replace
import json

from jsonschema import Draft202012Validator
import pytest

from agents import FINAL_READY_SIGNAL
from huggingface_api import prepare_deepinfra_response_schema
from models import prepare_collaboration_schema
from test_collaboration import (
    DOC_TOOLS, MODELS, ScriptedClient, answer, assignment, call, packet, reply, run,
)


class WorkerInvestigationReply(ScriptedClient):
    """Return worker notes or drafts with an independently controlled final."""

    def __init__(self, answer, wrap, *, worker="worker_2", final_text=None, draft_status="normal"):
        super().__init__(answer)
        self.worker = worker
        self.wrap, self.final_text, self.draft_status = wrap, final_text, draft_status
        self.raw_draft = None

    async def __call__(self, request):
        result = await super().__call__(request)
        if request.model_name != MODELS[self.worker]:
            return result
        if "response_format" in request.body:
            return reply(self.final_text) if self.final_text is not None else result
        task = next(context["task"] for context in self.tasks.values()
                    if context["task"]["worker_id"] == self.worker)
        draft = {name: task[name] for name in ("task_id", "worker_id", "draft_version")}
        draft.update(checked_pages=[1], findings=[{
            "description": "An unvalidated draft finding.", "related_action_id": None,
            "proposed_change": "Draft only; the final response must replace this.",
            "evidence": [{"quote": "Plant 20 trees.", "page_numbers": [1]}],
            "unresolved": False,
        }])
        self.raw_draft = self.wrap(json.dumps(draft))
        return reply(self.raw_draft, calls=result.tool_calls, status=self.draft_status)


@pytest.mark.parametrize("wrap", [
    lambda body: body,
    lambda body: FINAL_READY_SIGNAL + "\n\n" + body,
    lambda body: FINAL_READY_SIGNAL + "\n\n```json\n" + body + "\n```",
    lambda body: " \n" + FINAL_READY_SIGNAL + " \r\n```JSON\r\n" + body + "\r\n```\n ",
    lambda body: FINAL_READY_SIGNAL + "\n```\n" + body + "\n```",
    lambda body: "I have enough to report. Compiling findings now.",
])
@pytest.mark.parametrize("worker", ["worker_1", "worker_2"])
def test_worker_reply_ends_investigation_but_requires_a_separate_strict_result(packet, answer, wrap, worker):
    client = WorkerInvestigationReply(answer, wrap, worker=worker)
    result = run(packet, client)
    assert result.status == "succeeded", result.error
    calls = [entry for entry in result.model_calls if entry["actor"] == worker]
    assert [entry["phase"] for entry in calls] == ["investigation", "worker_result"]
    final = calls[-1]["request"].body
    assert "tools" not in final and final["response_format"]["json_schema"]["strict"] is True
    assert any(message["role"] == "assistant" and message["content"] == client.raw_draft
               for message in final["messages"])
    completed = next(event["result"] for event in result.events
                     if event["event"] == "task_completed" and event["worker_id"] == worker)
    assert completed["findings"][0]["proposed_change"] == "Retain supported tree planting."


@pytest.mark.parametrize("wrap", [
    lambda body: FINAL_READY_SIGNAL + "\n```json\n" + body + "\n```\nextra prose",
    lambda body: FINAL_READY_SIGNAL + "\n" + body + "\n{}",
    lambda body: FINAL_READY_SIGNAL + "\n```json\n" + body[:-1] + "\n```",
    lambda body: FINAL_READY_SIGNAL + "\n```json\n[]\n```",
    lambda body: FINAL_READY_SIGNAL + '\n{"task_id":"one","task_id":"two","worker_id":"worker_2","findings":[]}',
    lambda body: FINAL_READY_SIGNAL + '\n{"task_id":"one","worker_id":"worker_2","findings":NaN}',
    lambda body: "Here is my answer:\n" + FINAL_READY_SIGNAL + "\n" + body,
    lambda body: FINAL_READY_SIGNAL + "\n```python\n" + body + "\n```",
    lambda body: "```json\n" + body + "\n```",
])
def test_worker_text_is_unvalidated_until_a_separate_final_result(packet, answer, wrap):
    client = WorkerInvestigationReply(answer, wrap)
    result = run(packet, client)
    assert result.status == "succeeded", result.error
    calls = [entry for entry in result.model_calls if entry["actor"] == "worker_2"]
    assert [entry["phase"] for entry in calls] == ["investigation", "worker_result"]
    assert calls[0]["result"].response_text == client.raw_draft
    assert any(m["role"] == "assistant" and m["content"] == client.raw_draft
               for m in calls[-1]["request"].body["messages"])
    assert calls[-1]["request"].body["response_format"]["json_schema"]["strict"] is True


@pytest.mark.parametrize("content", ["", " \n\t "])
@pytest.mark.parametrize("worker", ["worker_1", "worker_2"])
def test_empty_worker_reply_cannot_start_final_generation(packet, answer, content, worker):
    client = WorkerInvestigationReply(answer, lambda body: content, worker=worker)
    result = run(packet, client)
    assert result.status == "failed" and result.answer is None and "empty reply" in result.error
    assert all(entry["phase"] == "investigation" for entry in result.model_calls if entry["actor"] == worker)


def test_worker_prose_with_tool_calls_executes_tools_before_final_generation(packet, answer):
    client = WorkerInvestigationReply(answer, lambda body: "I have enough to report.")
    client.tools = True
    submitted = []

    async def document(actor, name, arguments):
        submitted.append((actor, name, arguments))
        return {"page_number": 1, "text": "Plant 20 trees."}

    result = run(packet, client, document_tools=DOC_TOOLS, document_client=document,
                 document_source_fingerprint=packet.source_fingerprint)
    assert result.status == "succeeded", result.error
    assert len(submitted) == 4
    assert sum(actor == "worker_2" for actor, _, _ in submitted) == 2


@pytest.mark.parametrize("final_text", [
    '{"task_id":"wrong","worker_id":"worker_2","findings":[]}',
    FINAL_READY_SIGNAL + '\n```json\n{"task_id":"task_0002"}\n```',
])
@pytest.mark.parametrize("reply_kind", ["wrapped", "prose"])
def test_early_worker_reply_cannot_replace_or_unwrap_an_invalid_final(packet, answer, final_text, reply_kind):
    wrap = (lambda body: "I have enough to report.") if reply_kind == "prose" else (
        lambda body: FINAL_READY_SIGNAL + "\n```json\n" + body + "\n```")
    client = WorkerInvestigationReply(answer,
        wrap, final_text=final_text)
    result = run(packet, client)
    assert result.status == "failed" and result.answer is None
    worker_calls = [entry for entry in result.model_calls if entry["actor"] == "worker_2"]
    assert [entry["phase"] for entry in worker_calls] == ["investigation", "worker_result"]
    assert worker_calls[-1]["result"].response_text == final_text
    assert all(entry["phase"] != "final" for entry in result.model_calls)


@pytest.mark.parametrize("status", ["failed", "truncated", "unknown"])
def test_worker_draft_requires_confirmed_normal_completion(packet, answer, status):
    client = WorkerInvestigationReply(answer,
        lambda body: "I have enough to report. Compiling findings now.", draft_status=status)
    result = run(packet, client)
    assert result.status == "failed" and result.answer is None
    assert all(entry["phase"] == "investigation" for entry in result.model_calls
               if entry["actor"] == "worker_2")


def test_initial_worker_schemas_fix_identity_and_allow_only_null_action_links(packet, answer):
    template = prepare_collaboration_schema("collaboration_result.schema.json")
    before = deepcopy(template)
    client = ScriptedClient(answer)
    result = run(packet, client)
    assert result.status == "succeeded", result.error
    for entry in result.model_calls:
        if entry["phase"] != "worker_result":
            continue
        context = client.tasks[entry["task_id"]]
        task = context["task"]
        schema = entry["request"].body["response_format"]["json_schema"]["schema"]
        assert context["allowed_action_ids"] == []
        assert schema == prepare_deepinfra_response_schema(context["task_result_schema"])
        for field in ("task_id", "worker_id", "draft_version"):
            assert schema["properties"][field]["enum"] == [task[field]]
        assert schema["properties"]["findings"]["items"]["properties"]["related_action_id"]["enum"] == [None]
        value = json.loads(entry["result"].response_text)
        Draft202012Validator(schema).validate(value)
        value["findings"][0]["related_action_id"] = "action_0001"
        assert not Draft202012Validator(schema).is_valid(value)
        instructions = [m["content"] for m in entry["request"].body["messages"] if m["role"] == "user"][-1]
        assert "every related_action_id must be null" in instructions
    assert prepare_collaboration_schema("collaboration_result.schema.json") == before
    assert "enum" not in before["properties"]["task_id"]


def test_followup_schema_uses_the_accepted_draft_ids_without_mutating_initial_schemas(packet, answer):
    def link_existing(value):
        if value["task_id"] == "task_0003":
            value["findings"][0]["related_action_id"] = "action_0001"
    client = ScriptedClient(answer, bad_result=link_existing, coordinator=[
        ("assign_tasks", {"assignments": [assignment("worker_1"), assignment("worker_2")]}),
        ("submit_draft", {"based_on_version": 0, "draft": answer}),
        ("assign_tasks", {"assignments": [assignment("worker_1", independent=False, context=["task_0002"])]}),
        ("finish_investigation", {}),
    ])
    result = run(packet, client)
    assert result.status == "succeeded", result.error
    for entry in result.model_calls:
        if entry["phase"] != "worker_result":
            continue
        schema = entry["request"].body["response_format"]["json_schema"]["schema"]
        followup = entry["task_id"] == "task_0003"
        expected = [None, "action_0001"] if followup else [None]
        assert schema["properties"]["findings"]["items"]["properties"]["related_action_id"]["enum"] == expected
        assert schema["properties"]["draft_version"]["enum"] == [1 if followup else 0]
        Draft202012Validator(schema).validate(json.loads(entry["result"].response_text))
    assert client.tasks["task_0003"]["allowed_action_ids"] == ["action_0001"]
    assert client.tasks["task_0001"]["allowed_action_ids"] == []


@pytest.mark.parametrize("field,wrong", [
    ("task_id", "task_9999"), ("worker_id", "worker_2"), ("draft_version", 9),
    ("related_action_id", "action_0001"),
])
def test_python_still_rejects_wrong_identity_or_unknown_links_without_repair(packet, answer, field, wrong):
    def damaged(value):
        if value["worker_id"] != "worker_1":
            return
        if field == "related_action_id":
            value["findings"][0][field] = wrong
        else:
            value[field] = wrong
    result = run(packet, ScriptedClient(answer, bad_result=damaged))
    assert result.status == "failed" and result.answer is None
    assert all(entry["phase"] != "final" for entry in result.model_calls)
    raw = next(entry["result"].response_text for entry in result.model_calls
               if entry["actor"] == "worker_1" and entry["phase"] == "worker_result")
    value = json.loads(raw)
    assert (value["findings"][0][field] if field == "related_action_id" else value[field]) == wrong


class BusyWorkers(ScriptedClient):
    """Use investigation slots until admission stops; result slots stay reserved."""

    def __init__(self, answer, *, both=True, bad_final=False, bad_worker=False):
        assignments = [assignment("worker_1"), assignment("worker_2")] if both else [assignment("worker_1")]
        super().__init__(answer, coordinator=[("assign_tasks", {"assignments": assignments})])
        self.bad_final, self.bad_worker = bad_final, bad_worker

    async def __call__(self, request):
        if request.model_name == MODELS["coordinator"]:
            if self.bad_final and "response_format" in request.body:
                self.requests.append(request.body)
                return reply('{"plan_data":{},"plan_issues":{"issues":[]}}')
            return await super().__call__(request)
        if "response_format" in request.body:
            result = await super().__call__(request)
            if self.bad_worker and request.model_name == MODELS["worker_1"]:
                return reply(error="Controlled worker failure", status="failed")
            return result
        self.requests.append(request.body)
        return reply(calls=[call("get_page_text", {"page_number": 1}, f"lookup-{len(self.requests)}")])


def busy(packet, client):
    for profile in packet.profiles.values():
        profile["max_tool_calls"] = 20
    packet.configuration["limits"]["max_document_tool_calls"] = 60
    async def document(*args):
        return {"text": "Controlled source text."}
    return run(packet, client, document_tools=DOC_TOOLS, document_client=document,
               document_source_fingerprint=packet.source_fingerprint)


def test_request_budget_exhaustion_uses_request_twenty_one_for_first_complete_answer(packet, answer):
    client = BusyWorkers(answer)
    result = busy(packet, client)
    assert result.status == "succeeded", result.error
    assert result.budget["model_requests"] == 21
    assert result.stop_reason == "investigation_budget_exhausted"
    assert len(result.drafts) == 1 and result.drafts[0]["answer"] == answer
    assert sum(e["event"] == "task_completed" for e in result.events) == 2
    handoff = next(e for e in result.events if e["event"] == "final_handoff")
    assert handoff["draft_version"] == 0 and handoff["worker_task_ids"] == ["task_0001", "task_0002"]
    coordinator = [entry for entry in result.model_calls if entry["actor"] == "coordinator"]
    assert [entry["phase"] for entry in coordinator] == ["investigation", "final"]
    final = coordinator[-1]["request"].body
    assert "tools" not in final and final["response_format"]["json_schema"]["strict"] is True
    assert any("No intermediate draft was saved" in m["content"] for m in final["messages"] if m["role"] == "user")
    tool_result = next(m for m in final["messages"] if m["role"] == "tool")
    assert {r["worker_id"] for r in json.loads(tool_result["content"])["results"]} == {"worker_1", "worker_2"}


@pytest.mark.parametrize("failure", ["missing_worker", "failed_worker", "invalid_final"])
def test_budget_handoff_does_not_accept_missing_failed_workers_or_invalid_final(packet, answer, failure):
    result = busy(packet, BusyWorkers(answer, both=failure != "missing_worker",
                                     bad_worker=failure == "failed_worker", bad_final=failure == "invalid_final"))
    assert result.status == "failed" and result.answer is None
    assert result.budget["model_requests"] <= 21
    assert any(entry["phase"] == "final" for entry in result.model_calls) is (failure == "invalid_final")


def test_investigation_deadline_can_handoff_with_both_results_and_no_draft(packet, answer):
    now = [0.0]
    class Timed(ScriptedClient):
        async def __call__(self, request):
            result = await super().__call__(request)
            if request.model_name == MODELS["worker_2"] and "response_format" in request.body:
                now[0] = 9.0
            return result
    result = run(packet, Timed(answer), clock=lambda: now[0])
    assert result.status == "succeeded", result.error
    assert len(result.drafts) == 1 and result.budget["model_requests"] == 6
    assert result.stop_reason == "investigation_budget_exhausted"


def test_known_reported_usage_breach_blocks_handoff_even_with_both_worker_results(packet, answer):
    class OverBudget(ScriptedClient):
        async def __call__(self, request):
            result = await super().__call__(request)
            if request.model_name == MODELS["coordinator"] and self.tasks:
                return replace(result, input_tokens=packet.configuration["limits"]["max_estimated_tokens"])
            return result
    result = run(packet, OverBudget(answer))
    assert result.status == "failed" and "Reported usage" in result.error
    assert sum(e["event"] == "task_completed" for e in result.events) == 2
    assert all(entry["phase"] != "final" for entry in result.model_calls)
