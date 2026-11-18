"""Check terminal selection, saved outcomes, feedback restrictions and Ctrl+C.

Model HTTP is controlled. Storage and the saved coordinator remain real, and
separate subprocess cases exercise the installed command and signal handling.
These tests do not download models or extract real research plans.
"""

import asyncio
import copy
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

import agents
import cli
import storage
import test_agent_loop as loop
import test_saved_extractor as saved_tests

project = loop.project
scripted = loop.scripted
facts = saved_tests.facts
REPOSITORY = Path(__file__).resolve().parents[1]
COMMAND = REPOSITORY / ".venv/bin/heat-adaptation-llm-dataset"




def arguments(root, **changes):
    values = {"source-path": loop.SOURCE, "profile": loop.PROFILE, "purpose": "development", **changes}
    return ["run_extract_mode", loop.PLAN_ID, "--project-root", str(root),
            *(value for key, item in values.items() for value in ("--" + key, str(item)))]


@pytest.fixture
def connected_cli(monkeypatch, scripted):
    run = agents.run_extractor
    calls = []
    async def execute(*args, **options):
        calls.append((args, copy.deepcopy(options)))
        return await run(*args, **options, _transport=scripted.transport)
    monkeypatch.setattr(agents, "run_extractor", execute)
    return calls


def ready(scripted, run_record, *, fenced=False):
    answer = loop.answer(run_record)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL),
                        loop.message("```json\n" + answer + "\n```" if fenced else answer)]


def output_record(root, number=1):
    return root / f"runs/{loop.PLAN_ID}/run_extract_{number:04d}/output.json"


def test_extract_runs_real_saved_workflow_and_reports_actual_files(project, scripted, facts, connected_cli, run_record, capsys):
    ready(scripted, run_record)
    assert cli.main(arguments(project)) == 0
    output = capsys.readouterr()
    record = storage.load_run_record(project, output_record(project).relative_to(project).as_posix())
    assert record["status"] == "succeeded" and len(scripted.requests) == 2
    assert "Status: succeeded" in output.out and "Model requests: 2" in output.out
    assert f"Run record: runs/{loop.PLAN_ID}/run_extract_0001/output.json" in output.out
    assert f"Validation report: runs/{loop.PLAN_ID}/run_extract_0001/validation_report.json" in output.out
    assert output.err == ""
    assert connected_cli[0][1] == {"source_path": loop.SOURCE, "profile_name": loop.PROFILE,
        "purpose": "development", "retry_of_run_id": None, "config_path": "configs/profiles.json"}


def test_development_feedback_shows_permitted_repairs(project, scripted, facts, connected_cli, run_record, capsys):
    ready(scripted, run_record, fenced=True)
    assert cli.main(arguments(project)) == 0
    output = capsys.readouterr()
    assert "Repair [" in output.out and "->" in output.out
    assert output_record(project).with_name("responses").joinpath("repaired_final.txt").is_file()


@pytest.mark.parametrize("failure", ["invalid", "truncated", "connection", "overflow"])
def test_failed_execution_returns_nonzero_with_preserved_record(project, scripted, facts, connected_cli, run_record, capsys, monkeypatch, failure):
    if failure == "connection":
        scripted.replies = [httpx.ConnectError("Controlled unavailable hosted API.")]
    elif failure == "overflow":
        def estimate(request):
            return saved_tests.models.TokenBudgetResult({"fits": False, "input_tokens": None, "error": "Controlled context overflow."}, {})
        monkeypatch.setattr(saved_tests.hf, "estimate_huggingface_budget", estimate)
    else:
        final = loop.message("not JSON" if failure == "invalid" else loop.answer(run_record))
        if failure == "truncated":
            final["choices"][0]["finish_reason"] = "length"
        scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), final]
    assert cli.main(arguments(project)) == 1
    output = capsys.readouterr()
    assert "Status: failed" in output.out and "Error:" in output.err
    assert json.loads(output_record(project).read_text())["status"] == "failed"
    assert len(scripted.requests) == (0 if failure == "overflow" else 1 if failure == "connection" else 2)
    if failure == "invalid":
        assert "[syntax]" in output.err and "Validation report:" in output.out


def test_unsaved_completion_reports_last_running_record_and_nonzero(project, scripted, facts, connected_cli, run_record, monkeypatch, capsys):
    save = agents.save_run_record
    def fail(root, record):
        if record["status"] != "running":
            raise OSError("Controlled terminal-status write failure.")
        return save(root, record)
    monkeypatch.setattr(agents, "save_run_record", fail)
    ready(scripted, run_record)
    assert cli.main(arguments(project)) == 1
    output = capsys.readouterr()
    assert "Status: running" in output.out and "Saving error:" in output.err
    assert "Status: succeeded" not in output.out
    assert json.loads(output_record(project).read_text())["status"] == "running"


def test_report_path_is_not_claimed_when_publication_failed(project, scripted, facts, connected_cli, run_record, monkeypatch, capsys):
    save = agents.save_run_file
    def fail(root, record, relative, raw):
        if relative == "validation_report.json":
            raise OSError("Controlled validation-report write failure.")
        return save(root, record, relative, raw)
    monkeypatch.setattr(agents, "save_run_file", fail)
    ready(scripted, run_record)
    assert cli.main(arguments(project)) == 1
    output = capsys.readouterr()
    assert "Validation report: not saved." in output.out
    assert not output_record(project).with_name("validation_report.json").exists()


@pytest.mark.parametrize("missing", ["--source-path", "--profile", "--purpose"])
def test_selection_flags_are_required_before_work(project, scripted, connected_cli, capsys, missing):
    args = arguments(project)
    index = args.index(missing)
    del args[index:index + 2]
    with pytest.raises(SystemExit) as error:
        cli.main(args)
    assert error.value.code == 2 and missing in capsys.readouterr().err
    assert not connected_cli and not scripted.requests and not (project / "runs").exists()


@pytest.mark.parametrize("flags", [["--purp", "development"], ["--purpose", "pilot"], ["--resume"]])
def test_invalid_or_abbreviated_flags_never_start_work(project, scripted, connected_cli, flags):
    with pytest.raises(SystemExit) as error:
        cli.main(arguments(project) + flags)
    assert error.value.code == 2 and not connected_cli and not scripted.requests


@pytest.mark.parametrize("selection", [{"profile": "missing-profile"}, {"source-path": loop.SOURCE.replace("02", "99")},
    {"source-path": f"runs/{loop.PLAN_ID}/reference_initial.json"}, {"purpose": "comparison"}])
def test_bad_selection_returns_nonzero_before_model_requests(project, scripted, facts, connected_cli, capsys, selection):
    assert cli.main(arguments(project, **selection)) == 1
    output = capsys.readouterr()
    assert "Traceback" not in output.err
    assert not scripted.requests and not (project / "runs").exists()


def test_custom_configuration_is_selected_explicitly(project, scripted, facts, connected_cli, run_record):
    path = project / "configs/custom.json"
    path.write_bytes((project / "configs/profiles.json").read_bytes())
    ready(scripted, run_record)
    assert cli.main(arguments(project, **{"config-path": "configs/custom.json"})) == 0
    assert connected_cli[0][1]["config_path"] == "configs/custom.json"


def test_manual_retry_gets_new_id_and_preserves_failed_attempt(project, scripted, facts, connected_cli, run_record):
    scripted.replies = [loop.message("Wrong tool-phase response.")]
    assert cli.main(arguments(project)) == 1
    old = output_record(project).read_bytes()
    ready(scripted, run_record)
    assert cli.main(arguments(project, **{"retry-of-run-id": "run_extract_0001"})) == 0
    record = json.loads(output_record(project, 2).read_text())
    assert record["retry_of_run_id"] == "run_extract_0001" and record["status"] == "succeeded"
    assert output_record(project).read_bytes() == old


def test_comparison_plan_exploration_hides_claims_issues_repairs_and_client_logs(project, scripted, facts, connected_cli, run_record, capsys):
    registry = storage.load_registry(project)
    registry["plans"][0]["study_set"] = "comparison"
    storage.save_registry(project, registry)
    facts["code_dirty"] = False
    hidden = "UNSEEN_COMPARISON_MODEL_CLAIM"
    answer = json.loads(loop.answer(run_record))
    answer["plan_data"]["actions"][0]["action"] = hidden
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message("```json\n" + json.dumps(answer) + "\n```")]
    scripted.hooks = [lambda body: logging.getLogger("mcp.test").warning(hidden)]
    # Presence of an arbitrary reference filename must not unlock disclosure.
    fake_reference = project / f"runs/{loop.PLAN_ID}/reference_initial.json"
    fake_reference.parent.mkdir(parents=True)
    fake_reference.write_text('{"not_a_validated_reference":true}')
    assert cli.main(arguments(project, purpose="exploratory")) == 0
    output = capsys.readouterr()
    assert "Status: succeeded" in output.out and "Validation report:" in output.out
    assert hidden not in output.out + output.err and "Repair [" not in output.out
    assert "withheld" in output.out and "Model requests:" not in output.out
    record = json.loads(output_record(project).read_text())
    assert record["plan_data"]["actions"][0]["action"] == hidden


def test_comparison_failure_hides_validation_values_and_exception_notes(project, scripted, facts, connected_cli, capsys):
    registry = storage.load_registry(project)
    registry["plans"][0]["study_set"] = "comparison"
    storage.save_registry(project, registry)
    facts["code_dirty"] = False
    hidden = "UNSEEN_MODEL_RESPONSE_FRAGMENT"
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message('{"' + hidden + '":1}')]
    assert cli.main(arguments(project, purpose="exploratory")) == 1
    output = capsys.readouterr()
    assert hidden not in output.out + output.err
    assert "Error categories:" in output.err and "structure" in output.err
    assert "Status: failed" in output.out


def test_blind_setup_errors_hide_arbitrary_values_and_recovery_notes(project, connected_cli, monkeypatch, capsys):
    hidden = "MODEL_TEXT_IN_EXCEPTION"
    async def fail(*args, **options):
        error = ValueError(hidden)
        error.add_note(hidden)
        raise error
    monkeypatch.setattr(agents, "run_extractor", fail)
    assert cli.main(arguments(project, purpose="comparison")) == 1
    output = capsys.readouterr()
    assert hidden not in output.out + output.err and "Error categories: other" in output.err


def test_logger_configuration_is_restored_after_extraction(project, scripted, facts, connected_cli, run_record):
    registry = storage.load_registry(project)
    registry["plans"][0]["study_set"] = "comparison"
    storage.save_registry(project, registry)
    logger = logging.getLogger("mcp")
    before = (logger.handlers[:], logger.propagate)
    ready(scripted, run_record)
    assert cli.main(arguments(project, purpose="exploratory")) == 0
    assert (logger.handlers, logger.propagate) == before


def test_comparison_subprocess_stderr_is_saved_without_terminal_disclosure(project, scripted, facts, connected_cli, run_record, monkeypatch, capfd):
    import mcp.client.stdio

    registry = storage.load_registry(project)
    registry["plans"][0]["study_set"] = "comparison"
    storage.save_registry(project, registry)
    facts["code_dirty"] = False
    sentinel = "UNSEEN_COMPARISON_SUBPROCESS_DIAGNOSTIC"
    transport = mcp.client.stdio.stdio_client
    def with_diagnostic(parameters, **options):
        parameters.args = ["-c", "import sys; print(" + repr(sentinel) + ", file=sys.stderr); import document_tools; raise SystemExit(document_tools.main())",
                           *parameters.args[2:]]
        return transport(parameters, **options)
    monkeypatch.setattr(mcp.client.stdio, "stdio_client", with_diagnostic)
    monkeypatch.setattr(agents, "_document_client", loop.REAL_DOCUMENT_CLIENT)
    ready(scripted, run_record)
    assert cli.main(arguments(project, purpose="exploratory")) == 0
    output = capfd.readouterr()
    assert sentinel not in output.out + output.err
    log = output_record(project).parent / "artifacts/mcp_stderr.log"
    assert sentinel.encode() in log.read_bytes()
    assert json.loads(output_record(project).read_text())["status"] == "succeeded"


def test_mcp_diagnostic_save_failure_fails_the_stage_after_cleanup(project, scripted, facts, connected_cli, run_record, monkeypatch, capsys):
    monkeypatch.setattr(agents, "_document_client", loop.REAL_DOCUMENT_CLIENT)
    save = agents.save_run_file
    def fail(root, record, relative, raw):
        if relative == "artifacts/mcp_stderr.log":
            raise OSError("Controlled MCP diagnostic publication failure.")
        return save(root, record, relative, raw)
    monkeypatch.setattr(agents, "save_run_file", fail)
    ready(scripted, run_record)
    assert cli.main(arguments(project)) == 1
    output = capsys.readouterr()
    assert "Status: failed" in output.out and "diagnostic publication failure" in output.err
    assert len(scripted.requests) == 2
    assert json.loads(output_record(project).read_text())["plan_data"] is None


def test_installed_command_help_and_bad_profile_exit_status(project):
    help_result = subprocess.run([str(COMMAND), "run_extract_mode", "--help"], text=True, capture_output=True, timeout=10)
    assert help_result.returncode == 0 and "--source-path" in help_result.stdout and "--retry-of-run-id" in help_result.stdout
    failed = subprocess.run([str(COMMAND), *arguments(project, profile="missing")], text=True, capture_output=True, timeout=10)
    assert failed.returncode == 1 and "No profile named" in failed.stderr and "Traceback" not in failed.stderr


def test_installed_entrypoint_saves_a_successful_run_in_a_project_with_spaces(project, facts, run_record, tmp_path):
    # Execute the installed console script itself after supplying controlled
    # model HTTP. MCP remains a real subprocess; no local network is needed.
    root = project.with_name("project with spaces")
    project.rename(root)
    fixture = tmp_path / "console_fixture.json"
    fixture.write_text(json.dumps({"environment": facts, "answer": loop.answer(run_record)}))
    driver = tmp_path / "console_driver.py"
    driver.write_text('''import json,runpy,sys
from pathlib import Path
import httpx
import agents,models
fixture=json.loads(Path(sys.argv[1]).read_text())
agents._execution_environment=lambda *args:fixture["environment"].copy()
agents._code_snapshot=lambda:{"src/fixture.py":b"fixture"}
replies=[agents.FINAL_READY_SIGNAL,fixture["answer"]]
def handle(request):return httpx.Response(200,json={"model":"test-lab/fictional-model","choices":[{"index":0,"finish_reason":"stop","message":{"role":"assistant","content":replies.pop(0)}}],"usage":{"prompt_tokens":21,"completion_tokens":7}})
transport=httpx.MockTransport(handle)
real=agents.run_extractor
async def run(*args,**kwargs):return await real(*args,**kwargs,_transport=transport)
agents.run_extractor=run
command=sys.argv[2]
sys.argv=sys.argv[2:]
runpy.run_path(command,run_name="__main__")
''')
    result = subprocess.run([sys.executable, str(driver), str(fixture), str(COMMAND), *arguments(root)],
                            text=True, capture_output=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "Status: succeeded" in result.stdout and "Model requests: 2" in result.stdout
    record_path = output_record(root).relative_to(root).as_posix()
    assert storage.load_run_record(root, record_path)["status"] == "succeeded"
    assert output_record(root).parent.joinpath("artifacts/mcp_stderr.log").is_file()


@pytest.mark.parametrize("diagnostic_failure", [False, True])
def test_sigint_returns_130_after_preserving_cancelled_run(project, facts, tmp_path, diagnostic_failure):
    environment = tmp_path / "environment.json"
    environment.write_text(json.dumps(facts))
    driver = tmp_path / "interrupt_driver.py"
    driver.write_text('''import asyncio,json,sys
from pathlib import Path
import httpx
import agents,models,cli
agents._execution_environment=lambda *args:json.loads(Path(sys.argv[1]).read_text())
agents._code_snapshot=lambda:{"src/fixture.py":b"fixture"}
if sys.argv[2]=="1":
 save=agents.save_run_file
 def fail(root,record,relative,raw):
  if relative=="artifacts/mcp_stderr.log":raise OSError("Controlled diagnostic save failure during cancellation.")
  return save(root,record,relative,raw)
 agents.save_run_file=fail
class Body(httpx.AsyncByteStream):
 async def __aiter__(self):
  yield b'{"message":{"role":"assistant","content":"partial'
  await asyncio.sleep(60)
transport=httpx.MockTransport(lambda request:httpx.Response(200,stream=Body()))
real=agents.run_extractor
async def run(*args,**kwargs):return await real(*args,**kwargs,_transport=transport)
agents.run_extractor=run
raise SystemExit(cli.main(sys.argv[3:]))
''')
    child = subprocess.Popen([sys.executable, str(driver), str(environment), str(int(diagnostic_failure)), *arguments(project)],
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    chunk = output_record(project).parent / "responses/attempt_01/chunks/part_0001.bin"
    try:
        deadline = time.monotonic() + 15
        while not chunk.exists() and time.monotonic() < deadline:
            if child.poll() is not None:
                raise AssertionError(child.stderr.read())
            time.sleep(0.05)
        assert chunk.is_file()
        os.kill(child.pid, signal.SIGINT)
        stdout, stderr = child.communicate(timeout=10)
        assert child.returncode == 130 and "Status: failed" in stdout
        assert "cancelled" in stderr and "Traceback" not in stderr
        record = json.loads(output_record(project).read_text())
        assert record["status"] == "failed" and record["ended_at"] is not None
        if diagnostic_failure:
            assert "diagnostics could not be saved" in record["error"] and "diagnostics could not be saved" in stderr
        assert chunk.read_bytes().endswith(b'"partial')
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate(timeout=5)
        child.stdout.close()
        child.stderr.close()
