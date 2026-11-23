"""Exercise independent E/V request ceilings and the linked E+V token debit."""

from copy import deepcopy
import json

import pytest

import agents
from agent_budget import AgentRequestBudget, InvestigationBudgetExhausted
import test_agent_loop as loop
import test_saved_extractor as saved
import test_verifier as verifier


project = loop.project
scripted = loop.scripted
facts = saved.facts
baseline = verifier.baseline


def configure(root, stage=loop.PROFILE, **changes):
    path = root / "configs/profiles.json"
    document = json.loads(path.read_text())
    next(profile for profile in document["profiles"] if profile["name"] == stage).update(changes)
    path.write_text(json.dumps(document))


def test_request_ceiling_ends_investigation_before_spending_the_final_slot(project, scripted, run_record):
    configure(project, max_model_requests=3, max_tool_calls=25)
    scripted.replies = [loop.message(calls=[loop.call()]), loop.message(calls=[loop.call()]),
                        loop.message(loop.answer(run_record))]
    result = loop.run(project, scripted)
    assert result.status == "succeeded", result.error
    assert [attempt.phase for attempt in result.model_attempts] == ["tool_use", "tool_use", "final"]
    assert result.tool_calls_started == 2
    assert "response_format" in scripted.requests[-1] and "tools" not in scripted.requests[-1]
    assert "model-request allowance is exhausted" in scripted.requests[-1]["messages"][-2]["content"]
    assert result.request_budget.report()["stage_model_requests"] == 3


def test_one_api_reply_can_use_all_25_tools_while_final_stays_within_two_requests(project, scripted, run_record):
    configure(project, max_model_requests=2, max_tool_calls=25, context_limit=131072)
    scripted.replies = [loop.message(calls=[loop.call() for _ in range(25)]),
                        loop.message(loop.answer(run_record))]
    result = loop.run(project, scripted)
    assert result.status == "succeeded", result.error
    assert len(scripted.requests) == 2
    assert result.tool_calls_started == len(scripted.client.calls) == 25


def test_single_request_allowance_uses_the_source_directly_for_a_strict_final(project, scripted, run_record):
    configure(project, max_model_requests=1, max_tool_calls=25)
    scripted.replies = [loop.message(loop.answer(run_record))]
    result = loop.run(project, scripted)
    assert result.status == "succeeded", result.error
    assert [attempt.phase for attempt in result.model_attempts] == ["final"]
    assert len(scripted.requests) == 1 and not scripted.client.calls


def test_tool_ceiling_still_applies_when_request_allowance_is_larger(project, scripted, run_record):
    configure(project, max_model_requests=25, max_tool_calls=1)
    scripted.replies = [loop.message(calls=[loop.call(), loop.call()]), loop.message(loop.answer(run_record))]
    result = loop.run(project, scripted)
    assert result.status == "succeeded", result.error
    assert result.tool_calls_started == 1 and len(scripted.requests) == 2
    assert result.tool_log[-1]["error"] == "Tool-call limit reached; request was not executed."


def test_aggregate_token_guard_hands_off_without_an_extra_paid_investigation(
    project, scripted, run_record, monkeypatch,
):
    configure(project, max_model_requests=25, max_tool_calls=25, max_estimated_tokens=100000, context_limit=65536)
    original = agents.estimate_huggingface_budget

    def estimate(request):
        result = original(request)
        # Controlled admission estimates leave capacity for one investigation
        # and the worst-case final, but not for another investigation.
        result.report.update(estimated_input_tokens=100000 - request.context_limit - request.max_output_tokens)
        return result

    monkeypatch.setattr(agents, "estimate_huggingface_budget", estimate)
    scripted.replies = [loop.message(calls=[loop.call()]), loop.message(loop.answer(run_record))]
    result = loop.run(project, scripted)
    assert result.status == "succeeded", result.error
    assert [attempt.phase for attempt in result.model_attempts] == ["tool_use", "final"]
    assert "estimated-token allowance is exhausted" in scripted.requests[-1]["messages"][-2]["content"]
    assert result.request_budget.report()["configuration_charged_estimated_tokens"] <= 100000


def test_exhausted_investigation_cannot_take_reserved_final_capacity():
    budget = AgentRequestBudget({"context_limit": 100, "max_model_requests": 3, "max_estimated_tokens": 150})
    budget.admit(50, final=False)
    before = budget.report()
    with pytest.raises(InvestigationBudgetExhausted, match="estimated-token"):
        budget.admit(1, final=False)
    assert budget.report() == before
    budget.admit(100, final=True)
    assert budget.report()["configuration_charged_estimated_tokens"] == 150
    with pytest.raises(ValueError, match="estimated-token"):
        budget.admit(1, final=True)


def test_successful_run_saves_admission_estimates_separately_from_api_usage(project, scripted, facts, run_record):
    configure(project, max_model_requests=2, max_estimated_tokens=100000)
    scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(run_record))]
    result = saved.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    folder = saved.folder(project, result)
    report = json.loads((folder / "artifacts/request_budget.json").read_text())
    assert report["stage_model_requests"] == len(result.record["model_calls"]) == 2
    assert report["stage_charged_estimated_tokens"] > sum(call["input_tokens"] for call in result.record["model_calls"])
    assert report["extractor_charged_estimated_tokens"] == 0
    assert report == result.execution.request_budget.report()
    assert (folder / "responses/attempt_01/request_budget.json").exists()
    assert saved.storage.load_run_record(project, result.record_path) == result.record


def test_verifier_debits_the_exact_archived_e_requests_without_rewriting_them(project, baseline, scripted):
    original = verifier.saved_bytes((project / baseline.record_path).parent)
    configure(project, verifier.PROFILE, max_model_requests=2, max_estimated_tokens=1000000)
    expected = 0
    for path in (project / baseline.record_path).parent.glob("responses/attempt_*/token_budget.json"):
        report = json.loads(path.read_text())
        expected += report["estimated_input_tokens"] + report["max_output_tokens"]
    verifier.prepare_replies(scripted, verifier.answer(baseline.record))
    result = verifier.execute(project, scripted)
    assert result.record["status"] == "succeeded", result.record["error"]
    report = json.loads((saved.folder(project, result) / "artifacts/request_budget.json").read_text())
    assert report["extractor_charged_estimated_tokens"] == expected > 0
    assert report["configuration_charged_estimated_tokens"] == expected + report["stage_charged_estimated_tokens"]
    assert verifier.saved_bytes((project / baseline.record_path).parent) == original


def test_insufficient_linked_token_capacity_stops_before_allocating_v(project, baseline, scripted):
    packet = agents.build_verifier_input(project, loop.PLAN_ID, profile_name=verifier.PROFILE, purpose="development")
    configure(project, verifier.PROFILE, max_estimated_tokens=packet.settings["context_limit"])
    before = loop.snapshot(project)
    with pytest.raises(ValueError, match="cannot reserve"):
        verifier.execute(project, scripted)
    assert loop.snapshot(project) == before and not scripted.requests


@pytest.mark.parametrize("damage", ["missing", "malformed", "wrong_model", "wrong_output"])
def test_unverifiable_e_request_estimates_block_v_before_allocation(project, baseline, scripted, damage):
    configure(project, verifier.PROFILE, max_estimated_tokens=1000000)
    path = (project / baseline.record_path).parent / "responses/attempt_01/request.json"
    if damage == "missing":
        path.unlink()
    elif damage == "malformed":
        path.write_text('{}')
    else:
        request = json.loads(path.read_text())
        request["body"]["model" if damage == "wrong_model" else "max_tokens"] = "wrong"
        path.write_text(json.dumps(request))
    before = loop.snapshot(project)
    with pytest.raises((ValueError, OSError)):
        verifier.execute(project, scripted)
    assert loop.snapshot(project) == before and not scripted.requests


@pytest.mark.parametrize("value", [0, -1, True, None, 1.5])
def test_invalid_request_caps_are_rejected_by_profile_loading(project, value):
    configure(project, max_model_requests=value)
    with pytest.raises(agents.ProfileValidationError):
        agents.load_profile(project, loop.PROFILE, stage="extractor")


def test_saved_run_validation_rejects_more_requests_than_the_saved_ceiling(run_record):
    import validation
    record = deepcopy(run_record)
    record["settings"]["max_model_requests"] = 1
    record["model_calls"] = record["model_calls"] * 2
    assert any("exceed the stage allowance" in problem.message for problem in validation.validate_run_record(record, page_count=5))
