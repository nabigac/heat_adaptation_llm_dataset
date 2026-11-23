"""Run a small live coordinator check with labelled, controlled workers.

Only the configured coordinator contacts Hugging Face: at most eight attempts,
16,384 output tokens per request, and 900 seconds overall. Worker replies and
document tools are local fixtures. Nothing is registered or saved as a study
run. Passing checks interfaces and this fictional case, not worker/model quality.
"""

import argparse
import asyncio
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from uuid import uuid4

import httpx

from agents import FINAL_READY_SIGNAL, _code_snapshot, _format_plan_source
from collaboration import CollaborationCancelled, run_collaboration_prototype
from collaboration_contracts import CollaborationInput, DEFAULT_COLLABORATION_PROFILE, load_collaboration_configuration
from huggingface_api import estimate_huggingface_budget, request_huggingface_chat, require_huggingface_token
from models import ModelCallResult, ModelRequestCancelled, _json_object
from quotation_diagnostics import diagnose_quotation_pages
from storage import resolve_project_path


MAX_COORDINATOR_REQUESTS = 8
# Reasoning shares this allowance; 4,096 tokens truncated the first live check.
OUTPUT_LIMIT = 16384
REQUEST_TIMEOUT = 300
ELAPSED_LIMIT = 900
SOURCE_METADATA = {"source_url": "https://example.org/fictional-c-plan.pdf", "date_accessed": "2026-01-01"}
TREE_QUOTE = "To reduce heat exposure, the council plans to plant 100 trees in North Ward in 2027."
FOUNTAIN_QUOTE = "The council also plans to install three drinking fountains in Central Square in 2027."
BUDGET_QUOTE = (
    "The tree planting programme has an estimated budget of EUR 50,000.\n"
    "Table A lists the same tree planting programme budget as EUR 60,000.\n"
    "No explanation for the difference is supplied."
)
PAGE_TEXTS = [
    "Example City Heat Action Plan, 2026.\nJurisdiction: Example City. Country: Example Country.\n"
    "This city heat-specific plan is led by the Example City Council.\n" + TREE_QUOTE + "\n" + FOUNTAIN_QUOTE,
    "Budget clarification for heat adaptation:\n" + BUDGET_QUOTE,
]
DIAGNOSTIC_INSTRUCTIONS = (
    "This is a fictional coordination diagnostic with controlled worker fixtures, not live worker inference. "
    "Start by assigning both workers independent tasks in one assign_tasks batch: ask the first assignment "
    "for activity proposals and the second for source checks. Either worker may take either assignment. "
    "The first task returns a proposal card; the second returns a check card. These fixtures may contain "
    "mistakes or uncertainty. Reconcile them against the whole supplied source. Later tasks repeat the cards "
    "rather than supplying new observations. Use the activity labels tree planting and drinking fountain "
    "installation in your descriptions. Preserve source quantities and conflicting statements without guessing. "
    "Save a complete working draft, finish investigation, and return the complete C answer when requested."
)
DOCUMENT_TOOLS = [{"type": "function", "function": {
    "name": name, "description": description,
    "parameters": {"type": "object", "required": [field], "additionalProperties": False,
                   "properties": {field: definition}},
}} for name, description, field, definition in (
    ("get_page_text", "Read one physical page of the fictional source.", "page_number", {"type": "integer", "minimum": 1}),
    ("find_quote", "Find an exact passage in the fictional source.", "quote", {"type": "string", "minLength": 1}),
)]


def _json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n"


def _utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_diagnostic_input(project_root: Path, profile_name: str = DEFAULT_COLLABORATION_PROFILE):
    """Detach and cap settings, using no registered PDFs, runs, or expert data."""
    configuration, profiles = load_collaboration_configuration(project_root, profile_name)
    original = {"configuration": deepcopy(configuration), "profiles": deepcopy(profiles)}
    for profile in profiles.values():
        profile["generation"]["max_output_tokens"] = min(OUTPUT_LIMIT, profile["generation"]["max_output_tokens"])
        profile["model_timeout_seconds"] = min(REQUEST_TIMEOUT, profile["model_timeout_seconds"])
    # Shared logical request/token limits come from the C binding. Paid
    # coordinator attempts have a separate diagnostic guard below.
    configuration["limits"]["max_elapsed_seconds"] = min(ELAPSED_LIMIT, configuration["limits"]["max_elapsed_seconds"])
    configuration["limits"]["final_generation_seconds"] = min(
        configuration["limits"].get("final_generation_seconds", profiles["coordinator"]["model_timeout_seconds"]),
        profiles["coordinator"]["model_timeout_seconds"],
    )
    pages = [{"page_number": index, "text": text, "text_source": "fictional", "readable": True,
              "image_available": False, "image_regions": [], "problem": None}
             for index, text in enumerate(PAGE_TEXTS, start=1)]
    synthetic_preparation = {**SOURCE_METADATA, "page_count": 2, "status": "ready", "problem": None,
                             "settings": {"image_render_dpi": 150}}
    source = "FICTIONAL DIAGNOSTIC INPUT; no PDF was registered or prepared.\n\n" + _format_plan_source(synthetic_preparation, pages)
    fingerprint = hashlib.sha256(_json({"metadata": SOURCE_METADATA, "pages": pages}).encode()).hexdigest()
    packet = CollaborationInput("fictional_coordination_check", "diagnostic/fictional_source.json",
        fingerprint, 2, {"role": "user", "content": source}, deepcopy(SOURCE_METADATA), configuration, profiles)
    # These are diagnostic-specific controller instructions, saved separately
    # from the unchanged coordinator prompt and never presented as source text.
    packet.profiles["coordinator"]["prompt_texts"] += [DIAGNOSTIC_INSTRUCTIONS]
    packet.profiles["coordinator"]["prompt_paths"] += ["diagnostic/coordination_instructions"]
    return packet, pages, original


def controlled_findings(task: dict) -> dict:
    """Return a fixed card by task order, not by a permanent worker specialty."""
    def finding(description, change, quote, page, unresolved=False):
        return {"description": description, "related_action_id": None, "proposed_change": change,
                "evidence": [{"quote": quote, "page_numbers": [page]}], "unresolved": unresolved}
    proposal = int(task["task_id"].rsplit("_", 1)[1]) % 2 == 1
    if proposal:
        findings = [
            finding("The source proposes 100 trees in North Ward in 2027.", "Add tree planting.", TREE_QUOTE, 1),
            finding("The proposal is for four drinking fountains in Central Square in 2027.",
                    "Add four drinking fountains.", FOUNTAIN_QUOTE, 1),
        ]
        checked_pages = [1]
    else:
        findings = [
            finding("The source says three fountains, contradicting the four-fountain proposal.",
                    "Use three drinking fountains, not four.", FOUNTAIN_QUOTE, 1),
            finding("Two incompatible budgets are stated for the same tree planting programme; the source does not reconcile them.",
                    "Retain both EUR 50,000 and EUR 60,000 as conflicting statements with an open issue.",
                    BUDGET_QUOTE, 2, True),
        ]
        checked_pages = [1, 2]
    return {**{key: task[key] for key in ("task_id", "worker_id", "draft_version")},
            "checked_pages": checked_pages, "findings": findings}


def _controlled_result(request) -> ModelCallResult:
    context = next(_json_object(message["content"].split("\n", 1)[1].encode())
                   for message in request.body["messages"]
                   if message["content"].startswith("ASSIGNMENT AND CHECKABLE DATA:\n"))
    content = _json(controlled_findings(context["task"])) if "response_format" in request.body else FINAL_READY_SIGNAL
    message = {"role": "assistant", "content": content}
    raw = _json({"execution_kind": "controlled_worker", "message": message}).encode()
    return ModelCallResult(
        raw_response=raw, response_text=content, assistant_message=message,
        input_tokens=None, output_tokens=None, finish_reason="stop", truncated=False,
        completion_status="normal", elapsed_seconds=0.0, status_code=None,
        provider_timings_ns={}, error=None, token_budget=estimate_huggingface_budget(request),
        generation_started=False,
    )


async def _fictional_document(actor, name, arguments):
    if name == "get_page_text":
        page = arguments["page_number"]
        return {"page_number": page, "text": PAGE_TEXTS[page - 1], "text_source": "fictional"}
    quote = arguments["quote"]
    return {"matches": [{"page_number": index, "text": text}
                         for index, text in enumerate(PAGE_TEXTS, 1) if quote in text]}


class _Recorder:
    """Save every logical request before dispatch; HTTP callbacks retain chunks."""
    def __init__(self, folder, report):
        self.folder, self.report = folder, report

    def new_bytes(self, name, value):
        path = self.folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as destination:
            destination.write(value)

    def new_json(self, name, value):
        self.new_bytes(name, _json(value).encode())

    def checkpoint(self):
        temporary = self.folder / ".report.json.tmp"
        with temporary.open("x", encoding="utf-8") as destination:
            destination.write(_json(self.report))
        os.replace(temporary, self.folder / "report.json")

    def begin(self, actor, request):
        number = len(self.report["calls"]) + 1
        stem = f"calls/call_{number:03d}"
        record = {"actor": actor, "execution_kind": "coordinator_http" if actor == "coordinator" else "controlled_worker",
                  "request_path": stem + "/request.json", "response_path": None,
                  "http_status_code": None, "http_attempted": False, "generation_started": None,
                  "input_tokens": None, "output_tokens": None, "error": None}
        self.new_json(record["request_path"], {"url": request.url, "body": request.body,
                      "timeout_seconds": request.timeout_seconds, "context_limit": request.context_limit,
                      "max_output_tokens": request.max_output_tokens, "execution_kind": record["execution_kind"]})
        self.report["calls"].append(record)
        self.checkpoint()
        return stem, record

    def complete(self, stem, record, result):
        name = stem + "/response.json"
        self.new_bytes(name, result.raw_response)
        record.update(response_path=name, http_status_code=result.status_code,
                      input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                      completion_status=result.completion_status, finish_reason=result.finish_reason,
                      generation_started=result.generation_started, elapsed_seconds=result.elapsed_seconds,
                      error=result.error)
        self.checkpoint()


def diagnostic_checks(outcome, pages):
    """Small fixture assertions; these are not the study's quality scores."""
    checks = []
    def add(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
    add("controller_completed", outcome.status == "succeeded", outcome.error)
    completed = {event["worker_id"] for event in outcome.events if event["event"] == "task_completed"}
    add("both_controlled_workers", completed == {"worker_1", "worker_2"}, sorted(completed))
    batches = [call["function"]["arguments"]["assignments"] for event in outcome.model_calls
               if event["actor"] == "coordinator" and event["result"]
               for call in event["result"].tool_calls if call["function"]["name"] == "assign_tasks"]
    add("batched_delegation", any({item["worker_id"] for item in batch} == {"worker_1", "worker_2"}
                                 for batch in batches), "Both workers assigned in one batch.")
    if outcome.answer is None:
        return checks
    actions = outcome.answer["plan_data"]["actions"]
    trees = [item for item in actions if "tree" in item["action"].lower()]
    fountains = [item for item in actions if "fountain" in item["action"].lower()]
    add("two_distinct_activities", len(actions) == 2 and len(trees) == len(fountains) == 1,
        "One tree-planting and one drinking-fountain activity.")
    if len(fountains) == 1:
        text = fountains[0]["action"].lower()
        add("incorrect_worker_count_corrected", re.search(r"\b(three|3)\b", text) and not re.search(r"\b(four|4)\b", text),
            "Source says three fountains; the proposal card deliberately says four.")
    if len(trees) == 1:
        tree = trees[0]
        cost = re.sub(r"[\s,]", "", tree["action_cost"] or "")
        open_issue = any(issue["related_action_id"] == tree["action_id"] and issue["issue_status"] == "open"
                         for issue in outcome.answer["plan_issues"]["issues"])
        add("source_budget_conflict_retained", "50000" in cost and "60000" in cost and open_issue,
            "Both incompatible EUR budgets retained with an open tree-planting issue.")
    quotations = diagnose_quotation_pages(outcome.answer["plan_data"], pages)
    add("quotation_pages_match", quotations["summary"]["checked"] >= 2
        and quotations["summary"]["matched"] == quotations["summary"]["checked"], quotations["summary"])
    return checks


class CoordinationCheckCancelled(asyncio.CancelledError):
    def __init__(self, report_path):
        self.report_path = report_path
        super().__init__("Coordination check cancelled; available evidence saved.")


async def run_coordination_check(project_root: Path, profile_name: str = DEFAULT_COLLABORATION_PROFILE, *,
                                 _transport: httpx.AsyncBaseTransport | None = None):
    """Save a capped coordinator-only diagnostic without reading study inputs."""
    root = Path(project_root).resolve()
    packet, pages, original = build_diagnostic_input(root, profile_name)
    require_huggingface_token()
    snapshot = _code_snapshot()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:8]
    folder = resolve_project_path(root, f"artifacts/collaboration_checks/{stamp}")
    folder.mkdir(parents=True, exist_ok=False)
    report = {"mode": "coordinator_controlled_workers", "status": "running", "passed": False,
              "coordinator_execution": "mock_transport" if _transport is not None else "live_huggingface",
              "profile": profile_name, "coordinator_model": packet.profiles["coordinator"]["model"],
              "started_at": _utc_now(), "ended_at": None, "calls": [], "checks": [],
              "coordinator_http_attempts": 0, "max_coordinator_http_attempts": MAX_COORDINATOR_REQUESTS,
              "output_limit_per_request": packet.profiles["coordinator"]["generation"]["max_output_tokens"],
              "controlled_workers": True, "error": None}
    recorder = _Recorder(folder, report)
    recorder.checkpoint()
    recorder.new_bytes("diagnostic_instructions.md", DIAGNOSTIC_INSTRUCTIONS.encode())
    packet.profiles["coordinator"]["prompt_paths"][-1] = (
        folder.relative_to(root) / "diagnostic_instructions.md"
    ).as_posix()
    recorder.new_json("fictional_source.json", {"metadata": SOURCE_METADATA, "pages": pages,
                                               "source_fingerprint": packet.source_fingerprint})
    packet = replace(packet, source_path=(folder.relative_to(root) / "fictional_source.json").as_posix())
    recorder.new_json("input.json", {"packet": asdict(packet), "pages": pages, "base_settings": original})
    for name, raw in snapshot.items():
        recorder.new_bytes("code/" + name, raw)
    recorder.new_json("code_fingerprints.json", {"sha256": {name: hashlib.sha256(raw).hexdigest()
                                                           for name, raw in snapshot.items()}})
    print(f"Checking coordinator {packet.profiles['coordinator']['model']['name']} with controlled workers...", flush=True)

    async def model_client(request):
        actor = next(key for key, profile in packet.profiles.items()
                     if profile["model"]["name"].casefold() == request.model_name.casefold())
        stem, record = recorder.begin(actor, request)
        if actor != "coordinator":
            result = _controlled_result(request)
            recorder.complete(stem, record, result)
            return result
        if report["coordinator_http_attempts"] >= MAX_COORDINATOR_REQUESTS:
            record.update(execution_kind="blocked_coordinator_request", generation_started=False,
                          error="Diagnostic coordinator-request ceiling reached; no HTTP request started.")
            recorder.checkpoint()
            raise ValueError(record["error"])
        report["coordinator_http_attempts"] += 1
        record["http_attempted"] = True
        recorder.checkpoint()
        print(f"Coordinator request {report['coordinator_http_attempts']}/{MAX_COORDINATOR_REQUESTS}...", flush=True)
        partial = stem + "/response.partial"
        recorder.new_bytes(partial, b"")
        def progress(event, value):
            if event == "preflight_complete":
                recorder.new_json(stem + "/token_budget.json", value.report)
            elif event == "response_headers":
                record["http_status_code"] = value
                recorder.checkpoint()
            elif event == "response_chunk":
                with (folder / partial).open("ab") as destination:
                    destination.write(value)
        try:
            result = await request_huggingface_chat(request, _transport=_transport, on_progress=progress)
        except ModelRequestCancelled as error:
            recorder.complete(stem, record, error.result)
            raise
        recorder.complete(stem, record, result)
        return result

    cancelled = False
    try:
        outcome = await run_collaboration_prototype(packet, model_client=model_client,
            document_tools=DOCUMENT_TOOLS, document_client=_fictional_document,
            document_source_fingerprint=packet.source_fingerprint)
    except CollaborationCancelled as error:
        outcome, cancelled = error.result, True
    recorder.new_json("controller_result.json", {
        "status": outcome.status, "answer": outcome.answer, "error": outcome.error,
        "events": outcome.events, "tasks": outcome.tasks, "drafts": outcome.drafts,
        "budget": outcome.budget, "stop_reason": outcome.stop_reason,
    })
    report["checks"] = diagnostic_checks(outcome, pages)
    report["checks"].append({"name": "code_unchanged", "passed": _code_snapshot() == snapshot,
                             "detail": "Application code/contracts/lockfiles remained unchanged."})
    report["passed"] = not cancelled and all(check["passed"] for check in report["checks"])
    attempted = [call for call in report["calls"] if call["http_attempted"]]
    report["coordinator_reported_usage"] = {
        key: None if any(call[key] is None for call in attempted) else sum(call[key] for call in attempted)
        for key in ("input_tokens", "output_tokens")
    }
    report["controlled_worker_steps"] = sum(call["execution_kind"] == "controlled_worker" for call in report["calls"])
    report["controller_budget"] = outcome.budget
    report.update(status="cancelled" if cancelled else "passed" if report["passed"] else "failed",
                  error=outcome.error or (None if report["passed"] else "One or more diagnostic checks failed."),
                  ended_at=_utc_now())
    recorder.checkpoint()
    if cancelled:
        raise CoordinationCheckCancelled(folder / "report.json")
    return folder / "report.json", report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_COLLABORATION_PROFILE, help="Named C binding.")
    args = parser.parse_args()
    try:
        path, report = asyncio.run(run_coordination_check(Path.cwd(), args.profile))
    except CoordinationCheckCancelled as error:
        parser.exit(130, f"Coordination check cancelled. Report: {error.report_path}\n")
    except (KeyboardInterrupt, asyncio.CancelledError):
        parser.exit(130, "Coordination check cancelled; inspect artifacts/collaboration_checks/.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Coordination check failed: {error}\n")
    print(f"Status: {report['status']}")
    for check in report["checks"]:
        print(f"{check['name']}: {'passed' if check['passed'] else 'failed'}")
    if report.get("error"):
        print(f"Error: {report['error']}")
    print(f"Report: {path}")
    print("Workers were controlled fixtures. No study plan or live worker inference was launched; full-plan collaboration quality remains untested.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
