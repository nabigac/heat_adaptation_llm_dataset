"""Check startup facts and incremental HTTP evidence without a real service."""

import asyncio
import copy
import json
import time

import httpx
import pytest

import models


@pytest.fixture
def settings(run_record):
    return copy.deepcopy(run_record["settings"])


def observe(settings, handler):
    return asyncio.run(models.observe_ollama_environment(settings, _transport=httpx.MockTransport(handler)))


@pytest.mark.parametrize("loaded", [True, False])
def test_startup_observation_records_loaded_state_and_quantization_without_chat(settings, loaded):
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path == "/api/ps":
            return httpx.Response(200, json={"models": [{"name": settings["model"]["name"]}] if loaded else []})
        assert request.url.path == "/api/show"
        assert json.loads(request.content) == {"model": settings["model"]["name"], "verbose": False}
        return httpx.Response(200, json={"details": {"quantization_level": "fixture-format"}})
    result = observe(settings, handler)
    assert result.values == {"model_loaded_at_start": loaded, "quantization": "fixture-format"}
    assert result.errors == [] and len(result.raw_responses) == 2
    assert len(requests) == 2


@pytest.mark.parametrize("raw", [b"broken JSON", b'{"models":null}', b'{"models":[{}]}', b'[]'])
def test_unavailable_loaded_state_remains_unknown(settings, raw):
    def handler(request):
        return httpx.Response(200, content=raw if request.url.path == "/api/ps" else b'{"details":{}}')
    result = observe(settings, handler)
    assert result.values["model_loaded_at_start"] is None
    assert result.values["quantization"] is None and result.errors
    assert result.raw_responses["loaded_models"] == raw


def test_provider_unknown_quantization_is_not_fabricated_as_a_format(settings):
    result = observe(settings, lambda request: httpx.Response(200, json={"models": [],
        "details": {"quantization_level": "unknown"}}))
    assert result.values["quantization"] is None


@pytest.mark.parametrize("status", [302, 404, 500])
def test_observation_failures_keep_bodies_without_redirects_or_retries(settings, status):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, content=b"fixture failure", headers={"Location": "http://elsewhere/"})
    result = observe(settings, handler)
    assert len(requests) == 2 and len(result.errors) == 2
    assert result.values == {"model_loaded_at_start": None, "quantization": None}
    assert set(result.raw_responses.values()) == {b"fixture failure"}


def test_startup_metadata_does_not_contact_nonlocal_or_credentialed_endpoints(settings):
    settings["model"]["endpoint"] = "https://example.org"
    result = observe(settings, lambda request: pytest.fail("No remote metadata request is permitted."))
    assert result.errors and result.raw_responses == {}
    settings["model"]["endpoint"] = "http://user:secret@localhost:11434"
    with pytest.raises(ValueError, match="credentials"):
        observe(settings, lambda request: pytest.fail("Credentials must be rejected first."))


def test_cancelled_startup_retains_received_metadata_prefix(settings):
    async def exercise():
        received = asyncio.Event()
        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b'{"models":'
                received.set()
                await asyncio.sleep(60)
        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))
        task = asyncio.create_task(models.observe_ollama_environment(settings, _transport=transport))
        await received.wait()
        task.cancel()
        with pytest.raises(models.OllamaEnvironmentCancelled) as stopped:
            await task
        assert stopped.value.observation.raw_responses["loaded_models"] == b'{"models":'
        assert stopped.value.observation.values["model_loaded_at_start"] is None
    asyncio.run(exercise())


@pytest.fixture
def count(monkeypatch):
    async def counted(client, url, body, result, models_directory):
        result.report.update(fits=True, input_tokens=21)
    monkeypatch.setattr(models, "_check_token_budget", counted)


def test_preflight_headers_and_chunks_are_observed_in_order(settings, count):
    events = []
    raw = json.dumps({"done": True, "done_reason": "stop", "message": {"role": "assistant", "content": "done"},
                      "prompt_eval_count": 21, "eval_count": 2}).encode()
    def handler(request):
        assert events[0][0] == "preflight_complete"
        return httpx.Response(200, content=raw)
    result = asyncio.run(models.request_ollama_chat(settings, [{"role": "user", "content": "Fixture."}],
        _transport=httpx.MockTransport(handler), on_progress=lambda event, payload: events.append((event, payload))))
    assert result.generation_started is True
    assert [event for event, _ in events] == ["preflight_complete", "response_headers", "response_chunk"]
    assert events[-1][1] == result.raw_response == raw


@pytest.mark.parametrize("failure_point", ["preflight_complete", "response_headers", "response_chunk"])
def test_evidence_callback_failure_stops_request_and_keeps_available_data(settings, count, failure_point):
    requests = []
    raw = b'{"message":{"role":"assistant","content":"done"},"done":true,"done_reason":"stop"}'
    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=raw)
    def observer(event, payload):
        if event == failure_point:
            raise OSError("Controlled evidence failure.")
    result = asyncio.run(models.request_ollama_chat(settings, [{"role": "user", "content": "Fixture."}],
        _transport=httpx.MockTransport(handler), on_progress=observer))
    assert result.error and "preserve model evidence" in result.error
    assert result.generation_started is (failure_point != "preflight_complete")
    assert len(requests) == (0 if failure_point == "preflight_complete" else 1)
    if failure_point == "response_chunk": assert result.raw_response == raw


def test_synchronous_evidence_saving_cannot_bypass_model_deadline(settings, count):
    settings["model_timeout_seconds"] = 0.01
    def observer(event, payload):
        time.sleep(0.02)
    result = asyncio.run(models.request_ollama_chat(settings, [{"role": "user", "content": "Fixture."}],
        _transport=httpx.MockTransport(lambda request: pytest.fail("Expired request must not generate.")), on_progress=observer))
    assert not result.generation_started and "timeout" in result.error
