"""Check accepted-answer and code-archive integrity for saved E/V attempts.

All edits and missing files are intentional damage in temporary projects. These
checks establish agreement between saved artifacts, not source correctness.
"""

from copy import deepcopy
import json

import pytest

import agents
import storage
import test_agent_loop as loop
import test_saved_extractor as extractor
from test_run_storage import complete, project as storage_project, publish_response, running, snapshot
from test_saved_extractor import facts
from test_verifier import baseline, execute, prepare_replies, project, scripted


@pytest.fixture(params=["extractor", "verifier"])
def pending_run(storage_project, run_record, request):
    """Publish final evidence while leaving the E or V record running."""
    project = storage_project
    final = deepcopy(run_record)
    stage = request.param
    if stage == "verifier":
        path = storage.create_run_record(project, running(run_record))
        complete(project, path, deepcopy(run_record))
        final.update(run_id="run_verify_0001", stage=stage, input_run_id=run_record["run_id"])
        final["settings"].update(name="fictional_verifier", stage=stage)
        final["settings"]["model"]["name"] = "test-lab/fictional-verifier"
    final["plan_issues"]["issues"] = [{
        "issue_id": "issue_0001", "related_action_id": "action_0001",
        "issue_description": "Check the fictional activity.", "issue_type": "source_issue",
        "issue_origin": stage, "issue_status": "open", "resolved_by": None, "resolution": None,
    }]
    active = running(final, final["run_id"], stage=stage, input_run_id=final["input_run_id"])
    path = storage.create_run_record(project, active)
    publish_response(project, path, final)
    return project, path, final


def candidate_file(root, path):
    report = json.loads((root / path).with_name("validation_report.json").read_text())
    return root / (report["repaired_response_path"] or report["raw_response_path"])


def test_successful_e_and_v_roundtrip_without_rewriting_evidence(pending_run):
    root, path, final = pending_run
    storage.save_run_record(root, final)
    # Today's editable implementation is independent of the archived startup
    # bytes. Loading must compare with the saved manifest, not the current file.
    current = root / "src/fixture.py"
    current.parent.mkdir()
    current.write_bytes(b"# later implementation\n")
    before = snapshot(root)
    assert storage.load_run_record(root, path) == final
    assert snapshot(root) == before


@pytest.mark.parametrize("when", ["finalization", "loading"])
@pytest.mark.parametrize("target", ["accepted_action", "accepted_issue", "candidate_action", "candidate_issue"])
def test_different_accepted_answer_and_candidate_are_rejected(pending_run, when, target):
    root, path, final = pending_run
    if when == "loading":
        storage.save_run_record(root, final)
    candidate = candidate_file(root, path)
    data = final if target.startswith("accepted") else json.loads(candidate.read_text())
    if target.endswith("action"):
        data["plan_data"]["actions"][0]["action"] = "A different activity, still valid JSON."
    else:
        data["plan_issues"]["issues"][0]["issue_description"] = "A different concern."
    if target.startswith("candidate"):
        candidate.write_text(json.dumps(data))
    elif when == "loading":
        (root / path).write_text(json.dumps(data))
    before = snapshot(root)
    with pytest.raises(storage.RunValidationError, match="differs from the preserved final candidate"):
        if when == "finalization":
            storage.save_run_record(root, final)
        else:
            storage.load_run_record(root, path)
    assert snapshot(root) == before


@pytest.mark.parametrize("raw", [
    b'{"unfinished":', b'[]', b'\xff', b'{"value":NaN}', b'{"value":1,"value":2}',
])
def test_saved_final_candidate_requires_strict_json(pending_run, raw):
    root, path, final = pending_run
    storage.save_run_record(root, final)
    candidate_file(root, path).write_bytes(raw)
    before = snapshot(root)
    with pytest.raises(storage.RunValidationError):
        storage.load_run_record(root, path)
    assert snapshot(root) == before


@pytest.mark.parametrize("when", ["finalization", "loading"])
@pytest.mark.parametrize("damage", ["changed_code", "missing_code", "missing_manifest", "wrong_digest"])
def test_missing_or_changed_code_evidence_blocks_success(pending_run, when, damage):
    root, path, final = pending_run
    if when == "loading":
        storage.save_run_record(root, final)
    folder = (root / path).parent
    code = folder / "artifacts/code/src/fixture.py"
    manifest = folder / "artifacts/code_fingerprints.json"
    if damage == "changed_code":
        code.write_bytes(b"# changed after startup\n")
    elif damage == "missing_code":
        code.unlink()
    elif damage == "missing_manifest":
        manifest.unlink()
    else:
        data = json.loads(manifest.read_text())
        data["sha256"]["src/fixture.py"] = "0" * 64
        manifest.write_text(json.dumps(data))
    before = snapshot(root)
    with pytest.raises((storage.RunValidationError, OSError)):
        if when == "finalization":
            storage.save_run_record(root, final)
        else:
            storage.load_run_record(root, path)
    assert snapshot(root) == before


@pytest.mark.parametrize("manifest", [
    b'[]', b'{}', b'{"sha256":{}}', b'{"sha256":[]}',
    b'{"sha256":{"src/fixture.py":"not-a-checksum"}}',
    b'{"sha256":{"../responses/final.txt":"' + b'0' * 64 + b'"}}',
    b'{"sha256":{"/tmp/other.py":"' + b'0' * 64 + b'"}}',
    b'{"sha256":{},"sha256":{}}',
])
def test_malformed_code_manifest_cannot_bypass_integrity_checks(pending_run, manifest):
    root, path, final = pending_run
    storage.save_run_record(root, final)
    ((root / path).parent / "artifacts/code_fingerprints.json").write_bytes(manifest)
    before = snapshot(root)
    with pytest.raises(storage.RunValidationError):
        storage.load_run_record(root, path)
    assert snapshot(root) == before


def test_failed_attempt_retains_incomplete_code_and_unparseable_final_evidence(pending_run):
    root, path, final = pending_run
    candidate_file(root, path).write_bytes(b'{"unfinished":')
    ((root / path).parent / "artifacts/code_fingerprints.json").unlink()
    final.update(status="failed", plan_data=None, plan_issues=None, error="Controlled incomplete evidence.")
    storage.save_run_record(root, final)
    before = snapshot(root)
    assert storage.load_run_record(root, path) == final
    assert snapshot(root) == before


@pytest.mark.parametrize("damage", ["candidate", "code"])
@pytest.mark.parametrize("stage", ["extractor", "verifier"])
def test_saved_runner_cannot_publish_success_with_inconsistent_evidence(
    project, baseline, scripted, monkeypatch, damage, stage,
):
    # Exercise the actual saved runner in addition to direct storage calls. The
    # earlier extractor is intact; only the new attempt's evidence is changed.
    if stage == "extractor":
        scripted.replies = [loop.message(agents.FINAL_READY_SIGNAL), loop.message(loop.answer(baseline.record))]
    else:
        prepare_replies(scripted, {name: deepcopy(baseline.record[name]) for name in ("plan_data", "plan_issues")})
    save = agents.save_run_record

    def damage_before_success(root, record):
        if record["stage"] == stage and record["status"] == "succeeded":
            path = f"runs/{record['plan_id']}/{record['run_id']}/output.json"
            if damage == "candidate":
                target = candidate_file(root, path)
                data = json.loads(target.read_text())
                data["plan_data"]["actions"][0]["action"] = "Different preserved activity."
                target.write_text(json.dumps(data))
            else:
                ((root / path).parent / "artifacts/code/src/fixture.py").write_bytes(b"changed archive")
        return save(root, record)

    monkeypatch.setattr(agents, "save_run_record", damage_before_success)
    saved = extractor.execute(project, scripted) if stage == "extractor" else execute(project, scripted)
    assert saved.record["status"] != "succeeded"
    assert saved.persistence_error and "differs" in saved.persistence_error
    assert len(scripted.requests) == 2
    assert storage.load_run_record(project, saved.record_path)["status"] == "running"
