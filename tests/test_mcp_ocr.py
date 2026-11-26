"""Check run-bound OCR, preservation and MCP/agent delivery.

Most recognition results are controlled: blank fixture PDFs do not contain the
fictional returned words. A separate cached-model case checks actual pixels.
Neither type of test establishes coding accuracy on government plans.
"""

import asyncio
import copy
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator
from mcp import Client, StdioServerParameters
from mcp.shared.exceptions import MCPError
from PIL import Image, ImageDraw, ImageFont

import agents
import document_tools
import documents
import storage
import test_agent_loop as loop
import test_saved_extractor as saved_tests
from test_automatic_ocr import _CACHED_MODELS, _write_image_only_pdf

project = loop.project
scripted = loop.scripted
facts = saved_tests.facts




def enable_ocr(root, *, enabled=True):
    path = root / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["document_tools"].update(ocr_enabled=enabled,
        ocr_engine="easyocr" if enabled else None, ocr_language="en" if enabled else None,
        image_render_dpi=144)
    path.write_text(json.dumps(config))


@pytest.fixture
def active_run(project, run_record):
    enable_ocr(project)
    record = copy.deepcopy(run_record)
    record.update(status="running", ended_at=None, elapsed_seconds=None, plan_data=None, plan_issues=None,
                  model_calls=[], tool_log_path=None, error=None)
    record["settings"] = agents.load_profile(project, loop.PROFILE, stage="extractor")
    record["settings"]["environment"] = copy.deepcopy(run_record["settings"]["environment"])
    return storage.create_run_record(project, record)


@pytest.fixture
def recognition(monkeypatch):
    state = SimpleNamespace(loads=[], calls=[], text="Cost £500,000.\r\nCafé 2030", error=None)
    class Reader:
        def __init__(self, **options):
            state.loads.append(options)
        def read_text(self, image):
            state.calls.append(image)
            if state.error is not None:
                raise state.error
            return state.text
    monkeypatch.setattr(document_tools, "EasyOcrReader", Reader)
    return state


def toolset(root, record_path, **options):
    return document_tools.RunDocumentTools(root, loop.PLAN_ID, source_path=loop.SOURCE,
                                          run_record_path=record_path, **options)


def sources(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in (root / "data").rglob("*") if p.is_file()}


def server(root, record_path):
    return document_tools.create_document_tool_server(root, loop.PLAN_ID,
        source_path=loop.SOURCE, run_record_path=record_path)


def test_page_ocr_saves_exact_reading_image_settings_and_report_without_source_changes(project, active_run, recognition):
    before = sources(project)
    document = toolset(project, active_run)
    assert not recognition.loads  # Discovery/startup does not load neural weights.
    result = document.run_ocr(2)
    assert result["plan_id"] == loop.PLAN_ID and result["source_path"] == loop.SOURCE
    assert result["run_id"] == "run_extract_0001" and result["page_number"] == 2
    assert result["text"] == recognition.text and result["text_source"] == "ocr"
    assert (project / result["text_path"]).read_bytes() == recognition.text.encode("utf-8")
    image = (project / result["image_path"]).read_bytes()
    with Image.open(BytesIO(image)) as png:
        assert png.size == (200, 200)  # Original 100 PDF points rendered at saved 144 DPI.
    report = json.loads((project / result["report_path"]).read_text())
    assert report["status"] == "succeeded" and report["error"] is None
    assert report["image_sha256"] == hashlib.sha256(image).hexdigest()
    assert report["text_sha256"] == hashlib.sha256(recognition.text.encode()).hexdigest()
    assert report["ended_at"] >= report["started_at"] and report["elapsed_seconds"] >= 0
    assert result["settings"]["image_render_dpi"] == 144
    assert result["settings"]["ocr_engine"] == "easyocr" and result["settings"]["ocr_language"] == "en"
    assert result["settings"]["device"] == "cpu" and result["settings"]["download_models"] is False
    assert recognition.loads == [{"language": "en", "download_models": False}]
    assert sources(project) == before
    assert document.get_page_text(2)["page"]["text"] == ""
    assert document.find_quote(recognition.text)["matching_page_numbers"] == []


def test_repeated_pages_keep_earlier_files_and_reuse_one_reader(project, active_run, recognition):
    document = toolset(project, active_run)
    first = document.run_ocr(1)
    first_bytes = (project / first["text_path"]).read_bytes()
    recognition.text = "A separate recognition result."
    second = document.run_ocr(1)
    assert first["text_path"] != second["text_path"]
    assert (project / first["text_path"]).read_bytes() == first_bytes
    assert (project / second["text_path"]).read_text() == recognition.text
    assert len(recognition.loads) == 1 and len(recognition.calls) == 2


def test_restarted_server_skips_existing_partial_ocr_requests(project, active_run, recognition):
    record_folder = (project / active_run).parent
    partial = record_folder / "artifacts/ocr/request_0001/request.json"
    partial.parent.mkdir(parents=True)
    partial.write_bytes(b"partial preserved evidence")
    result = toolset(project, active_run).run_ocr(1)
    assert "request_0002/" in result["text_path"]
    assert partial.read_bytes() == b"partial preserved evidence"


@pytest.mark.parametrize("number", [0, -1, 4, True, "1", 1.0, None, "../reference_initial.json"])
def test_invalid_page_cannot_create_artifacts_or_load_ocr(project, active_run, recognition, number):
    with pytest.raises(document_tools.DocumentToolError, match="physical PDF pages"):
        toolset(project, active_run).run_ocr(number)
    assert not recognition.loads and not ((project / active_run).parent / "artifacts/ocr").exists()


@pytest.mark.parametrize("failure", ["recognition", "rendering", "missing-models"])
def test_failed_reading_preserves_diagnostics_without_inventing_empty_text(project, active_run, recognition, monkeypatch, failure):
    if failure == "rendering":
        def render(*args, **options):
            raise document_tools.PageRenderingError("Controlled renderer failure.")
        monkeypatch.setattr(document_tools, "render_page_image", render)
    elif failure == "missing-models":
        def unavailable(**options):
            assert options["download_models"] is False
            raise document_tools.OcrError("Controlled missing cached models.")
        monkeypatch.setattr(document_tools, "EasyOcrReader", unavailable)
    else:
        recognition.error = document_tools.OcrError("No usable text; blankness remains unconfirmed.")
    with pytest.raises(document_tools.DocumentToolError, match="Saved OCR report"):
        toolset(project, active_run).run_ocr(1)
    report = json.loads(((project / active_run).parent / "artifacts/ocr/request_0001/result.json").read_text())
    assert report["status"] == "failed" and report["error"] and report["text_path"] is None
    assert (report["image_path"] is None) == (failure == "rendering")
    if report["image_path"] is not None:
        assert (project / report["image_path"]).is_file()


def test_ocr_uses_saved_settings_and_frozen_original_pdf(project, active_run, recognition, monkeypatch):
    document = toolset(project, active_run)
    original = (project / f"data/source_pdfs/{loop.PLAN_ID}.pdf").read_bytes()
    (project / f"data/source_pdfs/{loop.PLAN_ID}.pdf").write_bytes(b"changed after startup")
    enable_ocr(project, enabled=False)  # Editing profiles cannot alter an active run.
    render = document_tools.render_page_image
    def frozen(pdf, number, **options):
        assert pdf == original and options["image_render_dpi"] == 144
        return render(pdf, number, **options)
    monkeypatch.setattr(document_tools, "render_page_image", frozen)
    result = document.run_ocr(1)
    assert result["settings"]["ocr_enabled"] is True
    assert (project / f"data/source_pdfs/{loop.PLAN_ID}.pdf").read_bytes() == b"changed after startup"


def test_other_source_record_cannot_bind_ocr(project, active_run):
    # Keep the JSON structurally valid, but select a different saved preparation.
    path = project / active_run
    record = json.loads(path.read_text())
    record["source_path"] = loop.SOURCE.replace("02", "01")
    path.write_text(json.dumps(record))
    with pytest.raises(document_tools.DocumentToolError):
        toolset(project, active_run)


def test_completed_record_cannot_bind_ocr_or_create_new_files(project, active_run, recognition):
    record = storage.load_run_record(project, active_run)
    record.update(status="failed", ended_at="2026-11-03T12:00:01Z", elapsed_seconds=1,
                  error="Controlled completed attempt.")
    storage.save_run_record(project, record)
    with pytest.raises(document_tools.DocumentToolError, match="active run"):
        toolset(project, active_run)
    assert not recognition.loads


def test_unsupported_engine_is_rejected_without_substituting_easyocr(project, active_run, recognition):
    path = project / active_run
    record = json.loads(path.read_text())
    record["settings"]["document_tools"]["ocr_engine"] = "fictional-engine"
    path.write_text(json.dumps(record))
    with pytest.raises(document_tools.DocumentToolError, match="no fallback"):
        toolset(project, active_run)
    assert not recognition.loads


@pytest.mark.parametrize("record_path", ["../output.json", "/tmp/output.json", "runs/plan_0099/reference_initial.json"])
def test_run_selection_cannot_open_unrelated_files(project, active_run, record_path):
    with pytest.raises(document_tools.DocumentToolError):
        toolset(project, record_path)


def test_version_disagreement_is_rejected_before_ocr(project, active_run, recognition):
    path = project / active_run
    record = json.loads(path.read_text())
    record["settings"]["environment"]["ocr_version"] = "fictional-other-version"
    path.write_text(json.dumps(record))
    with pytest.raises(document_tools.DocumentToolError, match="version differs"):
        toolset(project, active_run)
    assert not recognition.loads


def test_ocr_serializes_rendering_when_clients_submit_concurrent_calls(project, active_run, recognition, monkeypatch):
    document = toolset(project, active_run)
    render = document_tools.render_page_image
    guard = threading.Lock()
    running = 0
    def serialized(*args, **options):
        nonlocal running
        with guard:
            running += 1
            assert running == 1
        try:
            time.sleep(0.02)
            return render(*args, **options)
        finally:
            with guard:
                running -= 1
    monkeypatch.setattr(document_tools, "render_page_image", serialized)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(document.run_ocr, [1, 2]))
    assert len({r["text_path"] for r in results}) == 2 and len(recognition.loads) == 1


def test_cancellation_between_recognition_and_publication_keeps_image_but_no_text(project, active_run, recognition):
    def cancelled_after_recognition():
        if recognition.calls:
            raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        toolset(project, active_run).run_ocr(1, _check_cancelled=cancelled_after_recognition)
    directory = (project / active_run).parent / "artifacts/ocr/request_0001"
    assert (directory / "request.json").is_file() and (directory / "page.png").is_file()
    assert not (directory / "ocr.txt").exists() and not (directory / "result.json").exists()


def test_mcp_catalogue_declares_run_ocr_and_returns_schema_valid_text_with_paths(project, active_run, recognition):
    async def exercise():
        async with Client(server(project, active_run), read_timeout_seconds=5) as client:
            tools = {t.name: t for t in (await client.list_tools()).tools}
            assert set(tools) == {"get_page_text", "find_quote", "run_ocr"}
            ocr = tools["run_ocr"]
            assert set(ocr.input_schema["properties"]) == {"page_number"}
            assert ocr.annotations.read_only_hint is False and ocr.annotations.destructive_hint is False
            assert ocr.annotations.idempotent_hint is False and ocr.annotations.open_world_hint is False
            assert not recognition.loads
            result = await client.call_tool("run_ocr", {"page_number": 1, "image_render_dpi": 1,
                "path": "runs/plan_0099/reference_initial.json"})
            if result.is_error:  # SDK versions may reject additional arguments.
                result = await client.call_tool("run_ocr", {"page_number": 1})
            assert not result.is_error
            Draft202012Validator(ocr.output_schema).validate(result.structured_content)
            assert result.structured_content["settings"]["image_render_dpi"] == 144
            assert result.structured_content["text"] == recognition.text
            assert all(block.type == "text" for block in result.content)
    asyncio.run(exercise())


def test_disabled_ocr_has_no_catalogue_entry_or_ocr_side_effects(project, active_run, recognition):
    path = project / active_run
    record = json.loads(path.read_text())
    record["settings"]["document_tools"].update(ocr_enabled=False, ocr_engine=None, ocr_language=None)
    path.write_text(json.dumps(record))
    async def exercise():
        async with Client(server(project, active_run)) as client:
            assert {t.name for t in (await client.list_tools()).tools} == {"get_page_text", "find_quote"}
    asyncio.run(exercise())
    with pytest.raises(document_tools.DocumentToolError, match="disabled"):
        toolset(project, active_run).run_ocr(1)
    assert not recognition.loads


def test_recognition_failure_is_an_mcp_error_result_with_preserved_report(project, active_run, recognition):
    recognition.error = document_tools.OcrError("Controlled uncertain image.")
    async def exercise():
        async with Client(server(project, active_run)) as client:
            result = await client.call_tool("run_ocr", {"page_number": 1})
            assert result.is_error and result.structured_content is None
            assert "Saved OCR report" in result.content[0].text
    asyncio.run(exercise())


@pytest.mark.parametrize("file_name", ["request.json", "page.png", "ocr.txt", "result.json"])
def test_artifact_write_failure_reaches_client_as_a_fatal_protocol_error(project, active_run, recognition, monkeypatch, file_name):
    save = storage.save_run_file
    def fail(root, record, relative, raw):
        if relative.endswith("/" + file_name):
            raise OSError("Controlled OCR evidence-write failure.")
        return save(root, record, relative, raw)
    monkeypatch.setattr(storage, "save_run_file", fail)
    async def exercise():
        async with Client(server(project, active_run)) as client:
            with pytest.raises(MCPError, match="Cannot preserve OCR evidence"):
                await client.call_tool("run_ocr", {"page_number": 1})
    asyncio.run(exercise())


@pytest.mark.parametrize("outside_project", [False, True])
def test_ocr_artifacts_cannot_follow_a_symlink_outside_the_bound_run(project, active_run, recognition, tmp_path, outside_project):
    outside = (tmp_path if outside_project else project) / "private_expert_material"
    outside.mkdir()
    artifacts = (project / active_run).parent / "artifacts"
    artifacts.mkdir()
    (artifacts / "ocr").symlink_to(outside, target_is_directory=True)
    with pytest.raises(document_tools.OcrArtifactError):
        toolset(project, active_run).run_ocr(1)
    assert list(outside.iterdir()) == [] and not recognition.loads


def test_saved_runner_delivers_actual_mcp_ocr_result_to_next_model_request(project, scripted, facts, recognition, run_record, monkeypatch):
    enable_ocr(project)
    monkeypatch.setattr(agents, "_document_client", lambda root, packet, **options:
                        Client(server(root, options["run_record_path"]), read_timeout_seconds=5))
    def catalogue_and_prompt(body):
        assert {tool["function"]["name"] for tool in body["tools"]} == {"get_page_text", "find_quote", "run_ocr"}
    def received_reading(body):
        reply = next(message for message in body["messages"] if message["role"] == "tool")
        payload = json.loads(reply["content"])
        assert payload["is_error"] is False and payload["result"]["text"] == recognition.text
        assert (project / payload["result"]["image_path"]).is_file()
        assert (project / payload["result"]["text_path"]).read_bytes() == recognition.text.encode()
    scripted.hooks = [catalogue_and_prompt, received_reading]
    # Set OCR arguments before the helper encodes them into the hosted protocol.
    call = loop.call(name="run_ocr")
    call["function"]["arguments"] = {"page_number": 1}
    scripted.replies = [loop.message(calls=[call]),
                        loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    result = saved_tests.execute(project, scripted)
    assert result.record["status"] == "succeeded" and result.persistence_error is None
    log = json.loads((project / result.record["tool_log_path"]).read_text())
    assert len(log) == 1 and log[0]["tool"] == "run_ocr" and log[0]["error"] is None
    assert storage.load_run_record(project, result.record_path) == result.record


def test_ocr_storage_failure_stops_saved_execution_without_another_model_call(project, scripted, facts, recognition, monkeypatch):
    enable_ocr(project)
    monkeypatch.setattr(agents, "_document_client", lambda root, packet, **options:
                        Client(server(root, options["run_record_path"]), read_timeout_seconds=5))
    save = storage.save_run_file
    def fail(root, record, relative, raw):
        if relative.endswith("/ocr.txt"):
            raise OSError("Controlled OCR-text publication failure.")
        return save(root, record, relative, raw)
    monkeypatch.setattr(storage, "save_run_file", fail)
    call = loop.call(name="run_ocr")
    call["function"]["arguments"] = {"page_number": 1}
    scripted.replies = [loop.message(calls=[call])]
    result = saved_tests.execute(project, scripted)
    assert result.record["status"] == "failed" and result.record["plan_data"] is None
    assert len(scripted.requests) == 1
    log = json.loads((project / result.record["tool_log_path"]).read_text())
    assert "Cannot preserve OCR evidence" in log[0]["error"]


def test_recognition_failure_can_remain_an_open_issue_in_a_successful_saved_run(project, scripted, facts, recognition, run_record, monkeypatch):
    enable_ocr(project)
    recognition.error = document_tools.OcrError("Controlled unreadable image.")
    monkeypatch.setattr(agents, "_document_client", lambda root, packet, **options:
                        Client(server(root, options["run_record_path"]), read_timeout_seconds=5))
    call = loop.call(name="run_ocr")
    call["function"]["arguments"] = {"page_number": 1}
    final = json.loads(loop.answer(run_record))
    final["plan_issues"]["issues"] = [{"issue_id": "issue_0001", "issue_type": "source_issue", "issue_status": "open",
        "related_action_id": None, "issue_description": "OCR could not recover page 1 text.",
        "issue_origin": "extractor", "resolved_by": None, "resolution": None}]
    scripted.replies = [loop.message(calls=[call]), loop.message(agents.FINAL_READY_SIGNAL), loop.message(json.dumps(final))]
    result = saved_tests.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    assert result.record["plan_issues"]["issues"][0]["issue_status"] == "open"
    log = json.loads((project / result.record["tool_log_path"]).read_text())
    assert log[0]["result"]["isError"] is True and "Saved OCR report" in log[0]["error"]


@pytest.mark.skipif(not _CACHED_MODELS, reason="Requires the explicitly downloaded English OCR models.")
def test_real_mcp_subprocess_recognizes_image_only_page_and_saved_loop_forwards_it(project, scripted, facts, run_record, tmp_path, monkeypatch):
    # Real PDF pixels, PDFium, offline EasyOCR and MCP pipes; only the model
    # requests/preflight are controlled. This checks the complete OCR delivery
    # path without downloading weights or running a real LLM in the test suite.
    expected = "OPEN 3 COOLING CENTRES BY 2028"
    source_pdf = tmp_path / "scanned.pdf"
    with Image.new("RGB", (1200, 300), "white") as image:
        ImageDraw.Draw(image).text((35, 100), expected, font=ImageFont.load_default(size=48), fill="black")
        _write_image_only_pdf(source_pdf, image)
    entry, _ = documents.register_document(project, source_pdf, plan_title="Fictional scanned plan",
        source_url="https://example.org/scanned.pdf", date_accessed="2026-11-06", study_set="comparison")
    prep, source_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    before = sources(project)
    enable_ocr(project)
    monkeypatch.setattr(agents, "_document_client", loop.REAL_DOCUMENT_CLIENT)
    call = loop.call(name="run_ocr")
    call["function"]["arguments"] = {"page_number": 1}
    final = json.loads(loop.answer(run_record))
    final["plan_data"]["metadata"].update(source_url=prep["source_url"], date_accessed=prep["date_accessed"])
    final["plan_data"]["actions"][0].update(action="Open 3 cooling centres by 2028.",
        evidence=[{"quote": expected, "page_numbers": [1]}])
    def check_reading(body):
        message = next(m for m in body["messages"] if m["role"] == "tool")
        result = json.loads(message["content"])["result"]
        assert " ".join(result["text"].split()).upper() == expected
        assert all("images" not in m for m in body["messages"])
        assert (project / result["image_path"]).is_file() and (project / result["text_path"]).is_file()
    scripted.hooks = [lambda body: None, check_reading]
    scripted.replies = [loop.message(calls=[call]), loop.message(agents.FINAL_READY_SIGNAL), loop.message(json.dumps(final))]
    result = asyncio.run(agents.run_extractor(project, entry["plan_id"], source_path=source_path,
        profile_name=loop.PROFILE, purpose="comparison", _transport=scripted.transport))
    assert result.record["status"] == "succeeded", result.record["error"]
    assert result.persistence_error is None and len(scripted.requests) == 3
    assert storage.load_run_record(project, result.record_path) == result.record
    log = json.loads((project / result.record["tool_log_path"]).read_text())
    assert log[0]["tool"] == "run_ocr" and log[0]["error"] is None
    assert sources(project) == before


def test_timed_out_ocr_subprocess_stops_before_saved_run_is_finalized(project, scripted, facts, tmp_path, monkeypatch):
    enable_ocr(project)
    path = project / "configs/profiles.json"
    config = json.loads(path.read_text())
    config["document_tools"]["tool_timeout_seconds"] = 2
    path.write_text(json.dumps(config))
    marker = tmp_path / "recognition_started.json"
    program = tmp_path / "slow_ocr_server.py"
    program.write_text('''import json,os,time
from pathlib import Path
import document_tools
class Reader:
 def __init__(self,**options):pass
 def read_text(self,image):
  Path(''' + repr(str(marker)) + ''').write_text(json.dumps({"pid":os.getpid()}))
  time.sleep(60)
  return "A late reading must not be accepted."
document_tools.EasyOcrReader=Reader
raise SystemExit(document_tools.main())
''')
    def client(root, packet, **options):
        parameters = StdioServerParameters(command=sys.executable, args=[str(program),
            "--project-root", str(root), "--plan-id", packet.plan_id, "--source-path", packet.source_path,
            "--expected-source-fingerprint", packet.source_fingerprint,
            "--run-record-path", options["run_record_path"]], cwd=root)
        return Client(parameters, read_timeout_seconds=2)
    monkeypatch.setattr(agents, "_document_client", client)
    call = loop.call(name="run_ocr")
    call["function"]["arguments"] = {"page_number": 1}
    scripted.replies = [loop.message(calls=[call])]
    result = saved_tests.execute(project, scripted)
    assert marker.is_file(), result.record["error"]  # Prove OCR actually started.
    assert result.record["status"] == "failed" and len(scripted.requests) == 1
    pid = json.loads(marker.read_text())["pid"]
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)  # Observe stopped state; do not signal an unrelated process.
    directory = (project / result.record_path).parent / "artifacts/ocr/request_0001"
    assert (directory / "request.json").is_file() and (directory / "page.png").is_file()
    assert not (directory / "ocr.txt").exists()
    log = json.loads((project / result.record["tool_log_path"]).read_text())
    assert log[0]["error"] and log[0]["elapsed_seconds"] >= 2
