"""Connect the C controller to live HF/MCP clients and durable run evidence.

Read run_collaboration() first. The recorder publishes requests before dispatch
and HTTP chunks as they arrive. Its synchronous checkpoints give parallel
workers one writer; no lock or second persistence service is needed.
"""

import asyncio
from contextlib import AsyncExitStack
from copy import deepcopy
from dataclasses import asdict, dataclass, replace
import hashlib
from pathlib import Path, PurePosixPath
import time
from types import SimpleNamespace

import agents
from collaboration import CollaborationCancelled, CollaborationResult, run_collaboration_prototype
from collaboration_contracts import DEFAULT_COLLABORATION_PROFILE, build_collaboration_input, validate_collaboration_response
import collaboration_storage as saved_storage
from huggingface_api import request_huggingface_chat, require_huggingface_token
from models import ModelRequestCancelled, prepare_document_tools
from quotation_diagnostics import QUOTATION_PAGE_REPORT_PATH, correct_quotation_pages
import storage


@dataclass
class SavedCollaborationRun:
    """Return the last published status, even if execution or final saving failed."""

    record_path: str
    record: dict
    execution: CollaborationResult | None
    persistence_error: str | None = None
    quotation_diagnostics: dict | None = None
    validation_report: dict | None = None


class SavedCollaborationCancelled(asyncio.CancelledError):
    def __init__(self, result):
        self.result = result
        super().__init__("Collaboration cancelled; available saved evidence is attached.")


class _Recorder:
    def __init__(self, root, record):
        self.root, self.record = root, deepcopy(record)
        self.path = saved_storage.create_collaboration_record(root, self.record)
        self.folder = str(PurePosixPath(self.path).parent)
        self.last_saved = deepcopy(record)
        self.written, self.request_numbers, self.chunks = {}, {}, {}
        self.first_error = None
        self.execution_error = None

    def guard(self):
        if self.first_error:
            raise OSError("C evidence saving failed; no further work is permitted: " + self.first_error)
        if self.execution_error:
            raise ValueError("C document transport failed; no further work is permitted: " + self.execution_error)

    def file(self, name, raw):
        if name in self.written:
            if raw != self.written[name]:
                raise ValueError("Refusing to change preserved C evidence: " + name)
            return f"{self.folder}/{name}"
        try:
            path = saved_storage.save_collaboration_file(self.root, self.path, name, raw)
        except Exception as error:
            self.first_error = self.first_error or agents._failure_description(error)
            # Publication can precede an OS error; recognize identical surviving
            # bytes during failure handling without overwriting them.
            target = storage.resolve_project_path(self.root, f"{self.folder}/{name}")
            if target.is_file() and target.read_bytes() == raw:
                self.written[name] = raw
            raise
        self.written[name] = raw
        return path

    def json(self, name, data):
        return self.file(name, storage._serialize_run_json(data).encode())

    def active(self):
        try:
            saved_storage.save_collaboration_record(self.root, self.record)
        except Exception as error:
            self.first_error = self.first_error or agents._failure_description(error)
            raise
        self.last_saved = deepcopy(self.record)

    def progress(self, event, controller):
        self.guard()
        if event["event"] == "model_request":
            number = len(controller.calls)
            call = controller.calls[-1]
            request = call["request"]
            path = self.json(f"responses/attempt_{number:04d}/request.json", {
                "url": request.url, "body": request.body, "timeout_seconds": request.timeout_seconds,
                "context_limit": request.context_limit, "max_output_tokens": request.max_output_tokens,
            })
            self.request_numbers[id(request)] = number
            self.record["model_calls"].append({
                "actor": call["actor"], "task_id": call["task_id"], "phase": call["phase"],
                "request_path": path, "response_path": None, "input_tokens": None, "output_tokens": None,
                "finish_reason": None, "truncated": None, "http_status_code": None,
                "generation_started": None, "completion_status": None, "elapsed_seconds": None, "error": None,
            })
        self.json(f"artifacts/events/event_{len(controller.events):04d}.json", event)
        self.record["budget"] = controller.budget.report()
        self.record["stop_reason"] = controller.stop_reason
        self.active()

    def http_progress(self, number, event, payload):
        self.guard()
        stem = f"responses/attempt_{number:04d}"
        if event == "preflight_complete":
            self.json(stem + "/token_budget.json", payload.report)
        elif event == "response_headers":
            self.record["model_calls"][number - 1]["http_status_code"] = payload
            self.json(stem + "/http_status.json", {"http_status_code": payload})
        elif event == "response_chunk":
            chunk = self.chunks.get(number, 0) + 1
            self.file(f"{stem}/chunks/{chunk:06d}.bin", payload)
            self.chunks[number] = chunk
        self.active()

    def model_result(self, number, result):
        row = self.record["model_calls"][number - 1]
        row.update({key: getattr(result, key) for key in (
            "input_tokens", "output_tokens", "finish_reason", "truncated", "generation_started",
            "completion_status", "elapsed_seconds", "error",
        )})
        row["http_status_code"] = result.status_code
        row["response_path"] = self.file(f"responses/attempt_{number:04d}/response.json", result.raw_response)
        if result.response_text is not None:
            self.file(f"responses/attempt_{number:04d}/answer.txt", result.response_text.encode())
        self.active()


def _check_source(root, packet):
    _, preparation, pages = storage.load_plan_preparation(root, packet.plan_id, packet.source_path)
    if storage.preparation_text_fingerprint(preparation, pages) != packet.source_fingerprint:
        raise ValueError("The selected preparation changed during collaboration.")
    return preparation, pages


def _finish_answer(recorder, packet, outcome, pages, tools):
    """Keep strict C acceptance and citation correction separate from model text.

    Unmatched wording remains a review flag, as in E/V. Python never replaces a
    quotation with a draft excerpt or silently repairs its words.
    """
    finals = [(i, row) for i, row in enumerate(recorder.record["model_calls"], 1) if row["phase"] == "final"]
    if not finals:
        return None, None, None
    number, row = finals[-1]
    text_path = f"{recorder.folder}/responses/attempt_{number:04d}/answer.txt"
    raw_path = text_path if storage.resolve_project_path(recorder.root, text_path).is_file() else row["response_path"]
    if raw_path is None:
        return None, None, None
    report = {"raw_response_path": raw_path, "repaired_response_path": None,
              "initial_errors": [], "remaining_errors": [], "repairs": [], "valid": False}
    answer = diagnostic = None
    if outcome.status == "succeeded":
        answer = deepcopy(outcome.answer)
        answer["plan_data"], diagnostic = correct_quotation_pages(answer["plan_data"], pages, tool_log=tools)
        diagnostic.update(source_path=packet.source_path, source_fingerprint=packet.source_fingerprint)
        recorder.json(QUOTATION_PAGE_REPORT_PATH, diagnostic)
        if diagnostic["repairs"]:
            report["repaired_response_path"] = recorder.json("responses/page_corrected_final.json", answer)
            report["repairs"] = [{"rule": change["rule"], "location": change["location"],
                                  "before": str(change["before"]), "after": str(change["after"])}
                                 for change in diagnostic["repairs"]]
        validate_collaboration_response(answer, page_count=packet.page_count, source_metadata=packet.source_metadata)
        report["valid"] = True
    else:
        problem = {"category": "other", "location": "$", "message": outcome.error or "C did not complete."}
        report["initial_errors"] = report["remaining_errors"] = [problem]
    recorder.json("validation_report.json", report)
    return answer, diagnostic, report


async def run_collaboration(
    project_root: Path | str, plan_id: str, *, source_path: str,
    profile_name: str = DEFAULT_COLLABORATION_PROFILE, purpose: str = "development", retry_of_run_id: str | None = None,
    config_path: str = "configs/collaboration.json", model_config_path: str = "configs/profiles.json",
    _transport=None,
) -> SavedCollaborationRun:
    """Run one new development attempt; never import E/V or expert answers."""
    started, started_at = time.monotonic(), agents._utc_now()
    root = Path(project_root).resolve()
    if purpose != "development":
        raise ValueError("Saved C pilots currently allow development purpose only.")
    packet = build_collaboration_input(root, plan_id, source_path=source_path, profile_name=profile_name,
                                       config_path=config_path, model_config_path=model_config_path)
    require_huggingface_token()  # Authenticate before allocating any run files.
    preparation, pages = _check_source(root, packet)
    if retry_of_run_id is not None:
        storage._require_run_identifier(retry_of_run_id)
        previous = saved_storage.load_collaboration_record(root, f"runs/{plan_id}/{retry_of_run_id}/output.json")
        if (previous["status"] != "failed" or previous["source_path"] != source_path
                or previous["purpose"] != purpose):
            raise ValueError("Retry links require a failed C attempt for the same source and purpose.")
    bridge = SimpleNamespace(plan_id=plan_id, source_path=source_path,
                             source_fingerprint=packet.source_fingerprint, settings=packet.profiles["coordinator"])
    environment = agents._execution_environment(bridge, preparation)
    snapshot = agents._code_snapshot()
    record = {
        "schema_version": 1, "plan_id": plan_id, "run_id": storage.next_run_id(root, plan_id, "collaboration"),
        "stage": "collaboration", "purpose": purpose, "retry_of_run_id": retry_of_run_id,
        "source_path": source_path, "source_fingerprint": packet.source_fingerprint,
        "status": "running", "started_at": started_at, "ended_at": None, "elapsed_seconds": None,
        "settings": {"configuration": packet.configuration, "profiles": packet.profiles,
                     "document_tools": packet.profiles["coordinator"]["document_tools"], "environment": environment},
        "model_calls": [], "tool_log_path": None, "budget": None, "stop_reason": None,
        "plan_data": None, "plan_issues": None, "error": None,
    }
    recorder = _Recorder(root, record)
    outcome = cancellation = failure = answer = diagnostic = report = None
    tool_log = []

    async def model_client(request):
        recorder.guard()
        number = recorder.request_numbers[id(request)]
        try:
            result = await request_huggingface_chat(request, _transport=_transport,
                on_progress=lambda event, payload: recorder.http_progress(number, event, payload))
        except ModelRequestCancelled as error:
            recorder.model_result(number, error.result)
            raise
        recorder.model_result(number, result)
        return result

    try:
        recorder.json("artifacts/collaboration_input.json", {"packet": asdict(packet),
                                                            "preparation": preparation, "pages": pages})
        for name, raw in snapshot.items():
            recorder.file("artifacts/code/" + name, raw)
        recorder.json("artifacts/code_fingerprints.json", {
            "sha256": {name: hashlib.sha256(raw).hexdigest() for name, raw in snapshot.items()},
        })
        timeout = packet.profiles["coordinator"]["document_tools"]["tool_timeout_seconds"]
        async with AsyncExitStack() as cleanup:
            client = await agents._bounded_mcp_request(cleanup.enter_async_context(
                agents._document_client(root, bridge, run_record_path=recorder.path)), timeout)
            catalogue = await agents._bounded_mcp_request(client.list_tools(), timeout)
            if catalogue.next_cursor:
                raise ValueError("Unexpected paginated document-tool catalogue.")
            descriptions = [tool.model_dump(mode="json", by_alias=True) for tool in catalogue.tools]
            expected = {"get_page_text", "find_quote"}
            if bridge.settings["document_tools"]["ocr_enabled"]:
                expected.add("run_ocr")
            if {tool["name"] for tool in descriptions} != expected or len(descriptions) != len(expected):
                raise ValueError("C requires the supported source-bound document tools.")
            recorder.json("artifacts/mcp_catalogue.json", descriptions)

            async def document_client(actor, name, arguments):
                recorder.guard()
                # A request file precedes the await, so parallel tools receive
                # distinct stable indices even if their replies arrive reversed.
                index = len(tool_log) + 1
                entry = {"actor": actor, "tool": name, "arguments": deepcopy(arguments),
                         "result": None, "elapsed_seconds": None, "error": None}
                tool_log.append(entry)
                recorder.json(f"artifacts/tool_requests/tool_{index:04d}.json", entry)
                began = time.monotonic()
                try:
                    reply = await agents._bounded_mcp_request(client.call_tool(name, arguments), timeout)
                    entry["result"] = reply.model_dump(mode="json", by_alias=True)
                    if any(block.type != "text" for block in reply.content):
                        raise ValueError("C supports text document results only.")
                    if reply.is_error:
                        entry["error"] = " ".join(block.text for block in reply.content) or "Document tool failed."
                    payload = {"is_error": reply.is_error}
                    if reply.structured_content is not None:
                        payload["result"] = reply.structured_content
                    else:
                        payload["messages"] = [block.text for block in reply.content]
                    return payload
                except agents.MCPRequestTimeout as error:
                    if error.result is not None:
                        entry["result"] = error.result.model_dump(mode="json", by_alias=True)
                    entry["error"] = agents._failure_description(error)
                    # The controller records the fatal timeout and stops new work.
                    # Keep its progress recorder usable to preserve that evidence.
                    raise
                except BaseException as error:
                    entry["error"] = agents._failure_description(error)
                    if not isinstance(error, asyncio.CancelledError):
                        # Ordinary source/OCR problems arrive as is_error replies.
                        # RPC exceptions include unsaved OCR evidence and must
                        # stop the run rather than become recoverable findings.
                        recorder.execution_error = entry["error"]
                    raise
                finally:
                    entry["elapsed_seconds"] = time.monotonic() - began
                    recorder.json(f"artifacts/tool_results/tool_{index:04d}.json", entry)

            try:
                outcome = await run_collaboration_prototype(packet, model_client=model_client,
                    document_tools=prepare_document_tools(descriptions), document_client=document_client,
                    document_source_fingerprint=packet.source_fingerprint, on_progress=recorder.progress,
                    started_monotonic=started)
            except CollaborationCancelled as error:
                outcome, cancellation = error.result, error
            _check_source(root, packet)
        # Stop the MCP subprocess before citation processing or publication.
        recorder.guard()
        if outcome is not None:
            answer, diagnostic, report = _finish_answer(recorder, packet, outcome, pages, tool_log)
    except asyncio.CancelledError as error:
        cancellation, failure = error, "Collaboration was cancelled."
    except Exception as error:
        failure = agents._failure_description(error)

    # Preserve all surviving evidence; this block never starts another request.
    try:
        if tool_log:
            recorder.record["tool_log_path"] = saved_storage.save_tool_log(root, recorder.path, tool_log)
        if outcome is not None:
            recorder.json("artifacts/controller_result.json", {
                "status": outcome.status, "answer": outcome.answer, "error": outcome.error,
                "events": outcome.events, "tasks": outcome.tasks, "drafts": outcome.drafts,
                "budget": outcome.budget, "stop_reason": outcome.stop_reason,
            })
            recorder.record.update(budget=outcome.budget, stop_reason=outcome.stop_reason)
        _check_source(root, packet)
        if agents._code_snapshot() != snapshot:
            raise ValueError("Application code or schemas changed during collaboration.")
        if time.monotonic() - started > packet.configuration["limits"]["max_elapsed_seconds"]:
            raise ValueError("The whole collaboration run exceeded its elapsed-time limit.")
    except Exception as error:
        failure = failure or agents._failure_description(error)
    if outcome is not None and report is None:
        try:
            observed = outcome
            if failure or cancellation or recorder.first_error:
                observed = replace(outcome, status="failed", answer=None,
                                   error=failure or recorder.first_error or "Collaboration was cancelled.")
            answer, diagnostic, report = _finish_answer(recorder, packet, observed, pages, tool_log)
        except Exception as error:
            failure = failure or agents._failure_description(error)
    failure = failure or (outcome.error if outcome else None) or recorder.first_error
    success = outcome is not None and outcome.status == "succeeded" and answer is not None and not failure and not cancellation
    recorder.record.update(status="succeeded" if success else "failed", ended_at=agents._utc_now(),
                           elapsed_seconds=time.monotonic() - started,
                           error=None if success else failure or "Collaboration did not complete.")
    if success:
        recorder.record.update(plan_data=answer["plan_data"], plan_issues=answer["plan_issues"])
    try:
        # Validate all preserved inputs/files before publishing accepted content.
        if success:
            saved_storage.validate_record(recorder.record)
        recorder.active()
    except Exception as error:
        recorder.first_error = recorder.first_error or agents._failure_description(error)
    saved = SavedCollaborationRun(recorder.path, recorder.last_saved, outcome,
                                  recorder.first_error, diagnostic, report)
    if cancellation is not None:
        raise SavedCollaborationCancelled(saved) from cancellation
    return saved
