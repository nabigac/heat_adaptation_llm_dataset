"""Separate dataset-building execution from comparison in fictional projects.

Saved runners use controlled HTTP/MCP replies. These cases check purpose,
provenance, and selection boundaries, not scientific extraction quality.
"""

import asyncio
from copy import deepcopy
from dataclasses import asdict
import json

import pytest

import agents
import assessment_validation
import assessments
import cli
from collaboration_contracts import build_collaboration_input
import collaboration_storage
import metrics
import storage
import validation
from test_agent_loop import PLAN_ID, SOURCE, PROFILE, answer, message, project, scripted
from test_assessment_creation import clone_c, create, metadata, publish, snapshot, study, template_directory
from test_assessment_validation import finish
from test_collaboration_contracts import configured
from test_extract_cli import connected_cli
from test_run_storage import running
from test_saved_collaboration import ModelHTTP, ready, run as run_c
from test_saved_extractor import facts
from test_verifier import MODEL as V_MODEL, PROFILE as V_PROFILE, prepare_replies
from test_verify_cli import connected_cli as connected_verifier_cli


BUILDING = "dataset_building"


def membership(root, study_set):
    registry = storage.load_registry(root)
    registry["plans"][0]["study_set"] = study_set
    storage.save_registry(root, registry)


@pytest.fixture
def verifier_profile(project):
    """Add V's profile without first creating a comparison E run."""
    path = project / "configs/profiles.json"
    config = json.loads(path.read_text())
    profile = deepcopy(config["profiles"][0])
    profile.update(name=V_PROFILE, stage="verifier", context_limit=131072)
    profile["model"]["name"] = V_MODEL
    profile["prompt_paths"][-1] = "prompts/verifier.md"
    config["profiles"].append(profile)
    path.write_text(json.dumps(config))
    (project / "prompts/verifier.md").write_text("Fictional verifier instructions.\n")


@pytest.mark.parametrize("purpose,study_set,allowed", [
    ("comparison", "comparison", True), ("comparison", "expansion", False),
    (BUILDING, "comparison", True), (BUILDING, "expansion", True),
])
def test_membership_and_execution_purpose_have_distinct_rules(purpose, study_set, allowed):
    assert (validation.validate_run_purpose(purpose, study_set) == []) is allowed


@pytest.mark.parametrize("study_set", ["comparison", "expansion"])
def test_saved_dataset_e_and_v_share_purpose_without_changing_prompts(
    project, verifier_profile, scripted, facts, run_record, study_set,
):
    membership(project, study_set)
    before = snapshot(project)
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    e = asyncio.run(agents.run_extractor(project, PLAN_ID, source_path=SOURCE, profile_name=PROFILE,
        purpose=BUILDING, _transport=scripted.transport))
    assert e.record["status"] == "succeeded", e.record["error"]
    expected = agents.build_extractor_input(project, PLAN_ID, source_path=SOURCE, profile_name=PROFILE)
    assert e.execution.agent_input.messages == expected.messages
    prepare_replies(scripted, {name: deepcopy(e.record[name]) for name in ("plan_data", "plan_issues")})
    v = asyncio.run(agents.run_verifier(project, PLAN_ID, profile_name=V_PROFILE,
        purpose=BUILDING, input_run_id=e.record["run_id"], _transport=scripted.transport))
    assert v.record["status"] == "succeeded", v.record["error"]
    assert e.record["purpose"] == v.record["purpose"] == BUILDING
    assert storage.load_run_record(project, v.record_path) == v.record
    assert storage.load_registry(project)["plans"][0]["study_set"] == study_set
    saved_input = json.loads((project / v.record_path).with_name("artifacts").joinpath("verifier_input.json").read_text())
    assert saved_input["input_run"] == e.record and saved_input["purpose"] == BUILDING
    assert all((project / path).read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("study_set", ["comparison", "expansion"])
def test_saved_dataset_c_uses_the_same_source_and_prompts(ready, study_set):
    membership(ready.root, study_set)
    packet = build_collaboration_input(ready.root, PLAN_ID, source_path=SOURCE, purpose=BUILDING)
    if study_set == "comparison":
        assert asdict(packet) == asdict(build_collaboration_input(ready.root, PLAN_ID, source_path=SOURCE))
    before = snapshot(ready.root)
    saved = run_c(ready, purpose=BUILDING)
    assert saved.record["status"] == "succeeded", saved.record["error"]
    assert saved.record["purpose"] == BUILDING
    assert storage.load_run_record(ready.root, saved.record_path) == saved.record
    assert all((ready.root / path).read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("purpose", ["comparison", BUILDING])
def test_c_retry_cannot_switch_purpose_or_overwrite_failed_evidence(ready, purpose):
    ready.http.failure = "http"
    first = run_c(ready, purpose=purpose)
    before = snapshot(ready.root)
    calls = len(ready.http.calls)
    other = BUILDING if purpose == "comparison" else "comparison"
    with pytest.raises(ValueError, match="purpose"):
        run_c(ready, purpose=other, retry_of_run_id=first.record["run_id"])
    assert snapshot(ready.root) == before and len(ready.http.calls) == calls
    ready.http = ModelHTTP(ready.http.answer)
    second = run_c(ready, purpose=purpose, retry_of_run_id=first.record["run_id"])
    assert second.record["status"] == "succeeded" and second.record["purpose"] == purpose
    assert all((ready.root / path).read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize("boundary", ["create", "load"])
def test_c_storage_rejects_a_cross_purpose_retry(ready, boundary):
    ready.http.failure = "http"
    first = run_c(ready)
    ready.http = ModelHTTP(ready.http.answer)
    if boundary == "load":
        second = run_c(ready, retry_of_run_id=first.record["run_id"])
        file = ready.root / second.record_path
        record = json.loads(file.read_text())
        record["purpose"] = BUILDING
        file.write_text(json.dumps(record))
        with pytest.raises(ValueError, match="purpose"):
            storage.load_run_record(ready.root, second.record_path)
    else:
        record = deepcopy(first.record)
        record.update(run_id="run_collaboration_0002", status="running", purpose=BUILDING,
                      retry_of_run_id=first.record["run_id"], ended_at=None, elapsed_seconds=None,
                      model_calls=[], tool_log_path=None, budget=None, stop_reason=None, error=None)
        before = snapshot(ready.root)
        with pytest.raises(ValueError, match="purpose"):
            collaboration_storage.create_collaboration_record(ready.root, record)
        assert snapshot(ready.root) == before


@pytest.mark.parametrize("purpose", ["comparison", BUILDING])
def test_extractor_retry_cannot_change_its_original_purpose(project, run_record, purpose):
    record = running(run_record)
    record["purpose"] = purpose
    path = storage.create_run_record(project, record)
    record.update(status="failed", ended_at=run_record["ended_at"], elapsed_seconds=1, error="Controlled failure.")
    storage.save_run_record(project, record)
    retry = running(run_record, "run_extract_0002")
    retry.update(purpose=BUILDING if purpose == "comparison" else "comparison", retry_of_run_id=record["run_id"])
    before = snapshot(project)
    with pytest.raises(ValueError, match="same-purpose"):
        storage.create_run_record(project, retry)
    assert snapshot(project) == before and (project / path).is_file()


def dataset_outputs(root):
    """Add newer, valid dataset-building outputs beside the comparison set."""
    e = storage.load_run_record(root, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    v = storage.load_run_record(root, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    e["purpose"] = v["purpose"] = BUILDING
    publish(root, e, "extractor", 2)
    publish(root, v, "verifier", 2, input_run_id="run_extract_0002")
    c = clone_c(root, 2)
    c["purpose"] = BUILDING
    file = root / f"runs/{PLAN_ID}/run_collaboration_0002/output.json"
    file.write_text(json.dumps(c))
    storage.load_run_record(root, file.relative_to(root).as_posix())
    return {"extractor_run_id": "run_extract_0002", "verifier_run_id": "run_verify_0002",
            "collaboration_run_id": "run_collaboration_0002"}


def test_comparison_assessment_defaults_skip_newer_dataset_runs(study):
    dataset_outputs(study)
    path = create(study)
    data = metadata(study, path)
    assert [record["run_id"] for record in data["runs"].values()] == [
        "run_extract_0001", "run_verify_0001", "run_collaboration_0001"]
    assert assessment_validation.validate_assessment(study, PLAN_ID, "assessment_0001").valid


@pytest.mark.parametrize("flag", ["extractor_run_id", "verifier_run_id", "collaboration_run_id"])
def test_explicit_dataset_run_is_rejected_without_comparison_fallback(study, flag):
    selected = dataset_outputs(study)
    before = snapshot(study)
    with pytest.raises(ValueError, match="comparison"):
        create(study, **{flag: selected[flag]})
    assert snapshot(study) == before


def test_saved_assessment_and_metrics_cannot_be_rebound_to_dataset_outputs(study):
    path = create(study)
    finish(study, path)
    dataset_outputs(study)
    file = study / path / "metadata.json"
    data = json.loads(file.read_text())
    # Build a correctly fingerprinted source pointer: rejection must come from
    # the purpose boundary, even when the new files and hashes are intact.
    record_path = f"runs/{PLAN_ID}/run_collaboration_0002/output.json"
    data["runs"]["C"] = {"run_id": "run_collaboration_0002", "record_path": record_path,
        "record_sha256": assessments._fingerprint((study / record_path).read_bytes()), "selected_via": "explicit"}
    file.write_text(json.dumps(data))
    report = assessment_validation.validate_assessment(study, PLAN_ID, "assessment_0001")
    assert not report.valid and any("comparison" in item.message for item in report.problems)
    before = snapshot(study)
    with pytest.raises(ValueError, match="comparison"):
        metrics.calculate_metrics(study, PLAN_ID, "assessment_0001")
    assert snapshot(study) == before


def test_saved_verifier_rejects_a_cross_purpose_parent_when_loaded(study):
    dataset_outputs(study)
    file = study / f"runs/{PLAN_ID}/run_verify_0002/output.json"
    record = json.loads(file.read_text())
    record["purpose"] = "comparison"
    file.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="purposes must match"):
        storage.load_run_record(study, file.relative_to(study).as_posix())


def test_expansion_cli_requires_explicit_dataset_purpose_and_saves_matching_e_v(
    project, verifier_profile, scripted, facts, connected_cli, connected_verifier_cli, run_record, capsys,
):
    membership(project, "expansion")
    extract = ["run_extract_mode", PLAN_ID, "--source-path", SOURCE, "--profile", PROFILE,
               "--project-root", str(project)]
    before = snapshot(project)
    assert cli.main(extract) == 1
    assert "study sample" in capsys.readouterr().err
    assert snapshot(project) == before and not scripted.requests
    scripted.replies = [message(agents.FINAL_READY_SIGNAL), message(answer(run_record))]
    assert cli.main([*extract, "--purpose", BUILDING]) == 0
    e = storage.load_run_record(project, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    prepare_replies(scripted, {key: deepcopy(e[key]) for key in ("plan_data", "plan_issues")})
    assert cli.main(["run_verify_mode", PLAN_ID, "--profile", V_PROFILE, "--purpose", BUILDING,
                     "--project-root", str(project)]) == 0
    v = storage.load_run_record(project, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    assert e["purpose"] == v["purpose"] == BUILDING and v["input_run_id"] == e["run_id"]


@pytest.mark.parametrize("command,flags", [
    ("run_extract_mode", ["--source-path", SOURCE, "--profile", PROFILE]),
    ("run_verify_mode", ["--profile", V_PROFILE]),
    ("run_collaboration_mode", ["--source-path", SOURCE]),
])
def test_run_cli_purpose_defaults_and_explicit_choices(command, flags):
    parser = cli._build_parser()
    assert parser.parse_args([command, PLAN_ID, *flags]).purpose == "comparison"
    assert parser.parse_args([command, PLAN_ID, *flags, "--purpose", BUILDING]).purpose == BUILDING
