"""Assemble fictional saved reviews, checking provenance rather than quality."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

import cli
import dataset_assembly as datasets
import plan_reviews
import storage
from test_agent_loop import PLAN_ID, SOURCE, project
from test_assessment_creation import snapshot, study, template_directory
from test_collaboration_contracts import configured
from test_metric_summaries import clone_plan
from test_plan_reviews import building, finish
from test_saved_collaboration import ready
from test_saved_extractor import facts


@pytest.fixture
def pair(building):
    second = clone_plan(building)
    registry = storage.load_registry(building)
    registry["plans"][-1]["study_set"] = "expansion"
    storage.save_registry(building, registry)
    return building, second


def complete(root, plan_id=PLAN_ID, configuration="E"):
    folder = plan_reviews.create_review_draft(root, plan_id, configuration=configuration)
    finish(root, folder)
    review_id = folder.rsplit("/", 1)[1]
    return plan_reviews.finalize_reviewed_plan(root, plan_id, review_id)


def update_run(root, plan_id, stage, change):
    """Change a fictional saved setup before creating its expert review.

    Refresh dependent input snapshots so workflow-mismatch tests exercise the
    assembly boundary, not a deliberately broken source-run record.
    """
    prefixes = {"E": "run_extract", "V": "run_verify", "C": "run_collaboration"}
    file = root / f"runs/{plan_id}/{prefixes[stage]}_0002/output.json"
    record = json.loads(file.read_text())
    change(record)
    file.write_text(json.dumps(record))
    if stage == "E":
        for saved in (root / f"runs/{plan_id}").glob("run_verify_*/artifacts/verifier_input.json"):
            data = json.loads(saved.read_text())
            baseline = root / f"runs/{plan_id}/{data['input_run_id']}/output.json"
            data["input_run"] = json.loads(baseline.read_text())
            data["input_run_fingerprint"] = hashlib.sha256(baseline.read_bytes()).hexdigest()
            saved.write_text(json.dumps(data))
    elif stage == "C":
        saved = file.parent / "artifacts/collaboration_input.json"
        data = json.loads(saved.read_text())
        data["packet"]["configuration"] = deepcopy(record["settings"]["configuration"])
        data["packet"]["profiles"] = deepcopy(record["settings"]["profiles"])
        saved.write_text(json.dumps(data))
        record["budget"]["limits"] = deepcopy(record["settings"]["configuration"]["limits"])
        file.write_text(json.dumps(record))
    storage.load_run_record(root, file.relative_to(root).as_posix())


@pytest.mark.parametrize("configuration", ["E", "E+V", "C"])
def test_builds_mixed_sample_membership_from_exact_completed_reviews(pair, configuration, monkeypatch):
    root, second = pair
    monkeypatch.delenv("HF_TOKEN", raising=False)
    first_path = complete(root, configuration=configuration)
    second_path = complete(root, second, configuration)
    before = snapshot(root)
    folder = datasets.build_heat_action_dataset(root, [second_path + "/reviewed_plan.json", first_path])
    data, contents = datasets.load_heat_action_dataset(root, folder)
    assert folder.endswith("dataset_0001")
    assert contents["configuration"] == configuration
    assert contents["review_scope"] == "open_issues_only"
    assert contents["dataset"]["plan_count"] == 2
    assert [p["plan_id"] for p in data["plans"]] == [PLAN_ID, second]
    for product, path in zip(data["plans"], [first_path, second_path]):
        assert set(product) == {"plan_id", "metadata", "actions"}
        assert {k: v for k, v in product.items() if k != "plan_id"} == json.loads((root / path / "reviewed_plan.json").read_text())
        selection = next(p for p in contents["plans"] if p["plan_id"] == product["plan_id"])
        for name in datasets.REVIEW_FILES:
            assert (root / folder / "inputs" / product["plan_id"] / selection["review_id"] / name).read_bytes() == before[path + "/" + name]
    # Local action IDs legitimately repeat across plans; they are never renumbered.
    assert data["plans"][0]["actions"][0]["action_id"] == data["plans"][1]["actions"][0]["action_id"]
    assert not datasets._schema(data, "heat_action_dataset")
    assert all((root / name).read_bytes() == raw for name, raw in before.items())
    assert [s["stage"] for s in contents["workflow"]["stages"]] == {
        "E": ["extractor"], "E+V": ["extractor", "verifier"], "C": ["collaboration"],
    }[configuration]


@pytest.mark.parametrize("other", ["E+V", "C"])
def test_different_configurations_cannot_be_combined(pair, other):
    root, second = pair
    paths = [complete(root), complete(root, second, other)]
    before = snapshot(root)
    with pytest.raises(ValueError, match="same configuration"):
        datasets.build_heat_action_dataset(root, paths)
    assert snapshot(root) == before


@pytest.mark.parametrize("field", ["model", "provider", "prompt", "generation", "tools", "timeout", "tool_budget", "software", "model_revision", "code"])
def test_recorded_workflow_differences_are_rejected(pair, field):
    root, second = pair
    if field == "code":
        folder = root / f"runs/{second}/run_extract_0002/artifacts"
        manifest = json.loads((folder / "code_fingerprints.json").read_text())
        name = next(iter(manifest["sha256"]))
        file = folder / "code" / name
        file.write_bytes(file.read_bytes() + b"\n# fictional changed implementation\n")
        manifest["sha256"][name] = hashlib.sha256(file.read_bytes()).hexdigest()
        (folder / "code_fingerprints.json").write_text(json.dumps(manifest))
    else:
        def change(record):
            settings = record["settings"]
            if field == "model": settings["model"]["name"] = "test-lab/another-model"
            elif field == "provider": settings["model"]["endpoint"] = "https://example.org/another-endpoint"
            elif field == "prompt": settings["prompt_texts"][0] += "\nDifferent extraction instruction."
            elif field == "generation": settings["generation"]["temperature"] = 0.7
            elif field == "tools": settings["document_tools"]["tool_timeout_seconds"] += 1
            elif field == "timeout": settings["model_timeout_seconds"] += 1
            elif field == "tool_budget": settings["max_tool_calls"] += 1
            elif field == "software": settings["environment"]["tools_version"] = "different-sdk"
            else: settings["environment"]["model_revision"] = "known-revision"
        update_run(root, second, "E", change)
    paths = [complete(root), complete(root, second)]
    before = snapshot(root)
    with pytest.raises(ValueError, match="different recorded workflow version"):
        datasets.build_heat_action_dataset(root, paths)
    assert snapshot(root) == before


@pytest.mark.parametrize("stage", ["E", "V"])
def test_e_v_consistency_checks_both_the_extractor_and_verifier(pair, stage):
    root, second = pair
    def change(record): record["settings"]["prompt_texts"][0] += "\nChanged stage instruction."
    update_run(root, second, stage, change)
    paths = [complete(root, configuration="E+V"), complete(root, second, "E+V")]
    with pytest.raises(ValueError, match="different recorded workflow version"):
        datasets.build_heat_action_dataset(root, paths)


@pytest.mark.parametrize("field", ["worker_prompt", "limits"])
def test_c_consistency_includes_workers_and_shared_limits(pair, field):
    root, second = pair
    def change(record):
        if field == "worker_prompt":
            for actor in ("worker_1", "worker_2"):
                record["settings"]["profiles"][actor]["prompt_texts"][0] += "\nChanged worker instruction."
        else: record["settings"]["configuration"]["limits"]["max_model_requests"] += 1
    update_run(root, second, "C", change)
    paths = [complete(root, configuration="C"), complete(root, second, "C")]
    with pytest.raises(ValueError, match="different recorded workflow version"):
        datasets.build_heat_action_dataset(root, paths)


def test_run_identity_timing_and_git_observations_do_not_define_configuration(pair):
    root, second = pair
    def change(record):
        env = record["settings"]["environment"]
        env.update(code_commit="another-commit-with-identical-code", code_dirty=not env["code_dirty"], hardware="Observed other host", model_loaded_at_start=False)
        record["elapsed_seconds"] += 1
    update_run(root, second, "E", change)
    paths = [complete(root), complete(root, second)]
    folder = datasets.build_heat_action_dataset(root, paths)
    assert datasets.load_heat_action_dataset(root, folder)[1]["dataset"]["plan_count"] == 2


@pytest.mark.parametrize("variant", ["same_path", "file_alias", "different_review"])
def test_duplicate_plan_is_rejected_even_for_different_review_versions(building, variant):
    path = complete(building)
    other = path if variant == "same_path" else path + "/reviewed_plan.json" if variant == "file_alias" else complete(building)
    before = snapshot(building)
    with pytest.raises(ValueError, match="duplicate plans"):
        datasets.build_heat_action_dataset(building, [path, other])
    assert snapshot(building) == before


def test_identical_original_pdf_cannot_enter_under_two_plan_ids(pair):
    root, second = pair
    source = SOURCE.replace(PLAN_ID, second)
    _, preparation, pages = storage.load_plan_preparation(root, second, source)
    old_hash = preparation["document_sha256"]
    old_fingerprint = storage.preparation_text_fingerprint(preparation, pages)
    pdf = root / f"data/source_pdfs/{second}.pdf"
    pdf.write_bytes((root / f"data/source_pdfs/{PLAN_ID}.pdf").read_bytes())
    new_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    preparation["document_sha256"] = new_hash
    new_fingerprint = storage.preparation_text_fingerprint(preparation, pages)
    registry = storage.load_registry(root)
    registry["plans"][-1]["document_sha256"] = new_hash
    storage.save_registry(root, registry)
    for parent in ("data/prepared_plans", "data/comparison/expert_references", "runs"):
        for file in (root / parent / second).rglob("*.json"):
            raw = file.read_text()
            changed = raw.replace(old_hash, new_hash).replace(old_fingerprint, new_fingerprint)
            if changed != raw: file.write_text(changed)
    paths = [complete(root), complete(root, second)]
    before = snapshot(root)
    with pytest.raises(ValueError, match="Duplicate original PDFs"):
        datasets.build_heat_action_dataset(root, paths)
    assert snapshot(root) == before


def test_ten_plan_dataset_contains_every_explicit_review_once(building):
    plan_ids = [PLAN_ID, *[clone_plan(building, f"plan_{number:04d}") for number in range(100, 109)]]
    paths = [complete(building, plan_id) for plan_id in plan_ids]
    folder = datasets.build_heat_action_dataset(building, paths)
    data, contents = datasets.load_heat_action_dataset(building, folder)
    assert [p["plan_id"] for p in data["plans"]] == plan_ids
    assert contents["dataset"]["plan_count"] == 10
    assert contents["dataset"]["action_count"] == sum(len(p["actions"]) for p in data["plans"])


@pytest.mark.parametrize("value", [None, [], "a-folder", ["../review_0001"], ["data/dataset_building/review_drafts/plan_0099/review_0001"], ["data/dataset_building/reviewed_plans/plan_0099/review_0000"], [42]])
def test_invalid_selections_create_no_files(building, value):
    before = snapshot(building)
    with pytest.raises(ValueError):
        datasets.build_heat_action_dataset(building, value)
    assert snapshot(building) == before


@pytest.mark.parametrize("damage", ["missing_record", "open_issue", "missing_source", "data_issue_object", "wrong_scope", "wrong_source_purpose"])
def test_only_complete_consistent_reviews_are_eligible(building, damage):
    path = complete(building)
    folder = building / path
    if damage == "missing_record": (folder / "review_record.json").unlink()
    elif damage == "missing_source": (folder / "source_run.json").unlink()
    else:
        name = "review_draft.json" if damage == "open_issue" else "reviewed_plan.json" if damage == "data_issue_object" else "source_run.json" if damage == "wrong_source_purpose" else "review_record.json"
        data = json.loads((folder / name).read_text())
        if damage == "open_issue": data["plan_issues"]["issues"][0].update(issue_status="open", resolved_by=None, resolution=None)
        elif damage == "data_issue_object": data["plan_issues"] = {"issues": []}
        elif damage == "wrong_source_purpose": data["purpose"] = "comparison"
        else: data["review_scope"] = "full_audit"
        (folder / name).write_text(json.dumps(data))
    before = snapshot(building)
    with pytest.raises((ValueError, OSError)):
        datasets.build_heat_action_dataset(building, [path])
    assert snapshot(building) == before


def test_versions_preserve_prior_review_selections_and_survive_later_live_edits(building):
    first = complete(building)
    original = datasets.build_heat_action_dataset(building, [first])
    expected = datasets.load_heat_action_dataset(building, original)
    before = snapshot(building / original)
    draft = plan_reviews.create_review_draft(building, PLAN_ID, configuration="E")
    data = finish(building, draft)
    data["plan_data"]["actions"][0]["action"] = "Expert corrected activity detail."
    (building / draft / "review_draft.json").write_text(json.dumps(data))
    latest = plan_reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0002")
    second = datasets.build_heat_action_dataset(building, [latest])
    assert second.endswith("dataset_0002")
    assert snapshot(building / original) == before
    assert datasets.load_heat_action_dataset(building, second)[0] != expected[0]
    shutil.rmtree(building / first)
    shutil.rmtree(building / draft)
    assert datasets.load_heat_action_dataset(building, original) == expected


def test_input_order_is_deterministic_and_explicit_old_versions_do_not_use_latest(pair):
    root, second = pair
    paths = [complete(root), complete(root, second)]
    complete(root)  # A later completed review must not replace an explicit input.
    first = datasets.build_heat_action_dataset(root, paths)
    second_dataset = datasets.build_heat_action_dataset(root, list(reversed(paths)))
    one, one_contents = datasets.load_heat_action_dataset(root, first)
    two, two_contents = datasets.load_heat_action_dataset(root, second_dataset)
    assert one == two
    assert one_contents["workflow_sha256"] == two_contents["workflow_sha256"]
    assert one_contents["plans"] == two_contents["plans"]
    assert all(item["review_id"] == "review_0001" for item in one_contents["plans"])


@pytest.mark.parametrize("target", ["reviewed_plan.json", "dataset_assembly.py", "heat_action_dataset.json", "dataset_contents.json"])
def test_failed_publication_has_no_completion_marker_and_reserves_version(building, monkeypatch, target):
    path = complete(building)
    original = storage._publish_new_bytes
    def fail(file, raw):
        if file.name == target: raise OSError("Controlled assembly failure")
        return original(file, raw)
    monkeypatch.setattr(storage, "_publish_new_bytes", fail)
    with pytest.raises(OSError, match="Controlled"):
        datasets.build_heat_action_dataset(building, [path])
    folder = datasets.ROOT + "/dataset_0001"
    assert not (building / folder / "dataset_contents.json").exists()
    with pytest.raises(OSError): datasets.load_heat_action_dataset(building, folder)
    before = snapshot(building / folder)
    monkeypatch.setattr(storage, "_publish_new_bytes", original)
    assert datasets.build_heat_action_dataset(building, [path]).endswith("dataset_0002")
    assert snapshot(building / folder) == before


@pytest.mark.parametrize("changed", ["selected_review", "source_workflow", "assembly_code", "copied_review", "combined_data"])
def test_intervening_changes_prevent_completed_publication(building, monkeypatch, changed):
    path = complete(building)
    original = storage._publish_new_bytes
    original_code = datasets._assembly_code
    touched = []
    def change(file, raw):
        original(file, raw)
        if file.name != "heat_action_dataset.json": return
        if changed == "selected_review":
            source = building / path / "review_record.json"
            source.write_bytes(source.read_bytes() + b"\n")
        elif changed == "source_workflow":
            update_run(building, PLAN_ID, "E", lambda r: r["settings"]["prompt_texts"].append("A new instruction."))
        elif changed == "assembly_code": touched.append(True)
        elif changed == "copied_review":
            copy = file.parent / "inputs" / PLAN_ID / "review_0001" / "reviewed_plan.json"
            copy.write_text('{}')
        else: file.write_text('{}')
    monkeypatch.setattr(storage, "_publish_new_bytes", change)
    monkeypatch.setattr(datasets, "_assembly_code", lambda: {**original_code(), **({"src/extra.py": b"changed"} if touched else {})})
    with pytest.raises(ValueError): datasets.build_heat_action_dataset(building, [path])
    assert not (building / datasets.ROOT / "dataset_0001/dataset_contents.json").exists()


@pytest.mark.parametrize("target", ["product", "contents", "workflow", "review", "code", "missing_marker"])
def test_loading_rejects_modified_or_incomplete_packages(building, target):
    folder = datasets.build_heat_action_dataset(building, [complete(building)])
    marker = building / folder / "dataset_contents.json"
    if target == "missing_marker": marker.unlink()
    elif target == "product":
        file = building / folder / "heat_action_dataset.json"
        data = json.loads(file.read_text())
        data["plans"][0]["plan_issues"] = {"issues": []}
        file.write_text(json.dumps(data))
    elif target == "review":
        (building / folder / "inputs" / PLAN_ID / "review_0001/review_record.json").write_text('{}')
    elif target == "code":
        (building / folder / "artifacts/code/src/dataset_assembly.py").write_bytes(b"raise RuntimeError('must never execute')")
    else:
        data = json.loads(marker.read_text())
        if target == "workflow": data["workflow"]["stages"][0]["settings"]["max_tool_calls"] += 1
        else: data["dataset"]["action_count"] += 1
        marker.write_text(json.dumps(data))
    before = snapshot(building)
    with pytest.raises((ValueError, OSError)): datasets.load_heat_action_dataset(building, folder)
    assert snapshot(building) == before


def test_occupied_files_reserve_dataset_ids(building):
    path = complete(building)
    parent = building / datasets.ROOT
    parent.mkdir(parents=True)
    (parent / "dataset_0001").mkdir()
    (parent / "dataset_0003").write_text("Reserved evidence")
    assert datasets.build_heat_action_dataset(building, [path]).endswith("dataset_0004")


def test_cli_builds_new_dataset_and_requires_explicit_reviews(building, capsys):
    path = complete(building)
    with pytest.raises(SystemExit) as error: cli.main(["build_heat_action_dataset"])
    assert error.value.code == 2
    assert cli.main(["build_heat_action_dataset", "--review", path, "--project-root", str(building)]) == 0
    output = capsys.readouterr().out
    assert "heat_action_dataset.json" in output and "dataset_contents.json" in output
    assert "Configuration: E" in output and "Plans: 1" in output
    assert cli.main(["build_heat_action_dataset", "--review", path, "--review", path, "--project-root", str(building)]) == 1


@pytest.mark.parametrize("where", ["input", "output"])
def test_dataset_paths_reject_symlinks(building, tmp_path, where):
    path = complete(building)
    if where == "input":
        folder = building / path
        moved = tmp_path / "outside-review"
        shutil.move(folder, moved)
        folder.symlink_to(moved, target_is_directory=True)
    else:
        outside = tmp_path / "outside-datasets"
        outside.mkdir()
        (building / datasets.ROOT).symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic|outside"):
        datasets.build_heat_action_dataset(building, [path])
