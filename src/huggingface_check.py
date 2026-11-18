"""Check a pinned hosted setup on fictional inputs before extracting a plan.

Run explicitly with ``uv run --locked python -m huggingface_check``. This makes
up to three paid requests, preserves their artifacts outside study runs, and
stops at the first failure. Passing is a compatibility observation, not a
guarantee of future schema compliance, token limits, or extraction accuracy.
"""

import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator

from agents import load_profile
from huggingface_api import build_huggingface_request, request_huggingface_chat, require_huggingface_token
from models import ModelRequestCancelled, _json_object, prepare_response_schema
from validation import validate_agent_response


DEFAULT_PROFILE = "inkling2_small_hf_extractor"
SMALL_SCHEMA = {
    "type": "object", "properties": {"compatible": {"type": "boolean", "const": True}},
    "required": ["compatible"], "additionalProperties": False,
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


async def run_checks(
    project_root: Path, profile_name: str = DEFAULT_PROFILE, *,
    _transport: httpx.AsyncBaseTransport | None = None,
) -> tuple[Path, dict]:
    """Save exact requests and observed results without touching study files."""
    settings = load_profile(project_root, profile_name, stage="extractor")
    if settings["model"]["provider"] != "deepinfra":
        raise ValueError("This compatibility check requires the pinned DeepInfra profile.")
    require_huggingface_token()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = project_root / "artifacts" / "huggingface_checks" / f"{timestamp}-{uuid4().hex[:8]}"
    folder.mkdir(parents=True, exist_ok=False)
    report = {"profile": profile_name, "model": settings["model"], "checks": [], "passed": False}
    report_path = folder / "report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
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
    for name, limit, schema, messages in cases:
        chosen = deepcopy(settings)
        chosen["generation"]["max_output_tokens"] = min(limit, settings["generation"]["max_output_tokens"])
        # A diagnostic request gets a shorter deadline than a whole-plan pass.
        chosen["model_timeout_seconds"] = min(300, settings["model_timeout_seconds"])
        request = build_huggingface_request(chosen, messages, response_format=schema)
        request_record = {"url": request.url, "body": request.body, "settings": chosen}
        (folder / f"{name}_request.json").write_text(
            json.dumps(request_record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Checking {name} (requested output limit: {request.max_output_tokens})...", flush=True)
        cancelled = False
        try:
            result = await request_huggingface_chat(request, _transport=_transport)
        except ModelRequestCancelled as error:
            # Keep any bytes already received before propagating cancellation.
            result = error.result
            cancelled = True
        (folder / f"{name}_response.json").write_bytes(result.raw_response)
        problems = []
        if name == "short_output_limit":
            # Truncation is an acceptable outcome for this deliberately small
            # cap. Missing usage cannot establish whether the cap was observed.
            if result.completion_status not in {"normal", "truncated"}:
                problems.append(result.error or "Unsuccessful completion.")
            if result.output_tokens is None:
                problems.append("The provider did not report output usage.")
        elif result.error:
            problems.append(result.error)
        else:
            try:
                answer = _json_object((result.response_text or "").encode("utf-8"))
                if name == "project_schema":
                    problems.extend(f"{p.location}: {p.message}" for p in
                                    validate_agent_response(answer, page_count=1, stage="extractor"))
                else:
                    problems.extend(p.message for p in Draft202012Validator(schema).iter_errors(answer))
            except ValueError as error:
                problems.append(str(error))
        observed = {
            "name": name, "requested_output_limit": request.max_output_tokens,
            "input_tokens": result.input_tokens, "output_tokens": result.output_tokens,
            "finish_reason": result.finish_reason, "completion_status": result.completion_status,
            "elapsed_seconds": result.elapsed_seconds, "token_budget": result.token_budget.report,
            "passed": not problems, "errors": problems,
        }
        report["checks"].append(observed)
        report["passed"] = len(report["checks"]) == len(cases) and not problems
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {'passed' if not problems else 'failed'}", flush=True)
        if cancelled:
            raise asyncio.CancelledError
        if problems:
            break
    return report_path, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=DEFAULT_PROFILE,
                        help=f"Configured extractor profile (default: {DEFAULT_PROFILE}).")
    args = parser.parse_args()
    try:
        path, report = asyncio.run(run_checks(Path.cwd(), args.profile))
    except KeyboardInterrupt:
        parser.exit(130, "Compatibility check cancelled; inspect artifacts/huggingface_checks for saved observations.\n")
    except (OSError, ValueError) as error:
        parser.exit(1, f"Compatibility check failed: {error}\n")
    print(f"Report: {path}")
    print("No study extraction was launched. Live extraction quality is not established by these checks.")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
