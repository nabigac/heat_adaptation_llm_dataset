"""Exercise draft/review products with fictional, fully validated saved runs.

These checks establish preservation and format/issue boundaries, not factual
accuracy, reference completeness, or expert review quality.
"""

from copy import deepcopy
import json

import pytest

import cli
import plan_reviews as reviews
import storage
from test_agent_loop import PLAN_ID, SOURCE, project
from test_assessment_creation import issue, publish, snapshot, study, template_directory
from test_collaboration_contracts import configured
from test_dataset_building import dataset_outputs, membership
from test_saved_collaboration import ready
from test_saved_extractor import facts


@pytest.fixture
def building(study):
    dataset_outputs(study)
    return study


def create(root, configuration="E", **options):
    return reviews.create_review_draft(root, PLAN_ID, configuration=configuration, **options)


def read(root, folder):
    return json.loads((root / folder / "review_draft.json").read_text())


def write(root, folder, draft):
    (root / folder / "review_draft.json").write_text(json.dumps(draft))


def finish(root, folder):
    draft = read(root, folder)
    for item in draft["plan_issues"]["issues"]:
        if item["issue_status"] == "open":
            item.update(issue_status="resolved", resolved_by="expert", resolution="Checked the PDF and corrected the recorded detail.")
    write(root, folder, draft)
    return draft


@pytest.mark.parametrize("configuration", ["E", "E+V", "C"])
@pytest.mark.parametrize("study_set", ["comparison", "expansion"])
def test_create_review_finalize_and_load_keep_clean_data_and_separate_history(building, configuration, study_set):
    # Use a separate expansion project before publication; old comparison runs
    # become ineligible but are neither selected nor rewritten.
    membership(building, study_set)
    before = snapshot(building)
    folder = create(building, configuration)
    draft = read(building, folder)
    source_path = building / draft["source"]["record_path"]
    baseline = json.loads(source_path.read_text())
    assert draft["source"]["run_id"].endswith("0002")
    assert draft["plan_data"] == baseline["plan_data"]
    assert draft["plan_issues"] == baseline["plan_issues"]
    assert draft["review_scope"] == "open_issues_only"
    assert (building / folder / "source_run.json").read_bytes() == source_path.read_bytes()
    draft = finish(building, folder)
    report = reviews.validate_review_draft(building, PLAN_ID, "review_0001")
    assert report.valid and report.complete
    target = reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    clean, record = reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")
    assert clean == draft["plan_data"] and set(clean) == {"metadata", "actions"}
    assert "issues" not in clean and "plan_issues" not in clean
    assert record["issues"] == draft["plan_issues"]["issues"]
    assert record["configuration"] == configuration and record["review_scope"] == "open_issues_only"
    assert (building / target / "review_draft.json").read_bytes() == (building / folder / "review_draft.json").read_bytes()
    assert all((building / name).read_bytes() == raw for name, raw in before.items())
    assert not {"prepared_by", "frozen_by", "reviewers"} & record.keys()
    with pytest.raises(FileExistsError, match="already finalized"):
        reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")


@pytest.mark.parametrize("configuration,identifier", [("E", "run_extract_0001"), ("E+V", "run_verify_0001"), ("C", "run_collaboration_0001")])
def test_comparison_runs_cannot_supply_drafts_even_explicitly(building, configuration, identifier):
    before = snapshot(building)
    with pytest.raises(ValueError, match="dataset_building"):
        create(building, configuration, run_id=identifier)
    assert snapshot(building) == before


@pytest.mark.parametrize("configuration", ["E", "E+V", "C"])
def test_no_dataset_runs_does_not_fall_back_to_comparison(study, configuration):
    before = snapshot(study)
    with pytest.raises(ValueError, match="No validated, successful dataset_building"):
        create(study, configuration)
    assert snapshot(study) == before


@pytest.mark.parametrize("configuration,identifier", [("E", "run_verify_0002"), ("E+V", "run_verify_9999"), ("C", "../output.json"), ("other", None)])
def test_wrong_explicit_selection_never_falls_back(building, configuration, identifier):
    before = snapshot(building)
    with pytest.raises((OSError, ValueError)):
        create(building, configuration, run_id=identifier)
    assert snapshot(building) == before


def test_default_skips_newer_damaged_dataset_run_but_explicit_fails(building):
    (building / f"runs/{PLAN_ID}/run_extract_9999").mkdir()
    (building / f"runs/{PLAN_ID}/run_extract_9999/output.json").write_text('{"broken":')
    assert read(building, create(building))["source"]["run_id"] == "run_extract_0002"
    with pytest.raises(ValueError):
        create(building, run_id="run_extract_9999")


def test_open_issue_is_valid_pending_but_blocks_finalization_without_writes(building):
    folder = create(building)
    before = snapshot(building)
    report = reviews.validate_review_draft(building, PLAN_ID, "review_0001")
    assert report.valid and not report.complete and report.pending_issue_ids == ("issue_0001",)
    with pytest.raises(ValueError, match="every open issue"):
        reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    assert snapshot(building) == before
    assert read(building, folder)["plan_issues"]["issues"][0]["issue_status"] == "open"


@pytest.mark.parametrize("damage", ["delete_issue", "origin", "description", "type", "model_resolution", "model_reopened", "resolver", "blank_resolution", "dangling_link", "duplicate_issue", "duplicate_action", "page", "source_url", "source", "configuration", "review_id", "todo", "new_model_issue"])
def test_invalid_edits_cannot_be_finalized(building, damage):
    folder = create(building)
    draft = finish(building, folder)
    items = draft["plan_issues"]["issues"]
    first = items[0]
    if damage == "delete_issue": items.pop(0)
    elif damage == "origin": first["issue_origin"] = "expert"
    elif damage == "description": first["issue_description"] = "Hidden original concern."
    elif damage == "type": first["issue_type"] = "unclear_meaning"
    elif damage == "model_resolution": items[1]["resolution"] = "Rewritten claim."
    elif damage == "model_reopened": items[1].update(issue_status="open", resolved_by=None, resolution=None)
    elif damage == "resolver": first["resolved_by"] = "extractor"
    elif damage == "blank_resolution": first["resolution"] = " "
    elif damage == "dangling_link": first["related_action_id"] = "action_9999"
    elif damage == "duplicate_issue": items.append(deepcopy(first))
    elif damage == "duplicate_action": draft["plan_data"]["actions"].append(deepcopy(draft["plan_data"]["actions"][0]))
    elif damage == "page": draft["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [99999]
    elif damage == "source_url": draft["plan_data"]["metadata"]["source_url"] = "https://example.org/other.pdf"
    elif damage == "source": draft["source"]["record_sha256"] = "0" * 64
    elif damage == "configuration": draft["configuration"] = "C"
    elif damage == "review_id": draft["review_id"] = "review_9999"
    elif damage == "todo": first["resolution"] = "TODO: Finish the source check."
    else: items.append(issue("issue_9999", status="resolved", resolver="extractor"))
    write(building, folder, draft)
    before = snapshot(building)
    report = reviews.validate_review_draft(building, PLAN_ID, "review_0001")
    assert not report.valid, damage
    with pytest.raises(ValueError):
        reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    assert snapshot(building) == before


@pytest.mark.parametrize("configuration", ["E", "E+V", "C"])
def test_additional_expert_issue_must_also_be_addressed(building, configuration):
    folder = create(building, configuration)
    original = read(building, folder)["plan_issues"]["issues"]
    draft = finish(building, folder)
    draft["plan_issues"]["issues"].append(issue("issue_9999", origin="expert"))
    write(building, folder, draft)
    assert reviews.validate_review_draft(building, PLAN_ID, "review_0001").pending_issue_ids == ("issue_9999",)
    finish(building, folder)
    reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    _, record = reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")
    assert record["expert_addressed_issue_ids"] == [item["issue_id"] for item in original if item["issue_status"] == "open"] + ["issue_9999"]
    assert record["model_resolved_issue_ids"] == [item["issue_id"] for item in original if item["issue_status"] == "resolved"]


def test_review_ledger_keeps_multiple_issues_after_an_action_merge(building):
    source = storage.load_run_record(building, f"runs/{PLAN_ID}/run_extract_0002/output.json")
    other = deepcopy(source["plan_data"]["actions"][0])
    other.update(action_id="action_0002", action="A duplicate record for the same planting activity.")
    source["plan_data"]["actions"].append(other)
    source["plan_issues"]["issues"][0]["related_action_id"] = "action_0001"
    source["plan_issues"]["issues"][1]["related_action_id"] = "action_0002"
    publish(building, source, "extractor", 3)
    folder = create(building)
    draft = finish(building, folder)
    draft["plan_data"]["actions"].pop()
    for item in draft["plan_issues"]["issues"]:
        item["related_action_id"] = "action_0001"
    write(building, folder, draft)
    assert reviews.validate_review_draft(building, PLAN_ID, "review_0001").complete
    reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    assert len(reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")[1]["issues"]) == 2


def test_interrupted_draft_publication_keeps_evidence_and_reserves_its_id(building, monkeypatch):
    original = storage._publish_new_bytes
    def fail(file, raw):
        if file.name == "review_draft.json":
            raise OSError("Controlled draft failure")
        return original(file, raw)
    monkeypatch.setattr(storage, "_publish_new_bytes", fail)
    with pytest.raises(OSError, match="Controlled"):
        create(building)
    folder = building / f"data/dataset_building/review_drafts/{PLAN_ID}/review_0001"
    assert (folder / "source_run.json").is_file() and not (folder / "review_draft.json").exists()
    before = snapshot(building)
    monkeypatch.setattr(storage, "_publish_new_bytes", original)
    assert create(building).endswith("review_0002")
    assert all((building / name).read_bytes() == raw for name, raw in before.items())


@pytest.mark.parametrize("field", ["action_type", "evidence"])
def test_missing_values_require_review_issue_before_clean_product_is_created(building, field):
    folder = create(building)
    draft = finish(building, folder)
    draft["plan_data"]["actions"][0][field] = []
    write(building, folder, draft)
    assert not reviews.validate_review_draft(building, PLAN_ID, "review_0001").valid
    draft["plan_issues"]["issues"][0]["related_action_id"] = "action_0001"
    write(building, folder, draft)
    reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    clean, record = reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")
    assert clean["actions"][0][field] == [] and record["issues"][0]["resolution"]


@pytest.mark.parametrize("damage", ["source_copy", "source_run", "raw_json", "duplicate_json_keys", "name_field"])
def test_draft_integrity_errors_are_read_only(building, damage):
    folder = create(building)
    draft = read(building, folder)
    if damage == "source_copy": (building / folder / "source_run.json").write_text('{}')
    elif damage == "source_run": (building / draft["source"]["record_path"]).write_text('{}')
    elif damage == "raw_json": (building / folder / "review_draft.json").write_text('{broken')
    elif damage == "duplicate_json_keys":
        file = building / folder / "review_draft.json"
        file.write_text(file.read_text().replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1'))
    else:
        draft["reviewers"] = ["obsolete"]
        write(building, folder, draft)
    before = snapshot(building)
    assert not reviews.validate_review_draft(building, PLAN_ID, "review_0001").valid
    assert snapshot(building) == before


@pytest.mark.parametrize("target", ["reviewed_plan.json", "review_draft.json", "source_run.json", "review_record.json"])
def test_partial_finalization_never_publishes_completion_and_can_resume_matching_bytes(building, monkeypatch, target):
    folder = create(building)
    finish(building, folder)
    original = storage._publish_new_bytes
    def fail(file, raw):
        if file.name == target:
            raise OSError("Controlled publication failure")
        return original(file, raw)
    monkeypatch.setattr(storage, "_publish_new_bytes", fail)
    with pytest.raises(OSError, match="Controlled"):
        reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    with pytest.raises(OSError):
        reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")
    monkeypatch.setattr(storage, "_publish_new_bytes", original)
    reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    assert reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")[0] == read(building, folder)["plan_data"]


@pytest.mark.parametrize("changed", ["draft", "source", "clean"])
def test_intervening_changes_stop_completion_without_overwriting_partial_evidence(building, monkeypatch, changed):
    folder = create(building)
    draft = finish(building, folder)
    original = storage._publish_new_bytes
    def change_after_write(file, raw):
        original(file, raw)
        if file.name == "reviewed_plan.json":
            if changed == "draft":
                draft["plan_data"]["actions"][0]["action"] = "An intervening expert edit."
                write(building, folder, draft)
            elif changed == "source":
                source = building / draft["source"]["record_path"]
                source.write_bytes(source.read_bytes() + b"\n")
            else:
                data = json.loads(raw)
                data["actions"][0]["action"] = "Intervening data-product edit."
                file.write_text(json.dumps(data))
    monkeypatch.setattr(storage, "_publish_new_bytes", change_after_write)
    with pytest.raises(ValueError):
        reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    final = building / f"data/dataset_building/reviewed_plans/{PLAN_ID}/review_0001"
    assert (final / "reviewed_plan.json").exists() and not (final / "review_record.json").exists()
    with pytest.raises(OSError):
        reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")


@pytest.mark.parametrize("target", ["reviewed_plan.json", "review_draft.json", "source_run.json", "review_record.json"])
def test_completed_snapshot_tampering_is_rejected(building, target):
    folder = create(building)
    finish(building, folder)
    final = reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    file = building / final / target
    data = json.loads(file.read_text())
    if target == "reviewed_plan.json": data["actions"][0]["action"] = "Changed data product."
    elif target == "review_record.json": data["expert_addressed_issue_ids"] = []
    elif target == "review_draft.json": data["plan_issues"]["issues"][0]["resolution"] = "Changed resolution."
    else: data["purpose"] = "comparison"
    file.write_text(json.dumps(data))
    before = snapshot(building)
    with pytest.raises(ValueError):
        reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")
    assert snapshot(building) == before


def test_finalized_snapshot_survives_later_original_draft_edits(building):
    folder = create(building)
    finish(building, folder)
    reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
    expected = reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")
    draft = read(building, folder)
    draft["plan_data"]["actions"][0]["action"] = "Later unsaved-for-approval change."
    write(building, folder, draft)
    assert reviews.load_reviewed_plan(building, PLAN_ID, "review_0001") == expected
    assert not reviews.validate_review_draft(building, PLAN_ID, "review_0001").valid


def test_interrupted_and_completed_folders_reserve_review_numbers(building):
    parent = building / f"data/dataset_building/review_drafts/{PLAN_ID}"
    parent.mkdir(parents=True)
    (parent / "review_0001").mkdir()
    final = building / f"data/dataset_building/reviewed_plans/{PLAN_ID}"
    final.mkdir(parents=True)
    (final / "review_0002").write_text("Occupied evidence")
    assert create(building).endswith("review_0003")


def test_cli_lifecycle_needs_no_names_and_reports_pending_issues(building, capsys):
    base = [PLAN_ID, "--project-root", str(building)]
    assert cli.main(["create_review_draft", *base, "--configuration", "E"]) == 0
    folder = f"data/dataset_building/review_drafts/{PLAN_ID}/review_0001"
    assert "review_draft.json" in capsys.readouterr().out
    flags = [*base, "--review-id", "review_0001"]
    assert cli.main(["validate_review_draft", *flags]) == 0
    assert "Open issues: 1" in capsys.readouterr().out
    assert cli.main(["validate_review_draft", *flags, "--require-complete"]) == 1
    assert cli.main(["finalize_reviewed_plan", *flags]) == 1
    finish(building, folder)
    assert cli.main(["validate_review_draft", *flags, "--require-complete"]) == 0
    assert cli.main(["finalize_reviewed_plan", *flags]) == 0
    assert "review_record.json" in capsys.readouterr().out


@pytest.mark.parametrize("path", ["draft_root", "source_copy", "final_root"])
def test_review_paths_do_not_follow_symlinks(building, tmp_path, path):
    if path == "draft_root":
        outside = tmp_path / "outside"
        outside.mkdir()
        (building / "data/dataset_building").mkdir(exist_ok=True)
        (building / "data/dataset_building/review_drafts").symlink_to(outside, target_is_directory=True)
        with pytest.raises(ValueError, match="symbolic|outside"):
            create(building)
    else:
        folder = create(building)
        finish(building, folder)
        if path == "source_copy":
            file = building / folder / "source_run.json"
            copy = tmp_path / "source.json"
            copy.write_bytes(file.read_bytes())
            file.unlink()
            file.symlink_to(copy)
            assert not reviews.validate_review_draft(building, PLAN_ID, "review_0001").valid
        else:
            outside = tmp_path / "outside"
            outside.mkdir()
            (building / "data/dataset_building/reviewed_plans").symlink_to(outside, target_is_directory=True)
            with pytest.raises(ValueError, match="symbolic|outside"):
                reviews.finalize_reviewed_plan(building, PLAN_ID, "review_0001")
