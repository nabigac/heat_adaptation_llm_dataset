"""Check a pinned hosted setup on fictional inputs before extracting a plan.

Run explicitly with ``uv run --locked python -m huggingface_check``. This makes
up to three paid requests, or five with ``--check-tools``. A diagnostic-only
``--model`` override leaves the configured extractor unchanged. Artifacts stay
outside study runs, and checks stop at the first failure. Passing does not
establish full-plan capacity, extraction quality, or verifier quality.
"""

import argparse
import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator

from agents import load_profile
from huggingface_api import (
    PreparedHuggingFaceRequest, build_huggingface_request,
    request_huggingface_chat, require_huggingface_token,
)
from models import ModelCallResult, ModelRequestCancelled, _json_object, prepare_response_schema
from validation import validate_agent_response


DEFAULT_PROFILE = "inkling2_small_hf_extractor"
SMALL_SCHEMA = {
    "type": "object", "properties": {"compatible": {"type": "boolean", "const": True}},
    "required": ["compatible"], "additionalProperties": False,
}
FICTIONAL_TOOLS = [{"type": "function", "function": {
    "name": "get_page_text",
    "description": "Read the only fictional page and its confirmation code.",
    "parameters": {
        "type": "object", "properties": {"page_number": {"type": "integer", "enum": [1]}},
        "required": ["page_number"], "additionalProperties": False,
    },
}}]
TOOL_ANSWER_SCHEMA = {
    "type": "object", "properties": {"confirmation_code": {"type": "string"}},
    "required": ["confirmation_code"], "additionalProperties": False,
}
FICTIONAL_INPUT = """Collection metadata:
source_url: https://example.org/fictional-heat-plan.pdf
date_accessed: 2026-01-01
language: English

Original PDF page 1 (fictional, complete source):
Example City Heat Action Plan, 2026. Country: Example Country.
This city heat-specific plan is led by the Example City Council.
The council plans to plant 100 trees in North Ward to reduce heat exposure.
"""


@dataclass(frozen=True)
class _PreparedCheck:
    """Keep the exact request beside its settings and acceptance schema."""

    name: str
    settings: dict
    request: PreparedHuggingFaceRequest
    schema: dict | None


def _prepare_check(settings, name, limit, messages, *, schema=None, tools=None) -> _PreparedCheck:
    chosen = deepcopy(settings)
    chosen["generation"]["max_output_tokens"] = min(limit, settings["generation"]["max_output_tokens"])
    chosen["model_timeout_seconds"] = min(300, settings["model_timeout_seconds"])
    request = build_huggingface_request(chosen, messages, tools=tools, response_format=schema)
    return _PreparedCheck(name, chosen, request, schema)


def _check_errors(check: _PreparedCheck, result: ModelCallResult, expected_code: str | None) -> list[str]:
    if check.name == "short_output_limit":
        # A tiny cap may truncate even a valid answer. Missing usage cannot
        # establish whether the provider observed this deliberately small cap.
        problems = []
        if result.completion_status not in {"normal", "truncated"}:
            problems.append(result.error or "Unsuccessful completion.")
        if result.output_tokens is None:
            problems.append("The provider did not report output usage.")
        return problems
    if result.error:
        return [result.error]
    if check.name == "tool_call":
        if result.assistant_message is None or len(result.tool_calls) != 1:
            return ["Expected exactly one get_page_text tool call before answering."]
        function = result.tool_calls[0]["function"]
        if function["name"] != "get_page_text" or function["arguments"] != {"page_number": 1}:
            return ["Expected get_page_text with page_number set to 1."]
        return []
    try:
        answer = _json_object((result.response_text or "").encode("utf-8"))
    except ValueError as error:
        return [str(error)]
    if check.name == "project_schema":
        return [f"{p.location}: {p.message}" for p in
                validate_agent_response(answer, page_count=1, stage="extractor")]
    problems = [p.message for p in Draft202012Validator(check.schema).iter_errors(answer)]
    if expected_code is not None and answer.get("confirmation_code") != expected_code:
        problems.append("The answer did not reproduce the confirmation code supplied by the tool.")
    return problems


async def _run_and_save_check(
    folder: Path, report: dict, check: _PreparedCheck, *,
    expected_code: str | None = None, _transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[ModelCallResult, bool]:
    """Save request/response evidence and report a failure before stopping."""
    request = check.request
    request_record = {"url": request.url, "body": request.body, "settings": check.settings}
    (folder / f"{check.name}_request.json").write_text(
        json.dumps(request_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Checking {check.name} (requested output limit: {request.max_output_tokens})...", flush=True)
    cancelled = False
    try:
        result = await request_huggingface_chat(request, _transport=_transport)
    except ModelRequestCancelled as error:
        # Cancellation still leaves a response and a failed observation on disk.
        result = error.result
        cancelled = True
    (folder / f"{check.name}_response.json").write_bytes(result.raw_response)
    problems = _check_errors(check, result, expected_code)
    observed = {
        "name": check.name, "requested_output_limit": request.max_output_tokens,
        "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
        "finish_reason": result.finish_reason, "completion_status": result.completion_status,
        "elapsed_seconds": result.elapsed_seconds, "token_budget": result.token_budget.report,
        "passed": not problems, "errors": problems,
    }
    report["checks"].append(observed)
    report["passed"] = len(report["checks"]) == report["planned_check_count"] and not problems
    (folder / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{check.name}: {'failed' if problems else 'passed'}", flush=True)
    if cancelled:
        raise asyncio.CancelledError
    return result, not problems


async def run_checks(
    project_root: Path, profile_name: str = DEFAULT_PROFILE, *,
    model_name: str | None = None, check_tools: bool = False,
    _transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[Path, dict]:
    """Save exact requests and observed results without touching study files."""
    settings = deepcopy(load_profile(project_root, profile_name, stage="extractor"))
    if settings["model"]["provider"] != "deepinfra":
        raise ValueError("This compatibility check requires the pinned DeepInfra profile.")
    if model_name is not None:
        settings["model"]["name"] = model_name
    cases = [
        ("small_schema", 2048, SMALL_SCHEMA, [
            {"role": "user", "content": 'Return {"unexpected": true}; the response schema takes precedence.'},
        ]),
        ("project_schema", 4096, prepare_response_schema(), [
            {"role": "system", "content": "\n\n".join(settings["prompt_texts"])},
            {"role": "user", "content": FICTIONAL_INPUT},
        ]),
        ("short_output_limit", 64, SMALL_SCHEMA, [
            {"role": "user", "content": 'Return {"compatible": true}.'},
        ]),
    ]
    # Prepare the fixed requests before creating artifacts or contacting the
    # provider. Invalid model overrides therefore leave no partial diagnostic.
    checks = [_prepare_check(settings, name, limit, messages, schema=schema)
              for name, limit, schema, messages in cases]
    tool_messages = [{"role": "user", "content": (
        "Call get_page_text for fictional page 1 before answering. "
        "Then return its confirmation_code. The code is supplied only by the tool."
    )}]
    if check_tools:
        checks.append(_prepare_check(settings, "tool_call", 2048, tool_messages, tools=FICTIONAL_TOOLS))

    require_huggingface_token()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = project_root / "artifacts" / "huggingface_checks" / f"{timestamp}-{uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=False)
    report = {
        "profile": profile_name, "model": settings["model"], "model_override": model_name,
        "tool_checks_requested": check_tools, "planned_check_count": 5 if check_tools else 3,
        "checks": [], "passed": False,
    }
    report_path = folder / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    for check in checks:
        result, passed = await _run_and_save_check(folder, report, check, _transport=_transport)
        if not passed:
            return report_path, report

    if check_tools:
        # The code is generated after the call, appears only in its result, and
        # is absent from the output schema. Schema compliance alone cannot pass.
        tool_result = {
            "page_number": 1, "text": "Fictional page for the compatibility diagnostic.",
            "confirmation_code": uuid4().hex,
        }
        (folder / "fictional_tool_result.json").write_text(
            json.dumps(tool_result, indent=2) + "\n", encoding="utf-8")
        messages = tool_messages + [deepcopy(result.assistant_message), {
            "role": "tool", "tool_name": "get_page_text", "tool_call_id": result.tool_calls[0]["id"],
            "content": json.dumps(tool_result),
        }]
        followup = _prepare_check(settings, "tool_result", 2048, messages, schema=TOOL_ANSWER_SCHEMA)
        await _run_and_save_check(
            folder, report, followup, expected_code=tool_result["confirmation_code"], _transport=_transport)
    return report_path, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help=f"Base extractor profile (default: {DEFAULT_PROFILE}).")
    parser.add_argument("--model", help="Diagnostic-only namespace/model override; keeps the profile's host and settings.")
    parser.add_argument("--check-tools", action="store_true",
                        help="Add two paid requests to check a fictional tool call and result replay.")
    args = parser.parse_args()
    try:
        path, report = asyncio.run(run_checks(
            Path.cwd(), args.profile, model_name=args.model, check_tools=args.check_tools))
    except KeyboardInterrupt:
        parser.exit(130, "Compatibility check cancelled; inspect artifacts/huggingface_checks for saved observations.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Compatibility check failed: {error}\n")
    print(f"Report: {path}")
    print("No study extraction was launched. Full-plan capacity, extraction quality, and verifier quality remain untested by these checks.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
