"""An in-memory C controller with injected model and source-tool clients.

The coordinator chooses assignments; Python validates/runs them and owns draft
versions, budgets, and evidence. Independent workers run concurrently, each in
an isolated task conversation. No CLI, paid client, MCP startup, run publication,
or citation repair is enabled by this prototype.
"""

import asyncio
from copy import deepcopy
from dataclasses import dataclass, replace
import json
import time
from typing import Awaitable, Callable

from agents import FINAL_READY_SIGNAL
from collaboration_budget import CollaborationBudget, CollaborationBudgetExceeded
from collaboration_contracts import (
    WORKERS, CollaborationInput, CollaborationContractError,
    coordinator_tools, validate_bindings, validate_collaboration_response,
    validate_task, validate_worker_result,
)
from huggingface_api import (
    PreparedHuggingFaceRequest, build_huggingface_request,
    estimate_huggingface_budget,
)
from models import (
    ModelCallResult, ModelRequestCancelled, _json_object, _validate_tools,
    _validate_tool_calls, is_investigation_handoff, prepare_collaboration_schema,
)


ModelClient = Callable[[PreparedHuggingFaceRequest], Awaitable[ModelCallResult]]
DocumentClient = Callable[[str, str, dict], Awaitable[dict]]
CONTROL_NAMES = {"assign_tasks", "submit_draft", "finish_investigation"}
DOCUMENT_NAMES = {"get_page_text", "find_quote", "run_ocr"}


def _json(data) -> str:
    return json.dumps(data, ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class CollaborationResult:
    """A final outcome plus all in-memory evidence, including failed attempts."""

    status: str
    answer: dict | None
    error: str | None
    events: list[dict]
    model_calls: list[dict]
    tasks: list[dict]
    drafts: list[dict]
    budget: dict
    stop_reason: str | None


class CollaborationCancelled(asyncio.CancelledError):
    def __init__(self, result: CollaborationResult):
        self.result = result
        super().__init__("Collaboration cancelled; available evidence is retained.")


class _Controller:
    def __init__(self, packet, model_client, document_tools, document_client, source_fingerprint, clock,
                 on_progress, started_monotonic):
        self.packet = deepcopy(packet)
        self.model_client = model_client
        self.document_client = document_client
        self.document_tools = deepcopy(document_tools)
        self.on_progress = on_progress
        validate_bindings(self.packet.configuration, self.packet.profiles)
        if type(packet.page_count) is not int or packet.page_count < 1:
            raise CollaborationContractError("A positive source page count is required.")
        definitions = _validate_tools(self.document_tools)
        if definitions.keys() - DOCUMENT_NAMES:
            raise CollaborationContractError("C accepts only the existing source-document tools.")
        if self.document_tools and (document_client is None or source_fingerprint != packet.source_fingerprint):
            raise CollaborationContractError("Document tools require a client bound to this exact source fingerprint.")
        if "run_ocr" in definitions and not packet.profiles["coordinator"]["document_tools"]["ocr_enabled"]:
            raise CollaborationContractError("OCR is disabled for this input.")
        self.budget = CollaborationBudget(packet.configuration["limits"], packet.profiles, clock=clock)
        if started_monotonic is not None:
            self.budget.started = started_monotonic
        self.events, self.calls, self.tasks, self.drafts = [], [], [], []
        self.findings = {}
        self.retired_actions = set()
        self.worker_failed = False
        self.stop_reason = None
        self.result_schema = prepare_collaboration_schema("collaboration_result.schema.json")
        self.response_schema = prepare_collaboration_schema("collaboration_response.schema.json")
        self.control_tools = coordinator_tools()
        self.history = self._base_history("coordinator")

    def _base_history(self, actor):
        return [{"role": "system", "content": "\n\n".join(self.packet.profiles[actor]["prompt_texts"])},
                deepcopy(self.packet.source_message)]

    def _record(self, event, **details):
        self.events.append({"event": event, "elapsed_seconds": self.budget.report()["elapsed_seconds"],
                            **deepcopy(details)})
        if self.on_progress is not None:
            try:
                self.on_progress(self.events[-1], self)
            except Exception:
                # Persistence failure must stop new work, including a worker
                # awaiting admission in the other branch of a parallel batch.
                self.on_progress = None
                self.worker_failed = True
                raise

    def _action_ids(self, draft=None):
        if draft is None:
            draft = self.drafts[-1]["answer"] if self.drafts else None
        return {item["action_id"] for item in draft["plan_data"]["actions"]} if draft else set()

    def _prepare(self, actor, history, *, tools=None, schema=None, final=False):
        messages = deepcopy(history)
        messages.append({"role": "system", "content": (
            "Controller state at request preparation (instructions, not source). "
            "Admission and concurrent work may consume more; Python enforces live limits: " + _json({
                "agent_id": actor, "draft_version": len(self.drafts),
                "document_tools_remaining": self.budget.tools_left(actor),
                "budget": self.budget.report(),
            })
        )})
        request = build_huggingface_request(self.packet.profiles[actor], messages,
                                           tools=tools, response_format=schema)
        capacity = estimate_huggingface_budget(request).report
        if not capacity["fits"]:
            raise CollaborationBudgetExceeded("Request does not fit; the source is never shortened.")
        seconds = min(request.timeout_seconds, self.budget.seconds_left(final=final))
        if seconds <= 0:
            raise CollaborationBudgetExceeded("The phase deadline has been reached.")
        return replace(request, timeout_seconds=seconds), capacity["estimated_input_tokens"] + request.max_output_tokens

    async def _send(self, actor, request, tokens, *, reservation=None, task_id=None, phase="investigation"):
        if self.worker_failed:
            raise CollaborationContractError("A required worker failed; no new model request is started.")
        seconds = min(request.timeout_seconds, self.budget.seconds_left(final=phase == "final"))
        if seconds <= 0:
            raise CollaborationBudgetExceeded("No phase time remains; no model request started.")
        request = replace(request, timeout_seconds=seconds)
        key = reservation or f"call_{len(self.calls) + 1}"
        if reservation is None:
            self.budget.reserve_batch({key: tokens})
        self.budget.consume(key, tokens)
        evidence = {"actor": actor, "task_id": task_id, "phase": phase,
                    "request": request, "result": None, "error": None}
        self.calls.append(evidence)
        self._record("model_request", actor=actor, task_id=task_id, phase=phase,
                     request_number=len(self.calls))
        try:
            result = await asyncio.wait_for(self.model_client(request), timeout=request.timeout_seconds)
        except BaseException as error:
            # A timeout can wrap ModelRequestCancelled as its cause. Retain the
            # adapter's partial bytes before propagating cancellation/failure.
            cause = error
            while cause is not None:
                if isinstance(cause, ModelRequestCancelled):
                    evidence["result"] = deepcopy(cause.result)
                    break
                cause = cause.__cause__
            if evidence["result"] is not None:
                try:
                    self.budget.observe_usage(evidence["result"])
                except CollaborationBudgetExceeded as usage_error:
                    self._record("usage_limit_exceeded", reason=str(usage_error))
            else:
                self.budget.missing_usage.update(self.budget.usage)
            evidence["error"] = f"{type(error).__name__}: {error}"
            raise
        if not isinstance(result, ModelCallResult):
            self.budget.missing_usage.update(self.budget.usage)
            raise CollaborationContractError("The model client must return ModelCallResult evidence.")
        evidence["result"] = deepcopy(result)
        self.budget.observe_usage(result)
        self._record("model_response", actor=actor, task_id=task_id,
                     completion_status=result.completion_status)
        if result.error or result.completion_status != "normal":
            raise CollaborationContractError(result.error or "Incomplete model response.")
        if phase in {"worker_result", "final"} and result.tool_calls:
            raise CollaborationContractError("Schema-only final responses cannot request tools.")
        return result

    def _append_tool_result(self, history, call, value):
        history.append({"role": "tool", "tool_name": call["function"]["name"],
                        "tool_call_id": call["id"], "content": _json(value)})

    def _append_assistant(self, history, result):
        message = result.assistant_message
        if (not isinstance(message, dict) or message.get("role") != "assistant"
                or not isinstance(message.get("content"), str)
                or message.get("tool_calls", []) != result.tool_calls):
            raise CollaborationContractError("Model evidence must contain one consistent assistant message.")
        previous_ids = {call["id"] for item in history for call in item.get("tool_calls", [])}
        if any(call["id"] in previous_ids for call in result.tool_calls):
            raise CollaborationContractError("Tool call IDs cannot be reused in a conversation.")
        history.append(deepcopy(message))

    def _validate_document_page(self, call):
        page = call["function"]["arguments"].get("page_number")
        if page is not None and (type(page) is not int or not 1 <= page <= self.packet.page_count):
            raise CollaborationContractError("A tool page is outside this source.")

    async def _document_calls(self, actor, history, calls, *, task_id=None):
        definitions = _validate_tools(self.document_tools)
        _validate_tool_calls(calls, definitions, require_known=True)
        for call in calls:
            if self.worker_failed:
                raise CollaborationContractError("A required worker failed; no new document call is started.")
            name, arguments = call["function"]["name"], call["function"]["arguments"]
            self._validate_document_page(call)
            if self.budget.tools_left(actor) <= 0:
                value = {"error": "Document-tool allowance exhausted; no call submitted."}
                self._record("document_tool_denied", actor=actor, task_id=task_id, name=name)
            else:
                seconds = min(self.packet.profiles[actor]["document_tools"]["tool_timeout_seconds"],
                              self.budget.seconds_left())
                if seconds <= 0:
                    raise CollaborationBudgetExceeded("Investigation time is exhausted.")
                self.budget.submit_tool(actor)
                self._record("document_tool_submitted", actor=actor, task_id=task_id,
                             name=name, arguments=arguments)
                try:
                    value = await asyncio.wait_for(self.document_client(actor, name, deepcopy(arguments)),
                                                   timeout=seconds)
                    value = _json_object(_json(value).encode("utf-8"))
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    value = {"error": f"{type(error).__name__}: {error}"}
                self._record("document_tool_result", actor=actor, task_id=task_id, name=name, result=value)
            self._append_tool_result(history, call, value)

    def _worker_result_schema(self, task, action_ids):
        """Narrow generation to this task without changing acceptance rules.

        The shared schema describes all tasks. Its per-request copy fixes the
        assigned identity/version and permits links only to the draft snapshot.
        Python still checks these relationships after generation.
        """
        schema = deepcopy(self.result_schema)
        for field in ("task_id", "worker_id", "draft_version"):
            schema["properties"][field]["enum"] = [task[field]]
        link = schema["properties"]["findings"]["items"]["properties"]["related_action_id"]
        link["enum"] = [None, *sorted(action_ids)]
        return schema

    async def _worker(self, task, history, first_request, first_tokens, action_ids, result_schema):
        actor, identifier = task["worker_id"], task["task_id"]
        initial_key, final_key = identifier + ":initial", identifier + ":final"
        try:
            request, tokens, reservation = first_request, first_tokens, initial_key
            while True:
                result = await self._send(actor, request, tokens, reservation=reservation,
                                          task_id=identifier)
                self._append_assistant(history, result)
                if result.tool_calls:
                    await self._document_calls(actor, history, result.tool_calls, task_id=identifier)
                elif is_investigation_handoff(result):
                    break
                else:
                    raise CollaborationContractError("Worker investigation returned an empty reply; no final task request was made.")
                if self.budget.tools_left(actor) <= 0:
                    break
                try:
                    request, tokens = self._prepare(actor, history, tools=self.document_tools)
                    reservation = identifier + f":followup_{len(self.calls)}"
                    self.budget.reserve_batch({reservation: tokens})
                except CollaborationBudgetExceeded:
                    break
            identity = {field: task[field] for field in ("task_id", "worker_id", "draft_version")}
            links = ("The only permitted non-null links are " + _json(sorted(action_ids)) + ". " if action_ids else
                     "No accepted action IDs exist for this task; every related_action_id must be null. ")
            history.append({"role": "user", "content": (
                "Investigation has ended. Return one complete task-result JSON object using the supplied schema. "
                "Treat earlier investigation replies as unvalidated notes or drafts; retain unresolved concerns and do not invent source checks. "
                "Copy the assigned identity/version exactly: " + _json(identity) + ". "
                "For a new activity candidate or plan-level concern, related_action_id must be null. " + links +
                "Do not copy proposed action IDs from an earlier unvalidated response into this field."
            )})
            request, tokens = self._prepare(actor, history, schema=result_schema)
            result = await self._send(actor, request, tokens, reservation=final_key,
                                      task_id=identifier, phase="worker_result")
            answer = _json_object((result.response_text or "").encode("utf-8"))
            validate_worker_result(answer, task, page_count=self.packet.page_count, action_ids=action_ids)
            self.findings[identifier] = deepcopy(answer)
            self._record("task_completed", task_id=identifier, worker_id=actor, result=answer)
            return answer
        except BaseException as error:
            self.worker_failed = True
            self._record("task_failed", task_id=identifier, worker_id=actor,
                         error=f"{type(error).__name__}: {error}")
            raise

    def _assignment_tasks(self, assignments):
        """Check task context without starting workers or consuming reserves."""
        if len({item["worker_id"] for item in assignments}) != len(assignments):
            raise CollaborationContractError("A batch may contain at most one task per worker.")
        tasks = []
        for index, assignment in enumerate(assignments, start=len(self.tasks) + 1):
            task = {"task_id": f"task_{index:04d}", "draft_version": len(self.drafts), **deepcopy(assignment)}
            validate_task(task, page_count=self.packet.page_count, completed_tasks=set(self.findings))
            tasks.append(task)
        return tasks

    async def _dispatch(self, assignments):
        prepared, reservations = [], {}
        for task in self._assignment_tasks(assignments):
            history = self._base_history(task["worker_id"])
            action_ids = self._action_ids()
            result_schema = self._worker_result_schema(task, action_ids)
            context = {"task": task, "task_result_schema": result_schema, "allowed_action_ids": sorted(action_ids)}
            if not task["independent"]:
                context["draft"] = self.drafts[-1]["answer"] if self.drafts else None
                context["prior_findings"] = [self.findings[key] for key in task["context_task_ids"]]
            history.append({"role": "user", "content": "ASSIGNMENT AND CHECKABLE DATA:\n" + _json(context)})
            history.append({"role": "user", "content": (
                "During investigation request document tools as needed, or return exactly " + FINAL_READY_SIGNAL +
                ". A complete draft task result also ends investigation. Python will then request the final task JSON."
            )})
            tools = self.document_tools if self.budget.tools_left(task["worker_id"]) else None
            request, tokens = self._prepare(task["worker_id"], history, tools=tools)
            reservations[task["task_id"] + ":initial"] = tokens
            reservations[task["task_id"] + ":final"] = self.packet.profiles[task["worker_id"]]["context_limit"]
            prepared.append((task, history, request, tokens, action_ids, result_schema))
        # All tasks, first requests, and mandatory result requests must fit
        # together. A rejected batch starts neither worker and changes no draft.
        self.budget.reserve_batch(reservations)
        for task, *_ in prepared:
            self.tasks.append(deepcopy(task))
            self._record("task_assigned", task=task)
        results = await asyncio.gather(*(self._worker(*item) for item in prepared), return_exceptions=True)
        for result in results:
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, BaseException):
                raise CollaborationContractError(f"Required worker failed: {type(result).__name__}: {result}")
        return {"results": results}

    def _save_draft(self, answer, based_on_version):
        if based_on_version != len(self.drafts):
            raise CollaborationContractError("Draft update is based on a stale version.")
        validate_collaboration_response(answer, page_count=self.packet.page_count,
                                        source_metadata=self.packet.source_metadata)
        incoming = self._action_ids(answer)
        if incoming & self.retired_actions:
            raise CollaborationContractError("A retired action ID cannot be reused.")
        if self.drafts:
            old = {issue["issue_id"]: issue for issue in self.drafts[-1]["answer"]["plan_issues"]["issues"]}
            new = {issue["issue_id"]: issue for issue in answer["plan_issues"]["issues"]}
            if not old.keys() <= new.keys() or any(old[key]["issue_origin"] != new[key]["issue_origin"] for key in old):
                raise CollaborationContractError("Continuing issue IDs and origins must be retained.")
        self.retired_actions.update(self._action_ids() - incoming)
        self.drafts.append({"version": len(self.drafts) + 1, "answer": deepcopy(answer)})
        self._record("draft_saved", version=len(self.drafts), answer=answer)

    def _workers_complete(self):
        return {item["worker_id"] for item in self.findings.values()} == set(WORKERS)

    def _ready(self):
        return bool(self.drafts) and self._workers_complete()

    async def _coordinator_calls(self, calls, tools):
        """Validate the entire reply, then execute its calls in returned order.

        Only delegation may accompany source calls. Draft submission and ending
        investigation each need their own turn, so neither depends on tool
        results the coordinator has not yet received. Resource admission still
        happens at execution; worker dispatch retains its atomic reservations.
        """
        _validate_tool_calls(calls, _validate_tools(tools), require_known=True)
        controls = [call for call in calls if call["function"]["name"] in CONTROL_NAMES]
        if len(controls) > 1:
            raise CollaborationContractError("Use at most one coordination tool per turn.")
        if controls and controls[0]["function"]["name"] != "assign_tasks" and len(calls) != 1:
            raise CollaborationContractError("submit_draft and finish_investigation must each be standalone.")
        # Context checks precede every side effect, even when the invalid call
        # appears after an otherwise valid delegation or document lookup.
        for call in calls:
            if call["function"]["name"] == "assign_tasks":
                self._assignment_tasks(call["function"]["arguments"]["assignments"])
            elif call["function"]["name"] in DOCUMENT_NAMES:
                self._validate_document_page(call)
        for call in calls:
            name, arguments = call["function"]["name"], call["function"]["arguments"]
            if name in DOCUMENT_NAMES:
                await self._document_calls("coordinator", self.history, [call])
                continue
            if name == "assign_tasks":
                value = await self._dispatch(arguments["assignments"])
            elif name == "submit_draft":
                self._save_draft(arguments["draft"], arguments["based_on_version"])
                value = {"draft_version": len(self.drafts)}
            else:
                if not self._ready():
                    raise CollaborationContractError("Completion requires both worker contributions and a valid draft.")
                value = {"ready_for_final": True}
            self._append_tool_result(self.history, call, value)
            if name == "finish_investigation":
                self.stop_reason = "coordinator_finished"
                return True
        return False

    async def run(self):
        try:
            while True:
                tools = self.control_tools + (self.document_tools if self.budget.tools_left("coordinator") else [])
                self.history.append({"role": "user", "content": (
                    "Use the offered tools to assign tasks, submit a complete versioned draft, or finish investigation. "
                    "Use at most one coordination tool per turn. assign_tasks may accompany document-tool calls; "
                    "calls run in returned order, waiting for assigned workers before later calls. "
                    "submit_draft and finish_investigation must each be standalone. "
                    "Both workers must contribute before finishing."
                )})
                try:
                    request, tokens = self._prepare("coordinator", self.history, tools=tools)
                    result = await self._send("coordinator", request, tokens)
                    self._append_assistant(self.history, result)
                    if not result.tool_calls:
                        if (result.response_text or "").strip() != FINAL_READY_SIGNAL:
                            self._save_draft(_json_object((result.response_text or "").encode("utf-8")), len(self.drafts))
                        if not self._ready():
                            raise CollaborationContractError("Completion requires both worker contributions and a valid draft.")
                        self.stop_reason = "coordinator_ready"
                        break
                    if await self._coordinator_calls(result.tool_calls, tools):
                        break
                except CollaborationBudgetExceeded as error:
                    self._record("investigation_stopped", reason=str(error))
                    # Reserved final capacity can survive an admission refusal,
                    # but a known breach of the actual usage ceiling cannot.
                    usage_exceeded = sum(self.budget.usage.values()) > self.budget.limits["max_estimated_tokens"]
                    if not self._workers_complete() or self.worker_failed or usage_exceeded:
                        raise
                    # A denied dispatch still needs a matching tool result in
                    # history before the schema-only final request can replay it.
                    last_assistant = next((i for i in range(len(self.history) - 1, -1, -1)
                                           if self.history[i]["role"] == "assistant"), None)
                    if last_assistant is not None:
                        answered = {m.get("tool_call_id") for m in self.history[last_assistant + 1:]
                                    if m["role"] == "tool"}
                        for call in self.history[last_assistant].get("tool_calls", []):
                            if call["id"] not in answered:
                                self._append_tool_result(self.history, call, {"error": str(error), "submitted": False})
                    self.stop_reason = "investigation_budget_exhausted"
                    break
            self._record("final_handoff", reason=self.stop_reason, draft_version=len(self.drafts),
                         worker_task_ids=sorted(self.findings))
            assembly = ("Review the saved working draft against the source and validated worker findings. " if self.drafts else
                        "No intermediate draft was saved. Assemble the first complete answer from the full source "
                        "and both validated worker results already returned in this conversation. "
                        "Worker proposals are not independently verified source facts. ")
            self.history.append({"role": "user", "content": (
                "Investigation has ended. Return the complete plan_data and plan_issues answer using the supplied "
                "C schema. " + assembly + "Check source support and issue consistency; retain unresolved source concerns."
            )})
            request, tokens = self._prepare("coordinator", self.history, schema=self.response_schema, final=True)
            result = await self._send("coordinator", request, tokens, reservation="coordinator_final", phase="final")
            answer = _json_object((result.response_text or "").encode("utf-8"))
            self._save_draft(answer, len(self.drafts))
            return self._outcome("succeeded", answer=answer)
        except asyncio.CancelledError as error:
            self._record("cancelled")
            raise CollaborationCancelled(self._outcome("failed", error=f"{type(error).__name__}: cancelled")) from error
        except Exception as error:
            self._record("failed", error=f"{type(error).__name__}: {error}")
            return self._outcome("failed", error=f"{type(error).__name__}: {error}")

    def _outcome(self, status, *, answer=None, error=None):
        budget = self.budget.report()
        if status == "succeeded" and budget["elapsed_seconds"] > budget["limits"]["max_elapsed_seconds"]:
            status, answer = "failed", None
            error = "Total elapsed-time ceiling exceeded before final acceptance."
            self.stop_reason = "elapsed_limit_exceeded"
            self._record("failed", error=error)
        return CollaborationResult(status, deepcopy(answer), error, deepcopy(self.events),
                                   deepcopy(self.calls), deepcopy(self.tasks), deepcopy(self.drafts),
                                   budget, self.stop_reason)


async def run_collaboration_prototype(
    packet: CollaborationInput, *, model_client: ModelClient,
    document_tools: list[dict] | None = None, document_client: DocumentClient | None = None,
    document_source_fingerprint: str | None = None, clock=time.monotonic,
    on_progress=None,
    started_monotonic=None,
) -> CollaborationResult:
    """Run explicit injected clients; no implicit paid client or filesystem writes.

    The document client must be bound to packet.source_fingerprint. Production
    MCP lifecycle, recording, citation corrections, and CLI controls belong to
    collaboration_runner. Optional synchronous checkpoints run before external
    work; a checkpoint failure prevents further requests.
    """
    controller = _Controller(packet, model_client, document_tools or [], document_client,
                             document_source_fingerprint, clock, on_progress, started_monotonic)
    return await controller.run()
