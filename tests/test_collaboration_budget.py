"""Check shared reservations before concurrent workers can spend capacity."""

from copy import deepcopy

import pytest

from collaboration_budget import CollaborationBudget, CollaborationBudgetExceeded
from test_collaboration import packet, reply


def test_request_batch_failure_is_atomic_and_final_slot_is_protected(packet):
    limits = dict(packet.configuration["limits"], max_model_requests=4)
    budget = CollaborationBudget(limits, packet.profiles)
    budget.reserve_batch({"a": 100, "b": 100})
    before = deepcopy(budget.reservations)
    with pytest.raises(CollaborationBudgetExceeded, match="model-request"):
        budget.reserve_batch({"c": 100, "d": 100})
    assert budget.reservations == before
    budget.consume("a", 90)
    assert budget.used_requests == 1 and budget.estimated_tokens == 90
    assert "coordinator_final" in budget.reservations


def test_input_estimate_and_full_output_reservations_share_one_token_ceiling(packet):
    limits = dict(packet.configuration["limits"], max_estimated_tokens=65536 + 100)
    budget = CollaborationBudget(limits, packet.profiles)
    budget.reserve_batch({"a": 100})
    with pytest.raises(CollaborationBudgetExceeded, match="estimated-token"):
        budget.reserve_batch({"b": 1})
    with pytest.raises(CollaborationBudgetExceeded, match="reserved token"):
        budget.consume("a", 101)
    assert budget.used_requests == 0
    budget.consume("a", 100)
    budget.observe_usage(reply(usage=False))
    assert budget.report()["charged_estimated_tokens"] == 100
    assert budget.report()["reported_usage"] == {"input_tokens": None, "output_tokens": None}


def test_per_agent_and_global_tool_limits_both_apply(packet):
    budget = CollaborationBudget(dict(packet.configuration["limits"], max_document_tool_calls=3), packet.profiles)
    assert budget.submit_tool("worker_1") and budget.submit_tool("worker_1")
    assert not budget.submit_tool("worker_1")
    assert budget.submit_tool("worker_2")
    assert not budget.submit_tool("coordinator")
    assert budget.report()["document_tool_calls"] == {"coordinator": 0, "worker_1": 2, "worker_2": 1}


def test_investigation_deadline_leaves_time_for_final_generation(packet):
    now = [0.0]
    budget = CollaborationBudget(packet.configuration["limits"], packet.profiles, clock=lambda: now[0])
    assert budget.seconds_left() == 9 and budget.seconds_left(final=True) == 10
    now[0] = 9
    assert budget.seconds_left() == 0 and budget.seconds_left(final=True) == 1
    with pytest.raises(CollaborationBudgetExceeded, match="time"):
        budget.reserve_batch({"late": 100})
    budget.consume("coordinator_final", 500)
    assert budget.used_requests == 1
    now[0] = 11
    assert budget.seconds_left(final=True) == 0


def test_used_provider_tokens_never_release_the_conservative_dispatch_charge(packet):
    budget = CollaborationBudget(packet.configuration["limits"], packet.profiles)
    budget.reserve_batch({"a": 500})
    budget.consume("a", 500)
    budget.observe_usage(reply())
    assert budget.report()["charged_estimated_tokens"] == 500
    assert budget.report()["reported_usage"] == {"input_tokens": 100, "output_tokens": 10}


def test_explicit_final_window_overrides_the_historical_model_timeout_default(packet):
    limits = dict(packet.configuration["limits"], final_generation_seconds=2)
    budget = CollaborationBudget(limits, packet.profiles, clock=lambda: 0)
    assert budget.seconds_left() == 8
    assert budget.seconds_left(final=True) == 10
