"""Validate MCP conversion and shared tool history without network calls."""

import copy
import pytest
import models


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
    return models.prepare_document_tools(catalogue)


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


def test_conversion_preserves_complete_input_schemas_and_detaches_mutable_values(catalogue):
    original = copy.deepcopy(catalogue)
    converted = models.prepare_document_tools(catalogue)
    for actual, source in zip(converted, catalogue, strict=True):
        assert actual == {"type": "function", "function": {
            "name": source["name"], "description": source["description"], "parameters": source["inputSchema"],
        }}
    converted[0]["function"]["parameters"]["properties"]["page_number"]["minimum"] = 50
    assert catalogue == original
    assert models.prepare_document_tools([]) == []


@pytest.mark.parametrize("catalogue", [None, {}, ["tool"], [{}], [{"name": "read"}],
    [{"name": "read", "description": "Read.", "input_schema": {"type": "object"}}]])
def test_conversion_requires_serialized_mcp_catalogue_fields(catalogue):
    with pytest.raises(ValueError):
        models.prepare_document_tools(catalogue)


@pytest.mark.parametrize("damage", ["not-list", "not-function", "extra-tool-field", "missing-description",
    "blank-name", "padded-name", "duplicate-name", "blank-description", "nonobject-parameters",
    "nonobject-type", "invalid-schema", "different-dialect", "nonfinite", "unencodable"])
def test_bad_tool_definitions_are_rejected(tools, damage):
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
        models._validate_tools(tools)


def test_multiple_results_preserve_original_order_with_or_without_ids(tools):
    calls = [tool_call(id="page"), tool_call("find_quote", {"quote": "Café"}, id="quote")]
    results = [{"role": "tool", "tool_name": "get_page_text", "tool_call_id": "page", "content": "Source."},
               {"role": "tool", "tool_name": "find_quote", "tool_call_id": "quote", "content": "[]"}]
    models._validate_chat_messages(history(calls, results), models._validate_tools(tools))
    no_ids = history([tool_call(), tool_call("find_quote", {"quote": "Café"})], [
        {"role": "tool", "tool_name": "get_page_text", "content": "Source."},
        {"role": "tool", "tool_name": "find_quote", "content": "[]"},
    ])
    models._validate_chat_messages(no_ids, models._validate_tools(tools))


@pytest.mark.parametrize("damage", ["orphan-result", "missing-result", "interrupted-results", "wrong-name",
    "wrong-id", "duplicate-result", "missing-name", "blank-id", "nontext-result", "unknown-field",
    "nontext-thinking", "user-tool-call", "images", "wrong-order", "wrong-order-with-ids", "incomplete-multiple"])
def test_incomplete_or_mismatched_history_is_rejected(tools, damage):
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
        models._validate_chat_messages(messages, models._validate_tools(tools))


def test_argument_schemas_resolve_internal_references_and_reject_external_ones(tools):
    schema = tools[0]["function"]["parameters"]
    schema["$defs"] = {"page": schema["properties"]["page_number"]}
    schema["properties"]["page_number"] = {"$ref": "#/$defs/page"}
    calls = [tool_call()]
    assert models._validate_tool_calls(calls, models._validate_tools(tools), require_known=True) == calls
    schema["properties"]["page_number"] = {"$ref": "https://example.org/must-not-fetch"}
    with pytest.raises(ValueError, match="resolve"):
        models._validate_tool_calls(calls, models._validate_tools(tools), require_known=True)
