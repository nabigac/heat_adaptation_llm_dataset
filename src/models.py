"""Send one local Ollama chat request and retain its answer and measurements.

This is the first model-connection increment in DESIGN.md. It does not run an
agent loop, execute tools, or save a research run. Before generation it counts
the fully rendered text and reserves the configured maximum output. The first
counter supports the tested local Qwen/MLX setup; unsupported setups stop.
We also request no runtime truncation/rolling context and check reported usage
after the response: a runtime may ignore num_ctx.
This adapter's controls are checked against Ollama 0.40.14; test a changed
serving setup before using it for comparison work.
"""

import asyncio
import hashlib
import json
import os
import re
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urldefrag, urlsplit

import httpx
import tokenizers
from jsonschema import Draft202012Validator, SchemaError

from repair import CompletionStatus
from validation import validate_profiles


_TIMING_FIELDS = ("total_duration", "load_duration", "prompt_eval_duration", "eval_duration")
_SCHEMA_DIRECTORY = Path(__file__).resolve().parents[1] / "schemas"
_RESPONSE_SCHEMA_FILES = {
    "urn:heat-adaptation:content": "content.schema.json",
    "urn:heat-adaptation:agent-response": "agent_response.schema.json",
}
_RESPONSE_SCHEMA_URI = "urn:heat-adaptation:agent-response"
_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
_OLLAMA_NONBLANK_PATTERN = r"^[\s\S]*\S[\s\S]*$"
_COUNTING_RUNTIME_VERSION = "0.40.14"
_COUNTING_MODEL = "qwen3.5:27b"
# Tokenization must be revalidated if a tag update changes these assets, even
# when the public model name and runtime version remain the same.
_COUNTING_TOKENIZER_ASSETS = {
    "tokenizer.json": "sha256:5f9e4d4901a92b997e463c1f46055088b6cca5ca61a6522d1b9f64c4bb81cb42",
    "tokenizer_config.json": "sha256:316230d6a809701f4db5ea8f8fc862bc3a6f3229c937c174e674ff3ca0a64ac8",
}

# A JSON Schema document contains both schemas and ordinary JSON values. Walk
# only schema positions: a property's NAME or an example's literal "$ref" must
# never be mistaken for a schema keyword. Supporting another keyword requires
# a deliberate review instead of silently losing or misinterpreting its rules.
_SCHEMA_MAP_KEYWORDS = {"properties"}
_SCHEMA_LIST_KEYWORDS = {"allOf", "anyOf", "oneOf", "prefixItems"}
_SCHEMA_CHILD_KEYWORDS = {"items", "additionalProperties", "contains", "not", "if", "then", "else"}
_SCHEMA_VALUE_KEYWORDS = {
    "type", "enum", "const", "required", "format",
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "minItems", "maxItems", "uniqueItems", "minContains", "maxContains",
    "minProperties", "maxProperties", "dependentRequired",
}
_SCHEMA_ANNOTATIONS = {"title", "description", "$comment", "default", "examples", "deprecated", "readOnly", "writeOnly"}


@dataclass(frozen=True)
class ModelCallResult:
    """One attempted request, including evidence available when it failed.

    raw_response preserves the HTTP body after HTTP content decoding, without
    JSON rewriting. response_text is the exact assistant content field, while
    assistant_message also retains provider fields such as thinking/tool calls.
    The future runner saves these before deciding how to finalize the run.
    Frozen fields do not make nested dictionaries immutable.
    """

    raw_response: bytes
    response_text: str | None
    assistant_message: dict | None
    input_tokens: int | None
    output_tokens: int | None
    finish_reason: str | None
    truncated: bool | None
    completion_status: CompletionStatus
    elapsed_seconds: float
    status_code: int | None
    provider_timings_ns: dict[str, int | None]
    error: str | None
    # Separate preflight observations from actual generation usage. In
    # particular, a counted prompt is not a provider-reported input measurement.
    token_budget: "TokenBudgetResult | None" = None

    def to_run_call(self, response_path: str | None) -> dict:
        """Copy only Appendix A's model-call fields into a future run record.

        response_path must identify the file the caller actually saved. Client
        request time and provider timings are separate from whole-stage duration.
        """
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "finish_reason": self.finish_reason,
            "truncated": self.truncated,
            "response_path": response_path,
        }


class ModelRequestCancelled(asyncio.CancelledError):
    """Propagate cancellation while retaining evidence for an enclosing runner."""

    def __init__(self, result: ModelCallResult) -> None:
        self.result = result
        super().__init__("Ollama request cancelled; available evidence is retained in result.")


@dataclass(frozen=True)
class TokenBudgetResult:
    """A JSON-saveable report plus exact HTTP bodies from count-only setup.

    The future runner should save report, its rendered prompt, and raw_responses
    beside the exact request. These are audit artifacts, not extra model calls.
    Nested dictionaries remain mutable so a timeout can retain partial evidence.
    """

    report: dict
    raw_responses: dict[str, bytes]


class TokenBudgetCheckCancelled(asyncio.CancelledError):
    """Let a count-only caller retain observations when cancellation propagates."""

    def __init__(self, result: TokenBudgetResult) -> None:
        self.result = result
        super().__init__("Token-budget check cancelled; observations are retained in result.")


class OllamaSchemaError(ValueError):
    """Stop schema preparation when a compatible copy cannot be built safely."""


def prepare_ollama_response_schema() -> dict:
    """Build a fresh, self-contained provider copy of the response contract.

    Resolve only the two local authoritative schemas and rewrite the nonblank
    pattern using the equivalent whole-string expression tested with Ollama.
    No files are written, no HTTP request occurs, and no output default changes.
    Pass this dictionary explicitly as request_ollama_chat's response_format.

    This preserves the validation contract; it does not prove the serving setup
    enforces every keyword. Always use the original Python validators afterward.
    The future runner should preserve the exact sent schema with its request.
    """
    documents = {}
    for uri, filename in _RESPONSE_SCHEMA_FILES.items():
        path = _SCHEMA_DIRECTORY / filename
        try:
            document = json.loads(
                path.read_bytes().decode("utf-8"), object_pairs_hook=_unique_fields,
                parse_constant=_reject_constant,
            )
            Draft202012Validator.check_schema(document)
        except (OSError, ValueError, SchemaError) as error:
            raise OllamaSchemaError(f"Cannot load response schema {path}: {error}") from error
        if not isinstance(document, dict) or document.get("$id") != uri:
            raise OllamaSchemaError(f"Response schema {path} must declare its expected $id {uri!r}.")
        if document.get("$schema", _SCHEMA_DIALECT) != _SCHEMA_DIALECT:
            raise OllamaSchemaError(f"Response schema {path} must use JSON Schema Draft 2020-12.")
        documents[uri] = document
    try:
        prepared = _ResponseSchemaPreparer(documents).expand(documents[_RESPONSE_SCHEMA_URI], _RESPONSE_SCHEMA_URI)
        # All resource-local dialects are the same; retain one declaration on the
        # completed root after removing resource identities and local references.
        prepared = {"$schema": _SCHEMA_DIALECT, **prepared}
        Draft202012Validator.check_schema(prepared)
    except RecursionError as error:
        raise OllamaSchemaError("Response schemas are too deeply nested to prepare safely.") from error
    except SchemaError as error:
        raise OllamaSchemaError(f"Prepared response schema is invalid: {error.message}") from error
    return prepared


class _ResponseSchemaPreparer:
    """Keep the known source documents available during recursive expansion."""

    def __init__(self, documents: dict) -> None:
        self.documents = documents

    def expand(self, node, uri: str, source_path: tuple = (), active: tuple = ()):
        if isinstance(node, bool):
            return node  # True/false are complete schemas, for example additionalProperties.
        if not isinstance(node, dict):
            raise OllamaSchemaError(f"Expected a schema object or Boolean at {uri} {source_path!r}.")
        if "$id" in node and source_path:
            raise OllamaSchemaError(f"Nested schema resource IDs are not supported at {uri} {source_path!r}.")
        if "$schema" in node and node["$schema"] != _SCHEMA_DIALECT:
            raise OllamaSchemaError(f"Unsupported nested schema dialect at {uri} {source_path!r}.")

        if "$ref" in node:
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            unsupported = set(siblings) - _SCHEMA_ANNOTATIONS
            if unsupported:
                # Constraints beside a $ref apply together with its target.
                # Replacing or shallow-merging them could weaken the contract.
                raise OllamaSchemaError(f"Constraint or scope siblings beside $ref are not supported: {sorted(unsupported)}.")
            target_uri, target_path, target = self.resolve(node["$ref"], uri)
            identity = (target_uri, target_path)
            if identity in active:
                raise OllamaSchemaError(f"Recursive schema reference {node['$ref']!r} cannot be inlined.")
            expanded = self.expand(target, target_uri, target_path, active + (identity,))
            if siblings and not isinstance(expanded, dict):
                raise OllamaSchemaError("Annotations beside a Boolean schema reference are not yet supported.")
            if siblings:
                for key, value in siblings.items():
                    if key in {"title", "description", "$comment"} and key in expanded and expanded[key] != value:
                        expanded[key] += "\n" + value
                    else:
                        expanded[key] = deepcopy(value)
            return expanded

        result = {}
        for key, value in node.items():
            path = source_path + (key,)
            if key in {"$id", "$schema", "$defs"}:
                # Unused definitions do not constrain instances. Reachable ones
                # are retrieved from the original document when resolving $ref.
                continue
            if key in _SCHEMA_ANNOTATIONS or key in _SCHEMA_VALUE_KEYWORDS:
                result[key] = deepcopy(value)
            elif key == "pattern":
                if value not in (r"\S", _OLLAMA_NONBLANK_PATTERN):
                    raise OllamaSchemaError(f"Untested generation pattern {value!r} at {uri} {path!r}.")
                # [\s\S]* permits every character, including line breaks. A
                # non-whitespace character is still required somewhere inside.
                result[key] = _OLLAMA_NONBLANK_PATTERN
            elif key in _SCHEMA_MAP_KEYWORDS:
                result[key] = {name: self.expand(child, uri, path + (name,), active) for name, child in value.items()}
            elif key in _SCHEMA_LIST_KEYWORDS:
                result[key] = [self.expand(child, uri, path + (index,), active) for index, child in enumerate(value)]
            elif key in _SCHEMA_CHILD_KEYWORDS:
                result[key] = self.expand(value, uri, path, active)
            else:
                raise OllamaSchemaError(f"Unsupported generation schema keyword {key!r} at {uri} {path!r}.")
        return result

    def resolve(self, reference: str, current_uri: str) -> tuple[str, tuple, object]:
        """Resolve a known resource and JSON Pointer; never fetch a URL or file."""
        uri, fragment = urldefrag(reference)
        uri = uri or current_uri
        if uri not in self.documents:
            raise OllamaSchemaError(f"Unknown schema resource in reference {reference!r}.")
        try:
            fragment = unquote(fragment, encoding="utf-8", errors="strict")
        except UnicodeError as error:
            raise OllamaSchemaError(f"Invalid UTF-8 reference fragment {reference!r}.") from error
        if fragment and not fragment.startswith("/"):
            raise OllamaSchemaError(f"Only JSON Pointer references are supported: {reference!r}.")
        node = self.documents[uri]
        path = []
        for encoded in fragment[1:].split("/") if fragment else ():
            # JSON Pointer permits only ~0 (tilde) and ~1 (slash) escapes.
            for index, character in enumerate(encoded):
                if character == "~" and (index + 1 == len(encoded) or encoded[index + 1] not in "01"):
                    raise OllamaSchemaError(f"Invalid JSON Pointer escape in {reference!r}.")
            part = encoded.replace("~1", "/").replace("~0", "~")
            try:
                if isinstance(node, list):
                    if not part.isascii() or not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                        raise ValueError("Invalid array index.")
                    part = int(part)
                node = node[part]
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise OllamaSchemaError(f"Unresolved schema reference {reference!r}.") from error
            path.append(part)
        return uri, tuple(path), node


def build_ollama_request(
    settings: dict, messages: list[dict], *, response_format: Literal["json"] | dict | None = None
) -> tuple[str, dict, float]:
    """Validate inputs and return (chat URL, request body, overall timeout).

    The first increment accepts text messages only. Image delivery, tool
    definitions, and tool-message histories will be added with their capability
    and context-accounting checks; unsupported inputs are rejected, not dropped.
    """
    # The loader's dictionary may already include an observed environment. Those
    # saved-record additions do not belong in an editable profile or HTTP body.
    # All other field choices still use our shared profile/run setting rules.
    if not isinstance(settings, dict):
        raise ValueError("Model settings must be a loaded profile dictionary.")
    profile = deepcopy(settings)
    document_tools = profile.pop("document_tools", None)
    profile.pop("prompt_texts", None)
    profile.pop("environment", None)
    problems = validate_profiles({
        "schema_version": 1, "document_tools": document_tools, "profiles": [profile],
    })
    if problems:
        raise ValueError("Invalid model settings: " + "; ".join(problem.message for problem in problems))
    if profile["model"]["execution_mode"] != "local":
        raise ValueError("This first adapter supports local Ollama; hosted adapters remain planned.")

    endpoint = profile["model"]["endpoint"]
    address = urlsplit(endpoint)
    if (
        address.scheme not in ("http", "https") or not address.hostname
        or address.username is not None or address.password is not None
        or address.query or address.fragment
    ):
        raise ValueError("Use an HTTP(S) Ollama base URL without inline credentials, a query, or a fragment.")
    # urllib checks a port only when this property is accessed. Reject an invalid
    # port before httpx can fail partway through request construction.
    try:
        address.port
    except ValueError as error:
        raise ValueError("The Ollama base URL must contain a valid port.") from error

    if not isinstance(messages, list) or not messages:
        raise ValueError("Supply a nonempty list of text chat messages.")
    for message in messages:
        if (
            not isinstance(message, dict) or set(message) != {"role", "content"}
            or message["role"] not in ("system", "user", "assistant")
            or not isinstance(message["content"], str)
        ):
            raise ValueError("Each text message needs only role (system/user/assistant) and string content.")
    if response_format is not None and response_format != "json" and not isinstance(response_format, dict):
        raise ValueError("Response format must be 'json', a JSON schema object, or None.")

    generation = profile["generation"]
    options = {
        "num_ctx": profile["context_limit"],
        "num_predict": generation["max_output_tokens"],
    }
    for name in ("temperature", "top_p", "seed"):
        if generation[name] is not None:
            options[name] = generation[name]  # Preserve explicit zero; omit null controls.
    body = {
        "model": profile["model"]["name"], "messages": deepcopy(messages),
        "stream": False, "options": options,
        # These are top-level request fields, not generation options. Ollama's
        # defaults may discard old input or roll context; our workflow forbids
        # both. Source: Ollama v0.40.14 api/types.go and server/routes.go.
        "truncate": False, "shift": False,
    }
    if response_format is not None:
        body["format"] = deepcopy(response_format)
    # Fail on non-JSON values or unencodable text before contacting the service.
    json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return endpoint.rstrip("/") + "/api/chat", body, profile["model_timeout_seconds"]


def _new_token_budget(body: dict) -> TokenBudgetResult:
    """Bind a fresh audit report to the exact request, before any network I/O."""
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return TokenBudgetResult(report={
        "method": "ollama_render_only_and_local_tokenizer",
        "request_sha256": hashlib.sha256(encoded).hexdigest(),
        "model": body["model"], "model_digest": None, "tokenizer_digest": None,
        "tokenizers_version": tokenizers.__version__, "runtime_version": None,
        "context_limit": body["options"]["num_ctx"],
        "output_tokens_reserved": body["options"]["num_predict"],
        "input_tokens": None, "remaining_tokens": None, "fits": False,
        "rendered_prompt": None, "rendered_prompt_sha256": None,
        "elapsed_seconds": None, "error": None,
    }, raw_responses={})


def _json_object(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields, parse_constant=_reject_constant)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


def _load_counting_tokenizer(model_digest: str, models_directory: Path | str | None) -> tuple:
    """Read only named, digest-checked assets from the installed Qwen model.

    Ollama's local manifest can wrap multiple runner variants. Select the exact
    manifest reported by the server, not an arbitrary first model or tokenizer.
    This reads small JSON assets; it never loads tensors or downloads files.
    """
    root = Path(models_directory or os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama/models").expanduser()

    def blob(digest: str) -> bytes:
        if not isinstance(digest, str) or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None:
            raise ValueError("Invalid SHA-256 model asset digest.")
        raw = (root / "blobs" / digest.replace(":", "-")).read_bytes()
        if hashlib.sha256(raw).hexdigest() != digest[7:]:
            raise ValueError(f"Installed model asset checksum mismatch: {digest}.")
        return raw

    if not isinstance(model_digest, str) or re.fullmatch(r"[0-9a-f]{64}", model_digest) is None:
        raise ValueError("Ollama did not report a valid installed-model digest.")
    raw = (root / "manifests/registry.ollama.ai/library/qwen3.5/27b").read_bytes()
    manifest = _json_object(raw)
    if hashlib.sha256(raw).hexdigest() != model_digest:
        # The downloaded tag may contain runner variants as manifest layers.
        matching = [layer for layer in manifest.get("layers", []) if
                    layer.get("mediaType") == "application/vnd.docker.distribution.manifest.v2+json"
                    and layer.get("digest") == "sha256:" + model_digest]
        if len(matching) != 1:
            raise ValueError("The local model assets do not match the model served by this Ollama endpoint.")
        manifest = _json_object(blob(matching[0]["digest"]))
    config = _json_object(blob(manifest["config"]["digest"]))
    if config.get("model_format") != "safetensors" or config.get("renderer") != "qwen3.5":
        raise ValueError("Token counting currently supports the tested Qwen3.5 safetensors/MLX setup only.")

    def asset(name: str) -> tuple[bytes, str]:
        matches = [layer for layer in manifest["layers"] if layer.get("name") == name
                   and layer.get("mediaType") == "application/vnd.ollama.image.json"]
        if len(matches) != 1:
            raise ValueError(f"Expected one installed {name} asset; found {len(matches)}.")
        digest = matches[0]["digest"]
        return blob(digest), digest

    raw, tokenizer_digest = asset("tokenizer.json")
    config_raw, config_digest = asset("tokenizer_config.json")
    if any(digest != _COUNTING_TOKENIZER_ASSETS[name] for name, digest in (
        ("tokenizer.json", tokenizer_digest), ("tokenizer_config.json", config_digest),
    )):
        raise ValueError("Untested tokenizer assets; validate this model's tokenizer before generation.")
    tokenizer_config = _json_object(config_raw)
    if tokenizer_config.get("add_bos_token") is not False or tokenizer_config.get("split_special_tokens") is not False:
        raise ValueError("Untested tokenizer special-token settings; validate this model before generation.")
    model_config = _json_object(asset("config.json")[0])
    native_context = model_config.get("text_config", {}).get("max_position_embeddings")
    if type(native_context) is not int or native_context <= 0:
        raise ValueError("The installed model must declare a positive context capacity.")
    try:
        tokenizer = tokenizers.Tokenizer.from_str(raw.decode("utf-8"))
        # Counting must see all input, even if a saved tokenizer happens to have
        # padding or truncation enabled. No tokenizer asset is edited on disk.
        tokenizer.no_padding()
        tokenizer.no_truncation()
    except Exception as error:
        raise ValueError(f"Cannot load the installed tokenizer: {error}") from error
    return tokenizer, tokenizer_digest, native_context


async def _check_token_budget(client, url: str, body: dict, result: TokenBudgetResult, models_directory) -> None:
    """Fill a report without generating output; callers own the overall timeout."""
    started = time.monotonic()
    report = result.report

    async def observe(name, method, route, payload=None):
        result.raw_responses[name] = b""
        # Read incrementally so cancellation, timeout, or a broken connection
        # still leaves the bytes already received for this preflight operation.
        async with client.stream(method, url.removesuffix("/api/chat") + route, json=payload) as response:
            async for chunk in response.aiter_bytes():
                result.raw_responses[name] += chunk
            response.raise_for_status()
        return _json_object(result.raw_responses[name])

    try:
        if urlsplit(url).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise ValueError("Local tokenizer verification requires a loopback Ollama endpoint.")
        if body["model"] != _COUNTING_MODEL:
            raise ValueError(f"Token counting is currently tested only for {_COUNTING_MODEL}; validate another model before generation.")
        if report["output_tokens_reserved"] > report["context_limit"]:
            raise ValueError("The reserved output alone exceeds the configured context limit.")
        version = await observe("version", "GET", "/api/version")
        report["runtime_version"] = version.get("version")
        # Render-only is a private API flag. Check the tested version BEFORE
        # using it, so an unfamiliar server cannot silently ignore that flag.
        if report["runtime_version"] != _COUNTING_RUNTIME_VERSION:
            raise ValueError(f"Token counting requires tested Ollama {_COUNTING_RUNTIME_VERSION}; validate this runtime before generation.")
        tags = await observe("installed_models", "GET", "/api/tags")
        matches = [model for model in tags.get("models", []) if model.get("name") == body["model"]]
        if len(matches) != 1:
            raise ValueError("Ollama must list exactly one installed model with the selected name.")
        report["model_digest"] = matches[0].get("digest")
        tokenizer, digest, native_context = _load_counting_tokenizer(report["model_digest"], models_directory)
        report["tokenizer_digest"] = digest
        if report["context_limit"] > native_context:
            raise ValueError(f"Configured context exceeds the installed model's {native_context}-token capacity.")
        render_body = {**deepcopy(body), "_debug_render_only": True}
        rendered = await observe("render", "POST", "/api/chat", render_body)
        debug = rendered.get("_debug_info")
        # Ollama's JSON tags omit image_count when zero; absence means zero in
        # this version's DebugInfo structure, not an unknown image-token count.
        image_count = debug.get("image_count", 0) if isinstance(debug, dict) else None
        if not isinstance(debug, dict) or not isinstance(debug.get("rendered_template"), str) or type(image_count) is not int or image_count != 0:
            raise ValueError("Ollama did not return the expected text-only render result.")
        prompt = debug["rendered_template"]
        report["rendered_prompt"] = prompt
        report["rendered_prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        # The server already inserted role markers and the assistant prefix.
        # Qwen's tested renderer adds no separate BOS; do not add one again.
        report["input_tokens"] = len(tokenizer.encode(prompt, add_special_tokens=False).ids)
        report["remaining_tokens"] = report["context_limit"] - report["input_tokens"] - report["output_tokens_reserved"]
        report["fits"] = report["remaining_tokens"] >= 0
        if not report["fits"]:
            report["error"] = (
                f"Request needs {report['input_tokens']} input tokens plus {report['output_tokens_reserved']} reserved output tokens, "
                f"exceeding the {report['context_limit']}-token context by {-report['remaining_tokens']}. "
                "The document was not shortened and generation was not started."
            )
    except (OSError, ValueError, KeyError, TypeError, AttributeError, httpx.HTTPError) as error:
        report["error"] = f"Cannot establish the request token budget: {error}"
    finally:
        report["elapsed_seconds"] = time.monotonic() - started


async def check_ollama_token_budget(
    settings: dict, messages: list[dict], *, response_format: Literal["json"] | dict | None = None,
    models_directory: Path | str | None = None, _transport: httpx.AsyncBaseTransport | None = None,
) -> TokenBudgetResult:
    """Inspect request fit without generating an answer or changing any settings.

    The schema is forwarded in format, as it will be for generation. Count the
    actual rendered input, not the HTTP envelope or a second copy of the schema.
    Future tool/image support needs its own accounting before it can be enabled.
    A false fits result, including unavailable counting, must stop generation.
    """
    url, body, timeout_seconds = build_ollama_request(settings, messages, response_format=response_format)
    result = _new_token_budget(body)
    started = time.monotonic()
    try:
        async with asyncio.timeout(timeout_seconds):
            async with httpx.AsyncClient(timeout=None, follow_redirects=False, trust_env=False,
                transport=_transport or httpx.AsyncHTTPTransport(retries=0)) as client:
                await _check_token_budget(client, url, body, result, models_directory)
                # The async timer cannot interrupt synchronous tokenizer/file
                # work. Reject an elapsed deadline even when no await yielded.
                if time.monotonic() - started >= timeout_seconds:
                    raise TimeoutError
    except TimeoutError:
        result.report["fits"] = False
        result.report["error"] = f"Token-budget check exceeded its complete-request timeout of {timeout_seconds} seconds."
    except asyncio.CancelledError as error:
        result.report["fits"] = False
        result.report["error"] = "Token-budget check was cancelled."
        raise TokenBudgetCheckCancelled(result) from error
    return result


async def request_ollama_chat(
    settings: dict,
    messages: list[dict],
    *,
    response_format: Literal["json"] | dict | None = None,
    models_directory: Path | str | None = None,
    _transport: httpx.AsyncBaseTransport | None = None,
) -> ModelCallResult:
    """Check the token budget, then attempt generation once within one deadline.

    Use `await` in an async runner, or asyncio.run(...) from a synchronous script.
    _transport lets tests supply controlled HTTP responses without a real model.
    Configuration/programming errors raise before sending; operational failures
    return their available bytes and measurements. There are no automatic retries.
    """
    url, body, timeout_seconds = build_ollama_request(settings, messages, response_format=response_format)
    encoded = json.dumps(body, ensure_ascii=False, allow_nan=False).encode("utf-8")
    token_budget = _new_token_budget(body)
    chunks = []
    status_code = None
    failure = None
    started = time.monotonic()
    try:
        # A socket/read timeout alone can restart for every received chunk.
        # asyncio.timeout instead covers connection, waiting, and all body reads.
        async with asyncio.timeout(timeout_seconds):
            async with httpx.AsyncClient(
                timeout=None, follow_redirects=False, trust_env=False,
                transport=_transport or httpx.AsyncHTTPTransport(retries=0),
            ) as client:
                await _check_token_budget(client, url, body, token_budget, models_directory)
                if time.monotonic() - started >= timeout_seconds:
                    token_budget.report["fits"] = False
                    raise TimeoutError
                if not token_budget.report["fits"]:
                    failure = token_budget.report["error"] or "The request token budget could not be established."
                else:
                    async with client.stream(
                        "POST", url, content=encoded,
                        headers={"Content-Type": "application/json", "Accept-Encoding": "identity"},
                    ) as response:
                        status_code = response.status_code
                        async for chunk in response.aiter_bytes():
                            chunks.append(chunk)
    except TimeoutError:
        failure = f"Ollama request exceeded its complete-request timeout of {timeout_seconds} seconds."
        if not token_budget.report["fits"]:
            token_budget.report["error"] = failure
    except httpx.HTTPError as error:
        failure = f"Ollama connection or response read failed: {error}"
    except asyncio.CancelledError as error:
        # Keep cancellation semantics while giving the future runner access to
        # already-received bytes. Cancelling is not a successful model response.
        if not token_budget.report["fits"]:
            token_budget.report["error"] = "Ollama request was cancelled during token-budget checking."
        result = _interpret_response(
            b"".join(chunks), status_code=status_code,
            elapsed_seconds=time.monotonic() - started, failure="Ollama request was cancelled.",
            context_limit=body["options"]["num_ctx"], output_limit=body["options"]["num_predict"],
        )
        raise ModelRequestCancelled(replace(result, token_budget=token_budget)) from error
    result = _interpret_response(
        b"".join(chunks), status_code=status_code,
        elapsed_seconds=time.monotonic() - started, failure=failure,
        context_limit=body["options"]["num_ctx"], output_limit=body["options"]["num_predict"],
    )
    if result.error is None and result.input_tokens is not None and result.input_tokens != token_budget.report["input_tokens"]:
        result = replace(result, completion_status="failed", error=(
            f"Ollama reported {result.input_tokens} input tokens but preflight counted {token_budget.report['input_tokens']}; "
            "the input may have changed, been shortened, or used different tokenization. Retest before proceeding."
        ))
    return replace(result, token_budget=token_budget)


def _interpret_response(
    raw: bytes, *, status_code: int | None, elapsed_seconds: float, failure: str | None,
    context_limit: int, output_limit: int,
) -> ModelCallResult:
    """Retain valid observations even if another field or the request failed."""
    problems = []
    payload = {}
    try:
        decoded = json.loads(
            raw.decode("utf-8"), object_pairs_hook=_unique_fields,
            parse_constant=_reject_constant,
        )
        if not isinstance(decoded, dict):
            raise ValueError("The Ollama response must be one JSON object.")
        payload = decoded
    except ValueError as error:
        problems.append(f"Cannot decode the Ollama response: {error}")

    def observed_count(name: str) -> int | None:
        value = payload.get(name)
        if value is None:
            return None  # Unknown is not zero, even for an otherwise successful call.
        if type(value) is int and value >= 0:
            return value
        problems.append(f"Ollama field {name!r} must be a nonnegative integer or null.")
        return None

    input_tokens = observed_count("prompt_eval_count")
    output_tokens = observed_count("eval_count")
    # num_ctx is a requested setting, not proof the runtime honored it. The live
    # development probe exposed this distinction on the installed MLX runner.
    # Reject known over-budget results without discarding their observations.
    # This is a post-response consistency check, not pre-generation token counting.
    if input_tokens is not None and input_tokens > context_limit:
        problems.append(f"Ollama reported {input_tokens} input tokens, exceeding the configured context limit of {context_limit}.")
    elif input_tokens is not None and output_tokens is not None and input_tokens + output_tokens > context_limit:
        problems.append(f"Ollama reported {input_tokens + output_tokens} input/output tokens, exceeding the configured context limit of {context_limit}.")
    if output_tokens is not None and output_tokens > output_limit:
        problems.append(f"Ollama reported {output_tokens} output tokens, exceeding the configured output limit of {output_limit}.")
    timings = {name: observed_count(name) for name in _TIMING_FIELDS}
    finish_reason = payload.get("done_reason")
    if finish_reason is not None and (not isinstance(finish_reason, str) or not finish_reason.strip()):
        problems.append("Ollama's completion reason must be nonblank text or null.")
        finish_reason = None
    # Recognize only provider reasons whose meaning we have established. An
    # unfamiliar or undisclosed reason does not confirm normal generation.
    truncated = True if finish_reason == "length" else False if finish_reason == "stop" else None

    message = payload.get("message")
    text = None
    if isinstance(message, dict):
        if message.get("role") != "assistant":
            problems.append("The Ollama message must have assistant role.")
        text = message.get("content")
        if not isinstance(text, str):
            problems.append("The Ollama assistant content must be a string.")
            text = None
    else:
        message = None
        problems.append("The Ollama response is missing its assistant message.")
    if payload.get("done") is not True:
        problems.append("Ollama did not confirm that this non-streaming response finished.")
    if payload.get("error") is not None:
        problems.insert(0, f"Ollama reported an error: {payload['error']}")
    if status_code is not None and not 200 <= status_code < 300:
        problems.insert(0, f"Ollama returned HTTP {status_code}.")

    if failure or problems:
        completion_status = "failed"
        error = failure or " ".join(problems)
    elif truncated is True:
        completion_status = "truncated"
        error = "Ollama reported output truncation (done_reason='length'); retain the response and retry manually."
    else:
        completion_status = "normal" if finish_reason == "stop" else "unknown"
        error = None
    return ModelCallResult(
        raw_response=raw, response_text=text, assistant_message=message,
        input_tokens=input_tokens, output_tokens=output_tokens,
        finish_reason=finish_reason, truncated=truncated, completion_status=completion_status,
        elapsed_seconds=elapsed_seconds, status_code=status_code,
        provider_timings_ns=timings, error=error,
    )


def _unique_fields(pairs: list[tuple[str, object]]) -> dict:
    """Reject duplicate fields instead of discarding an earlier provider value."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON field {key!r}.")
        result[key] = value
    return result


def _reject_constant(value: str):
    raise ValueError(f"Non-standard JSON number {value!r}.")
