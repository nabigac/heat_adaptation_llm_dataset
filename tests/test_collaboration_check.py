"""Run the coordinator diagnostic through mock HTTP; workers never use HTTP."""

import asyncio
from copy import deepcopy
import hashlib
import json

import httpx
import pytest

import collaboration_check as check
from collaboration_contracts import validate_bindings
from test_agent_loop import project
from test_collaboration import assignment
from test_collaboration_contracts import configured


TOKEN = "hf-fictional-coordination-test-token"


def final_answer():
    def action(identifier, description, types, location, evidence, cost=None):
        return {"action_id": identifier, "action": description, "action_type": types,
                "action_status": "planned", "action_location": location, "action_recipient": None,
                "action_cost": cost, "action_benefit": None, "evidence": evidence}
    def evidence(quote, page):
        return {"quote": quote, "page_numbers": [page]}
    return {"plan_data": {"metadata": {
        "plan_title": "Example City Heat Action Plan", "jurisdiction_name": "Example City",
        "country": "Example Country", "plan_scale": "city", "plan_type": "heat_specific_plan",
        "publication_year": 2026, "lead_agencies": ["Example City Council"],
        **check.SOURCE_METADATA, "language": "English",
    }, "actions": [
        action("action_0001", "Tree planting: plant 100 trees in North Ward in 2027.", ["nature-based"],
               "North Ward", [evidence(check.TREE_QUOTE, 1), evidence(check.BUDGET_QUOTE, 2)],
               "Conflicting programme estimates: EUR 50,000 and EUR 60,000; the source does not reconcile them."),
        action("action_0002", "Install three drinking fountains in Central Square in 2027.", ["infrastructural"],
               "Central Square", [evidence(check.FOUNTAIN_QUOTE, 1)]),
    ]}, "plan_issues": {"issues": [{
        "issue_id": "issue_0001", "related_action_id": "action_0001",
        "issue_description": "Physical page 2 gives incompatible EUR 50,000 and EUR 60,000 tree planting budgets.",
        "issue_type": "conflicting_evidence", "issue_origin": "coordinator", "issue_status": "open",
        "resolved_by": None, "resolution": None,
    }]}}


class CoordinatorHTTP:
    def __init__(self, *, final=None, failure=None, loop=False):
        self.answer = final or final_answer()
        self.failure, self.loop = failure, loop
        self.calls = []

    def __call__(self, request):
        body = json.loads(request.content)
        self.calls.append(body)
        assert body["model"] == "zai-org/GLM-5.3-Flash:deepinfra"
        assert body["max_tokens"] <= 16384
        if self.failure == "http":
            return httpx.Response(400, json={"error": {"message": "Fictional unsupported C tool arguments"}})
        if "response_format" in body:
            message = {"role": "assistant", "content": json.dumps(self.answer)}
            finish = "stop"
        else:
            number = len(self.calls)
            if self.loop:
                name, arguments = "submit_draft", {"based_on_version": number - 1, "draft": self.answer}
            elif number == 1:
                # Swap the model order: cards follow task order, not a permanent
                # extraction/checking specialization assigned to either model.
                name, arguments = "assign_tasks", {"assignments": [
                    assignment("worker_2"), assignment("worker_1"),
                ]}
            elif number == 2:
                name, arguments = "submit_draft", {"based_on_version": 0, "draft": self.answer}
            else:
                name, arguments = "finish_investigation", {}
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": f"coordinator-{number}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }]}
            finish = "tool_calls"
        return httpx.Response(200, json={"model": "z-ai/glm-5.3-flash",
            "choices": [{"index": 0, "message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 123, "completion_tokens": 456}})


@pytest.fixture
def ready(configured, monkeypatch):
    monkeypatch.setenv("HF_TOKEN", TOKEN)
    # Use the pilot's capacity so tests exercise the diagnostic override without
    # exhausting the smaller context in the shared fictional profile.
    profile_path = configured / "configs/profiles.json"
    profiles = json.loads(profile_path.read_text())
    for profile in profiles["profiles"]:
        profile["context_limit"] = 1048576
        profile["generation"]["max_output_tokens"] = 131072
    profile_path.write_text(json.dumps(profiles))
    return configured


def run(root, http):
    return asyncio.run(check.run_coordination_check(root, _transport=httpx.MockTransport(http)))


def test_diagnostic_caps_explicit_final_window_without_changing_the_binding(ready):
    path = ready / "configs/collaboration.json"
    document = json.loads(path.read_text())
    document["profiles"][0]["limits"]["final_generation_seconds"] = 1800
    path.write_text(json.dumps(document))
    before = path.read_bytes()
    packet, _, original = check.build_diagnostic_input(ready)
    validate_bindings(packet.configuration, packet.profiles)
    assert packet.configuration["limits"]["final_generation_seconds"] == 300
    assert original["configuration"]["limits"]["final_generation_seconds"] == 1800
    assert path.read_bytes() == before


def test_complete_check_preserves_calls_caps_and_explicit_controlled_provenance(ready):
    profiles_before = (ready / "configs/profiles.json").read_bytes()
    study_before = {str(p): p.read_bytes() for name in ("data", "runs", "expert_references")
                    for p in (ready / name).rglob("*") if p.is_file()}
    http = CoordinatorHTTP()
    path, report = run(ready, http)
    assert report["passed"] and report["status"] == "passed"
    assert report["coordinator_execution"] == "mock_transport"
    assert len(http.calls) == report["coordinator_http_attempts"] == 4
    assert report["output_limit_per_request"] == 16384
    assert all(body["max_tokens"] == 16384 for body in http.calls)
    assert report["controlled_worker_steps"] == 4 and len(report["calls"]) == 8
    assert report["coordinator_reported_usage"] == {"input_tokens": 492, "output_tokens": 1824}
    assert (ready / "configs/profiles.json").read_bytes() == profiles_before
    assert study_before == {str(p): p.read_bytes() for name in ("data", "runs", "expert_references")
                            for p in (ready / name).rglob("*") if p.is_file()}
    saved = json.loads((path.parent / "input.json").read_text())
    assert (ready / saved["packet"]["source_path"]).exists()
    for profile in saved["packet"]["profiles"].values():
        assert profile["generation"]["max_output_tokens"] == 16384
        assert profile["model_timeout_seconds"] <= 300
    assert saved["packet"]["configuration"]["limits"]["max_elapsed_seconds"] <= 900
    assert saved["packet"]["configuration"]["limits"]["max_model_requests"] == 21
    assert saved["base_settings"]["configuration"]["limits"]["max_model_requests"] == 21
    assert report["max_coordinator_http_attempts"] == 8
    assert (ready / saved["packet"]["profiles"]["coordinator"]["prompt_paths"][-1]).exists()
    manifest = json.loads((path.parent / "code_fingerprints.json").read_text())["sha256"]
    for name, digest in manifest.items():
        assert hashlib.sha256((path.parent / "code" / name).read_bytes()).hexdigest() == digest
    for record in report["calls"]:
        assert (path.parent / record["request_path"]).exists()
        assert (path.parent / record["response_path"]).exists()
        if record["execution_kind"] == "controlled_worker":
            assert record["http_attempted"] is False and record["generation_started"] is False
            assert record["input_tokens"] is None and record["http_status_code"] is None
    for file in path.parent.rglob("*"):
        if file.is_file():
            assert TOKEN.encode() not in file.read_bytes()
    outcome = json.loads((path.parent / "controller_result.json").read_text())
    assert outcome["answer"] == final_answer() and outcome["events"] and outcome["drafts"]
    assert json.loads(path.read_text()) == report


@pytest.mark.parametrize("damage,check_name", [
    ("wrong_count", "incorrect_worker_count_corrected"),
    ("lost_conflict", "source_budget_conflict_retained"),
    ("altered_quote", "quotation_pages_match"),
])
def test_structurally_valid_but_incorrect_fixture_answers_do_not_pass(ready, damage, check_name):
    answer = final_answer()
    if damage == "wrong_count":
        answer["plan_data"]["actions"][1]["action"] = "Install four drinking fountains in Central Square in 2027."
    elif damage == "lost_conflict":
        answer["plan_data"]["actions"][0]["action_cost"] = "Estimated EUR 50,000."
        answer["plan_issues"]["issues"] = []
    else:
        answer["plan_data"]["actions"][0]["evidence"][0]["quote"] = "The source says something else."
    http = CoordinatorHTTP(final=answer)
    path, report = run(ready, http)
    assert not report["passed"] and len(http.calls) == 4
    checks = {item["name"]: item["passed"] for item in report["checks"]}
    assert checks["controller_completed"] and not checks[check_name]
    assert json.loads((path.parent / "controller_result.json").read_text())["status"] == "succeeded"


def test_provider_error_is_saved_without_retry_or_worker_http(ready):
    http = CoordinatorHTTP(failure="http")
    path, report = run(ready, http)
    assert not report["passed"] and len(http.calls) == 1
    record = report["calls"][0]
    assert record["http_status_code"] == 400 and "HTTP 400" in report["error"]
    assert b"unsupported C tool arguments" in (path.parent / record["response_path"]).read_bytes()
    assert report["controlled_worker_steps"] == 0


def test_diagnostic_ceiling_stops_an_unproductive_coordinator_before_ninth_http_attempt(ready):
    http = CoordinatorHTTP(loop=True)
    path, report = run(ready, http)
    assert not report["passed"] and len(http.calls) == 8
    assert report["coordinator_http_attempts"] == 8
    assert report["calls"][-1]["execution_kind"] == "blocked_coordinator_request"
    assert report["calls"][-1]["http_attempted"] is False
    assert "ceiling" in report["error"]


@pytest.mark.parametrize("cancel", [False, True])
def test_partial_connection_failure_or_cancellation_keeps_received_bytes(ready, cancel):
    class Partial(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield b'{"partial":'
            if cancel:
                raise asyncio.CancelledError
            raise httpx.ReadError("Fictional incomplete body")
    def http(request):
        return httpx.Response(200, stream=Partial())
    if cancel:
        with pytest.raises(check.CoordinationCheckCancelled) as caught:
            run(ready, http)
        path = caught.value.report_path
        report = json.loads(path.read_text())
        assert report["status"] == "cancelled"
    else:
        path, report = run(ready, http)
        assert report["status"] == "failed"
    assert report["coordinator_http_attempts"] == 1
    record = report["calls"][0]
    raw = path.parent / record["response_path"]
    assert raw.read_bytes() == b'{"partial":'
    assert (raw.parent / "response.partial").read_bytes() == b'{"partial":'


@pytest.mark.parametrize("when", ["request", "response"])
def test_saving_failures_stop_further_http_requests(ready, monkeypatch, when):
    original = check._Recorder.new_bytes
    def fail(self, name, value):
        if name.endswith(f"/{when}.json"):
            raise OSError("Fictional saving failure")
        return original(self, name, value)
    monkeypatch.setattr(check._Recorder, "new_bytes", fail)
    http = CoordinatorHTTP()
    path, report = run(ready, http)
    assert not report["passed"] and "saving failure" in report["error"]
    assert len(http.calls) == (0 if when == "request" else 1)
    if when == "response":
        assert (path.parent / "calls/call_001/response.partial").read_bytes()


def test_missing_token_leaves_no_diagnostic_folder(configured, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    with pytest.raises(ValueError, match="HF_TOKEN"):
        run(configured, CoordinatorHTTP())
    assert not (configured / "artifacts").exists()


def test_code_change_during_check_prevents_passing(ready, monkeypatch):
    snapshots = iter([{"src/example.py": b"before"}, {"src/example.py": b"after"}])
    monkeypatch.setattr(check, "_code_snapshot", lambda: next(snapshots))
    _, report = run(ready, CoordinatorHTTP())
    assert not report["passed"]
    assert report["checks"][-1] == {"name": "code_unchanged", "passed": False,
                                  "detail": "Application code/contracts/lockfiles remained unchanged."}


@pytest.mark.parametrize("passed", [False, True])
def test_cli_uses_the_selected_binding_and_explains_controlled_workers(ready, monkeypatch, capsys, passed):
    monkeypatch.chdir(ready)
    monkeypatch.setattr("sys.argv", ["collaboration_check", "--profile", "chosen_binding"])
    received = []
    async def fake(root, profile):
        received.append((root, profile))
        return root / "artifacts/collaboration_checks/example/report.json", {
            "status": "passed" if passed else "failed", "passed": passed, "checks": [],
            "error": None if passed else "Fictional failure",
        }
    monkeypatch.setattr(check, "run_coordination_check", fake)
    assert check.main() == (0 if passed else 1)
    assert received == [(ready, "chosen_binding")]
    assert "Workers were controlled fixtures" in capsys.readouterr().out
