"""Exercise verification with fictional source pages and controlled HTTP replies.

The baseline is saved by the real extractor runner. Most MCP calls are simulated;
one test uses the real local server. No test sends a paid request or establishes
factual verification quality. Source/record damage stays in temporary projects.
"""

import asyncio
import copy
import json
from pathlib import Path

import pytest
from mcp.types import CallToolResult, TextContent, Tool

import agents
import storage
import test_agent_loop as loop
import test_saved_extractor as saved


project = loop.project
scripted = loop.scripted
facts = saved.facts
PROFILE = "fictional_verifier"
MODEL = "test-lab/fictional-verifier"


def message(content="", calls=None, **options):
    result = loop.message(content, calls, **options)
    result["model"] = MODEL
    return result


def answer(record):
    return {"plan_data": copy.deepcopy(record["plan_data"]),
            "plan_issues": copy.deepcopy(record["plan_issues"])}


@pytest.fixture
def baseline(project, scripted, facts, run_record):
    pages_path = project / loop.SOURCE.replace("preparation.json", "pages.json")
    pages = json.loads(pages_path.read_text())
    pages[1]["text"] = "The council will run a heat awareness campaign."
    pages_path.write_text(json.dumps(pages))
    run_record["plan_issues"]["issues"] = [{
        "issue_id": "issue_0001", "related_action_id": "action_0001",
        "issue_description": "Check whether the tree planting is planned on page 1.",
        "issue_type": "unclear_meaning", "issue_origin": "extractor", "issue_status": "open",
        "resolved_by": None, "resolution": None,
    }]
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    result = saved.execute(project, scripted)
    assert result.record["status"] == "succeeded"
    config_path = project / "configs/profiles.json"
    config = json.loads(config_path.read_text())
    profile = copy.deepcopy(config["profiles"][0])
    profile.update(name=PROFILE, stage="verifier", context_limit=131072)
    profile["model"]["name"] = MODEL
    profile["prompt_paths"][-1] = "prompts/verifier.md"
    config["profiles"].append(profile)
    config_path.write_text(json.dumps(config))
    (project / "prompts/verifier.md").write_text("Fictional verifier instructions.\n")
    scripted.requests.clear()
    scripted.client = loop.FakeClient()
    return result


def execute(project, scripted, **options):
    return asyncio.run(agents.run_verifier(project, loop.PLAN_ID, profile_name=PROFILE,
        purpose="development", _transport=scripted.transport, **options))


def prepare_replies(scripted, response):
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(json.dumps(response))]


@pytest.mark.parametrize("valid_final", [True, False])
@pytest.mark.parametrize("reply_kind", ["plain", "wrapped", "prose"])
def test_early_verifier_draft_does_not_bypass_final_schema_or_quotation_checks(
    project, baseline, scripted, valid_final, reply_kind,
):
    original = saved_bytes((project / baseline.record_path).parent)
    draft = answer(baseline.record)
    draft["plan_issues"]["issues"][0]["resolution_pages"] = [1]
    raw_draft = json.dumps(draft)
    if reply_kind == "wrapped":
        raw_draft = agents.FINAL_READY_SIGNAL + "\n```json\n" + raw_draft + "\n```"
    elif reply_kind == "prose":
        raw_draft = "I have enough to report. Compiling findings now."
    final = answer(baseline.record) if valid_final else copy.deepcopy(draft)
    final["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [2]
    scripted.replies = [message(raw_draft), message(json.dumps(final))]
    result = execute(project, scripted)
    folder = (project / result.record_path).parent
    assert (folder / "responses/response_01.txt").read_text() == raw_draft
    assert json.loads((folder / "responses/response_02.txt").read_text()) == final
    request = json.loads((folder / "responses/attempt_02/request.json").read_text())
    assert request["phase"] == "final" and request["body"]["response_format"]["type"] == "json_schema"
    assert "tools" not in request["body"]
    report = json.loads((folder / "validation_report.json").read_text())
    if valid_final:
        assert result.record["status"] == "succeeded"
        assert result.record["plan_data"] == baseline.record["plan_data"]
        assert result.record["plan_issues"] == baseline.record["plan_issues"]
        assert report["valid"] is True and report["repairs"][0]["rule"] == "quotation_page_number"
        assert result.execution.quotation_diagnostics["summary"]["corrected"] == 1
    else:
        assert result.record["status"] == "failed" and result.record["plan_data"] is None
        assert report["valid"] is False and report["repairs"] == []
        assert any("resolution_pages" in e["message"] for e in report["remaining_errors"])
        assert result.execution.quotation_diagnostics is None
    assert storage.load_run_record(project, result.record_path) == result.record
    assert len(scripted.requests) == 2
    assert saved_bytes((project / baseline.record_path).parent) == original


def test_retained_extractor_ocr_remains_available_to_the_verifier_diagnostic(
    project, baseline, scripted, monkeypatch,
):
    config_path = project / "configs/profiles.json"
    config = json.loads(config_path.read_text())
    config["document_tools"].update(ocr_enabled=True, ocr_engine="easyocr", ocr_language="en")
    config_path.write_text(json.dumps(config))
    async def catalogue(self):
        result = loop.catalogue()
        result.tools.append(Tool(name="run_ocr", description="Read a page with OCR.", input_schema={
            "type": "object", "properties": {"page_number": {"type": "integer", "minimum": 1}},
            "required": ["page_number"],
        }))
        return result
    monkeypatch.setattr(loop.FakeClient, "list_tools", catalogue)
    quote = "OCR-only tree planting detail."
    response = answer(baseline.record)
    response["plan_data"]["actions"][0]["evidence"] = [{"quote": quote, "page_numbers": [2]}]
    scripted.client.result = CallToolResult(content=[TextContent(type="text", text=quote)],
        structured_content={"page_number": 2, "text_source": "ocr", "text": quote})
    call = {"id": "recognize_page_2", "function": {"name": "run_ocr", "arguments": {"page_number": 2}}}
    scripted.replies = [loop.message(calls=[call]), loop.message(agents.FINAL_READY_SIGNAL),
                        loop.message(json.dumps(response))]
    extraction = saved.execute(project, scripted)
    assert extraction.record["status"] == "succeeded"
    before = saved_bytes((project / extraction.record_path).parent)
    scripted.client = loop.FakeClient()
    scripted.requests.clear()
    prepare_replies(scripted, response)
    result = execute(project, scripted)
    assert result.record["status"] == "succeeded"
    assert result.record["input_run_id"] == extraction.record["run_id"]
    assert result.execution.tool_log == [] and len(scripted.requests) == 2
    report = json.loads(((project / result.record_path).parent / agents.QUOTATION_PAGE_REPORT_PATH).read_text())
    assert report["ocr_page_numbers"] == [2] and report["summary"]["matched"] == 1
    assert report["findings"] == []
    assert saved_bytes((project / extraction.record_path).parent) == before


def test_input_contains_complete_source_and_only_the_selected_answer(project, baseline):
    before = saved_bytes(project)
    packet = agents.build_verifier_input(project, loop.PLAN_ID, profile_name=PROFILE, purpose="development")
    assert saved_bytes(project) == before
    assert packet.input_run_id == baseline.record["run_id"]
    assert packet.input_run == baseline.record
    assert packet.source_path == baseline.record["source_path"]
    assert "heat awareness campaign" in packet.messages[1]["content"]
    assert "ORIGINAL PDF PAGE 3" in packet.messages[1]["content"]
    supplied = json.loads(packet.messages[2]["content"].split("\n", 2)[2])
    assert supplied == answer(baseline.record)
    assert "model_calls" not in supplied and "settings" not in supplied
    assert packet.messages[0]["content"] == "\n\n".join(packet.settings["prompt_texts"])


def test_verifier_receives_the_page_corrected_e_answer_without_overwriting_e(
    project, baseline, scripted,
):
    original = (project / baseline.record_path).read_bytes()
    raw_answer = answer(baseline.record)
    raw_answer["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [2]
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(json.dumps(raw_answer))]
    extraction = saved.execute(project, scripted)
    assert extraction.record["status"] == "succeeded"
    corrected = answer(extraction.record)
    assert corrected["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] == [1]
    assert corrected["plan_issues"] == raw_answer["plan_issues"]
    frozen_e = saved_bytes((project / extraction.record_path).parent)
    scripted.client = loop.FakeClient()
    prepare_replies(scripted, corrected)
    result = execute(project, scripted)
    assert result.record["status"] == "succeeded" and result.record["input_run_id"] == extraction.record["run_id"]
    sent = scripted.requests[2]["messages"]
    supplied = json.loads(next(m["content"] for m in sent if m["role"] == "user" and "plan_data" in m["content"]).split("\n", 2)[2])
    assert supplied == corrected
    assert result.execution.quotation_diagnostics["summary"]["corrected"] == 0
    assert len(scripted.requests) == 4
    assert saved_bytes((project / extraction.record_path).parent) == frozen_e
    assert (project / baseline.record_path).read_bytes() == original


def test_page_corrected_candidate_must_pass_validation_again(
    project, baseline, scripted, monkeypatch,
):
    correct = agents.correct_quotation_pages
    def invalid(*args, **options):
        candidate, report = correct(*args, **options)
        candidate["actions"][0]["evidence"][0]["page_numbers"] = [99]
        return candidate, report
    monkeypatch.setattr(agents, "correct_quotation_pages", invalid)
    response = answer(baseline.record)
    response["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [2]
    prepare_replies(scripted, response)
    result = execute(project, scripted)
    assert result.record["status"] == "failed" and result.record["plan_data"] is None
    assert "page-corrected candidate failed validation" in result.record["error"]
    assert result.execution.final_validation.report["remaining_errors"]
    folder = (project / result.record_path).parent
    assert json.loads((folder / "responses/response_02.txt").read_text()) == response
    assert json.loads((folder / "validation_report.json").read_text())["valid"] is False
    assert len(scripted.requests) == 2


def saved_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in Path(root).rglob("*") if p.is_file()}


def test_success_saves_a_full_revision_and_a_separate_pinned_input(project, baseline, scripted):
    original_folder = (project / baseline.record_path).parent
    before = saved_bytes(original_folder)
    revised = answer(baseline.record)
    issue = revised["plan_issues"]["issues"][0]
    issue.update(issue_status="resolved", resolved_by="verifier",
                 resolution="Page 1 states 'We will plant 20 trees', supporting planned status.")
    added = copy.deepcopy(revised["plan_data"]["actions"][0])
    added.update(action_id="action_0002", action="Run a heat awareness campaign.",
                 action_type=["behavioral/cultural"], evidence=[{
                     "quote": "The council will run a heat awareness campaign.", "page_numbers": [2]}])
    revised["plan_data"]["actions"].append(added)
    revised["plan_issues"]["issues"].append({
        "issue_id": "issue_0002", "related_action_id": "action_0002",
        "issue_description": "The extractor omitted the awareness campaign on page 2.",
        "issue_type": "extraction_process_issue", "issue_origin": "verifier", "issue_status": "resolved",
        "resolved_by": "verifier", "resolution": "Added the campaign with its page 2 quotation.",
    })
    scripted.replies = [message(calls=[loop.call()]), message(agents.FINAL_READY_SIGNAL),
                        message(json.dumps(revised))]
    result = execute(project, scripted)
    assert result.record["status"] == "succeeded" and result.persistence_error is None
    assert result.record_path == f"runs/{loop.PLAN_ID}/run_verify_0001/output.json"
    assert result.record["input_run_id"] == baseline.record["run_id"]
    assert result.record["plan_data"] == revised["plan_data"]
    assert result.record["plan_issues"] == revised["plan_issues"]
    assert storage.load_run_record(project, result.record_path) == result.record
    assert len(result.record["model_calls"]) == 3
    assert all(request["model"] == MODEL + ":deepinfra" for request in scripted.requests)
    assert "2 total; 0 submitted; 2 remaining" in scripted.requests[0]["messages"][1]["content"]
    assert "2 total; 1 submitted; 1 remaining" in scripted.requests[1]["messages"][1]["content"]
    assert any("every evidence quotation, including unchanged extractor evidence" in m["content"]
               for m in scripted.requests[-1]["messages"] if m["role"] == "system")
    folder = (project / result.record_path).parent
    packet = json.loads((folder / "artifacts/verifier_input.json").read_text())
    assert packet["input_run"] == baseline.record
    assert packet["input_run_id"] == baseline.record["run_id"]
    assert (folder / "artifacts/conversation.json").is_file()
    assert (folder / "tool_log.json").is_file()
    assert json.loads((folder / "validation_report.json").read_text())["valid"]
    assert result.execution.verifier_input.input_run_id == baseline.record["run_id"]
    assert saved_bytes(original_folder) == before


@pytest.mark.parametrize("problem", ["lost-issue", "origin", "resolver", "expert", "link", "metadata", "field"])
def test_invalid_revision_is_preserved_and_rejected_without_another_model_call(
    project, baseline, scripted, problem,
):
    revised = answer(baseline.record)
    issue = revised["plan_issues"]["issues"][0]
    if problem == "lost-issue":
        revised["plan_issues"]["issues"] = []
    elif problem == "origin":
        issue["issue_origin"] = "verifier"
    elif problem in {"resolver", "expert"}:
        issue.update(issue_status="resolved", resolved_by="expert" if problem == "expert" else "extractor",
                     resolution="An unsupported claimed resolution.")
    elif problem == "link":
        issue["related_action_id"] = "missing-action"
    elif problem == "metadata":
        revised["plan_data"]["metadata"]["source_url"] = "https://example.org/wrong.pdf"
    else:
        del revised["plan_data"]["actions"][0]["action_status"]
    prepare_replies(scripted, revised)
    result = execute(project, scripted)
    assert result.record["status"] == "failed"
    assert result.record["plan_data"] is None and result.record["plan_issues"] is None
    assert len(scripted.requests) == 2
    folder = (project / result.record_path).parent
    assert (folder / "responses/response_02.txt").read_text() == json.dumps(revised)
    report = json.loads((folder / "validation_report.json").read_text())
    assert not report["valid"] and report["remaining_errors"]
    assert storage.load_run_record(project, result.record_path) == result.record


def test_existing_extractor_resolution_can_be_retained_or_reopened(project, baseline, scripted):
    # Baseline is already immutable; create a second E record with a fictional
    # resolved issue using the normal extractor runner rather than editing it.
    revised = answer(baseline.record)
    issue = revised["plan_issues"]["issues"][0]
    issue.update(issue_status="resolved", resolved_by="extractor", resolution="Page 1 states the planned work.")
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(json.dumps(revised))]
    second = saved.execute(project, scripted)
    assert second.record["status"] == "succeeded"
    for reopen in (False, True):
        response = answer(second.record)
        if reopen:
            response["plan_issues"]["issues"][0].update(issue_status="open", resolved_by=None, resolution=None)
        prepare_replies(scripted, response)
        result = execute(project, scripted)
        assert result.record["status"] == "succeeded"
        assert result.record["input_run_id"] == second.record["run_id"]


def test_retry_uses_original_e_even_after_a_newer_success(project, baseline, scripted):
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message("{incomplete", finish="length")]
    failed = execute(project, scripted)
    assert failed.record["status"] == "failed"
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(json.dumps(answer(baseline.record)))]
    newer = saved.execute(project, scripted)
    assert newer.record["status"] == "succeeded" and newer.record["run_id"] != baseline.record["run_id"]
    prepare_replies(scripted, answer(baseline.record))
    retried = execute(project, scripted, retry_of_run_id=failed.record["run_id"])
    assert retried.record["status"] == "succeeded"
    assert retried.record["run_id"] == "run_verify_0002"
    assert retried.record["input_run_id"] == baseline.record["run_id"]
    assert retried.record["retry_of_run_id"] == failed.record["run_id"]
    assert storage.load_run_record(project, failed.record_path) == failed.record


@pytest.mark.parametrize("change", ["tools", "same-model", "no-auth"])
def test_setup_failures_create_no_verifier_attempt(project, baseline, scripted, monkeypatch, change):
    config_path = project / "configs/profiles.json"
    config = json.loads(config_path.read_text())
    if change == "tools":
        config["document_tools"]["tool_timeout_seconds"] += 1
    elif change == "same-model":
        config["profiles"][1]["model"]["name"] = baseline.record["settings"]["model"]["name"]
    else:
        monkeypatch.delenv("HF_TOKEN")
    config_path.write_text(json.dumps(config))
    before = saved_bytes(project)
    with pytest.raises(ValueError):
        execute(project, scripted)
    assert saved_bytes(project) == before and not scripted.requests


def test_formal_comparison_remains_disabled(project, baseline, scripted):
    before = saved_bytes(project)
    with pytest.raises(ValueError, match="not yet enabled"):
        asyncio.run(agents.run_verifier(project, loop.PLAN_ID, profile_name=PROFILE,
            purpose="comparison", _transport=scripted.transport))
    assert saved_bytes(project) == before and not scripted.requests


def test_cancellation_preserves_the_failed_attempt_and_propagates(project, baseline, scripted):
    def cancel(_):
        raise asyncio.CancelledError()
    scripted.hooks = [cancel]
    scripted.replies = [message(agents.FINAL_READY_SIGNAL)]
    with pytest.raises(agents.SavedVerifierCancelled) as caught:
        execute(project, scripted)
    result = caught.value.result
    assert result.record["status"] == "failed"
    assert result.record["input_run_id"] == baseline.record["run_id"]
    assert storage.load_run_record(project, result.record_path) == result.record
    assert len(scripted.requests) == 1


def test_evidence_saving_failure_stops_before_the_next_request(project, baseline, scripted, monkeypatch):
    prepare_replies(scripted, answer(baseline.record))
    original = agents.save_run_file
    def fail_final_request(root, path, relative, raw):
        if relative == "responses/attempt_02/request.json":
            raise OSError("Fictional disk failure.")
        return original(root, path, relative, raw)
    monkeypatch.setattr(agents, "save_run_file", fail_final_request)
    result = execute(project, scripted)
    assert result.record["status"] == "failed" and result.persistence_error
    assert len(scripted.requests) == 1
    assert result.record["plan_data"] is None


@pytest.mark.parametrize("change", ["source", "extractor"])
def test_changing_source_or_baseline_during_verification_rejects_the_answer(project, baseline, scripted, change):
    prepare_replies(scripted, answer(baseline.record))
    def damage(_):
        if change == "source":
            path = project / loop.SOURCE.replace("preparation.json", "pages.json")
            pages = json.loads(path.read_text())
            pages[0]["text"] = "Changed prepared text."
            path.write_text(json.dumps(pages))
        else:
            path = project / baseline.record_path
            path.write_bytes(path.read_bytes() + b"\n")
    scripted.hooks = [damage]
    result = execute(project, scripted)
    assert result.record["status"] == "failed" and result.record["plan_data"] is None
    assert result.record["input_run_id"] == baseline.record["run_id"]


@pytest.mark.parametrize("change", ["baseline", "snapshot", "missing-input"])
def test_completed_v_loading_requires_its_exact_preserved_input(project, baseline, scripted, change):
    prepare_replies(scripted, answer(baseline.record))
    result = execute(project, scripted)
    assert result.record["status"] == "succeeded"
    packet_path = (project / result.record_path).parent / "artifacts/verifier_input.json"
    if change == "baseline":
        path = project / baseline.record_path
        path.write_bytes(path.read_bytes() + b"\n")
    elif change == "snapshot":
        packet = json.loads(packet_path.read_text())
        packet["input_run_id"] = "run_extract_9999"
        packet_path.write_text(json.dumps(packet))
    else:
        packet_path.unlink()
    with pytest.raises((storage.RunValidationError, FileNotFoundError)):
        storage.load_run_record(project, result.record_path)


def test_real_local_mcp_server_supplies_text_to_verification(project, baseline, scripted, monkeypatch):
    monkeypatch.setattr(agents, "_document_client", loop.REAL_DOCUMENT_CLIENT)
    scripted.replies = [message(calls=[loop.call()]), message(agents.FINAL_READY_SIGNAL),
                        message(json.dumps(answer(baseline.record)))]
    result = execute(project, scripted)
    assert result.record["status"] == "succeeded"
    log_path = project / result.record["tool_log_path"]
    entries = json.loads(log_path.read_text())
    assert len(entries) == 1 and entries[0]["error"] is None
    assert "We will plant 20 trees" in json.dumps(entries[0]["result"])
    assert storage.load_run_record(project, result.record_path) == result.record
