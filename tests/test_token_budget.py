"""Exercise token-budget decisions with tiny fictional local model assets.

Mock HTTP replaces Ollama, but real tokenizers encode the rendered text. The
fixture tokenizer is deliberately simple; live calibration checks Qwen/MLX.
No tensors, model downloads, or real research documents are used here.
"""

import asyncio
import copy
import hashlib
import json
import time

import httpx
import pytest
from tokenizers import Tokenizer, models as tokenizer_models, pre_tokenizers

import models


@pytest.fixture
def assets(tmp_path, monkeypatch):
    root = tmp_path / "models"
    (root / "blobs").mkdir(parents=True)

    def save_blob(data, *, name=None):
        raw = json.dumps(data).encode() if isinstance(data, dict) else data
        digest = "sha256:" + hashlib.sha256(raw).hexdigest()
        (root / "blobs" / digest.replace(":", "-")).write_bytes(raw)
        return {"mediaType": "application/vnd.ollama.image.json", "digest": digest, "size": len(raw), **({"name": name} if name else {})}

    tokenizer = Tokenizer(tokenizer_models.WordLevel({"[UNK]": 0, "one": 1, "two": 2, "three": 3, "four": 4}, unk_token="[UNK]"))
    tokenizer.pre_tokenizer = pre_tokenizers.WhitespaceSplit()
    # A count must disable these settings rather than accepting a shortened or
    # artificially padded sequence from a tokenizer asset.
    tokenizer.enable_truncation(2)
    tokenizer.enable_padding(length=8)
    config = save_blob({"model_format": "safetensors", "renderer": "qwen3.5"})
    tokenizer_asset = save_blob(tokenizer.to_str().encode(), name="tokenizer.json")
    tokenizer_config = save_blob({"add_bos_token": False, "split_special_tokens": False}, name="tokenizer_config.json")
    # Register only this fixture's synthetic assets, independently of the real
    # Qwen fingerprints used in production. No live assets are needed by tests.
    monkeypatch.setattr(models, "_COUNTING_TOKENIZER_ASSETS", {
        "tokenizer.json": tokenizer_asset["digest"], "tokenizer_config.json": tokenizer_config["digest"],
    })
    model_config = save_blob({"text_config": {"max_position_embeddings": 32768}}, name="config.json")
    manifest = {"config": config, "layers": [tokenizer_asset, tokenizer_config, model_config]}
    raw = json.dumps(manifest).encode()
    path = root / "manifests/registry.ollama.ai/library/qwen3.5/27b"
    path.parent.mkdir(parents=True)
    path.write_bytes(raw)
    return {"root": root, "digest": hashlib.sha256(raw).hexdigest(), "manifest": manifest,
            "manifest_path": path, "save_blob": save_blob, "tokenizer": tokenizer_asset}


@pytest.fixture
def settings(run_record):
    settings = copy.deepcopy(run_record["settings"])
    settings["model"]["name"] = "qwen3.5:27b"
    settings["generation"]["max_output_tokens"] = 4
    settings["context_limit"] = 16
    return settings


@pytest.fixture
def messages():
    return [{"role": "system", "content": "Instructions."}, {"role": "user", "content": "Fictional source."}]


@pytest.fixture
def server(assets):
    """Keep rendered text independent of source text to expose wrong counting."""
    state = {"prompt": "one two three four", "version": "0.40.14", "digest": assets["digest"],
             "reported_input_tokens": 4, "requests": [], "render_body": None}

    def handle(request):
        state["requests"].append(request)
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": state["version"]})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:27b", "digest": state["digest"]}]})
        body = json.loads(request.content)
        if body.get("_debug_render_only") is True:
            state["render_body"] = body
            return httpx.Response(200, json={"_debug_info": {"rendered_template": state["prompt"]}})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "OK"}, "done": True,
            "done_reason": "stop", "prompt_eval_count": state["reported_input_tokens"], "eval_count": 1})

    state["handle"] = handle
    state["transport"] = httpx.MockTransport(handle)
    return state


def check(settings, messages, assets, server, **options):
    return asyncio.run(models.check_ollama_token_budget(settings, messages,
        models_directory=assets["root"], _transport=server["transport"], **options))


def generate(settings, messages, assets, server, **options):
    return asyncio.run(models.request_ollama_chat(settings, messages,
        models_directory=assets["root"], _transport=server["transport"], **options))


def generation_requests(server):
    return [request for request in server["requests"] if request.url.path == "/api/chat"
            and json.loads(request.content).get("_debug_render_only") is not True]


def test_counts_rendered_input_reserves_full_answer_and_leaves_assets_unchanged(settings, messages, assets, server):
    before = {p: p.read_bytes() for p in assets["root"].rglob("*") if p.is_file()}
    result = check(settings, messages, assets, server)
    assert result.report["input_tokens"] == 4  # Saved tokenizer truncation/padding were disabled.
    assert result.report["output_tokens_reserved"] == 4
    assert result.report["remaining_tokens"] == 8 and result.report["fits"]
    assert result.report["error"] is None
    assert result.report["rendered_prompt"] == server["prompt"]
    assert result.report["rendered_prompt_sha256"] == hashlib.sha256(server["prompt"].encode()).hexdigest()
    assert result.report["tokenizer_digest"] == assets["tokenizer"]["digest"]
    assert set(result.raw_responses) == {"version", "installed_models", "render"}
    assert generation_requests(server) == []
    assert {p: p.read_bytes() for p in before} == before


@pytest.mark.parametrize("limit,expected", [(7, False), (8, True), (9, True)])
def test_exact_budget_boundary(settings, messages, assets, server, limit, expected):
    settings["context_limit"] = limit
    result = check(settings, messages, assets, server)
    assert result.report["fits"] is expected
    assert result.report["remaining_tokens"] == limit - 8
    if not expected:
        assert "generation was not started" in result.report["error"]


def test_forwards_entire_request_and_schema_to_rendering_without_double_counting_http_fields(settings, messages, assets, server):
    schema = models.prepare_ollama_response_schema()
    result = check(settings, messages, assets, server, response_format=schema)
    _, body, _ = models.build_ollama_request(settings, messages, response_format=schema)
    assert server["render_body"] == {**body, "_debug_render_only": True}
    assert result.report["request_sha256"] == hashlib.sha256(json.dumps(body, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    assert result.report["input_tokens"] == 4  # Count what the runtime actually renders.


def test_auto_preflight_precedes_generation_and_returns_audit_evidence(settings, messages, assets, server):
    result = generate(settings, messages, assets, server)
    assert result.completion_status == "normal" and result.response_text == "OK"
    assert result.token_budget.report["fits"] and result.token_budget.report["input_tokens"] == 4
    assert result.input_tokens == 4 and result.output_tokens == 1
    assert len(generation_requests(server)) == 1
    assert server["requests"][-1] is generation_requests(server)[0]


def test_oversized_request_never_generates_or_becomes_a_recorded_model_call(settings, messages, assets, server):
    server["prompt"] = "one " * 20
    original_messages = copy.deepcopy(messages)
    result = generate(settings, messages, assets, server)
    assert result.completion_status == "failed" and "exceeding" in result.error
    assert result.token_budget.report["input_tokens"] == 20 and not result.token_budget.report["fits"]
    assert result.input_tokens is None and result.output_tokens is None
    assert result.raw_response == b"" and result.status_code is None
    assert generation_requests(server) == [] and messages == original_messages


def test_each_request_is_counted_again_instead_of_reusing_a_stale_decision(settings, messages, assets, server):
    assert generate(settings, messages, assets, server).completion_status == "normal"
    messages.append({"role": "assistant", "content": "Additional history."})
    server["prompt"] = "one " * 30
    result = generate(settings, messages, assets, server)
    assert result.completion_status == "failed" and len(generation_requests(server)) == 1
    assert server["render_body"]["messages"] == messages


@pytest.mark.parametrize("reported", [0, 3, 5])
def test_changed_or_shortened_provider_input_fails_without_erasing_response(settings, messages, assets, server, reported):
    server["reported_input_tokens"] = reported
    result = generate(settings, messages, assets, server)
    assert result.completion_status == "failed" and "preflight counted 4" in result.error
    assert result.response_text == "OK" and result.raw_response
    assert result.input_tokens == reported


@pytest.mark.parametrize("problem", ["model", "host", "version", "digest", "missing_manifest", "corrupt_blob", "too_much_output", "native_capacity"])
def test_unverified_setups_stop_before_render_or_generation(settings, messages, assets, server, problem):
    if problem == "model":
        settings["model"]["name"] = "untested-model"
    elif problem == "host":
        settings["model"]["endpoint"] = "http://other-machine:11434"
    elif problem == "version":
        server["version"] = "99.0.0"
    elif problem == "digest":
        server["digest"] = "0" * 64
    elif problem == "missing_manifest":
        assets["manifest_path"].unlink()
    elif problem == "corrupt_blob":
        (assets["root"] / "blobs" / assets["tokenizer"]["digest"].replace(":", "-")).write_bytes(b"corrupt")
    elif problem == "too_much_output":
        settings["generation"]["max_output_tokens"] = 17
    else:
        settings["context_limit"] = 32769
    result = generate(settings, messages, assets, server)
    assert result.completion_status == "failed" and result.error
    assert not result.token_budget.report["fits"]
    assert server["render_body"] is None and generation_requests(server) == []


def test_downloaded_manifest_wrapper_selects_exact_served_runner(settings, messages, assets, server):
    manifest_blob = assets["save_blob"](assets["manifest"])
    assets["manifest_path"].write_text(json.dumps({"layers": [{
        "mediaType": "application/vnd.docker.distribution.manifest.v2+json", "digest": manifest_blob["digest"]}]}))
    result = check(settings, messages, assets, server)
    assert result.report["fits"] and result.report["model_digest"] == server["digest"]


@pytest.mark.parametrize("name", ["tokenizer.json", "tokenizer_config.json"])
def test_same_tag_cannot_silently_use_unvalidated_tokenizer_assets(settings, messages, assets, server, name):
    models._COUNTING_TOKENIZER_ASSETS[name] = "sha256:" + "0" * 64
    result = generate(settings, messages, assets, server)
    assert not result.token_budget.report["fits"] and "Untested tokenizer assets" in result.error
    assert generation_requests(server) == [] and server["render_body"] is None


@pytest.mark.parametrize("count", [0, 1, -1, True, None])
def test_rendered_image_accounting_is_explicit(settings, messages, assets, server, count):
    original = server["handle"]

    def handle(request):
        if request.url.path == "/api/chat" and json.loads(request.content).get("_debug_render_only") is True:
            server["requests"].append(request)
            return httpx.Response(200, json={"_debug_info": {"rendered_template": server["prompt"], "image_count": count}})
        return original(request)

    server["transport"] = httpx.MockTransport(handle)
    result = check(settings, messages, assets, server)
    assert result.report["fits"] is (type(count) is int and count == 0)
    assert generation_requests(server) == []


@pytest.mark.parametrize("body", [
    b"not-json", b'{"version":"0.40.14","version":"0.40.14"}', b'{"version":NaN}',
    b'[]', b'{"version":"0.40.14"}',
])
def test_missing_or_malformed_render_observations_are_retained_and_stop_generation(settings, messages, assets, server, body):
    original = server["handle"]

    def handle(request):
        if request.url.path == "/api/chat":
            server["requests"].append(request)
            return httpx.Response(200, content=body)
        return original(request)

    server["transport"] = httpx.MockTransport(handle)
    result = generate(settings, messages, assets, server)
    assert result.completion_status == "failed" and not result.token_budget.report["fits"]
    assert result.token_budget.raw_responses["render"] == body
    assert generation_requests(server) == []


@pytest.mark.parametrize("status", [302, 404, 500])
def test_preflight_http_failures_have_no_retry_or_generation(settings, messages, assets, server, status):
    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(status, content=b"Controlled preflight error.", headers={"Location": "http://other-machine/"})

    server["transport"] = httpx.MockTransport(handle)
    result = generate(settings, messages, assets, server)
    assert result.completion_status == "failed" and len(calls) == 1
    assert result.token_budget.raw_responses["version"] == b"Controlled preflight error."
    assert result.raw_response == b"" and result.input_tokens is None


def test_preflight_timeout_preserves_partial_body_and_blocks_generation(settings, messages, assets, server):
    settings["model_timeout_seconds"] = 0.02

    class SlowBody(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"version":'
            await asyncio.sleep(1)

        async def aclose(self):
            pass

    server["transport"] = httpx.MockTransport(lambda request: httpx.Response(200, stream=SlowBody()))
    result = check(settings, messages, assets, server)
    assert not result.report["fits"] and "timeout" in result.report["error"]
    assert result.raw_responses["version"] == b'{"version":'


def test_one_deadline_covers_all_preflight_phases_and_generation(settings, messages, assets, server):
    settings["model_timeout_seconds"] = 0.03
    original = server["handle"]

    async def handle(request):
        await asyncio.sleep(0.02)
        return original(request)

    server["transport"] = httpx.MockTransport(handle)
    result = generate(settings, messages, assets, server)
    assert result.completion_status == "failed" and "timeout" in result.error
    assert generation_requests(server) == []
    assert result.token_budget.raw_responses["version"]


@pytest.mark.parametrize("count_only", [True, False])
def test_synchronous_tokenizer_work_cannot_bypass_the_deadline(settings, messages, assets, server, monkeypatch, count_only):
    settings["model_timeout_seconds"] = 0.01
    original = models._load_counting_tokenizer

    def slow_load(*args):
        # asyncio's timer cannot interrupt synchronous CPU/file work. The
        # adapter must check elapsed time before it starts generation as well.
        time.sleep(0.02)
        return original(*args)

    monkeypatch.setattr(models, "_load_counting_tokenizer", slow_load)
    result = check(settings, messages, assets, server) if count_only else generate(settings, messages, assets, server)
    if count_only:
        assert not result.report["fits"] and "timeout" in result.report["error"]
    else:
        assert result.completion_status == "failed" and "timeout" in result.error
        assert generation_requests(server) == []


@pytest.mark.parametrize("count_only", [True, False])
def test_cancellation_propagates_with_preflight_evidence(settings, messages, assets, server, count_only):
    async def run():
        started = asyncio.Event()

        class Body(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial preflight bytes"
                started.set()
                await asyncio.sleep(1)

            async def aclose(self):
                pass

        transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=Body()))
        call = models.check_ollama_token_budget if count_only else models.request_ollama_chat
        task = asyncio.create_task(call(settings, messages, models_directory=assets["root"], _transport=transport))
        await started.wait()
        task.cancel()
        exception = models.TokenBudgetCheckCancelled if count_only else models.ModelRequestCancelled
        with pytest.raises(exception) as caught:
            await task
        budget = caught.value.result if count_only else caught.value.result.token_budget
        assert not budget.report["fits"]
        assert budget.raw_responses["version"] == b"partial preflight bytes"

    asyncio.run(run())
