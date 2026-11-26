"""Check verifier terminal behavior with saved fictional E inputs and mock HTTP.

Most cases call the real runner. Disclosure-only cases simulate runner results
to test the terminal boundary independently. No paid model requests are made.
"""

import asyncio
import copy
import json
import logging
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import agents
import cli
import storage
import test_agent_loop as loop
import test_saved_extractor as extractor
import test_verifier as verifier


project = verifier.project
scripted = verifier.scripted
facts = verifier.facts
baseline = verifier.baseline
COMMAND = Path(__file__).resolve().parents[1] / ".venv/bin/heat-adaptation-llm-dataset"


def arguments(root, **changes):
    values = {"profile": verifier.PROFILE, "purpose": "comparison", **changes}
    return ["run_verify_mode", loop.PLAN_ID, "--project-root", str(root),
            *(value for key, item in values.items() for value in ("--" + key, str(item)))]


@pytest.fixture
def connected_cli(monkeypatch, scripted):
    run = agents.run_verifier
    calls = []
    async def execute(*args, **options):
        calls.append((args, copy.deepcopy(options)))
        return await run(*args, **options, _transport=scripted.transport)
    monkeypatch.setattr(agents, "run_verifier", execute)
    return calls


def output_record(root, number=1):
    return root / f"runs/{loop.PLAN_ID}/run_verify_{number:04d}/output.json"


def test_cli_verifies_latest_e_without_a_source_flag_and_reports_the_actual_input(
    project, baseline, scripted, connected_cli, capsys,
):
    before = (project / baseline.record_path).read_bytes()
    verifier.prepare_replies(scripted, verifier.answer(baseline.record))
    assert cli.main(arguments(project)) == 0
    output = capsys.readouterr()
    record = storage.load_run_record(project, output_record(project).relative_to(project).as_posix())
    assert record["status"] == "succeeded" and record["input_run_id"] == baseline.record["run_id"]
    assert "Starting verifier" in output.out and "Status: succeeded" in output.out
    assert "Extractor input: run_extract_0001" in output.out
    assert "run_verify_0001/output.json" in output.out and "Validation report:" in output.out
    assert "Model requests: 2" in output.out and output.err == ""
    assert connected_cli[0][1] == {"input_run_id": None, "profile_name": verifier.PROFILE,
        "purpose": "comparison", "retry_of_run_id": None, "config_path": "configs/profiles.json"}
    assert (project / baseline.record_path).read_bytes() == before


def test_unique_wrong_page_is_corrected_and_raw_answer_and_e_are_preserved(
    project, baseline, scripted, connected_cli, capsys,
):
    before = (project / baseline.record_path).read_bytes()
    response = verifier.answer(baseline.record)
    response["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [2]
    verifier.prepare_replies(scripted, response)
    assert cli.main(arguments(project)) == 0
    output = capsys.readouterr()
    record = storage.load_run_record(project, output_record(project).relative_to(project).as_posix())
    expected = copy.deepcopy(response["plan_data"])
    expected["actions"][0]["evidence"][0]["page_numbers"] = [1]
    assert record["status"] == "succeeded" and record["plan_data"] == expected
    assert record["plan_issues"] == response["plan_issues"]
    folder = output_record(project).parent
    validation = json.loads((folder / "validation_report.json").read_text())
    assert validation["valid"] is True
    assert validation["repairs"] == [{"rule": "quotation_page_number",
        "location": "$.plan_data.actions[0].evidence[0].page_numbers", "before": "[2]", "after": "[1]"}]
    candidate = json.loads((folder / "responses/repaired_final.txt").read_text())
    assert candidate == {"plan_data": expected, "plan_issues": response["plan_issues"]}
    assert json.loads((folder / "responses/response_02.txt").read_text()) == response
    diagnostic = json.loads((folder / agents.QUOTATION_PAGE_REPORT_PATH).read_text())
    assert diagnostic["summary"]["corrected"] == 1
    assert diagnostic["summary"]["possible_page_mismatch"] == 0
    assert diagnostic["repairs"][0]["before"] == [2] and diagnostic["repairs"][0]["after"] == [1]
    assert "Quotation/page diagnostic:" in output.out
    assert "Quotation/page corrections: 1" in output.out
    assert "Repair [quotation_page_number]" in output.out
    assert len(scripted.requests) == 2 and output.err == ""
    assert (project / baseline.record_path).read_bytes() == before


def test_failed_diagnostic_save_is_reported_without_losing_the_model_response(
    project, baseline, scripted, connected_cli, monkeypatch, capsys,
):
    save = agents.save_run_file
    def fail(root, record_path, relative, data):
        if relative == agents.QUOTATION_PAGE_REPORT_PATH:
            raise OSError("Fictional diagnostic save failure.")
        return save(root, record_path, relative, data)
    monkeypatch.setattr(agents, "save_run_file", fail)
    response = verifier.answer(baseline.record)
    verifier.prepare_replies(scripted, response)
    assert cli.main(arguments(project)) == 1
    output = capsys.readouterr()
    record = storage.load_run_record(project, output_record(project).relative_to(project).as_posix())
    assert record["status"] == "failed" and record["plan_data"] is None
    assert "Quotation/page diagnostic: not saved." in output.out
    assert "diagnostic save failure" in output.err
    raw = output_record(project).parent / "responses/response_02.txt"
    assert json.loads(raw.read_text()) == response and len(scripted.requests) == 2


def test_explicit_older_input_and_custom_configuration_reach_the_runner(
    project, baseline, scripted, connected_cli,
):
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(json.dumps(verifier.answer(baseline.record)))]
    newer = extractor.execute(project, scripted)
    assert newer.record["status"] == "succeeded"
    custom = project / "configs/custom.json"
    custom.write_bytes((project / "configs/profiles.json").read_bytes())
    verifier.prepare_replies(scripted, verifier.answer(baseline.record))
    assert cli.main(arguments(project, **{"input-run-id": baseline.record["run_id"],
                                         "config-path": "configs/custom.json"})) == 0
    record = json.loads(output_record(project).read_text())
    assert record["input_run_id"] == baseline.record["run_id"] != newer.record["run_id"]
    assert connected_cli[-1][1]["input_run_id"] == baseline.record["run_id"]
    assert connected_cli[-1][1]["config_path"] == "configs/custom.json"


def test_failed_json_returns_nonzero_and_keeps_the_response_and_validation_report(
    project, baseline, scripted, connected_cli, capsys,
):
    scripted.replies = [verifier.message(agents.FINAL_READY_SIGNAL), verifier.message("not JSON")]
    assert cli.main(arguments(project)) == 1
    output = capsys.readouterr()
    assert "Status: failed" in output.out and "Validation report:" in output.out
    assert "Extractor input: run_extract_0001" in output.out and "[syntax]" in output.err
    assert json.loads(output_record(project).read_text())["plan_data"] is None
    assert output_record(project).parent.joinpath("responses/response_02.txt").read_text() == "not JSON"
    assert len(scripted.requests) == 2


def test_retry_keeps_the_original_e_when_a_newer_extraction_exists(
    project, baseline, scripted, connected_cli,
):
    scripted.replies = [verifier.message("Unexpected tool-phase answer.")]
    assert cli.main(arguments(project)) == 1
    failed_bytes = output_record(project).read_bytes()
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(json.dumps(verifier.answer(baseline.record)))]
    assert extractor.execute(project, scripted).record["status"] == "succeeded"
    verifier.prepare_replies(scripted, verifier.answer(baseline.record))
    assert cli.main(arguments(project, **{"retry-of-run-id": "run_verify_0001"})) == 0
    record = json.loads(output_record(project, 2).read_text())
    assert record["input_run_id"] == baseline.record["run_id"]
    assert record["retry_of_run_id"] == "run_verify_0001"
    assert output_record(project).read_bytes() == failed_bytes


def test_cancellation_returns_130_with_the_preserved_verifier_result(
    project, baseline, scripted, connected_cli, capsys,
):
    def cancel(_):
        raise asyncio.CancelledError()
    scripted.hooks = [cancel]
    scripted.replies = [verifier.message(agents.FINAL_READY_SIGNAL)]
    assert cli.main(arguments(project)) == 130
    output = capsys.readouterr()
    assert "Status: failed" in output.out and "Verification cancelled" in output.err
    assert "Traceback" not in output.err
    assert storage.load_run_record(project, output_record(project).relative_to(project).as_posix())["status"] == "failed"


def test_failed_completion_save_cannot_be_reported_as_success(
    project, baseline, scripted, connected_cli, monkeypatch, capsys,
):
    save = agents.save_run_record
    def fail(root, record):
        if record["stage"] == "verifier" and record["status"] != "running":
            raise OSError("Fictional final save failure.")
        return save(root, record)
    monkeypatch.setattr(agents, "save_run_record", fail)
    verifier.prepare_replies(scripted, verifier.answer(baseline.record))
    assert cli.main(arguments(project)) == 1
    output = capsys.readouterr()
    assert "Status: running" in output.out and "Saving error:" in output.err
    assert "Status: succeeded" not in output.out


@pytest.mark.parametrize("missing", ["--profile"])
def test_required_flags_are_checked_before_any_work(project, connected_cli, missing):
    args = arguments(project)
    index = args.index(missing)
    del args[index:index + 2]
    with pytest.raises(SystemExit) as caught:
        cli.main(args)
    assert caught.value.code == 2 and not connected_cli
    assert not (project / "runs").exists()


@pytest.mark.parametrize("flags", [["--input-run", "run_extract_0001"], ["--purpose", "pilot"],
                                    ["--source-path", loop.SOURCE], ["--resume"]])
def test_unknown_flags_do_not_start_verification(project, connected_cli, flags):
    with pytest.raises(SystemExit) as caught:
        cli.main(arguments(project) + flags)
    assert caught.value.code == 2 and not connected_cli


@pytest.mark.parametrize("selection", [{"profile": "missing"}, {"profile": loop.PROFILE},
                                       {"input-run-id": "run_extract_9999"}])
def test_bad_selections_do_not_allocate_an_attempt_or_request_a_model(
    project, baseline, scripted, connected_cli, selection,
):
    before = verifier.saved_bytes(project)
    assert cli.main(arguments(project, **selection)) == 1
    assert verifier.saved_bytes(project) == before and not scripted.requests


def make_comparison(project):
    registry = storage.load_registry(project)
    registry["plans"][0]["study_set"] = "comparison"
    storage.save_registry(project, registry)


def test_comparison_setup_errors_are_available_for_debugging(project, monkeypatch, capsys):
    make_comparison(project)
    hidden = "UNSEEN_COMPARISON_TEXT"
    async def fail(*args, **options):
        logging.getLogger("httpx.verifier_test").warning(hidden)
        error = ValueError(hidden)
        error.add_note(hidden)
        raise error
    monkeypatch.setattr(agents, "run_verifier", fail)
    assert cli.main(arguments(project, purpose="comparison")) == 1
    output = capsys.readouterr()
    assert hidden in output.err and "withheld" not in output.out + output.err


def test_comparison_result_reports_repairs_errors_and_diagnostics(project, run_record, monkeypatch, capsys):
    make_comparison(project)
    hidden = "UNSEEN_COMPARISON_MODEL_CLAIM"
    record = copy.deepcopy(run_record)
    record.update(stage="verifier", run_id="run_verify_0001", input_run_id="run_extract_0001",
                  status="failed", error=hidden)
    report = {"remaining_errors": [{"category": "structure", "location": "$", "message": hidden}],
              "repairs": [{"rule": "code_fence", "location": "$", "before": hidden, "after": hidden}]}
    diagnostic = {"summary": {"possible_page_mismatch": 123, "unmatched_quote": 456,
                              "unconfirmed_page_span": 789, "corrected": 321}, "findings": [{"quote": hidden}]}
    result = agents.SavedVerifierRun(f"runs/{loop.PLAN_ID}/run_verify_0001/output.json", record,
        SimpleNamespace(final_validation=SimpleNamespace(report=report), quotation_diagnostics=diagnostic), hidden)
    async def finish(*args, **options):
        return result
    monkeypatch.setattr(agents, "run_verifier", finish)
    fake_reference = project / f"runs/{loop.PLAN_ID}/reference_initial.json"
    fake_reference.parent.mkdir(parents=True)
    fake_reference.write_text('{"not_a_validated_reference":true}')
    assert cli.main(arguments(project, purpose="comparison")) == 1
    output = capsys.readouterr()
    assert hidden in output.out + output.err
    assert "Status: failed" in output.out and "Extractor input: run_extract_0001" in output.out
    assert "Model requests:" in output.out and "Repair [" in output.out
    assert "Quotation/page flags:" in output.out
    assert "Quotation/page corrections:" in output.out
    assert all(str(count) in output.out for count in (123, 456, 789, 321))
    assert "withheld" not in output.out


def test_comparison_programming_errors_remain_visible(project, monkeypatch):
    async def fail(*args, **options):
        raise RuntimeError("Fictional programming error.")
    monkeypatch.setattr(agents, "run_verifier", fail)
    with pytest.raises(RuntimeError, match="programming error"):
        cli.main(arguments(project))


def test_installed_command_help_and_mocked_execution_work_with_spaces(project, baseline, facts, tmp_path):
    help_result = subprocess.run([str(COMMAND), "run_verify_mode", "--help"],
                                 text=True, capture_output=True, timeout=10)
    assert help_result.returncode == 0
    assert "--input-run-id" in help_result.stdout and "--retry-of-run-id" in help_result.stdout
    assert "--source-path" not in help_result.stdout
    root = project.with_name("verifier project with spaces")
    project.rename(root)
    fixture = tmp_path / "verify_fixture.json"
    fixture.write_text(json.dumps({"environment": facts, "answer": json.dumps(verifier.answer(baseline.record)),
                                   "model": verifier.MODEL}))
    driver = tmp_path / "verify_console_driver.py"
    driver.write_text('''import json,runpy,sys
from pathlib import Path
import httpx
import agents
fixture=json.loads(Path(sys.argv[1]).read_text())
agents._execution_environment=lambda *args:fixture["environment"].copy()
agents._code_snapshot=lambda:{"src/fixture.py":b"fixture"}
replies=[agents.FINAL_READY_SIGNAL,fixture["answer"]]
def handle(request):return httpx.Response(200,json={"model":fixture["model"],"choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":replies.pop(0)}}],"usage":{"prompt_tokens":21,"completion_tokens":7}})
transport=httpx.MockTransport(handle)
real=agents.run_verifier
async def run(*args,**kwargs):return await real(*args,**kwargs,_transport=transport)
agents.run_verifier=run
command=sys.argv[2]
sys.argv=sys.argv[2:]
runpy.run_path(command,run_name="__main__")
''')
    result = subprocess.run([sys.executable, str(driver), str(fixture), str(COMMAND), *arguments(root)],
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "Status: succeeded" in result.stdout and "Extractor input: run_extract_0001" in result.stdout
    record_path = output_record(root).relative_to(root).as_posix()
    assert storage.load_run_record(root, record_path)["status"] == "succeeded"
