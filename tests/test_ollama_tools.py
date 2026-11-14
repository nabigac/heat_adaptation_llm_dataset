"""Check tool descriptions and conversation transport without a real model.

Controlled responses establish what we accept, preserve and reject. These tests
do not establish that Qwen chooses useful tools; the live development diagnostic
checks the installed renderer, reported counts and a small model exchange.
"""

import asyncio
import copy
import json

import httpx
import pytest

import models


@pytest.fixture
def settings(run_record):
    return copy.deepcopy(run_record["settings"])


@pytest.fixture
def catalogue():
    return [
        {"name": "get_page_text", "description": "Read a physical PDF page, counting from 1.",
         "inputSchema": {"type": "object", "properties": {"page_number": {"type": "integer", "minimum": 1}},
                         "required": ["page_number"], "additionalProperties": False},
         "outputSchema": {"type": "object"}, "annotations": {"readOnlyHint": True}},
        {"name": "find_quote", "description": "Find exact source wording without changing whitespace.",
         "inputSchema": {"type": "object", "properties": {"quote": {"type": "string", "minLength": 1}},
                         "required": ["quote"], "additionalProperties": False}},
    ]


@pytest.fixture
def tools(catalogue):
    return models.prepare_ollama_tools(catalogue)


def tool_call(name="get_page_text", arguments=None, **fields):
    return {"function": {"name": name, "arguments": {"page_number": 3} if arguments is None else arguments}, **fields}


def history(calls=None, results=None):
    calls = [tool_call(id="call_page")] if calls is None else calls
    results = [{"role": "tool", "tool_name": "get_page_text", "tool_call_id": "call_page",
                "content": '{"page_number":3,"text":"Fictional source — £500."}'}] if results is None else results
    return [{"role": "system", "content": "Extract from fictional source."},
            {"role": "user", "content": "Read page 3 before answering."},
            {"role": "assistant", "content": "", "thinking": "Keep this exact.\r\n", "tool_calls": calls},
            *results]


def reply(monkeypatch, settings, message, *, tools=None, **changes):
    """Isolate response interpretation; real preflight is covered separately."""
    async def count(client, url, body, result, models_directory):
        result.report.update(fits=True, input_tokens=21)
    monkeypatch.setattr(models, "_check_token_budget", count)
    payload = {"done": True, "done_reason": "stop", "message": message,
               "prompt_eval_count": 21, "eval_count": 5, **changes}
    raw = json.dumps(payload, ensure_ascii=False, allow_nan=True).encode("utf-8")
    requests = []
    def handle(request):
        requests.append(request)
        return httpx.Response(200, content=raw)
    result = asyncio.run(models.request_ollama_chat(settings, [{"role": "user", "content": "Fictional request."}],
        tools=tools, _transport=httpx.MockTransport(handle)))
    assert len(requests) == 1  # No tool execution, follow-up generation or automatic retry.
    assert result.raw_response == raw
    return result


def test_conversion_preserves_complete_input_schemas_and_detaches_mutable_values(catalogue):
    original = copy.deepcopy(catalogue)
    converted = models.prepare_ollama_tools(catalogue)
    for actual, source in zip(converted, catalogue, strict=True):
        assert actual == {"type": "function", "function": {
            "name": source["name"], "description": source["description"], "parameters": source["inputSchema"],
        }}
    converted[0]["function"]["parameters"]["properties"]["page_number"]["minimum"] = 50
    assert catalogue == original
    assert models.prepare_ollama_tools([]) == []


@pytest.mark.parametrize("catalogue", [None, {}, ["tool"], [{}], [{"name": "read"}],
    [{"name": "read", "description": "Read.", "input_schema": {"type": "object"}}]])
def test_conversion_requires_serialized_mcp_catalogue_fields(catalogue):
    with pytest.raises(ValueError):
        models.prepare_ollama_tools(catalogue)


@pytest.mark.parametrize("damage", ["not-list", "not-function", "extra-tool-field", "missing-description",
    "blank-name", "padded-name", "duplicate-name", "blank-description", "nonobject-parameters",
    "nonobject-type", "invalid-schema", "different-dialect", "nonfinite", "unencodable"])
def test_bad_tool_definitions_are_rejected_before_http(settings, tools, damage):
    function = tools[0]["function"]
    if damage == "not-list": tools = {}
    elif damage == "not-function": tools[0]["type"] = "code"
    elif damage == "extra-tool-field": tools[0]["unexpected"] = True
    elif damage == "missing-description": del function["description"]
    elif damage == "blank-name": function["name"] = " "
    elif damage == "padded-name": function["name"] = " get_page_text "
    elif damage == "duplicate-name": tools.append(copy.deepcopy(tools[0]))
    elif damage == "blank-description": function["description"] = " "
    elif damage == "nonobject-parameters": function["parameters"] = True
    elif damage == "nonobject-type": function["parameters"]["type"] = "array"
    elif damage == "invalid-schema": function["parameters"]["required"] = "page_number"
    elif damage == "different-dialect": function["parameters"]["$schema"] = "https://example.org/unknown"
    elif damage == "nonfinite": function["parameters"]["maximum"] = float("inf")
    elif damage == "unencodable": function["description"] = "\ud800"
    with pytest.raises((ValueError, TypeError)):
        models.build_ollama_request(settings, [{"role": "user", "content": "Source."}], tools=tools)


def test_request_preserves_tools_format_thinking_calls_ids_and_exact_result_text(settings, tools):
    messages = history()
    messages[2]["tool_calls"][0]["function"]["index"] = 0
    before_messages, before_tools = copy.deepcopy(messages), copy.deepcopy(tools)
    schema = models.prepare_ollama_response_schema()
    _, body, _ = models.build_ollama_request(settings, messages, tools=tools, response_format=schema)
    assert body["tools"] == tools and body["messages"] == messages and body["format"] == schema
    body["messages"][2]["thinking"] = "Changed only in returned body."
    body["tools"][0]["function"]["parameters"].clear()
    assert messages == before_messages and tools == before_tools


def test_empty_catalogue_can_disable_new_tools_while_replaying_completed_history(settings):
    _, body, _ = models.build_ollama_request(settings, history(), tools=[])
    assert body["tools"] == []
    assert body["messages"] == history()


def test_multiple_results_preserve_original_order_with_or_without_ids(settings, tools):
    calls = [tool_call(id="page"), tool_call("find_quote", {"quote": "Café"}, id="quote")]
    results = [{"role": "tool", "tool_name": "get_page_text", "tool_call_id": "page", "content": "Source."},
               {"role": "tool", "tool_name": "find_quote", "tool_call_id": "quote", "content": "[]"}]
    models.build_ollama_request(settings, history(calls, results), tools=tools)
    no_ids = history([tool_call(), tool_call("find_quote", {"quote": "Café"})], [
        {"role": "tool", "tool_name": "get_page_text", "content": "Source."},
        {"role": "tool", "tool_name": "find_quote", "content": "[]"},
    ])
    models.build_ollama_request(settings, no_ids, tools=tools)


@pytest.mark.parametrize("damage", ["orphan-result", "missing-result", "interrupted-results", "wrong-name",
    "wrong-id", "duplicate-result", "missing-name", "blank-id", "nontext-result", "unknown-field",
    "nontext-thinking", "user-tool-call", "images", "wrong-order", "wrong-order-with-ids", "incomplete-multiple"])
def test_incomplete_or_mismatched_history_is_rejected(settings, tools, damage):
    messages = history()
    if damage == "orphan-result": del messages[2]
    elif damage == "missing-result": messages.pop()
    elif damage == "interrupted-results": messages.insert(3, {"role": "user", "content": "Continue."})
    elif damage == "wrong-name": messages[-1]["tool_name"] = "find_quote"
    elif damage == "wrong-id": messages[-1]["tool_call_id"] = "other-call"
    elif damage == "duplicate-result": messages.append(copy.deepcopy(messages[-1]))
    elif damage == "missing-name": del messages[-1]["tool_name"]
    elif damage == "blank-id": messages[-1]["tool_call_id"] = ""
    elif damage == "nontext-result": messages[-1]["content"] = {"text": "Source."}
    elif damage == "unknown-field": messages[-1]["unexpected"] = True
    elif damage == "nontext-thinking": messages[2]["thinking"] = None
    elif damage == "user-tool-call": messages[1]["tool_calls"] = []
    elif damage == "images": messages[2]["images"] = ["unsupported"]
    elif damage == "wrong-order":
        messages[2]["tool_calls"].append(tool_call("find_quote", {"quote": "Source"}))
        messages[-1] = {"role": "tool", "tool_name": "find_quote", "content": "[]"}
    elif damage == "wrong-order-with-ids":
        messages[2]["tool_calls"].append(tool_call("find_quote", {"quote": "Source"}, id="quote"))
        messages.insert(3, {"role": "tool", "tool_name": "find_quote", "tool_call_id": "quote", "content": "[]"})
    elif damage == "incomplete-multiple": messages[2]["tool_calls"].append(tool_call())
    with pytest.raises(ValueError):
        models.build_ollama_request(settings, messages, tools=tools)


def test_tool_request_is_exposed_separately_from_final_answer_text(monkeypatch, settings, tools):
    calls = [tool_call(id="call_page")]
    message = {"role": "assistant", "content": "", "thinking": "Need the page.\n", "tool_calls": calls}
    result = reply(monkeypatch, settings, message, tools=tools)
    assert result.completion_status == "normal" and result.error is None
    assert result.response_text == "" and result.tool_calls == calls
    assert result.assistant_message == message
    result.tool_calls[0]["function"]["arguments"]["page_number"] = 5
    assert result.assistant_message == message
    final = reply(monkeypatch, settings, {"role": "assistant", "content": '{"answer":"done"}'}, tools=tools)
    assert final.tool_calls == [] and final.response_text == '{"answer":"done"}'


@pytest.mark.parametrize("calls", [None, {}, [None], [{}], [tool_call(arguments="{\"page_number\":3}")],
    [tool_call(arguments=[])], [tool_call(arguments={})], [tool_call(arguments={"page_number": 0})],
    [tool_call(arguments={"page_number": True})], [tool_call(arguments={"page_number": "3"})],
    [tool_call(arguments={"page_number": 3, "path": "unrelated-file"})],
    [tool_call("undeclared")], [tool_call(type="code")], [tool_call(id="")],
    [tool_call(id="same"), tool_call(id="same")],
    [{"function": {"name": "get_page_text", "arguments": {"page_number": 3}, "index": True}}],
    [{"function": {"name": "get_page_text", "arguments": {"page_number": 3}, "index": -1}}],
    [{"function": {"name": "get_page_text", "arguments": {"page_number": 3}, "extra": True}}],
])
def test_bad_model_tool_requests_fail_with_raw_message_retained(monkeypatch, settings, tools, calls):
    message = {"role": "assistant", "content": "", "tool_calls": calls}
    result = reply(monkeypatch, settings, message, tools=tools)
    assert result.completion_status == "failed" and result.error
    assert result.assistant_message == message and result.tool_calls == []


def test_unadvertised_tool_request_is_not_exposed_as_executable(monkeypatch, settings):
    result = reply(monkeypatch, settings, {"role": "assistant", "content": "", "tool_calls": [tool_call()]})
    assert "undeclared" in result.error and result.tool_calls == []


@pytest.mark.parametrize("changes", [
    {"done_reason": "length"}, {"done_reason": None}, {"done": False}, {"prompt_eval_count": 22},
])
def test_failed_truncated_or_unconfirmed_tool_requests_are_not_executable(monkeypatch, settings, tools, changes):
    result = reply(monkeypatch, settings, {"role": "assistant", "content": "", "tool_calls": [tool_call()]},
                   tools=tools, **changes)
    assert result.error is not None and result.tool_calls == []
    assert result.assistant_message["tool_calls"]
    if changes.get("done_reason") == "length":
        assert result.completion_status == "truncated" and result.truncated is True


def test_local_schema_references_are_supported_without_external_retrieval(monkeypatch, settings, tools):
    schema = tools[0]["function"]["parameters"]
    schema["$defs"] = {"page": schema["properties"]["page_number"]}
    schema["properties"]["page_number"] = {"$ref": "#/$defs/page"}
    result = reply(monkeypatch, settings, {"role": "assistant", "content": "", "tool_calls": [tool_call()]}, tools=tools)
    assert result.error is None and result.tool_calls
    schema["properties"]["page_number"] = {"$ref": "https://example.org/must-not-fetch"}
    result = reply(monkeypatch, settings, {"role": "assistant", "content": "", "tool_calls": [tool_call()]}, tools=tools)
    assert result.error and result.tool_calls == []
