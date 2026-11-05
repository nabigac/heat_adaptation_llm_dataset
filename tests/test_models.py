"""Test the Ollama connection with controlled HTTP, without a downloaded model.

MockTransport replaces the network. Streaming fixtures exercise actual async
deadline/cancellation handling, not OCR, GPU performance, or extraction quality.
"""

import asyncio
import copy
import json

import httpx
import pytest

import models
import validation


@pytest.fixture(autouse=True)
def counted_request(monkeypatch):
    """Isolate transport behavior; test_token_budget covers real preflight wiring.

    The transport cases intentionally use fictional models and impossible tiny
    contexts to test post-response guards. Their preflight result is synthetic.
    """
    counts = {"input_tokens": 21}

    async def check(client, url, body, result, models_directory):
        result.report.update(fits=True, input_tokens=counts["input_tokens"])

    monkeypatch.setattr(models, "_check_token_budget", check)
    return counts


@pytest.fixture
def settings(run_record: dict) -> dict:
    return copy.deepcopy(run_record["settings"])


@pytest.fixture
def messages() -> list[dict]:
    return [{"role": "system", "content": "Use exact source evidence."},
        {"role": "user", "content": "Fictional page 1: Plant 20 trees to reduce heat exposure."}]


def envelope(**changes) -> dict:
    # All usage/timing numbers below are deliberately synthetic observations.
    data = {
        "model": "fictional-model", "done": True, "done_reason": "stop",
        "message": {"role": "assistant", "content": '{"answer":"Exact £ wording."}'},
        "prompt_eval_count": 21, "eval_count": 7, "total_duration": 1_000_000_000,
        "load_duration": 0, "prompt_eval_duration": 100_000_000, "eval_duration": 900_000_000,
    }
    data.update(changes)
    return data


def call_with_body(settings: dict, messages: list, raw: bytes, *, status: int = 200):
    requests = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(status, content=raw)

    result = asyncio.run(models.request_ollama_chat(
        settings, messages, response_format="json", _transport=httpx.MockTransport(handle),
    ))
    return result, requests


def test_request_uses_selected_settings_without_sending_saved_observations(settings: dict, messages: list) -> None:
    before_settings, before_messages = copy.deepcopy(settings), copy.deepcopy(messages)
    settings["generation"].update(temperature=0, top_p=None, seed=0)
    url, body, timeout = models.build_ollama_request(settings, messages, response_format="json")
    assert url == "http://localhost:11434/api/chat"
    assert body == {
        "model": "fictional-model", "messages": messages,
        "stream": False, "truncate": False, "shift": False, "format": "json",
        "options": {"num_ctx": 32768, "num_predict": 8192, "temperature": 0, "seed": 0},
    }
    assert timeout == 600
    body["messages"][0]["content"] = "Changed only in request copy."
    assert messages == before_messages
    settings["generation"] = before_settings["generation"]
    assert settings == before_settings


def test_optional_generation_controls_are_omitted_only_when_null(settings: dict, messages: list) -> None:
    settings["generation"].update(temperature=None, top_p=0.9, seed=None)
    _, body, _ = models.build_ollama_request(settings, messages)
    assert body["options"] == {"num_ctx": 32768, "num_predict": 8192, "top_p": 0.9}
    assert "format" not in body


def test_json_schema_format_is_copied_without_rewriting(settings: dict, messages: list) -> None:
    schema = {"type": "object", "properties": {"action": {"type": "string"}}}
    _, body, _ = models.build_ollama_request(settings, messages, response_format=schema)
    assert body["format"] == schema
    body["format"]["properties"].clear()
    assert schema["properties"]


@pytest.mark.parametrize("damage", ["not-dict", "missing-field", "unknown-field", "nonfinite", "hosted"])
def test_invalid_settings_fail_before_any_request(settings: dict, messages: list, damage: str) -> None:
    if damage == "not-dict":
        settings = None
    elif damage == "missing-field":
        del settings["model_timeout_seconds"]
    elif damage == "unknown-field":
        settings["retry_count"] = 3
    elif damage == "nonfinite":
        settings["generation"]["temperature"] = float("inf")
    else:
        settings["model"].update(execution_mode="hosted_api", api_service="fictional", provider="fictional")
    with pytest.raises(ValueError):
        models.build_ollama_request(settings, messages)


@pytest.mark.parametrize("endpoint", ["localhost:11434", "file:///tmp/model", "http://user:password@localhost:11434", "http://localhost:11434/?key=x", "http://localhost:11434/#fragment"])
def test_invalid_endpoint_is_not_contacted(settings: dict, messages: list, endpoint: str) -> None:
    settings["model"]["endpoint"] = endpoint
    with pytest.raises(ValueError, match="base URL"):
        models.build_ollama_request(settings, messages)


@pytest.mark.parametrize("endpoint", ["http://localhost:invalid", "http://localhost:999999"])
def test_invalid_port_is_rejected_before_request_construction(settings: dict, messages: list, endpoint: str) -> None:
    settings["model"]["endpoint"] = endpoint
    with pytest.raises(ValueError, match="valid port"):
        models.build_ollama_request(settings, messages)


@pytest.mark.parametrize("invalid_messages", [
    [], {}, ["text"], [{"role": "user"}], [{"role": "user", "content": None}],
    [{"role": "developer", "content": "instructions"}],
    [{"role": "user", "content": "source", "images": ["image"]}],
    [{"role": "tool", "content": "result"}],
])
def test_first_increment_rejects_unsupported_messages_without_dropping_fields(settings: dict, invalid_messages: object) -> None:
    with pytest.raises(ValueError):
        models.build_ollama_request(settings, invalid_messages)


@pytest.mark.parametrize("value", [True, 1, "yaml", []])
def test_unsupported_response_format_is_not_sent(settings: dict, messages: list, value: object) -> None:
    with pytest.raises(ValueError, match="Response format"):
        models.build_ollama_request(settings, messages, response_format=value)


def test_success_preserves_body_text_and_reported_measurements(settings: dict, messages: list) -> None:
    raw = (" \n" + json.dumps(envelope(), ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    result, requests = call_with_body(settings, messages, raw)
    assert len(requests) == 1 and requests[0].method == "POST"
    assert requests[0].url == "http://localhost:11434/api/chat"
    assert json.loads(requests[0].content)["messages"] == messages
    assert result.raw_response == raw
    assert result.response_text == '{"answer":"Exact £ wording."}'
    assert result.input_tokens == 21 and result.output_tokens == 7
    assert result.finish_reason == "stop" and result.truncated is False
    assert result.completion_status == "normal" and result.error is None
    assert result.status_code == 200 and result.elapsed_seconds >= 0
    assert result.provider_timings_ns["load_duration"] == 0
    assert result.to_run_call("runs/example/responses/response_01.json") == {
        "input_tokens": 21, "output_tokens": 7, "finish_reason": "stop", "truncated": False,
        "response_path": "runs/example/responses/response_01.json",
    }


def test_unknown_and_zero_usage_are_kept_distinct(settings: dict, messages: list, counted_request) -> None:
    counted_request["input_tokens"] = 0
    payload = envelope(prompt_eval_count=0)
    del payload["eval_count"]
    del payload["load_duration"]
    result, _ = call_with_body(settings, messages, json.dumps(payload).encode())
    assert result.input_tokens == 0 and result.output_tokens is None
    assert result.provider_timings_ns["load_duration"] is None
    assert result.error is None


@pytest.mark.parametrize("limit,accepted", [(20, False), (27, False), (28, True)])
def test_reported_usage_must_fit_configured_context_even_when_runtime_ignores_it(settings: dict, messages: list, limit: int, accepted: bool) -> None:
    settings["context_limit"] = limit
    result, requests = call_with_body(settings, messages, json.dumps(envelope()).encode())
    assert result.input_tokens == 21 and result.output_tokens == 7
    assert len(requests) == 1
    assert (result.completion_status == "normal") is accepted
    assert (result.error is None) is accepted
    if not accepted:
        assert "context limit" in result.error


@pytest.mark.parametrize("limit,accepted", [(6, False), (7, True)])
def test_reported_output_must_fit_configured_output_limit(settings: dict, messages: list, limit: int, accepted: bool) -> None:
    settings["generation"]["max_output_tokens"] = limit
    result, _ = call_with_body(settings, messages, json.dumps(envelope()).encode())
    assert result.output_tokens == 7
    assert (result.error is None) is accepted
    if not accepted:
        assert "output limit" in result.error


@pytest.mark.parametrize("reason,expected,truncated", [
    ("stop", "normal", False), ("length", "truncated", True),
    (None, "unknown", None), ("unfamiliar-provider-reason", "unknown", None),
])
def test_completion_metadata_is_explicit_not_inferred_from_json(settings: dict, messages: list, reason: str, expected: str, truncated: bool) -> None:
    result, requests = call_with_body(settings, messages, json.dumps(envelope(done_reason=reason)).encode())
    assert result.completion_status == expected and result.truncated is truncated
    assert result.finish_reason == reason and len(requests) == 1
    assert (result.error is not None) == (expected == "truncated")


def test_transport_does_not_repair_or_validate_research_content(settings: dict, messages: list) -> None:
    payload = envelope(message={"role": "assistant", "content": "```json\n{invalid,}\n```"})
    result, _ = call_with_body(settings, messages, json.dumps(payload).encode())
    assert result.completion_status == "normal" and result.error is None
    assert result.response_text == payload["message"]["content"]
    # Normal generation is a provider observation, not a passing research answer.
    answer, problems = validation.parse_agent_response_json(result.response_text, page_count=5, stage="extractor")
    assert answer is None and problems


def test_thinking_and_tool_calls_are_retained_without_executing_them(settings: dict, messages: list) -> None:
    message = {"role": "assistant", "content": "", "thinking": "Fictional provider text.",
        "tool_calls": [{"function": {"name": "page_text", "arguments": {"page_number": 1}}}]}
    result, _ = call_with_body(settings, messages, json.dumps(envelope(message=message)).encode())
    assert result.assistant_message == message
    assert result.response_text == "" and result.error is None


@pytest.mark.parametrize("status", [301, 400, 404, 429, 500, 503])
def test_http_failures_keep_response_without_retry_or_redirect(settings: dict, messages: list, status: int) -> None:
    raw = json.dumps({"error": "Controlled provider failure.", "prompt_eval_count": 21}).encode()
    result, requests = call_with_body(settings, messages, raw, status=status)
    assert len(requests) == 1
    assert result.raw_response == raw and result.input_tokens == 21
    assert result.completion_status == "failed"
    assert f"HTTP {status}" in result.error


@pytest.mark.parametrize("raw", [b"", b"not JSON", b"\xff", b"[]", b'{"done":true,"done":false}', b'{"done":NaN}'])
def test_malformed_provider_envelopes_remain_available(settings: dict, messages: list, raw: bytes) -> None:
    result, requests = call_with_body(settings, messages, raw)
    assert result.raw_response == raw and result.completion_status == "failed"
    assert result.error and len(requests) == 1


@pytest.mark.parametrize("changes", [
    {"done": False}, {"done": None}, {"done_reason": True}, {"done_reason": ""},
    {"message": None}, {"message": {"role": "user", "content": "wrong role"}},
    {"message": {"role": "assistant", "content": None}},
    {"prompt_eval_count": -1}, {"prompt_eval_count": True}, {"eval_count": 1.5},
    {"total_duration": -1}, {"load_duration": "unknown"}, {"error": "provider failed"},
])
def test_invalid_metadata_fails_without_erasing_other_observations(settings: dict, messages: list, changes: dict) -> None:
    raw = json.dumps(envelope(**changes)).encode()
    result, _ = call_with_body(settings, messages, raw)
    assert result.completion_status == "failed" and result.error
    assert result.raw_response == raw
    if "eval_count" not in changes:
        assert result.output_tokens == 7


def test_connection_failure_has_unknown_usage_and_no_retry(settings: dict, messages: list) -> None:
    requests = []

    def handle(request):
        requests.append(request)
        raise httpx.ConnectError("Controlled connection refusal.")

    result = asyncio.run(models.request_ollama_chat(settings, messages, _transport=httpx.MockTransport(handle)))
    assert len(requests) == 1 and result.raw_response == b""
    assert result.input_tokens is None and result.output_tokens is None
    assert result.completion_status == "failed" and "connection" in result.error


class SlowBody(httpx.AsyncByteStream):
    """Deliver bytes regularly but take longer than a total-request deadline."""

    def __init__(self):
        self.closed = False

    async def __aiter__(self):
        for part in (b'{"message":', b'{"role":', b'"assistant",', b'"content":', b'"unfinished"}}'):
            yield part
            await asyncio.sleep(0.03)

    async def aclose(self):
        self.closed = True


def test_deadline_covers_the_whole_exchange_and_preserves_partial_bytes(settings: dict, messages: list) -> None:
    settings["model_timeout_seconds"] = 0.05
    stream = SlowBody()
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, stream=stream)

    result = asyncio.run(models.request_ollama_chat(settings, messages, _transport=httpx.MockTransport(handle)))
    assert result.completion_status == "failed" and "complete-request timeout" in result.error
    assert result.raw_response.startswith(b'{"message":')
    assert not result.raw_response.endswith(b"}}")
    assert result.status_code == 200 and result.elapsed_seconds >= 0.05
    assert len(requests) == 1 and stream.closed


def test_timeout_still_fails_when_complete_looking_json_arrived(settings: dict, messages: list) -> None:
    settings["model_timeout_seconds"] = 0.03
    raw = json.dumps(envelope()).encode()

    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield raw
            await asyncio.sleep(1)

    result = asyncio.run(models.request_ollama_chat(
        settings, messages, _transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Body())),
    ))
    assert result.raw_response == raw and result.input_tokens == 21
    assert result.finish_reason == "stop" and result.truncated is False
    assert result.completion_status == "failed" and "timeout" in result.error


def test_cancelled_request_propagates_and_attaches_available_evidence(settings: dict, messages: list) -> None:
    async def run():
        started = asyncio.Event()

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"available partial bytes"
                started.set()
                await asyncio.sleep(60)

        def handle(request):
            return httpx.Response(200, stream=Body())

        task = asyncio.create_task(models.request_ollama_chat(settings, messages, _transport=httpx.MockTransport(handle)))
        await started.wait()
        task.cancel()
        with pytest.raises(models.ModelRequestCancelled) as caught:
            await task
        assert caught.value.result.raw_response == b"available partial bytes"
        assert caught.value.result.completion_status == "failed"
        assert isinstance(caught.value, asyncio.CancelledError)

    asyncio.run(run())


def test_read_error_retains_received_bytes_without_retry(settings: dict, messages: list) -> None:
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b"received before disconnect"
            raise httpx.ReadError("Controlled disconnect.")

    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, stream=Body())

    result = asyncio.run(models.request_ollama_chat(settings, messages, _transport=httpx.MockTransport(handle)))
    assert result.raw_response == b"received before disconnect"
    assert len(requests) == 1 and result.completion_status == "failed"


def test_run_call_metadata_fits_existing_run_record(settings: dict, messages: list, run_record: dict) -> None:
    result, _ = call_with_body(settings, messages, json.dumps(envelope()).encode())
    run_record["model_calls"] = [result.to_run_call(run_record["model_calls"][0]["response_path"])]
    assert validation.validate_run_record(run_record, page_count=5) == []
