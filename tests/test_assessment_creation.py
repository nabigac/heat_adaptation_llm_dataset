"""Check CSV setup and exact input selection with fictional saved study artifacts.

One controlled C execution builds a reusable source fixture. Each test receives
its own copy, including real saved-run validation evidence. No paid requests or
scientific assessment judgments are involved.
"""

from copy import deepcopy
import csv
import hashlib
import json
import shutil

import pytest

import assessments
import cli
import expert_files
import storage
import validation
from test_agent_loop import PLAN_ID, SOURCE, project
from test_collaboration_contracts import configured
from test_saved_collaboration import ready, run as run_c
from test_saved_extractor import facts
from test_run_storage import complete, running


def issue(identifier, *, status="open", origin="extractor", resolver=None):
    return {
        "issue_id": identifier, "related_action_id": None, "issue_description": "Check fictional source details.",
        "issue_type": "source_issue", "issue_origin": origin, "issue_status": status,
        "resolved_by": resolver, "resolution": "Source details checked." if status == "resolved" else None,
    }


def publish(root, template, stage, number, *, input_run_id=None):
    record = deepcopy(template)
    prefix = assessments.PREFIXES[stage]
    record.update(run_id=f"{prefix}_{number:04d}", stage=stage, input_run_id=input_run_id)
    record["settings"]["stage"] = stage
    if stage == "verifier":
        record["settings"]["model"]["name"] = "test-lab/fictional-verifier"
    path = storage.create_run_record(root, running(record, record["run_id"], stage=stage, input_run_id=input_run_id))
    complete(root, path, record)
    return storage.load_run_record(root, path)


@pytest.fixture(scope="module")
def template_directory(tmp_path_factory):
    return tmp_path_factory.mktemp("assessment-input-fixture") / "study"


@pytest.fixture
def study(ready, run_record, template_directory, tmp_path):
    if not template_directory.exists():
        saved_c = run_c(ready)
        assert saved_c.record["status"] == "succeeded", saved_c.record["error"]
        extractor = deepcopy(run_record)
        extractor["plan_data"]["actions"][0]["action"] = 'Plant "20" trees,\nretaining details — fictional.'
        extractor["plan_issues"]["issues"] = [issue("issue_0001"), issue("issue_0002", status="resolved", resolver="extractor")]
        publish(ready.root, extractor, "extractor", 1)
        verifier = deepcopy(extractor)
        verifier["plan_issues"]["issues"][0].update(issue_status="resolved", resolved_by="verifier", resolution="Checked all concerns.")
        verifier["plan_issues"]["issues"].extend([
            issue("issue_0003", status="resolved", origin="verifier", resolver="verifier"),
            issue("issue_0004", origin="verifier"),
        ])
        publish(ready.root, verifier, "verifier", 1, input_run_id="run_extract_0001")
        expert_files.create_expert_reference(ready.root, PLAN_ID, prepared_by=["fictional_expert"])
        path = ready.root / f"data/expert_references/{PLAN_ID}/expert_reference.json"
        reference = json.loads(path.read_text())
        reference["plan_data"] = deepcopy(extractor["plan_data"])
        another = deepcopy(reference["plan_data"]["actions"][0])
        another.update(action_id="action_0002", action="Fictional drinking fountain activity.")
        reference["plan_data"]["actions"].append(another)
        reference["plan_issues"]["issues"] = []
        path.write_text(json.dumps(reference, ensure_ascii=False))
        expert_files.freeze_expert_reference(ready.root, PLAN_ID, frozen_by=["fictional_expert"])
        shutil.copytree(ready.root, template_directory)
    root = tmp_path / "assessment study"
    shutil.copytree(template_directory, root)
    return root


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def create(root, **options):
    return assessments.create_assessment(root, PLAN_ID, reviewers=["reviewer_01"], **options)


def metadata(root, path):
    return json.loads((root / path / "metadata.json").read_text())


def rows(root, path, name):
    with (root / path / name).open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def clone_c(root, number):
    parent = root / f"runs/{PLAN_ID}"
    original, replacement = "run_collaboration_0001", f"run_collaboration_{number:04d}"
    destination = parent / replacement
    shutil.copytree(parent / original, destination)
    for path in destination.rglob("*.json"):
        path.write_text(path.read_text().replace(original, replacement))
    relative = f"runs/{PLAN_ID}/{replacement}/output.json"
    return storage.load_run_record(root, relative)


def test_creation_prefills_context_and_preserves_every_input_without_paid_calls(study, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    before = snapshot(study)
    path = create(study, notes="Fictional assessment pilot.")
    assert path == f"data/assessments/{PLAN_ID}/assessment_0001"
    data = metadata(study, path)
    assert validation.validate_assessment_metadata(data) == []
    assert data["reviewers"] == ["reviewer_01"] and data["notes"] == "Fictional assessment pilot."
    assert data["included_attempts"] is None
    assert data["source"]["preparation_path"] == SOURCE
    for run in data["runs"].values():
        assert run["record_sha256"] == hashlib.sha256((study / run["record_path"]).read_bytes()).hexdigest()
        assert run["selected_via"] == "latest_successful"
    assert data["reference"]["sha256"] == hashlib.sha256((study / data["reference"]["path"]).read_bytes()).hexdigest()
    scores = rows(study, path, "action_scores.csv")
    assert len(scores) == 6 and {row["configuration"] for row in scores} == {"E", "E+V", "C"}
    assert all(row["matched_output_action_ids"] == row["score"] == row["reason"] == "" for row in scores)
    assert scores[0]["reference_action"] == 'Plant "20" trees,\nretaining details — fictional.'
    assert json.loads(scores[0]["reference_evidence"])[0]["page_numbers"] == [1]
    outputs = rows(study, path, "output_review.csv")
    assert len(outputs) == 3
    assert all(row["activity_supported"] == row["evidence_adequate"] == row["reason"] == "" for row in outputs)
    assert all(json.loads(row["output_action_ids"]) == ["action_0001"] for row in outputs)
    claims = rows(study, path, "verifier_resolutions.csv")
    assert len(claims) == 1 and claims[0]["issue_id"] == "issue_0001"
    assert claims[0]["confirmed"] == claims[0]["reason"] == ""
    assert claims[0]["claimed_resolution"] == "Checked all concerns."
    after = snapshot(study)
    assert all(after[name] == raw for name, raw in before.items())
    assert set(after) - set(before) == {f"{path}/{name}" for name in (
        "metadata.json", "action_scores.csv", "output_review.csv", "verifier_resolutions.csv")}


def test_newer_runs_do_not_replace_an_existing_assessment_and_new_creation_gets_a_new_id(study):
    first = create(study)
    before = snapshot(study / first)
    e = storage.load_run_record(study, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    v = storage.load_run_record(study, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    publish(study, e, "extractor", 2)
    publish(study, v, "verifier", 2, input_run_id="run_extract_0002")
    clone_c(study, 2)
    second = create(study)
    assert second.endswith("assessment_0002")
    assert snapshot(study / first) == before
    assert {key: value["run_id"] for key, value in metadata(study, second)["runs"].items()} == {
        "E": "run_extract_0002", "E+V": "run_verify_0002", "C": "run_collaboration_0002"}


def test_explicit_ids_retain_older_outputs_and_v_alone_supplies_its_linked_e(study):
    e = storage.load_run_record(study, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    v = storage.load_run_record(study, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    publish(study, e, "extractor", 2)
    publish(study, v, "verifier", 2, input_run_id="run_extract_0002")
    clone_c(study, 2)
    selected = assessments.select_assessment_runs(study, PLAN_ID, verifier_run_id="run_verify_0001", collaboration_run_id="run_collaboration_0001")
    assert selected["E"]["record"]["run_id"] == "run_extract_0001"
    assert selected["E"]["selected_via"] == "verifier_link"
    assert selected["C"]["selected_via"] == "explicit"
    path = create(study, extractor_run_id="run_extract_0001", verifier_run_id="run_verify_0001", collaboration_run_id="run_collaboration_0001")
    assert all(run["selected_via"] == "explicit" for run in metadata(study, path)["runs"].values())


def test_latest_e_without_a_linked_v_is_an_error_not_a_silent_older_pair(study):
    e = storage.load_run_record(study, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    publish(study, e, "extractor", 2)
    with pytest.raises(ValueError, match="linked to E run_extract_0002"):
        create(study)
    assert not (study / "data/assessments").exists()


def test_explicit_mismatched_pair_is_rejected(study):
    e = storage.load_run_record(study, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    publish(study, e, "extractor", 2)
    with pytest.raises(ValueError, match="not linked"):
        create(study, extractor_run_id="run_extract_0002", verifier_run_id="run_verify_0001")


def test_number_order_and_damaged_defaults_ignore_modification_times(study):
    e = storage.load_run_record(study, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    v = storage.load_run_record(study, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    publish(study, e, "extractor", 9999)
    publish(study, e, "extractor", 10000)
    publish(study, v, "verifier", 10000, input_run_id="run_extract_10000")
    damaged = study / f"runs/{PLAN_ID}/run_extract_10001"
    damaged.mkdir()
    (damaged / "output.json").write_text('{"unfinished":')
    selected = assessments.select_assessment_runs(study, PLAN_ID)
    assert selected["E"]["record"]["run_id"] == "run_extract_10000"
    with pytest.raises((ValueError, OSError)):
        create(study, extractor_run_id="run_extract_10001")


def test_failed_and_running_newer_runs_do_not_replace_successful_defaults(study):
    e = storage.load_run_record(study, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    failed = running(e, "run_extract_0002")
    storage.create_run_record(study, failed)
    failed.update(status="failed", ended_at=e["ended_at"], elapsed_seconds=0.5, error="Controlled failed attempt")
    storage.save_run_record(study, failed)
    storage.create_run_record(study, running(e, "run_extract_0003"))
    c = clone_c(study, 2)
    c.update(status="failed", plan_data=None, plan_issues=None, error="Controlled C failure")
    path = study / f"runs/{PLAN_ID}/run_collaboration_0002/output.json"
    path.write_text(json.dumps(c))
    assert storage.load_run_record(study, path.relative_to(study).as_posix())["status"] == "failed"
    selected = assessments.select_assessment_runs(study, PLAN_ID)
    assert selected["E"]["record"]["run_id"] == "run_extract_0001"
    assert selected["C"]["record"]["run_id"] == "run_collaboration_0001"
    with pytest.raises(ValueError, match="successful"):
        create(study, collaboration_run_id="run_collaboration_0002")


def test_latest_c_must_use_the_selected_preparation_even_when_pdf_and_text_match(study):
    _, preparation, pages = storage.load_plan_preparation(study, PLAN_ID, SOURCE)
    alternate = deepcopy(preparation)
    alternate["pages_path"] = f"data/processed/{PLAN_ID}/preparation_03/pages.json"
    alternate_path = storage.save_preparation(study, alternate, pages)
    c = clone_c(study, 2)
    c.update(source_path=alternate_path, source_fingerprint=storage.preparation_text_fingerprint(alternate, pages))
    folder = study / f"runs/{PLAN_ID}/run_collaboration_0002"
    (folder / "output.json").write_text(json.dumps(c))
    input_path = folder / "artifacts/collaboration_input.json"
    saved = json.loads(input_path.read_text())
    saved["packet"].update(source_path=alternate_path, source_fingerprint=c["source_fingerprint"])
    saved["preparation"] = alternate
    input_path.write_text(json.dumps(saved))
    diagnostic_path = folder / "artifacts/quotation_page_report.json"
    diagnostic = json.loads(diagnostic_path.read_text())
    diagnostic.update(source_path=alternate_path, source_fingerprint=c["source_fingerprint"])
    diagnostic_path.write_text(json.dumps(diagnostic))
    assert storage.load_run_record(study, f"runs/{PLAN_ID}/run_collaboration_0002/output.json")["source_path"] == alternate_path
    selected = assessments.select_assessment_runs(study, PLAN_ID)
    assert selected["C"]["record"]["run_id"] == "run_collaboration_0001"
    with pytest.raises(ValueError, match="another preparation"):
        create(study, collaboration_run_id="run_collaboration_0002")


def test_only_initially_open_e_issues_resolved_by_v_become_claim_rows(study):
    v = storage.load_run_record(study, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    v["plan_issues"]["issues"][0].update(issue_status="open", resolved_by=None, resolution=None)
    publish(study, v, "verifier", 2, input_run_id="run_extract_0001")
    path = create(study)
    assert rows(study, path, "verifier_resolutions.csv") == []
    header = (study / path / "verifier_resolutions.csv").read_text()
    assert header.startswith("issue_id,related_action_id,")


def test_comparison_plan_cannot_create_or_disclose_development_assessments(study):
    registry = storage.load_registry(study)
    registry["plans"][0]["study_set"] = "comparison"
    (study / "data/registry/plans.json").write_text(json.dumps(registry))
    before = snapshot(study)
    with pytest.raises(ValueError, match="development plans only"):
        create(study)
    assert snapshot(study) == before


def test_modified_metadata_or_missing_required_fields_fail_structure_checks(study):
    path = create(study)
    data = metadata(study, path)
    for field, value in (("reviewers", []), ("purpose", "comparison"), ("included_attempts", [])):
        changed = deepcopy(data)
        changed[field] = value
        assert validation.validate_assessment_metadata(changed)
    data["runs"]["E"]["record_sha256"] = "not-a-fingerprint"
    assert validation.validate_assessment_metadata(data)


@pytest.mark.parametrize("flag", ["extractor_run_id", "verifier_run_id", "collaboration_run_id"])
@pytest.mark.parametrize("identifier", ["missing", "../run_extract_0001", "run_extract_0000"])
def test_explicit_bad_ids_never_fall_back_or_create_files(study, flag, identifier):
    before = snapshot(study)
    with pytest.raises((ValueError, OSError)):
        create(study, **{flag: identifier})
    assert snapshot(study) == before


@pytest.mark.parametrize("damage", ["unfrozen", "changed_reference", "missing_source", "missing_c"])
def test_unready_inputs_never_create_an_assessment(study, damage):
    reference = study / f"data/expert_references/{PLAN_ID}/expert_reference.json"
    if damage == "unfrozen":
        reference.with_name("reference_freeze.json").unlink()
    elif damage == "changed_reference":
        reference.write_text(reference.read_text() + "\n")
    elif damage == "missing_source":
        (study / SOURCE).unlink()
    else:
        shutil.rmtree(study / f"runs/{PLAN_ID}/run_collaboration_0001")
    before = snapshot(study)
    with pytest.raises((ValueError, OSError)):
        create(study)
    assert snapshot(study) == before and not (study / "data/assessments").exists()


@pytest.mark.parametrize("reviewers", [[], [""], [None], None, "name"])
def test_missing_reviewer_identity_is_rejected_without_writing(study, reviewers):
    with pytest.raises(ValueError, match="reviewer"):
        assessments.create_assessment(study, PLAN_ID, reviewers=reviewers)
    assert not (study / "data/assessments").exists()


def test_occupied_and_interrupted_assessment_numbers_are_preserved(study):
    parent = study / f"data/assessments/{PLAN_ID}"
    parent.mkdir(parents=True)
    (parent / "assessment_0004").mkdir()
    (parent / "assessment_0005").write_bytes(b"interrupted setup")
    path = create(study)
    assert path.endswith("assessment_0006")
    assert (parent / "assessment_0005").read_bytes() == b"interrupted setup"


def test_assessment_paths_cannot_redirect_even_inside_the_project(study):
    target = study / "elsewhere"
    target.mkdir()
    (study / "data/assessments").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic"):
        create(study)
    assert list(target.iterdir()) == []


def test_input_changes_before_publication_are_detected(study, monkeypatch):
    original = assessments._review_files
    def changed(reference, snapshots):
        path = study / snapshots["C"]["record_path"]
        path.write_bytes(path.read_bytes() + b"\n")
        return original(reference, snapshots)
    monkeypatch.setattr(assessments, "_review_files", changed)
    with pytest.raises(ValueError, match="input changed"):
        create(study)
    assert not (study / "data/assessments").exists()


def test_supporting_run_evidence_is_rechecked_before_publication(study, monkeypatch):
    original = assessments._review_files
    def removed(reference, snapshots):
        record = snapshots["C"]["record"]
        (study / record["model_calls"][0]["response_path"]).unlink()
        return original(reference, snapshots)
    monkeypatch.setattr(assessments, "_review_files", removed)
    with pytest.raises((ValueError, OSError)):
        create(study)
    assert not (study / "data/assessments").exists()


def test_failed_bundle_publication_retains_partial_evidence_without_completion_metadata(study, monkeypatch):
    original = storage._publish_new_bytes
    def failed(path, raw):
        if path.name == "output_review.csv":
            raise OSError("Controlled assessment publication failure")
        return original(path, raw)
    monkeypatch.setattr(storage, "_publish_new_bytes", failed)
    with pytest.raises(OSError, match="publication failure"):
        create(study)
    folder = study / f"data/assessments/{PLAN_ID}/assessment_0001"
    assert (folder / "action_scores.csv").is_file()
    assert not (folder / "metadata.json").exists()


def test_cli_creates_new_assessment_with_default_and_explicit_selection(study, capsys):
    result = cli.main(["create_assessment", PLAN_ID, "--reviewer", "Reviewer One", "--reviewer", "reviewer_02",
                       "--notes", "Development pilot", "--project-root", str(study)])
    assert result == 0
    output = capsys.readouterr()
    assert f"data/assessments/{PLAN_ID}/assessment_0001" in output.out and output.err == ""
    data = metadata(study, f"data/assessments/{PLAN_ID}/assessment_0001")
    assert data["reviewers"] == ["Reviewer One", "reviewer_02"]
    result = cli.main(["create_assessment", PLAN_ID, "--reviewer", "Reviewer One", "--extractor-run-id", "run_extract_0001",
                       "--verifier-run-id", "run_verify_0001", "--collaboration-run-id", "run_collaboration_0001",
                       "--project-root", str(study)])
    assert result == 0
    assert "assessment_0002" in capsys.readouterr().out


def test_cli_requires_plan_and_reviewer():
    for arguments in ([], [PLAN_ID], ["--reviewer", "name"]):
        with pytest.raises(SystemExit) as error:
            cli.main(["create_assessment", *arguments])
        assert error.value.code == 2
