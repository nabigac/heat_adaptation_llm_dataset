"""Select saved E inputs using fictional files, without model or MCP calls.

Reuse the storage tests' temporary PDF/preparation and publication helpers so
selection exercises full saved-run validation rather than mocked run dictionaries.
Every selection, including a failed one, must leave the project files unchanged.
"""

import copy
import json

import pytest

import agents
import storage
import test_run_storage as saved


project = saved.project
PLAN_ID = "plan_0099"


@pytest.fixture(autouse=True)
def no_model_requests(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Input selection must not authenticate, call a model, or start MCP.")

    monkeypatch.setattr(agents, "require_huggingface_token", forbidden)
    monkeypatch.setattr(agents, "request_huggingface_chat", forbidden)
    monkeypatch.setattr(agents, "_document_client", forbidden)


@pytest.fixture
def save_extractor(project, run_record):
    def publish(run_id, *, status="succeeded", purpose="development"):
        record = copy.deepcopy(run_record)
        record.update(run_id=run_id, purpose=purpose)
        active = saved.running(record, run_id)
        path = storage.create_run_record(project, active)
        if status == "succeeded":
            saved.complete(project, path, record)
        elif status == "failed":
            active.update(status="failed", ended_at=record["ended_at"],
                          elapsed_seconds=1.0, error="Fictional extraction failure.")
            storage.save_run_record(project, active)
        return path

    return publish


def save_verifier(project, input_path, *, status="failed"):
    baseline = storage.load_run_record(project, input_path)
    record = saved.running(baseline, "run_verify_0001", stage="verifier",
                           input_run_id=baseline["run_id"])
    record["settings"]["name"] = "fictional_verifier"
    record["settings"]["model"]["name"] = "test-lab/fictional-verifier"
    path = storage.create_run_record(project, record)
    if status != "running":
        record.update(status=status, ended_at=baseline["ended_at"], elapsed_seconds=1.0,
                      error="Fictional verification failure." if status == "failed" else None)
        if status == "succeeded":
            record["plan_data"] = baseline["plan_data"]
            record["plan_issues"] = baseline["plan_issues"]
            record["model_calls"] = baseline["model_calls"]
            saved.complete(project, path, record)
        else:
            storage.save_run_record(project, record)
    return path


def select(project, *, plan_id=PLAN_ID, purpose="development", **kwargs):
    before = saved.snapshot(project)
    try:
        return agents.select_verifier_input_run(project, plan_id, purpose=purpose, **kwargs)
    finally:
        assert saved.snapshot(project) == before


def set_study_set(project, study_set):
    registry = storage.load_registry(project)
    registry["plans"][0]["study_set"] = study_set
    storage.save_registry(project, registry)


def test_default_uses_run_number_instead_of_creation_order(project, save_extractor):
    higher = save_extractor("run_extract_10000")
    save_extractor("run_extract_9999")
    chosen = select(project)
    assert chosen == storage.load_run_record(project, higher)


def test_default_skips_failed_running_and_incomplete_attempts(project, save_extractor):
    successful = save_extractor("run_extract_0001")
    save_extractor("run_extract_0002", status="failed")
    save_extractor("run_extract_0003", status="running")
    parent = project / f"runs/{PLAN_ID}"
    (parent / "run_extract_0004").mkdir()
    (parent / "run_extract_0005").write_text("Interrupted directory allocation.")
    (parent / "run_extract_0000").mkdir()
    (parent / "run_extract_notes").mkdir()
    save_verifier(project, successful, status="succeeded")
    assert select(project)["run_id"] == "run_extract_0001"


@pytest.mark.parametrize("damage", ["json", "missing-output", "fingerprint", "response", "report"])
def test_default_skips_damaged_success_but_explicit_selection_fails(project, save_extractor, damage):
    save_extractor("run_extract_0001")
    latest = project / save_extractor("run_extract_0002")
    if damage == "json":
        latest.write_text("{broken JSON")
    elif damage == "missing-output":
        latest.unlink()
    elif damage == "fingerprint":
        (latest.parent / "artifacts/extractor_input.json").write_text(
            json.dumps({"source_fingerprint": "wrong"}))
    elif damage == "response":
        (latest.parent / "responses/response_01.json").unlink()
    else:
        (latest.parent / "validation_report.json").unlink()
    assert select(project)["run_id"] == "run_extract_0001"
    with pytest.raises(agents.VerifierInputError, match="Cannot load"):
        select(project, input_run_id="run_extract_0002")


def test_explicit_selection_keeps_an_older_success(project, save_extractor):
    older = save_extractor("run_extract_0001")
    save_extractor("run_extract_0002")
    assert select(project, input_run_id="run_extract_0001") == storage.load_run_record(project, older)


@pytest.mark.parametrize("status", ["failed", "running"])
def test_explicit_unsuccessful_extractor_never_falls_back(project, save_extractor, status):
    save_extractor("run_extract_0001")
    save_extractor("run_extract_0002", status=status)
    with pytest.raises(agents.VerifierInputError, match="successful extractor"):
        select(project, input_run_id="run_extract_0002")


@pytest.mark.parametrize("run_id", ["", "../run_extract_0001", "run_extract_0001/extra",
                                    "run_extract_0001\\extra", "C:run_extract_0001",
                                    "run_extract_0000", "run_verify_0001", 1])
def test_explicit_id_must_be_a_numbered_extractor_id(project, save_extractor, run_id):
    save_extractor("run_extract_0001")
    with pytest.raises(agents.VerifierInputError, match="numbered run_extract"):
        select(project, input_run_id=run_id)


def test_explicit_missing_extractor_never_falls_back(project, save_extractor):
    save_extractor("run_extract_0001")
    with pytest.raises(agents.VerifierInputError, match="Cannot load"):
        select(project, input_run_id="run_extract_9999")


@pytest.mark.parametrize("with_failed_attempt", [False, True])
def test_no_eligible_extraction_is_an_error(project, save_extractor, with_failed_attempt):
    if with_failed_attempt:
        save_extractor("run_extract_0001", status="failed")
    with pytest.raises(agents.VerifierInputError, match="No validated, successful"):
        select(project)


@pytest.mark.parametrize("plan_id", ["plan_0001", "../plan_0099", "plan_0099/extra", None])
def test_unknown_or_unsafe_plan_id_is_rejected(project, save_extractor, plan_id):
    save_extractor("run_extract_0001")
    with pytest.raises(agents.VerifierInputError, match="No registered plan"):
        select(project, plan_id=plan_id)


@pytest.mark.parametrize("purpose", ["analysis", "", None])
def test_unknown_purpose_is_rejected(project, purpose):
    with pytest.raises(agents.VerifierInputError, match="Select development"):
        select(project, purpose=purpose)


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("study_set,purpose,extractor_purpose,allowed", [
    ("development", "development", "development", True),
    ("development", "development", "exploratory", True),
    ("comparison", "comparison", "comparison", True),
    ("comparison", "comparison", "exploratory", False),
    ("comparison", "exploratory", "comparison", True),
    ("expansion", "exploratory", "exploratory", True),
    ("development", "comparison", "development", False),
    ("comparison", "development", "comparison", False),
    ("expansion", "development", "exploratory", False),
])
def test_default_and_explicit_selection_share_purpose_rules(
    project, save_extractor, explicit, study_set, purpose, extractor_purpose, allowed,
):
    set_study_set(project, study_set)
    save_extractor("run_extract_0001", purpose=extractor_purpose)
    kwargs = {"input_run_id": "run_extract_0001"} if explicit else {}
    if allowed:
        assert select(project, purpose=purpose, **kwargs)["run_id"] == "run_extract_0001"
    else:
        with pytest.raises(agents.VerifierInputError):
            select(project, purpose=purpose, **kwargs)


def test_comparison_skips_newer_exploratory_extraction(project, save_extractor):
    set_study_set(project, "comparison")
    save_extractor("run_extract_0001", purpose="comparison")
    save_extractor("run_extract_0002", purpose="exploratory")
    assert select(project, purpose="comparison")["run_id"] == "run_extract_0001"


def test_selected_snapshot_keeps_saved_source_and_settings(project, save_extractor):
    original = save_extractor("run_extract_0001")
    chosen = select(project)
    expected = copy.deepcopy(chosen)
    save_extractor("run_extract_0002")
    registry = storage.load_registry(project)
    registry["plans"][0].update(source_url="https://example.org/corrected.pdf",
                                 date_accessed="2026-11-19", prepared_source_path=None)
    storage.save_registry(project, registry)
    assert chosen == expected
    assert select(project, input_run_id=chosen["run_id"]) == expected
    assert chosen["source_path"] == "data/processed/plan_0099/preparation_02/preparation.json"
    chosen["settings"]["generation"]["max_output_tokens"] = 1
    assert storage.load_run_record(project, original) == expected


def test_changed_prepared_text_invalidates_the_selection(project, save_extractor):
    saved_run = storage.load_run_record(project, save_extractor("run_extract_0001"))
    pages_file = project / saved_run["source_path"].replace("preparation.json", "pages.json")
    pages = json.loads(pages_file.read_text())
    pages[0]["text"] = "Changed after extraction."
    pages_file.write_text(json.dumps(pages))
    with pytest.raises(agents.VerifierInputError, match="No validated, successful"):
        select(project)
    with pytest.raises(agents.VerifierInputError, match="startup fingerprint"):
        select(project, input_run_id="run_extract_0001")


def test_retry_keeps_its_exact_input_after_a_newer_extraction(project, save_extractor):
    first = save_extractor("run_extract_0001")
    save_verifier(project, first)
    save_extractor("run_extract_0002")
    assert select(project)["run_id"] == "run_extract_0002"
    assert select(project, retry_of_run_id="run_verify_0001")["run_id"] == "run_extract_0001"
    assert select(project, retry_of_run_id="run_verify_0001",
                  input_run_id="run_extract_0001")["run_id"] == "run_extract_0001"
    with pytest.raises(agents.VerifierInputError, match="retain its original"):
        select(project, retry_of_run_id="run_verify_0001", input_run_id="run_extract_0002")


@pytest.mark.parametrize("status", ["succeeded", "running"])
def test_only_failed_verifier_attempts_can_be_retried(project, save_extractor, status):
    save_verifier(project, save_extractor("run_extract_0001"), status=status)
    with pytest.raises(agents.VerifierInputError, match="Only a failed verifier"):
        select(project, retry_of_run_id="run_verify_0001")


@pytest.mark.parametrize("retry_id", ["run_extract_0001", "../run_verify_0001", "run_verify_9999"])
def test_invalid_retry_link_never_falls_back(project, save_extractor, retry_id):
    save_extractor("run_extract_0001")
    with pytest.raises(agents.VerifierInputError):
        select(project, retry_of_run_id=retry_id)


def test_damaged_retry_baseline_cannot_be_replaced_by_a_newer_success(project, save_extractor):
    first = save_extractor("run_extract_0001")
    save_verifier(project, first)
    save_extractor("run_extract_0002")
    (project / first).unlink()
    with pytest.raises(agents.VerifierInputError, match="Cannot load"):
        select(project, retry_of_run_id="run_verify_0001")
