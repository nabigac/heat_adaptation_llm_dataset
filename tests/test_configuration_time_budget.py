"""Check complete-configuration deadlines with controlled clocks and clients."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

import agents
import validation
import test_agent_loop as loop
import test_saved_extractor as saved
import test_verifier as verifier


project = loop.project
scripted = loop.scripted
facts = saved.facts
baseline = verifier.baseline


class Clock:
    """Advance controller time without changing asyncio or transport clocks."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now


def set_limit(project, seconds, *, profile=loop.PROFILE):
    path = project / "configs/profiles.json"
    config = json.loads(path.read_text())
    selected = next(item for item in config["profiles"] if item["name"] == profile)
    selected.update(max_elapsed_seconds=seconds, model_timeout_seconds=1800)
    path.write_text(json.dumps(config))


def known_extractor_duration(project, baseline, seconds):
    # Only this isolated fixture is changed, before taking preservation snapshots.
    baseline.record["elapsed_seconds"] = seconds
    (project / baseline.record_path).write_text(json.dumps(baseline.record))


def test_extraction_clock_includes_setup_and_clips_both_model_requests(
    project, scripted, facts, run_record, monkeypatch,
):
    set_limit(project, 100)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    original = agents.build_extractor_input

    def prepare(*args, **kwargs):
        packet = original(*args, **kwargs)
        clock.now = 40
        return packet

    monkeypatch.setattr(agents, "build_extractor_input", prepare)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    scripted.hooks = [lambda body: setattr(clock, "now", 45), lambda body: setattr(clock, "now", 50)]
    result = saved.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    assert result.record["elapsed_seconds"] == result.execution.elapsed_seconds == 50
    assert [attempt.request.timeout_seconds for attempt in result.execution.model_attempts] == [60, 55]
    report = json.loads((saved.folder(project, result) / "artifacts/time_budget.json").read_text())
    assert report == {"configuration_limit_seconds": 100, "input_run_id": None,
                      "extractor_elapsed_seconds": 0, "stage_allowance_seconds": 100}


@pytest.mark.parametrize("expire_on", ["investigation", "final", "validation"])
def test_extraction_cannot_succeed_after_its_deadline(
    project, scripted, facts, run_record, monkeypatch, expire_on,
):
    set_limit(project, 10)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    if expire_on == "investigation":
        scripted.hooks = [lambda body: setattr(clock, "now", 11)]
    elif expire_on == "final":
        scripted.hooks = [lambda body: setattr(clock, "now", 6), lambda body: setattr(clock, "now", 11)]
    else:
        original = agents._correct_final_quotation_pages

        def finish(*args):
            original(*args)
            clock.now = 11

        monkeypatch.setattr(agents, "_correct_final_quotation_pages", finish)
    result = saved.execute(project, scripted)
    assert result.record["status"] == "failed" and result.record["plan_data"] is None
    assert "time allowance exhausted" in result.record["error"]
    assert len(scripted.requests) == (1 if expire_on == "investigation" else 2)
    assert result.execution.model_attempts[0].request.timeout_seconds == 10
    if expire_on == "final":
        assert result.execution.model_attempts[1].request.timeout_seconds == 4
    assert scripted.client.closed
    assert saved.storage.load_run_record(project, result.record_path) == result.record


def test_document_wait_uses_remaining_time_and_cannot_trigger_another_model_call(
    project, scripted, facts, monkeypatch,
):
    set_limit(project, 10)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    scripted.replies = [loop.message(calls=[loop.call()])]
    scripted.hooks = [lambda body: setattr(clock, "now", 6)]
    original = scripted.client.call_tool

    async def slow_tool(*args):
        result = await original(*args)
        clock.now = 11
        return result

    scripted.client.call_tool = slow_tool
    original_wait = agents._bounded_mcp_request
    timeouts = []

    async def observe(awaitable, seconds):
        timeouts.append(seconds)
        return await original_wait(awaitable, seconds)

    monkeypatch.setattr(agents, "_bounded_mcp_request", observe)
    result = saved.execute(project, scripted)
    assert result.record["status"] == "failed" and len(scripted.requests) == 1
    assert timeouts == [10, 10, 4]  # Server startup, catalogue, document request.
    assert result.execution.tool_calls_started == 1 and result.execution.tool_log[0]["error"]
    assert scripted.client.closed


def test_verification_deducts_only_its_pinned_extraction_duration(
    project, baseline, scripted, monkeypatch,
):
    known_extractor_duration(project, baseline, 60)
    original = verifier.saved_bytes((project / baseline.record_path).parent)
    set_limit(project, 100, profile=verifier.PROFILE)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    verifier.prepare_replies(scripted, verifier.answer(baseline.record))
    scripted.hooks = [lambda body: setattr(clock, "now", 5), lambda body: setattr(clock, "now", 10)]
    result = verifier.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    assert result.record["input_run_id"] == baseline.record["run_id"]
    assert [attempt.request.timeout_seconds for attempt in result.execution.model_attempts] == [40, 35]
    report = json.loads((saved.folder(project, result) / "artifacts/time_budget.json").read_text())
    assert report == {"configuration_limit_seconds": 100, "input_run_id": baseline.record["run_id"],
                      "extractor_elapsed_seconds": 60, "stage_allowance_seconds": 40}
    assert verifier.saved_bytes((project / baseline.record_path).parent) == original
    assert saved.storage.load_run_record(project, result.record_path) == result.record


@pytest.mark.parametrize("duration", [100, 101])
def test_exhausted_extraction_blocks_verification_before_allocation(
    project, baseline, scripted, duration,
):
    known_extractor_duration(project, baseline, duration)
    set_limit(project, 100, profile=verifier.PROFILE)
    original = verifier.saved_bytes(project)
    with pytest.raises(ValueError, match="linked extraction has exhausted"):
        verifier.execute(project, scripted)
    assert not scripted.requests and verifier.saved_bytes(project) == original


def test_verifier_retry_receives_a_new_attempt_with_the_same_e_deduction(
    project, baseline, scripted, monkeypatch,
):
    known_extractor_duration(project, baseline, 60)
    set_limit(project, 100, profile=verifier.PROFILE)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    scripted.replies = [verifier.message(agents.FINAL_READY_SIGNAL)]
    scripted.hooks = [lambda body: setattr(clock, "now", 41)]
    failed = verifier.execute(project, scripted)
    assert failed.record["status"] == "failed"
    original = verifier.saved_bytes((project / failed.record_path).parent)
    clock.now = 0
    scripted.requests.clear()
    scripted.client = loop.FakeClient()
    verifier.prepare_replies(scripted, verifier.answer(baseline.record))
    scripted.hooks = []
    retried = verifier.execute(project, scripted, retry_of_run_id=failed.record["run_id"])
    assert retried.record["status"] == "succeeded", retried.record["error"]
    assert retried.execution.model_attempts[0].request.timeout_seconds == 40
    assert retried.record["input_run_id"] == failed.record["input_run_id"]
    assert verifier.saved_bytes((project / failed.record_path).parent) == original


@pytest.mark.parametrize("duration", [None, -1, float("inf"), float("nan"), True])
def test_unknown_or_invalid_baseline_duration_cannot_create_a_timed_budget(
    project, baseline, duration,
):
    set_limit(project, 100, profile=verifier.PROFILE)
    packet = agents.build_verifier_input(project, loop.PLAN_ID,
        profile_name=verifier.PROFILE, purpose="comparison")
    packet.input_run["elapsed_seconds"] = duration
    with pytest.raises(ValueError, match="recorded elapsed duration"):
        agents._configuration_time_budget(packet)


def test_saved_success_requires_the_combined_e_and_v_duration_to_fit(run_record):
    extraction = deepcopy(run_record)
    extraction["elapsed_seconds"] = 60
    verification = deepcopy(run_record)
    verification.update(stage="verifier", run_id="run_verify_0001",
                        input_run_id=extraction["run_id"], elapsed_seconds=41)
    verification["settings"].update(stage="verifier", max_elapsed_seconds=100)
    problems = validation.validate_run_links(verification, input_run=extraction)
    assert any("shared time allowance" in problem.message for problem in problems)
    verification["status"] = "failed"
    assert not any("time allowance" in problem.message for problem in
                   validation.validate_run_links(verification, input_run=extraction))


@pytest.mark.parametrize("value", [0, -1, True, None, float("inf")])
def test_invalid_configuration_ceiling_is_rejected_during_profile_loading(project, value):
    set_limit(project, value)
    with pytest.raises(agents.ProfileValidationError):
        agents.load_profile(project, loop.PROFILE, stage="extractor")


def test_current_profiles_and_c_binding_have_the_same_configuration_ceiling():
    root = Path(__file__).resolve().parents[1]
    for name, stage in (("inkling2_small_hf_extractor", "extractor"),
                        ("deepseek_v4_1_flash_1017_hf_verifier", "verifier")):
        assert agents.load_profile(root, name, stage=stage)["max_elapsed_seconds"] == 5400
    config = json.loads((root / "configs/collaboration.json").read_text())
    assert config["profiles"][0]["limits"]["max_elapsed_seconds"] == 5400
    assert config["profiles"][0]["limits"]["final_generation_seconds"] == 1800


def protect_final(project, seconds=30, *, profile=loop.PROFILE):
    set_limit(project, 100, profile=profile)
    path = project / "configs/profiles.json"
    document = json.loads(path.read_text())
    next(p for p in document["profiles"] if p["name"] == profile).update(
        final_generation_seconds=seconds, model_timeout_seconds=seconds,
    )
    path.write_text(json.dumps(document))


def test_protected_final_clips_investigation_separately_from_the_last_request(
    project, scripted, facts, run_record, monkeypatch,
):
    protect_final(project)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    original = agents.build_extractor_input

    def prepare(*args, **kwargs):
        packet = original(*args, **kwargs)
        clock.now = 60
        return packet

    monkeypatch.setattr(agents, "build_extractor_input", prepare)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    scripted.hooks = [lambda body: setattr(clock, "now", 65), lambda body: setattr(clock, "now", 80)]
    result = saved.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    assert [a.request.timeout_seconds for a in result.execution.model_attempts] == [10, 30]
    folder = saved.folder(project, result)
    handoff = json.loads((folder / "artifacts/final_handoff.json").read_text())
    assert handoff["stage_prefinal_elapsed_seconds"] == 65
    assert handoff["configuration_prefinal_elapsed_seconds"] == 65


def test_investigation_boundary_stops_new_tools_and_uses_the_final_window(
    project, scripted, facts, run_record, monkeypatch,
):
    protect_final(project)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    scripted.replies = [loop.message(calls=[loop.call()]), loop.message(loop.answer(run_record))]
    scripted.hooks = [lambda body: setattr(clock, "now", 70), lambda body: setattr(clock, "now", 90)]
    result = saved.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    assert not scripted.client.calls and result.execution.tool_calls_started == 0
    assert len(scripted.requests) == 2
    assert "Investigation time is exhausted" in scripted.requests[-1]["messages"][-2]["content"]
    assert result.execution.model_attempts[-1].request.timeout_seconds == 30


def test_setup_reaching_final_window_skips_investigation_and_still_saves_a_valid_run(
    project, scripted, facts, run_record, monkeypatch,
):
    protect_final(project)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    original = agents.build_extractor_input

    def prepare(*args, **kwargs):
        packet = original(*args, **kwargs)
        clock.now = 70
        return packet

    monkeypatch.setattr(agents, "build_extractor_input", prepare)
    scripted.replies = [loop.message(loop.answer(run_record))]
    result = saved.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    assert [a.phase for a in result.execution.model_attempts] == ["final"]
    assert not scripted.client.entered
    assert saved.storage.load_run_record(project, result.record_path) == result.record


@pytest.mark.parametrize("duration", [71, 99])
def test_extractor_must_leave_the_protected_v_window_before_any_v_run_is_allocated(
    project, baseline, scripted, duration,
):
    known_extractor_duration(project, baseline, duration)
    protect_final(project, profile=verifier.PROFILE)
    before = verifier.saved_bytes(project)
    with pytest.raises(ValueError, match="protected final window"):
        verifier.execute(project, scripted)
    assert verifier.saved_bytes(project) == before and not scripted.requests


def test_e_at_the_prefinal_boundary_leaves_only_the_v_final_request(
    project, baseline, scripted, monkeypatch,
):
    known_extractor_duration(project, baseline, 70)
    protect_final(project, profile=verifier.PROFILE)
    clock = Clock()
    monkeypatch.setattr(agents, "time", clock)
    scripted.replies = [verifier.message(json.dumps(verifier.answer(baseline.record)))]
    result = verifier.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    assert [a.phase for a in result.execution.model_attempts] == ["final"]
    report = json.loads((saved.folder(project, result) / "artifacts/time_budget.json").read_text())
    assert report["stage_allowance_seconds"] == report["final_generation_seconds"] == 30
    assert report["investigation_allowance_seconds"] == 0


def test_v_investigation_deducts_e_from_the_common_prefinal_allowance(project, baseline, scripted):
    known_extractor_duration(project, baseline, 20)
    protect_final(project, profile=verifier.PROFILE)
    packet = agents.build_verifier_input(project, loop.PLAN_ID, profile_name=verifier.PROFILE, purpose="comparison")
    budget = agents._configuration_time_budget(packet)
    assert budget["stage_allowance_seconds"] == 80
    assert budget["investigation_allowance_seconds"] == 50
    assert budget["final_generation_seconds"] == 30


@pytest.mark.parametrize("reserve", [101, float("inf"), True, None, 0])
def test_invalid_final_reserve_is_rejected_by_profile_loading(project, reserve):
    protect_final(project, reserve)
    with pytest.raises(agents.ProfileValidationError):
        agents.load_profile(project, loop.PROFILE, stage="extractor")


def test_protected_final_window_requires_an_overall_deadline(project):
    path = project / "configs/profiles.json"
    document = json.loads(path.read_text())
    document["profiles"][0]["final_generation_seconds"] = 30
    document["profiles"][0].pop("max_elapsed_seconds", None)
    path.write_text(json.dumps(document))
    with pytest.raises(agents.ProfileValidationError, match="requires an overall deadline"):
        agents.load_profile(project, loop.PROFILE, stage="extractor")
