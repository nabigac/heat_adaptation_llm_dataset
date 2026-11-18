"""Shared model evidence, response schemas, and tool-history validation.

Hugging Face transport lives in huggingface_api.py. This module has no network
or model-runtime operations: it prepares contracts and validates protocol data.
"""

import asyncio
import json
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote, urldefrag

from jsonschema import Draft202012Validator, SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable

from repair import CompletionStatus

_SCHEMA_DIRECTORY = Path(__file__).resolve().parents[1] / "schemas"

_RESPONSE_SCHEMA_FILES = {
    "urn:heat-adaptation:plan-data": "plan_data.schema.json",
    "urn:heat-adaptation:agent-response": "agent_response.schema.json",
}

_RESPONSE_SCHEMA_URI = "urn:heat-adaptation:agent-response"

_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

_NONBLANK_PATTERN = r"^[\s\S]*\S[\s\S]*$"

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
    The saved runner preserves these before deciding how to finalize the run.
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
    # Keep the preflight estimate separate from provider-reported usage.
    token_budget: "TokenBudgetResult | None" = None
    # Only validated, normally completed tool requests are exposed here. On
    # failure the original message/raw bytes still retain every received field.
    # The agent checks error/completion_status before executing any tool request.
    tool_calls: list[dict] = field(default_factory=list)
    # True once the generation HTTP exchange begins. A blocked size estimate
    # must not become a research model-call observation.
    generation_started: bool = False

    def to_run_call(self, response_path: str | None) -> dict:
        """Copy the model-call fields defined in IMPLEMENTATION.MD into a run record.

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
        super().__init__("Model request cancelled; available evidence is retained in result.")


class ModelProgressError(RuntimeError):
    """An evidence callback failed; stop this request without losing its bytes."""


def _model_progress(callback, event: str, payload) -> None:
    if callback is not None:
        try:
            callback(event, payload)
        except Exception as error:
            raise ModelProgressError(f"Cannot preserve model evidence: {type(error).__name__}: {error}") from error


@dataclass(frozen=True)
class TokenBudgetResult:
    """A saved capacity estimate, separate from actual generation usage.

    Raw setup evidence, when available, is retained without counting it as a
    model generation. Nested dictionaries remain mutable for failure handling.
    """

    report: dict
    raw_responses: dict[str, bytes]


class ResponseSchemaError(ValueError):
    """Stop schema preparation when a compatible copy cannot be built safely."""


def prepare_response_schema() -> dict:
    """Build a fresh, self-contained provider copy of the response contract.

    Resolve only the two local authoritative schemas and rewrite the nonblank
    pattern using an equivalent whole-string expression for generation.
    No files are written, no HTTP request occurs, and no output default changes.
    The transport derives its provider-specific generation copy from this.

    This preserves the validation contract; it does not prove the serving setup
    enforces every keyword. Always use the original Python validators afterward.
    The saved runner preserves the exact sent schema with its request.
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
            raise ResponseSchemaError(f"Cannot load response schema {path}: {error}") from error
        if not isinstance(document, dict) or document.get("$id") != uri:
            raise ResponseSchemaError(f"Response schema {path} must declare its expected $id {uri!r}.")
        if document.get("$schema", _SCHEMA_DIALECT) != _SCHEMA_DIALECT:
            raise ResponseSchemaError(f"Response schema {path} must use JSON Schema Draft 2020-12.")
        documents[uri] = document
    try:
        prepared = _ResponseSchemaPreparer(documents).expand(documents[_RESPONSE_SCHEMA_URI], _RESPONSE_SCHEMA_URI)
        # All resource-local dialects are the same; retain one declaration on the
        # completed root after removing resource identities and local references.
        prepared = {"$schema": _SCHEMA_DIALECT, **prepared}
        Draft202012Validator.check_schema(prepared)
    except RecursionError as error:
        raise ResponseSchemaError("Response schemas are too deeply nested to prepare safely.") from error
    except SchemaError as error:
        raise ResponseSchemaError(f"Prepared response schema is invalid: {error.message}") from error
    return prepared


class _ResponseSchemaPreparer:
    """Keep the known source documents available during recursive expansion."""

    def __init__(self, documents: dict) -> None:
        self.documents = documents

    def expand(self, node, uri: str, source_path: tuple = (), active: tuple = ()):
        if isinstance(node, bool):
            return node  # True/false are complete schemas, for example additionalProperties.
        if not isinstance(node, dict):
            raise ResponseSchemaError(f"Expected a schema object or Boolean at {uri} {source_path!r}.")
        if "$id" in node and source_path:
            raise ResponseSchemaError(f"Nested schema resource IDs are not supported at {uri} {source_path!r}.")
        if "$schema" in node and node["$schema"] != _SCHEMA_DIALECT:
            raise ResponseSchemaError(f"Unsupported nested schema dialect at {uri} {source_path!r}.")

        if "$ref" in node:
            siblings = {key: value for key, value in node.items() if key != "$ref"}
            unsupported = set(siblings) - _SCHEMA_ANNOTATIONS
            if unsupported:
                # Constraints beside a $ref apply together with its target.
                # Replacing or shallow-merging them could weaken the contract.
                raise ResponseSchemaError(f"Constraint or scope siblings beside $ref are not supported: {sorted(unsupported)}.")
            target_uri, target_path, target = self.resolve(node["$ref"], uri)
            identity = (target_uri, target_path)
            if identity in active:
                raise ResponseSchemaError(f"Recursive schema reference {node['$ref']!r} cannot be inlined.")
            expanded = self.expand(target, target_uri, target_path, active + (identity,))
            if siblings and not isinstance(expanded, dict):
                raise ResponseSchemaError("Annotations beside a Boolean schema reference are not yet supported.")
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
                if value not in (r"\S", _NONBLANK_PATTERN):
                    raise ResponseSchemaError(f"Untested generation pattern {value!r} at {uri} {path!r}.")
                # [\s\S]* permits every character, including line breaks. A
                # non-whitespace character is still required somewhere inside.
                result[key] = _NONBLANK_PATTERN
            elif key in _SCHEMA_MAP_KEYWORDS:
                result[key] = {name: self.expand(child, uri, path + (name,), active) for name, child in value.items()}
            elif key in _SCHEMA_LIST_KEYWORDS:
                result[key] = [self.expand(child, uri, path + (index,), active) for index, child in enumerate(value)]
            elif key in _SCHEMA_CHILD_KEYWORDS:
                result[key] = self.expand(value, uri, path, active)
            else:
                raise ResponseSchemaError(f"Unsupported generation schema keyword {key!r} at {uri} {path!r}.")
        return result

    def resolve(self, reference: str, current_uri: str) -> tuple[str, tuple, object]:
        """Resolve a known resource and JSON Pointer; never fetch a URL or file."""
        uri, fragment = urldefrag(reference)
        uri = uri or current_uri
        if uri not in self.documents:
            raise ResponseSchemaError(f"Unknown schema resource in reference {reference!r}.")
        try:
            fragment = unquote(fragment, encoding="utf-8", errors="strict")
        except UnicodeError as error:
            raise ResponseSchemaError(f"Invalid UTF-8 reference fragment {reference!r}.") from error
        if fragment and not fragment.startswith("/"):
            raise ResponseSchemaError(f"Only JSON Pointer references are supported: {reference!r}.")
        node = self.documents[uri]
        path = []
        for encoded in fragment[1:].split("/") if fragment else ():
            # JSON Pointer permits only ~0 (tilde) and ~1 (slash) escapes.
            for index, character in enumerate(encoded):
                if character == "~" and (index + 1 == len(encoded) or encoded[index + 1] not in "01"):
                    raise ResponseSchemaError(f"Invalid JSON Pointer escape in {reference!r}.")
            part = encoded.replace("~1", "/").replace("~0", "~")
            try:
                if isinstance(node, list):
                    if not part.isascii() or not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                        raise ValueError("Invalid array index.")
                    part = int(part)
                node = node[part]
            except (KeyError, IndexError, TypeError, ValueError) as error:
                raise ResponseSchemaError(f"Unresolved schema reference {reference!r}.") from error
            path.append(part)
        return uri, tuple(path), node


def prepare_document_tools(mcp_tools: list[dict]) -> list[dict]:
    """Translate serialized MCP catalogue entries into function definitions.

    A caller obtains these dictionaries with each MCP Tool's
    model_dump(mode="json", by_alias=True). Keep the names, descriptions and
    complete inputSchema unchanged. MCP output schemas, annotations and other
    catalogue metadata remain on the MCP side; they are not model parameters.
    This helper neither contacts the server/model nor executes a tool.
    """
    if not isinstance(mcp_tools, list):
        raise ValueError("MCP tools must be a list of serialized catalogue dictionaries.")
    converted = []
    for tool in mcp_tools:
        if not isinstance(tool, dict) or not {"name", "description", "inputSchema"} <= tool.keys():
            raise ValueError("Each MCP tool needs name, description and inputSchema.")
        converted.append({"type": "function", "function": {
            "name": tool["name"], "description": tool["description"],
            "parameters": deepcopy(tool["inputSchema"]),
        }})
    _validate_tools(converted)
    return converted


def _validate_tools(tools: list[dict] | None) -> dict[str, dict]:
    """Check the provider catalogue without weakening its argument schemas."""
    if tools is None:
        return {}
    if not isinstance(tools, list):
        raise ValueError("Tools must be a list of function definitions or None.")
    definitions = {}
    for tool in tools:
        if not isinstance(tool, dict) or set(tool) != {"type", "function"} or tool["type"] != "function":
            raise ValueError("Each tool needs only type='function' and a function definition.")
        function = tool["function"]
        if not isinstance(function, dict) or set(function) != {"name", "description", "parameters"}:
            raise ValueError("A tool function needs only name, description and parameters.")
        name = function["name"]
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("Tool names must be nonblank strings without surrounding whitespace.")
        if name in definitions:
            raise ValueError(f"Duplicate tool name: {name!r}.")
        if not isinstance(function["description"], str) or not function["description"].strip():
            raise ValueError("Tool descriptions must be nonblank strings.")
        parameters = function["parameters"]
        if not isinstance(parameters, dict) or parameters.get("type") != "object":
            raise ValueError("Tool parameters must be a JSON Schema object with type='object'.")
        if parameters.get("$schema", _SCHEMA_DIALECT) != _SCHEMA_DIALECT:
            raise ValueError("Tool parameters must use JSON Schema Draft 2020-12.")
        try:
            Draft202012Validator.check_schema(parameters)
        except SchemaError as error:
            raise ValueError(f"Invalid parameter schema for {name!r}: {error.message}") from error
        definitions[name] = function
    # Fail before HTTP if values contain NaN, infinity, unsupported objects or
    # invalid Unicode. Do not trim names/descriptions or rewrite schema contents.
    json.dumps(tools, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return definitions


def _validate_tool_calls(
    calls: object, definitions: dict[str, dict], *, require_known: bool,
) -> list[dict]:
    """Validate a request list; retain argument values, order and provider IDs.

    Historical calls may name tools no longer advertised on the current turn.
    Newly generated calls must name a currently declared tool. No JSON strings
    are decoded into arguments, defaults inserted, or model mistakes repaired.
    """
    if not isinstance(calls, list):
        raise ValueError("tool_calls must be a list.")
    identifiers = set()
    for call in calls:
        if not isinstance(call, dict) or not {"function"} <= call.keys() or call.keys() - {"function", "id", "type"}:
            raise ValueError("Each tool call needs function and only optional id/type fields.")
        if "type" in call and call["type"] != "function":
            raise ValueError("Only function tool calls are supported.")
        if "id" in call:
            identifier = call["id"]
            if not isinstance(identifier, str) or not identifier.strip() or identifier in identifiers:
                raise ValueError("Tool call IDs must be unique nonblank strings within a request list.")
            identifiers.add(identifier)
        function = call["function"]
        if (
            not isinstance(function, dict) or not {"name", "arguments"} <= function.keys()
            or function.keys() - {"name", "arguments", "index"}
        ):
            raise ValueError("Tool calls require function name and object arguments, with only optional index.")
        name = function["name"]
        if not isinstance(name, str) or not name.strip() or name != name.strip():
            raise ValueError("Tool call names must be nonblank strings without surrounding whitespace.")
        if not isinstance(function["arguments"], dict):
            raise ValueError("Tool call arguments must be an object, not encoded JSON text.")
        if "index" in function and (type(function["index"]) is not int or function["index"] < 0):
            raise ValueError("Tool function index must be a nonnegative integer.")
        if require_known and name not in definitions:
            raise ValueError(f"The model requested undeclared tool {name!r}.")
        if name in definitions:
            # An empty registry prevents JSON Schema references from fetching
            # external URLs/files. Local self-contained references still work.
            validator = Draft202012Validator(definitions[name]["parameters"], registry=Registry())
            try:
                problem = next(validator.iter_errors(function["arguments"]), None)
            except (Unresolvable, RecursionError) as error:
                raise ValueError(f"Cannot resolve the declared argument schema for {name!r}.") from error
            if problem is not None:
                raise ValueError(f"Invalid arguments for tool {name!r}: {problem.message}")
    json.dumps(calls, ensure_ascii=False, allow_nan=False).encode("utf-8")
    return calls


def _validate_chat_messages(messages: list[dict], definitions: dict[str, dict]) -> None:
    """Check replayable text/tool history without executing or rewriting it.

    Results follow the original call order, with IDs checked when present.
    The hosted transport also requires IDs when it serializes the history.
    Reject incomplete or mismatched histories before continuing.
    """
    if not isinstance(messages, list) or not messages:
        raise ValueError("Supply a nonempty list of chat messages.")
    pending = []
    for message in messages:
        if not isinstance(message, dict) or not {"role", "content"} <= message.keys() or not isinstance(message["content"], str):
            raise ValueError("Each message needs role and string content.")
        role = message["role"]
        if pending and role != "tool":
            raise ValueError("Supply a tool result for every pending call before continuing the conversation.")
        if role in ("system", "user"):
            if set(message) != {"role", "content"}:
                raise ValueError("System/user messages support only role and text content; images remain unsupported.")
        elif role == "assistant":
            if message.keys() - {"role", "content", "thinking", "tool_calls"}:
                raise ValueError("Assistant history supports only role, content, thinking and tool_calls.")
            if "thinking" in message and not isinstance(message["thinking"], str):
                raise ValueError("Assistant thinking must be preserved as text.")
            if "tool_calls" in message:
                calls = _validate_tool_calls(message["tool_calls"], definitions, require_known=False)
                pending = list(calls)
        elif role == "tool":
            if message.keys() - {"role", "content", "tool_name", "tool_call_id"}:
                raise ValueError("Tool messages support only role, content, tool_name and optional tool_call_id.")
            if not isinstance(message.get("tool_name"), str) or not message["tool_name"].strip() or not pending:
                raise ValueError("A tool result needs tool_name and a preceding unanswered tool call.")
            if "tool_call_id" in message:
                identifier = message["tool_call_id"]
                if not isinstance(identifier, str) or not identifier.strip():
                    raise ValueError("tool_call_id must be a nonblank string.")
                if pending[0].get("id") != identifier:
                    raise ValueError("tool_call_id must match the next pending call in original order.")
            if pending[0]["function"]["name"] != message["tool_name"]:
                raise ValueError("Tool result name must match the next pending call in original order.")
            pending.pop(0)
        else:
            raise ValueError("Message role must be system, user, assistant or tool.")
    if pending:
        raise ValueError("The conversation ends with tool calls that still need results.")


def _json_object(raw: bytes) -> dict:
    data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_fields, parse_constant=_reject_constant)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


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
