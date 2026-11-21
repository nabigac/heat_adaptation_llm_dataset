"""Exercise hosted protocol and saved execution with no real API or credentials."""

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import time

import httpx
import pytest
from jsonschema import Draft202012Validator

import agents
import huggingface_api as hf
import storage
import test_agent_loop as loop
from validation import validate_agent_response


project = loop.project
MODEL = "thinkingmachines/Inkling-2-Small"
DEEPSEEK_MODEL = "deepseek-ai/DeepSeek-V4.1-Flash-1017"
DEEPSEEK_ROUTER_MODEL = "deepseek/deepseek-v4.1-flash-1017"
GLM_MODEL = "zai-org/GLM-5.3-Flash"
GLM_ROUTER_MODEL = "z-ai/glm-5.3-flash"
TOKEN = "fictional-hf-token-for-tests"
TOOLS = [{"type": "function", "function": {
    "name": "get_page_text", "description": "Read a page.", "parameters": {
        "type": "object", "properties": {"page_number": {"type": "integer", "minimum": 1}},
        "required": ["page_number"], "additionalProperties": False,
    },
}}]


@pytest.fixture
def settings(run_record, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    value = deepcopy(run_record["settings"])
    value["model"].update(name=MODEL, execution_mode="hosted_api", api_service="huggingface",
                          provider="deepinfra", endpoint=hf.HF_ENDPOINT)
    value["context_limit"] = 262144
    return value


def envelope(content="answer", *, calls=None, finish="stop", **changes):
    message = {"role": "assistant", "content": content}
    if calls is not None:
        message["tool_calls"] = calls
    data = {"id": "fictional-response", "model": MODEL,
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}}
    data.update(changes)
    return data


def tool_call(*, arguments='{"page_number":1}', name="get_page_text", identifier="page-1"):
    return {"id": identifier, "type": "function", "function": {"name": name, "arguments": arguments}}


def request(settings, data, *, tools=None, status=200, messages=None, progress=None):
    requests = []
    def handler(req):
        requests.append(req)
        return httpx.Response(status, content=data if isinstance(data, bytes) else json.dumps(data).encode())
    prepared = hf.build_huggingface_request(
        settings, messages or [{"role": "user", "content": "Fictional source."}],
        tools=tools, response_format={"type": "object"} if not tools else None,
    )
    result = asyncio.run(hf.request_huggingface_chat(prepared,
        _transport=httpx.MockTransport(handler), on_progress=progress))
    return result, requests


def test_wire_request_pins_provider_preserves_schema_and_omits_secrets(settings):
    messages = [{"role": "system", "content": "Use source."}, {"role": "user", "content": "Plan £."}]
    schema = {"type": "object", "additionalProperties": False, "properties": {}}
    settings["generation"].update(temperature=0, top_p=0.9, seed=0)
    before = deepcopy((settings, messages, schema))
    prepared = hf.build_huggingface_request(settings, messages, response_format=schema)
    body = prepared.body
    assert prepared.url == hf.HF_ENDPOINT + "/chat/completions"
    assert body["model"] == MODEL + ":deepinfra"
    assert body["temperature"] == 0 and body["seed"] == 0 and body["top_p"] == 0.9
    assert body["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "heat_adaptation_extraction", "strict": True, "schema": schema}}
    assert "JSON Schema" in body["messages"][-1]["content"]
    assert body["messages"][:-1] == messages
    assert (settings, messages, schema) == before
    assert TOKEN not in json.dumps(body)


@pytest.mark.parametrize("reported", [
    DEEPSEEK_MODEL, DEEPSEEK_MODEL.lower(), DEEPSEEK_MODEL + ":deepinfra",
    DEEPSEEK_ROUTER_MODEL, DEEPSEEK_ROUTER_MODEL.upper(),
])
def test_deepseek_exact_identity_and_verified_alias_preserve_wire_and_raw_names(settings, reported):
    settings["model"]["name"] = DEEPSEEK_MODEL
    data = envelope('{"compatible":true}', model=reported)
    result, sent = request(settings, data)
    assert result.error is None and result.completion_status == "normal"
    assert json.loads(sent[0].content)["model"] == DEEPSEEK_MODEL + ":deepinfra"
    assert json.loads(result.raw_response)["model"] == reported
    assert result.response_text == '{"compatible":true}'


@pytest.mark.parametrize("reported", [
    "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash-1018",
    "deepseek-ai/DeepSeek-V4.1-Flash-1018", "other-owner/deepseek-v4.1-flash-1017",
    DEEPSEEK_ROUTER_MODEL + "-extra", DEEPSEEK_ROUTER_MODEL + ":other-host", MODEL, 123,
])
def test_deepseek_alias_does_not_accept_other_models_namespaces_or_checkpoints(settings, reported):
    settings["model"]["name"] = DEEPSEEK_MODEL
    result, sent = request(settings, envelope(model=reported))
    assert result.completion_status == "failed" and "model identity" in result.error
    assert len(sent) == 1 and json.loads(result.raw_response)["model"] == reported


@pytest.mark.parametrize("expected", [MODEL, GLM_MODEL, "deepseek-ai/DeepSeek-V4.1-Flash",
                                     "deepseek-ai/DeepSeek-V4.1-Flash-1018"])
def test_verified_alias_is_not_reused_for_other_selected_models(settings, expected):
    settings["model"]["name"] = expected
    result, _ = request(settings, envelope(model=DEEPSEEK_ROUTER_MODEL))
    assert result.completion_status == "failed" and "model identity" in result.error


@pytest.mark.parametrize("reported", [
    GLM_MODEL, GLM_MODEL.lower(), GLM_MODEL + ":deepinfra",
    GLM_ROUTER_MODEL, GLM_ROUTER_MODEL.upper(),
])
def test_glm_exact_identity_and_verified_alias_preserve_wire_and_raw_names(settings, reported):
    settings["model"]["name"] = GLM_MODEL
    data = envelope('{"compatible":true}', model=reported)

    result, sent = request(settings, data)

    assert result.error is None and result.completion_status == "normal"
    assert json.loads(sent[0].content)["model"] == GLM_MODEL + ":deepinfra"
    assert json.loads(result.raw_response)["model"] == reported
    assert result.response_text == '{"compatible":true}'


@pytest.mark.parametrize("reported", [
    "z-ai/glm-5.3", "z-ai/glm-5.2-flash", "z-ai/glm-5.3-flashx",
    "z-ai/glm-5.3-flash-uncensored", "other-owner/glm-5.3-flash",
    GLM_ROUTER_MODEL + ":other-host", DEEPSEEK_ROUTER_MODEL, MODEL, 123,
])
def test_glm_alias_rejects_other_models_namespaces_and_variants(settings, reported):
    settings["model"]["name"] = GLM_MODEL

    result, sent = request(settings, envelope(model=reported))

    assert result.completion_status == "failed" and "model identity" in result.error
    assert len(sent) == 1 and json.loads(result.raw_response)["model"] == reported


@pytest.mark.parametrize("expected", [MODEL, DEEPSEEK_MODEL, "zai-org/GLM-5.3", "zai-org/GLM-5.2-Flash"])
def test_glm_alias_is_not_reused_for_other_selected_models(settings, expected):
    settings["model"]["name"] = expected

    result, _ = request(settings, envelope(model=GLM_ROUTER_MODEL))

    assert result.completion_status == "failed" and "model identity" in result.error


def test_sending_uses_prepared_bytes_and_limits_after_callers_edit_inputs(settings, monkeypatch):
    messages = [{"role": "user", "content": "Preserve this source — £500."}]
    prepared = hf.build_huggingface_request(settings, messages)
    original_bytes = prepared.body_bytes
    settings["model"]["name"] = "different/model"
    settings["context_limit"] = 1
    settings["generation"]["max_output_tokens"] = 1
    messages[0]["content"] = "Changed after preparation."
    inspected_body = prepared.body
    inspected_body["messages"][0]["content"] = "Changed while inspecting."
    def forbidden(*args, **options):
        pytest.fail("Sending must not rebuild a prepared request.")
    monkeypatch.setattr(hf, "build_huggingface_request", forbidden)
    sent = []
    def handle(request):
        sent.append(request.content)
        return httpx.Response(200, json=envelope())
    result = asyncio.run(hf.request_huggingface_chat(prepared, _transport=httpx.MockTransport(handle)))
    assert result.error is None and sent == [original_bytes]
    assert prepared.body["messages"][0]["content"] == "Preserve this source — £500."
    assert result.token_budget.report["request_bytes"] == len(original_bytes)
    assert result.token_budget.report["max_output_tokens"] == prepared.max_output_tokens


@pytest.mark.parametrize("field,value", [
    ("usage", []), ("usage", False), ("usage", 0), ("usage", ""),
    ("tool_calls", {}), ("tool_calls", False), ("tool_calls", 0), ("tool_calls", ""),
])
def test_malformed_optional_containers_fail_with_raw_bytes_preserved(settings, field, value):
    data = envelope()
    target = data if field == "usage" else data["choices"][0]["message"]
    target[field] = value
    raw = json.dumps(data).encode()
    result, sent = request(settings, raw)
    assert result.completion_status == "failed" and field in result.error
    assert result.raw_response == raw and len(sent) == 1 and result.tool_calls == []


@pytest.mark.parametrize("field,value", [
    ("usage", None), ("usage", {}), ("tool_calls", None), ("tool_calls", []),
])
def test_valid_empty_optional_metadata_is_accepted(settings, field, value):
    data = envelope()
    target = data if field == "usage" else data["choices"][0]["message"]
    target[field] = value
    result, _ = request(settings, data)
    assert result.error is None and result.completion_status == "normal"


def test_deepinfra_requests_strict_schema_without_changing_the_contract(settings):
    settings["model"]["provider"] = "deepinfra"
    settings["generation"]["max_output_tokens"] = 131072
    schema = agents.prepare_response_schema()
    messages = [{"role": "user", "content": "Fictional source."}]
    before = deepcopy((settings, schema, messages))
    prepared = hf.build_huggingface_request(settings, messages, response_format=schema)
    body = prepared.body
    assert body["model"] == MODEL + ":deepinfra" and body["max_tokens"] == 131072
    assert body["response_format"] == {"type": "json_schema", "json_schema": {
        "name": "heat_adaptation_extraction", "strict": True,
        "schema": hf.prepare_deepinfra_response_schema(schema),
    }}
    assert body["messages"][:-1] == messages
    assert (settings, schema, messages) == before


def test_deepinfra_schema_preserves_structural_rules_and_literal_property_names():
    schema = {
        "type": "object", "required": ["uniqueItems", "if", "values"], "additionalProperties": False,
        "properties": {
            "uniqueItems": {"type": "boolean", "const": True},
            "if": {"const": {"if": "literal", "uniqueItems": True}},
            "values": {"type": "array", "minItems": 1, "uniqueItems": True,
                       "items": {"type": "string", "enum": ["a", "b"]}},
        },
        "allOf": [{"if": {"properties": {"uniqueItems": {"const": True}}},
                   "then": {"properties": {"values": {"maxItems": 2}}},
                   "else": {"properties": {"values": {"maxItems": 3}}}}],
    }
    original = deepcopy(schema)
    expected = deepcopy(schema)
    del expected["properties"]["values"]["uniqueItems"]
    expected["allOf"] = [{}]
    converted = hf.prepare_deepinfra_response_schema(schema)
    assert converted == expected and schema == original
    converted["properties"]["values"]["items"]["enum"].append("c")
    assert schema == original


@pytest.mark.parametrize("failure", ["duplicate-types", "duplicate-pages", "open-with-resolution", "resolved-without-resolution"])
def test_python_retains_rules_omitted_from_the_generation_schema(run_record, failure):
    response = json.loads(loop.answer(run_record))
    action = response["plan_data"]["actions"][0]
    if failure == "duplicate-types":
        action["action_type"] *= 2
    elif failure == "duplicate-pages":
        action["evidence"][0]["page_numbers"] *= 2
    else:
        response["plan_issues"]["issues"] = [{
            "issue_id": "issue_0001", "related_action_id": action["action_id"],
            "issue_description": "Fictional uncertainty.", "issue_type": "unclear_meaning",
            "issue_origin": "extractor", "issue_status": "open", "resolved_by": None, "resolution": None,
        }]
        issue = response["plan_issues"]["issues"][0]
        if failure == "open-with-resolution":
            issue.update(resolved_by="extractor", resolution="Fictional claimed resolution.")
        else:
            issue["issue_status"] = "resolved"
    schema = hf.prepare_deepinfra_response_schema(agents.prepare_response_schema())
    # These answers satisfy the provider's structural copy but must never pass
    # the unchanged dataset rules used to accept an extraction.
    assert not list(Draft202012Validator(schema).iter_errors(response))
    assert validate_agent_response(response, page_count=3, stage="extractor")


def test_other_hosts_do_not_receive_deepinfra_schema_adaptations(settings):
    settings["model"]["provider"] = "other-host"
    schema = agents.prepare_response_schema()
    prepared = hf.build_huggingface_request(settings, [{"role": "user", "content": "Source."}], response_format=schema)
    body = prepared.body
    assert body["response_format"]["json_schema"]["schema"] == schema


@pytest.mark.parametrize("limit", [32768, 131072])
@pytest.mark.parametrize("offset,accepted", [(-1, True), (0, True), (1, False)])
def test_hosted_output_limit_counts_all_reported_tokens_including_reasoning(settings, limit, offset, accepted):
    settings["model"]["provider"] = "deepinfra"
    settings["generation"]["max_output_tokens"] = limit
    tokens = limit + offset
    data = envelope(usage={"prompt_tokens": 100, "completion_tokens": tokens,
                           "completion_tokens_details": {"reasoning_tokens": 5555}})
    result, _ = request(settings, data)
    assert result.output_tokens == tokens
    assert (result.error is None) == accepted
    if not accepted:
        assert "output limit" in result.error
        assert result.completion_status == "failed"


def test_deepinfra_schema_rejection_is_preserved_without_json_mode_fallback(settings):
    settings["model"]["provider"] = "deepinfra"
    result, sent = request(settings, {"error": {"message": "Unsupported schema keyword"}}, status=400)
    assert len(sent) == 1 and json.loads(sent[0].content)["response_format"]["type"] == "json_schema"
    assert result.completion_status == "failed" and "Unsupported schema keyword" in result.error


def test_usage_and_estimate_are_distinct_and_request_is_authenticated(settings):
    result, sent = request(settings, envelope())
    assert result.completion_status == "normal" and result.error is None
    assert (result.input_tokens, result.output_tokens) == (100, 10)
    assert result.token_budget.report["input_tokens"] is None
    assert result.token_budget.report["counting_mode"] == "conservative_estimate"
    assert result.token_budget.report["estimated_input_tokens"] > 8192
    assert sent[0].headers["Authorization"] == "Bearer " + TOKEN
    assert len(sent) == 1 and result.generation_started


@pytest.mark.parametrize("change", [
    {"endpoint": "https://other.example/v1"},
    {"endpoint": hf.HF_ENDPOINT + "?token=secret"},
    {"endpoint": "http://router.huggingface.co/v1"},
    {"provider": "auto"}, {"provider": "fastest"}, {"provider": "deepinfra:other"},
    {"name": MODEL + ":deepinfra"}, {"api_service": "other"},
])
def test_invalid_hosted_selection_is_rejected_before_network(settings, change):
    settings["model"].update(change)
    with pytest.raises(ValueError):
        hf.build_huggingface_request(settings, [{"role": "user", "content": "Plan."}])


def test_missing_credentials_never_sends_a_request(settings, monkeypatch):
    monkeypatch.delenv("HF_TOKEN")
    with pytest.raises(ValueError, match="HF_TOKEN"):
        request(settings, envelope())


def test_over_budget_preflight_does_not_generate_or_truncate_source(settings):
    settings["context_limit"] = settings["generation"]["max_output_tokens"] + 1
    result, sent = request(settings, envelope())
    assert not sent and not result.generation_started
    assert result.completion_status == "failed" and "estimate" in result.error
    assert result.input_tokens is None and not result.token_budget.report["fits"]


def test_tool_calls_are_decoded_validated_and_replayed_with_ids(settings):
    result, _ = request(settings, envelope(None, calls=[tool_call()], finish="tool_calls"), tools=TOOLS)
    assert result.error is None
    assert result.tool_calls[0]["function"]["arguments"] == {"page_number": 1}
    assert result.assistant_message["tool_calls"] == result.tool_calls
    messages = [{"role": "user", "content": "Plan."}, result.assistant_message,
                {"role": "tool", "tool_name": "get_page_text", "tool_call_id": "page-1", "content": "Page text."}]
    prepared = hf.build_huggingface_request(settings, messages, tools=[])
    body = prepared.body
    assert body["messages"][1]["tool_calls"][0]["function"]["arguments"] == '{"page_number": 1}'
    assert body["messages"][2] == {"role": "tool", "name": "get_page_text", "tool_call_id": "page-1", "content": "Page text."}
    assert "tools" not in body


@pytest.mark.parametrize("call", [
    tool_call(arguments="not JSON"), tool_call(arguments='{"page_number":0}'),
    tool_call(arguments='{"page_number":true}'), tool_call(arguments="[]"),
    tool_call(name="delete_file"), tool_call(identifier=""),
    tool_call(arguments='{"page_number":1,"page_number":2}'),
])
def test_invalid_calls_never_become_executable(settings, call):
    result, _ = request(settings, envelope(None, calls=[call], finish="tool_calls"), tools=TOOLS)
    assert result.completion_status == "failed" and result.tool_calls == []
    assert result.input_tokens == 100 and result.raw_response


@pytest.mark.parametrize("data,status", [
    (b"not-json", 200), (b"\xff", 200), (b"[]", 200),
    (b'{"choices":[],"choices":[]}', 200), (b'{"usage":NaN}', 200),
    (envelope(choices=[]), 200),
    (envelope(finish="content_filter"), 200), (envelope(model="other/model"), 200),
    (envelope(usage={"prompt_tokens": True}), 200),
    (envelope(None), 200), (envelope({"invalid": "content"}), 200),
    (envelope(finish="tool_calls"), 200),
    ({"error": {"message": "Rate limited"}}, 429),
    ({"error": {"message": "Invalid credential"}}, 401),
    (envelope(), 503), (envelope(), 302),
    (envelope(error="Controlled provider error"), 200),
])
def test_failures_are_preserved_without_retry(settings, data, status):
    result, sent = request(settings, data, status=status)
    assert result.completion_status == "failed" and result.error
    assert result.raw_response and len(sent) == 1 and result.tool_calls == []


def test_nested_provider_error_reports_the_actual_reason_and_preserves_usage(settings):
    reason = "Model does not support 'json_schema' response format. Supported formats: json_object."
    data = {"error": {"message": "Provider returned error", "metadata": {
        "raw": json.dumps({"code": 400, "message": reason}), "provider_name": "DeepInfra",
    }}, "usage": {"prompt_tokens": 100, "completion_tokens": 0}}
    result, sent = request(settings, data, status=400)
    assert result.error == "Hugging Face HTTP 400: " + reason
    assert "completed choice" not in result.error
    assert (result.input_tokens, result.output_tokens) == (100, 0)
    assert json.loads(result.raw_response) == data and len(sent) == 1


@pytest.mark.parametrize("raw", ["not JSON", "[]", None, {"message": "Wrong metadata type"}])
def test_unreadable_nested_error_uses_router_explanation(settings, raw):
    data = {"error": {"message": "Permission denied", "metadata": {"raw": raw}}}
    result, _ = request(settings, data, status=403)
    assert result.error == "Hugging Face HTTP 403: Permission denied"


def test_length_finish_remains_truncated_even_with_complete_json(settings):
    result, _ = request(settings, envelope('{"valid":"JSON"}', finish="length"))
    assert result.truncated and result.completion_status == "truncated"
    assert result.input_tokens == 100 and result.response_text == '{"valid":"JSON"}'


def test_unavailable_usage_is_not_invented(settings):
    result, _ = request(settings, envelope(usage=None))
    assert result.error is None and result.input_tokens is None and result.output_tokens is None


def test_reported_zero_usage_is_retained_as_zero(settings):
    result, _ = request(settings, envelope(usage={"prompt_tokens": 0, "completion_tokens": 0}))
    assert result.error is None and result.input_tokens == 0 and result.output_tokens == 0


@pytest.mark.parametrize("extra,accepted", [(0, True), (1, False)])
def test_reported_total_usage_must_fit_the_context_limit(settings, extra, accepted):
    usage = {"prompt_tokens": settings["context_limit"] - 10 + extra, "completion_tokens": 10}
    result, sent = request(settings, envelope(usage=usage))
    assert (result.error is None) is accepted
    assert len(sent) == 1 and result.input_tokens == usage["prompt_tokens"]
    if not accepted:
        assert "context limit" in result.error


def test_preflight_headers_and_chunks_are_observed_in_order(settings):
    events = []
    raw = json.dumps(envelope()).encode()
    result, sent = request(settings, raw, progress=lambda event, payload: events.append((event, payload)))
    assert len(sent) == 1 and result.generation_started
    assert [event for event, _ in events] == ["preflight_complete", "response_headers", "response_chunk"]
    assert events[-1][1] == result.raw_response == raw


@pytest.mark.parametrize("failure_point", ["preflight_complete", "response_headers", "response_chunk"])
def test_evidence_callback_failure_stops_request_and_keeps_available_data(settings, failure_point):
    raw = json.dumps(envelope()).encode()
    def observer(event, payload):
        if event == failure_point:
            raise OSError("Controlled evidence failure.")
    result, sent = request(settings, raw, progress=observer)
    assert "preserve model evidence" in result.error
    assert result.generation_started is (failure_point != "preflight_complete")
    assert len(sent) == (0 if failure_point == "preflight_complete" else 1)
    if failure_point == "response_chunk":
        assert result.raw_response == raw


def test_expired_preflight_callback_does_not_start_a_paid_request(settings):
    settings["model_timeout_seconds"] = 0.01
    def slow_save(event, payload):
        if event == "preflight_complete":
            time.sleep(0.03)
    result, sent = request(settings, envelope(), progress=slow_save)
    assert not sent and not result.generation_started
    assert "timeout" in result.error


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_cancellation_keep_partial_received_bytes(settings, cancel):
    class PartialStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"partial":'
            if cancel:
                raise asyncio.CancelledError
            await asyncio.sleep(1)
    settings["model_timeout_seconds"] = 0.03
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=PartialStream()))
    async def run():
        prepared = hf.build_huggingface_request(settings, [{"role": "user", "content": "Plan."}])
        return await hf.request_huggingface_chat(prepared, _transport=transport)
    if cancel:
        from models import ModelRequestCancelled
        with pytest.raises(ModelRequestCancelled) as error:
            asyncio.run(run())
        result = error.value.result
    else:
        result = asyncio.run(run())
    assert result.raw_response == b'{"partial":' and result.completion_status == "failed"
    assert result.generation_started and result.token_budget.report["fits"]


def hosted_project(root, provider="deepinfra", model=MODEL):
    path = root / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["profiles"][0]["model"].update(name=model, execution_mode="hosted_api", api_service="huggingface",
        provider=provider, endpoint=hf.HF_ENDPOINT)
    config["profiles"][0]["context_limit"] = 262144
    path.write_text(json.dumps(config))


@pytest.mark.parametrize("provider,model", [("deepinfra", MODEL)])
def test_saved_hosted_run_reuses_tools_validation_and_preserves_evidence(project, settings, monkeypatch, run_record, provider, model):
    hosted_project(project, provider, model)
    client = loop.FakeClient()
    monkeypatch.setattr(agents, "_document_client", lambda *args, **kwargs: client)
    responses = [envelope(None, calls=[tool_call()], finish="tool_calls", model=model),
                 envelope(agents.FINAL_READY_SIGNAL, model=model), envelope(loop.answer(run_record), model=model)]
    sent = []
    def handler(req):
        assert str(req.url) == hf.HF_ENDPOINT + "/chat/completions"
        sent.append(json.loads(req.content))
        assert req.headers["Authorization"] == "Bearer " + TOKEN
        return httpx.Response(200, json=responses.pop(0))
    saved = asyncio.run(agents.run_extractor(project, loop.PLAN_ID, source_path=loop.SOURCE,
        profile_name=loop.PROFILE, purpose="development", _transport=httpx.MockTransport(handler)))
    assert saved.record["status"] == "succeeded" and saved.persistence_error is None
    assert storage.load_run_record(project, saved.record_path) == saved.record
    assert client.calls == [("get_page_text", {"page_number": 1})] and client.closed
    assert len(sent) == 3 and saved.record["model_calls"][0]["input_tokens"] == 100
    assert all(body["model"] == model + ":" + provider for body in sent)
    assert sent[-1]["response_format"]["type"] == "json_schema"
    schema = sent[-1]["response_format"]["json_schema"]["schema"]
    original = saved.execution.extractor_input.response_format
    assert schema == hf.prepare_deepinfra_response_schema(original)
    env = saved.record["settings"]["environment"]
    assert env["runtime"] == "huggingface_inference_providers" and env["hardware"] is None
    assert env["model_revision"] is None and env["quantization"] is None
    folder = (project / saved.record_path).parent
    for file in folder.rglob('*'):
        if file.is_file():
            assert TOKEN.encode() not in file.read_bytes()
    budget = json.loads((folder/'responses/attempt_01/token_budget.json').read_text())
    assert budget["verified_provider_count"] is False
    assert json.loads((folder/'validation_report.json').read_text())["valid"]


@pytest.mark.parametrize("provider", ["deepinfra"])
def test_hosted_modes_do_not_accept_valid_json_with_missing_required_fields(project, settings, monkeypatch, provider):
    hosted_project(project, provider)
    client = loop.FakeClient()
    monkeypatch.setattr(agents, "_document_client", lambda *args, **kwargs: client)
    responses = [envelope(agents.FINAL_READY_SIGNAL), envelope('{}')]
    sent = []
    def handler(req):
        sent.append(json.loads(req.content))
        return httpx.Response(200, json=responses.pop(0))
    saved = asyncio.run(agents.run_extractor(project, loop.PLAN_ID, source_path=loop.SOURCE,
        profile_name=loop.PROFILE, purpose="development", _transport=httpx.MockTransport(handler)))
    assert saved.record["status"] == "failed" and saved.persistence_error is None
    assert saved.record["plan_data"] is None and saved.record["plan_issues"] is None
    assert len(sent) == 2 and not responses
    assert sent[-1]["response_format"]["type"] == "json_schema"
    folder = (project / saved.record_path).parent
    report = json.loads((folder/'validation_report.json').read_text())
    assert report["valid"] is False and report["remaining_errors"]
    assert (folder/'responses/response_02.txt').read_text() == '{}'
    assert storage.load_run_record(project, saved.record_path) == saved.record


@pytest.mark.parametrize("reason", ["missing-token", "comparison"])
def test_hosted_pilot_setup_rejections_create_no_run(project, settings, monkeypatch, reason):
    hosted_project(project)
    if reason == "missing-token":
        monkeypatch.delenv("HF_TOKEN")
    with pytest.raises(ValueError):
        asyncio.run(agents.run_extractor(project, loop.PLAN_ID, source_path=loop.SOURCE,
            profile_name=loop.PROFILE, purpose="comparison" if reason == "comparison" else "development"))
    assert not list((project/'runs').glob('**/output.json'))


@pytest.mark.parametrize("failure", ["duplicate-pages", "open-with-resolution"])
def test_saved_deepinfra_run_rejects_python_only_rules(project, settings, monkeypatch, run_record, failure):
    hosted_project(project, "deepinfra")
    client = loop.FakeClient()
    monkeypatch.setattr(agents, "_document_client", lambda *args, **kwargs: client)
    response = json.loads(loop.answer(run_record))
    if failure == "duplicate-pages":
        response["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [1, 1]
    else:
        response["plan_issues"]["issues"] = [{
            "issue_id": "issue_0001", "related_action_id": "action_0001",
            "issue_description": "Fictional uncertainty.", "issue_type": "unclear_meaning",
            "issue_origin": "extractor", "issue_status": "open", "resolved_by": "extractor",
            "resolution": "An open issue must not claim a resolution.",
        }]
    raw_answer = json.dumps(response)
    replies = [envelope(agents.FINAL_READY_SIGNAL), envelope(raw_answer)]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=replies.pop(0)))
    saved = asyncio.run(agents.run_extractor(project, loop.PLAN_ID, source_path=loop.SOURCE,
        profile_name=loop.PROFILE, purpose="development", _transport=transport))
    assert saved.record["status"] == "failed" and not replies
    assert saved.record["plan_data"] is None and saved.record["plan_issues"] is None
    folder = (project / saved.record_path).parent
    assert (folder / "responses/response_02.txt").read_text() == raw_answer
    report = json.loads((folder / "validation_report.json").read_text())
    assert not report["valid"] and report["remaining_errors"]
