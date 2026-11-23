"""Translate our text/tool conversations to Hugging Face's hosted chat API.

The runner owns tools, validation and saving. This adapter owns one HTTP request,
protocol translation, completion checks and provider-reported usage. It uses the
existing httpx dependency, with no SDK retries or automatic provider selection.
Preflight uses a conservative request-size estimate; actual usage comes from the API.
"""

import asyncio
import json
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass, replace

import httpx

from models import (
    ModelCallResult, ModelProgressError, ModelRequestCancelled, TokenBudgetResult,
    _json_object, _model_progress, _validate_chat_messages, _validate_tools,
    _validate_tool_calls,
)
from validation import validate_profiles


HF_ENDPOINT = "https://router.huggingface.co/v1"
HOSTED_MARGIN_TOKENS = 8192

# Router response names can differ from Hugging Face IDs. Only explicitly
# verified aliases are accepted; matching just the basename would hide changes
# of model owner or checkpoint. OpenRouter's weights links confirm these pairs:
# https://openrouter.ai/deepseek/deepseek-v4.1-flash-1017
# https://openrouter.ai/z-ai/glm-5.3-flash
_RESPONSE_MODEL_ALIASES = {
    "deepseek-ai/deepseek-v4.1-flash-1017": frozenset({"deepseek/deepseek-v4.1-flash-1017"}),
    "zai-org/glm-5.3-flash": frozenset({"z-ai/glm-5.3-flash"}),
}


@dataclass(frozen=True)
class PreparedHuggingFaceRequest:
    """A validated request whose bytes and response limits stay fixed.

    Authentication is added only when sending. The runner saves body as JSON;
    budgeting and HTTP use body_bytes from this same snapshot. Returning a fresh
    body dictionary prevents inspection or logging from changing what is sent.
    """

    url: str
    body_bytes: bytes
    timeout_seconds: float
    model_name: str
    context_limit: int
    max_output_tokens: int

    @property
    def body(self) -> dict:
        return _json_object(self.body_bytes)


def require_huggingface_token() -> str:
    """Read credentials only for execution; never put them in saved settings."""
    token = os.environ.get("HF_TOKEN", "")
    if not token or any(character.isspace() for character in token):
        raise ValueError("Set HF_TOKEN to a Hugging Face token with Inference Providers permission.")
    return token


def prepare_deepinfra_response_schema(schema: dict) -> dict:
    """Copy the generation schema, leaving some acceptance rules to Python.

    DeepInfra rejected uniqueItems in the live compatibility check. Conditional
    issue rules are also kept out of the generation grammar. The authoritative
    schema and Python validation retain both requirements. Merge the known
    issue-resolver conjunction without changing its permitted answers, using
    the same representation for every model on this host. Other constraints
    stay in place so further incompatibilities fail visibly.
    """
    result = deepcopy(schema)
    for keyword in ("uniqueItems", "if", "then", "else"):
        result.pop(keyword, None)
    # Visit schema positions only. A field named "if", or an object inside an
    # enum/const, is data and must not lose keys during schema preparation.
    for keyword in ("properties", "patternProperties", "$defs", "dependentSchemas"):
        if isinstance(result.get(keyword), dict):
            result[keyword] = {
                name: prepare_deepinfra_response_schema(child) if isinstance(child, dict) else child
                for name, child in result[keyword].items()
            }
    for keyword in ("items", "additionalProperties", "contains", "propertyNames", "not",
                    "unevaluatedProperties", "unevaluatedItems"):
        if isinstance(result.get(keyword), dict):
            result[keyword] = prepare_deepinfra_response_schema(result[keyword])
    for keyword in ("allOf", "anyOf", "oneOf", "prefixItems"):
        if isinstance(result.get(keyword), list):
            result[keyword] = [
                prepare_deepinfra_response_schema(child) if isinstance(child, dict) else child
                for child in result[keyword]
            ]
    _flatten_issue_resolver_constraint(result)
    return result


def _flatten_issue_resolver_constraint(schema: dict) -> None:
    """Merge the known issue conjunction in a detached generation copy.

    Only the exact resolver restriction is supported, and only when its enum
    is a subset of the issue definition's enum. Other compositions stay intact
    rather than risking a general allOf merge that changes accepted answers.
    """
    try:
        items = schema["properties"]["plan_issues"]["properties"]["issues"]["items"]
    except (KeyError, TypeError):
        return
    if not isinstance(items, dict) or set(items) != {"allOf"}:
        return
    branches = items["allOf"]
    if not isinstance(branches, list) or len(branches) != 2:
        return
    issue, restriction = branches
    permitted = ["extractor", "verifier", None]
    if restriction != {"properties": {"resolved_by": {"enum": permitted}}}:
        return
    if not isinstance(issue, dict) or issue.get("type") != "object":
        return
    properties = issue.get("properties")
    resolver = properties.get("resolved_by") if isinstance(properties, dict) else None
    if not isinstance(resolver, dict) or not isinstance(resolver.get("enum"), list):
        return
    if not all(value in resolver["enum"] for value in permitted):
        return
    # The second enum already excludes expert resolutions from model answers.
    # Moving that restriction preserves every other rule in the issue object.
    resolver["enum"] = permitted
    items.clear()
    items.update(issue)


def _huggingface_profile(settings: dict) -> dict:
    """Check editable settings and routing before preparing any HTTP evidence."""
    profile = deepcopy(settings)
    shared = profile.pop("document_tools", None)
    profile.pop("prompt_texts", None)
    profile.pop("environment", None)
    problems = validate_profiles({"schema_version": 1, "document_tools": shared, "profiles": [profile]})
    if problems:
        raise ValueError("Invalid model settings: " + "; ".join(p.message for p in problems))
    model = profile["model"]
    if model["endpoint"].rstrip("/") != HF_ENDPOINT:
        raise ValueError("Use the Hugging Face router HTTPS endpoint without credentials, query or fragment.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", model["name"]):
        raise ValueError("Use a namespace/model ID without a routing suffix; select provider separately.")
    provider = model["provider"] or ""
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", provider) or provider in {"auto", "fastest", "cheapest"}:
        raise ValueError("Select one explicit Hugging Face hosting provider.")
    if profile["image_input_enabled"]:
        raise ValueError("The hosted workflow supports text and local document tools, not image input.")
    if profile["generation"]["max_output_tokens"] >= profile["context_limit"]:
        raise ValueError("Reserve output space smaller than the context limit.")
    return profile


def _wire_messages(messages: list[dict], definitions: dict) -> list[dict]:
    """Translate validated history into the API's text and tool-call format."""
    _validate_chat_messages(messages, definitions)
    wire = []
    identifiers = set()
    for message in messages:
        item = {"role": message["role"], "content": message["content"]}
        if "tool_calls" in message:
            item["tool_calls"] = []
            for call in message["tool_calls"]:
                identifier = call.get("id")
                if not identifier or identifier in identifiers:
                    raise ValueError("Hosted tool calls require unique IDs throughout the conversation.")
                identifiers.add(identifier)
                item["tool_calls"].append({
                    "id": identifier, "type": "function", "function": {
                        "name": call["function"]["name"],
                        "arguments": json.dumps(call["function"]["arguments"], ensure_ascii=False, allow_nan=False),
                    },
                })
        if message["role"] == "tool":
            if not message.get("tool_call_id"):
                raise ValueError("Hosted tool results require a tool_call_id.")
            item.update(tool_call_id=message["tool_call_id"], name=message["tool_name"])
        # Raw artifacts retain reasoning. Replay uses only final content and
        # tool calls, following the protocol checked for the Inkling setup.
        wire.append(item)
    return wire


def build_huggingface_request(
    settings: dict, messages: list[dict], *, tools: list[dict] | None = None,
    response_format: dict | None = None,
) -> PreparedHuggingFaceRequest:
    """Prepare one detached request for recording, size checks, and sending.

    Tool arguments become JSON strings on the wire. Final generation uses the
    provider's schema copy; Python still checks the authoritative full contract.
    This function reads no credentials and makes no network requests.
    """
    profile = _huggingface_profile(settings)
    model = profile["model"]
    messages = _wire_messages(messages, _validate_tools(tools))
    body = {
        "model": model["name"] + ":" + model["provider"], "messages": messages,
        "stream": False, "max_tokens": profile["generation"]["max_output_tokens"],
    }
    for name in ("temperature", "top_p", "seed"):
        if profile["generation"][name] is not None:
            body[name] = profile["generation"][name]
    if tools:
        body.update(tools=deepcopy(tools), tool_choice="auto")
    if response_format is not None:
        if not isinstance(response_format, dict):
            raise ValueError("Hosted final generation requires an explicit JSON schema.")
        schema = (prepare_deepinfra_response_schema(response_format)
                  if model["provider"] == "deepinfra" else deepcopy(response_format))
        body["response_format"] = {"type": "json_schema", "json_schema": {
            "name": "heat_adaptation_extraction", "strict": True, "schema": schema,
        }}
        messages.append({"role": "system", "content": (
            "Return exactly one JSON object matching the supplied JSON Schema. "
            "Do not include Markdown or commentary."
        )})
    return PreparedHuggingFaceRequest(
        url=HF_ENDPOINT + "/chat/completions",
        body_bytes=json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8"),
        timeout_seconds=profile["model_timeout_seconds"], model_name=model["name"],
        context_limit=profile["context_limit"], max_output_tokens=body["max_tokens"],
    )


def estimate_huggingface_budget(request: PreparedHuggingFaceRequest) -> TokenBudgetResult:
    """Estimate capacity from the exact bytes to send, reserving full output.

    One estimated token per UTF-8 byte plus a formatting margin is a deliberately
    loose size screen. It is not a certified bound on hidden provider rendering.
    Actual API usage remains a separate observation, including when unavailable.
    """
    size = len(request.body_bytes)
    estimate = size + HOSTED_MARGIN_TOKENS
    fits = estimate + request.max_output_tokens <= request.context_limit
    return TokenBudgetResult({
        "counting_mode": "conservative_estimate", "input_tokens": None,
        "estimated_input_tokens": estimate, "request_bytes": size,
        "margin_tokens": HOSTED_MARGIN_TOKENS, "max_output_tokens": request.max_output_tokens,
        "context_limit": request.context_limit, "fits": fits,
        "method": "utf8_request_bytes_plus_margin", "verified_provider_count": False,
        "error": None if fits else "Hosted request estimate plus output reservation exceeds the context limit; no request sent.",
    }, {})


def _provider_error_detail(error: object) -> str:
    """Prefer a provider's nested explanation over the router's generic label.

    Hugging Face can wrap the actual provider error in metadata.raw as encoded
    JSON. Keep the complete original body in artifacts even when decoding that
    optional detail fails; malformed error metadata must not hide the failure.
    """
    if isinstance(error, dict):
        metadata = error.get("metadata")
        raw = metadata.get("raw") if isinstance(metadata, dict) else None
        if isinstance(raw, str):
            try:
                message = _json_object(raw.encode("utf-8")).get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            except (ValueError, RecursionError):
                pass
        error = error.get("message")
    return error.strip() if isinstance(error, str) and error.strip() else "The provider returned an API error."


def _reported_usage(payload: dict, problems: list[str]) -> tuple[int | None, int | None]:
    """Keep valid counts even if another usage field is malformed."""
    usage = payload.get("usage")
    if usage is None:
        return None, None
    if not isinstance(usage, dict):
        raise ValueError("usage must be an object or null.")
    counts = []
    for name in ("prompt_tokens", "completion_tokens"):
        value = usage.get(name)
        if value is not None and (type(value) is not int or value < 0):
            problems.append(f"Usage {name} must be a nonnegative integer or null.")
            value = None
        counts.append(value)
    return counts[0], counts[1]


def _returned_tool_calls(received: object, definitions: dict) -> list[dict]:
    """Decode API argument strings without repairing or executing a call."""
    if received is None:
        return []
    if not isinstance(received, list):
        raise ValueError("tool_calls must be a list or null.")
    calls = []
    for call in received:
        if (not isinstance(call, dict) or call.get("type") != "function"
                or not isinstance(call.get("id"), str) or not call["id"].strip()):
            raise ValueError("Each hosted tool call requires an ID and type=function.")
        function = call.get("function")
        if not isinstance(function, dict) or not isinstance(function.get("arguments"), str):
            raise ValueError("Hosted function arguments must be JSON-encoded text.")
        calls.append({"id": call["id"], "type": "function", "function": {
            "name": function.get("name"),
            "arguments": _json_object(function["arguments"].encode("utf-8")),
        }})
    return _validate_tool_calls(calls, definitions, require_known=True)


def _matches_model_identity(expected: str, reported: object) -> bool:
    """Accept the configured ID or an exact documented response alias."""
    if not isinstance(reported, str):
        return False
    expected = expected.lower()
    reported = reported.lower()
    # Keep existing support for a routing suffix on the configured ID. Aliases
    # are matched whole, without guessing extra suffixes or namespace rewrites.
    return (reported.split(":")[0] == expected
            or reported in _RESPONSE_MODEL_ALIASES.get(expected, ()))


def _interpret_huggingface_response(
    raw: bytes, request: PreparedHuggingFaceRequest, *, status_code: int | None,
    elapsed_seconds: float, failure: str | None = None,
) -> ModelCallResult:
    """Retain raw bytes and valid observations when any response check fails."""
    problems = []
    text = assistant = None
    calls = []
    finish = truncated = input_tokens = output_tokens = None
    try:
        payload = _json_object(raw)
        input_tokens, output_tokens = _reported_usage(payload, problems)
        if payload.get("error") is not None:
            # Provider errors have no generated choices. Expose their explanation
            # instead of masking it with a missing-answer parsing error.
            status = f"HTTP {status_code}: " if status_code is not None else ""
            detail = "Hugging Face " + status + _provider_error_detail(payload["error"])
            return ModelCallResult(
                raw_response=raw, response_text=None, assistant_message=None,
                input_tokens=input_tokens, output_tokens=output_tokens, finish_reason=None,
                truncated=None, completion_status="failed", elapsed_seconds=elapsed_seconds,
                status_code=status_code, provider_timings_ns={}, error=failure or detail,
            )
        returned_model = payload.get("model")
        if returned_model is not None and not _matches_model_identity(request.model_name, returned_model):
            problems.append("Returned model identity differs from the selected model.")
        choices = payload.get("choices")
        if not isinstance(choices, list) or len(choices) != 1:
            raise ValueError("Expected exactly one completed choice.")
        choice = choices[0]
        reason = choice.get("finish_reason")
        if reason is not None and not isinstance(reason, str):
            # Keep malformed metadata in raw bytes, never in typed run fields.
            raise ValueError("finish_reason must be text or null.")
        finish = reason
        truncated = finish == "length" if isinstance(finish, str) else None
        message = choice.get("message")
        if not isinstance(message, dict) or message.get("role") != "assistant":
            raise ValueError("Expected an assistant message.")
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("Assistant content must be text or null.")
        text = content
        assistant = {"role": "assistant", "content": text or ""}
        reasoning = message.get("reasoning_content")
        if reasoning is not None:
            if not isinstance(reasoning, str):
                raise ValueError("reasoning_content must be text or null.")
            assistant["thinking"] = reasoning
        definitions = _validate_tools(request.body.get("tools"))
        calls = _returned_tool_calls(message.get("tool_calls"), definitions)
        if calls:
            assistant["tool_calls"] = deepcopy(calls)
        if finish not in {"stop", "tool_calls", "length"}:
            problems.append("Unknown or unsuccessful hosted completion reason.")
        if (finish == "tool_calls") != bool(calls):
            problems.append("Completion reason and tool calls disagree.")
        if finish == "stop" and text is None:
            problems.append("Completed response has no text.")
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as error:
        problems.append(f"Invalid Hugging Face response: {error}")
    if input_tokens is not None and input_tokens + (output_tokens or 0) > request.context_limit:
        problems.append("Reported usage exceeds the configured context limit.")
    if output_tokens is not None and output_tokens > request.max_output_tokens:
        problems.append("Reported output usage exceeds the configured output limit.")
    if status_code is not None and not 200 <= status_code < 300:
        problems.insert(0, f"Hugging Face returned HTTP {status_code}.")
    error = failure or (" ".join(problems) if problems else None)
    if truncated and not problems and failure is None:
        error = "Hugging Face reported output truncation; retain the response and retry manually."
        completion = "truncated"
    else:
        completion = "failed" if error else "normal"
    return ModelCallResult(
        raw_response=raw, response_text=text, assistant_message=assistant,
        input_tokens=input_tokens, output_tokens=output_tokens, finish_reason=finish,
        truncated=truncated, completion_status=completion, elapsed_seconds=elapsed_seconds,
        status_code=status_code, provider_timings_ns={}, error=error,
        tool_calls=deepcopy(calls) if error is None else [],
    )


async def request_huggingface_chat(
    request: PreparedHuggingFaceRequest, *,
    _transport: httpx.AsyncBaseTransport | None = None, on_progress=None,
) -> ModelCallResult:
    """Send the prepared bytes once, with evidence callbacks and no retries.

    Callers own preparation and saving. This boundary adds authentication only
    for HTTP, checks capacity, and retains partial bytes on failure/cancellation.
    """
    token = require_huggingface_token()
    budget = estimate_huggingface_budget(request)
    timeout = request.timeout_seconds
    chunks = []
    status = failure = None
    started_generation = False
    started = time.monotonic()

    def observed_result():
        parsed = _interpret_huggingface_response(
            b"".join(chunks), request, status_code=status,
            elapsed_seconds=time.monotonic() - started, failure=failure,
        )
        return replace(parsed, token_budget=budget, generation_started=started_generation)

    try:
        async with asyncio.timeout(timeout):
            _model_progress(on_progress, "preflight_complete", budget)
            if time.monotonic() - started >= timeout:
                raise TimeoutError  # Synchronous saving also consumes the deadline.
            if not budget.report["fits"]:
                failure = budget.report["error"]
            else:
                async with httpx.AsyncClient(
                    timeout=None, follow_redirects=False, trust_env=False,
                    transport=_transport or httpx.AsyncHTTPTransport(retries=0),
                ) as client:
                    started_generation = True
                    async with client.stream("POST", request.url, content=request.body_bytes, headers={
                        "Authorization": "Bearer " + token,
                        "Content-Type": "application/json", "Accept-Encoding": "identity",
                    }) as response:
                        status = response.status_code
                        _model_progress(on_progress, "response_headers", status)
                        async for chunk in response.aiter_bytes():
                            chunks.append(chunk)
                            _model_progress(on_progress, "response_chunk", chunk)
                            if time.monotonic() - started >= timeout:
                                raise TimeoutError
    except TimeoutError:
        failure = f"Hugging Face request exceeded its complete-request timeout of {timeout} seconds."
    except httpx.HTTPError as error:
        failure = f"Hugging Face connection or response read failed: {error}"
    except ModelProgressError as error:
        failure = str(error)
    except asyncio.CancelledError as error:
        failure = "Hugging Face request was cancelled."
        raise ModelRequestCancelled(observed_result()) from error
    return observed_result()
