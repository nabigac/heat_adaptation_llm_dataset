"""Regression cases found during the complete plan-to-dataset code review."""

from copy import deepcopy
import json

import pytest

import cli
import collaboration_storage
import dataset_assembly
import plan_reviews
import storage
from test_agent_loop import PLAN_ID, SOURCE, project
from test_assessment_creation import snapshot, study, template_directory
from test_collaboration_contracts import configured
from test_dataset_assembly import complete
from test_plan_reviews import building
from test_saved_collaboration import ready
from test_saved_extractor import facts


@pytest.mark.parametrize("start,end,valid", [
    ("00Z", "00.1Z", True), ("00.9Z", "00Z", False),
    ("00+00:00", "00.1Z", True), ("00.1Z", "00.1+00:00", True),
    ("00.1+00:00", "00.1Z", True), ("00Z", "01+00:00", True),
    ("01Z", "00.9+00:00", False), ("00z", "00.1+00:00", True),
])
def test_c_timestamp_order_uses_actual_utc_times(study, start, end, valid):
    record = storage.load_run_record(study, f"runs/{PLAN_ID}/run_collaboration_0001/output.json")
    record.update(started_at="2026-11-25T00:00:" + start, ended_at="2026-11-25T00:00:" + end)
    if valid:
        collaboration_storage.validate_record(record)
    else:
        with pytest.raises(ValueError, match="end must follow"):
            collaboration_storage.validate_record(record)


@pytest.mark.parametrize("damage", ["missing_packet", "list_packet", "missing_field", "wrong_pages_type", "bool_page_number", "extra_field"])
def test_malformed_c_preserved_input_is_a_readable_validation_failure(study, damage):
    path = f"runs/{PLAN_ID}/run_collaboration_0001/output.json"
    file = study / f"runs/{PLAN_ID}/run_collaboration_0001/artifacts/collaboration_input.json"
    data = json.loads(file.read_text())
    if damage == "missing_packet": data.pop("packet")
    elif damage == "list_packet": data["packet"] = []
    elif damage == "missing_field": data["packet"].pop("profiles")
    elif damage == "wrong_pages_type": data["pages"] = {}
    elif damage == "bool_page_number": data["pages"][0]["page_number"] = True
    else: data["packet"]["unexpected"] = "Not preserved model input"
    file.write_text(json.dumps(data))
    before = snapshot(study)
    with pytest.raises(ValueError, match="[Pp]reserved C input|Saved C input"):
        storage.load_run_record(study, path)
    assert snapshot(study) == before
    # This path goes through the normal CLI error handling, not a Python traceback.
    assert cli.main(["create_assessment", PLAN_ID, "--collaboration-run-id", "run_collaboration_0001",
                     "--project-root", str(study)]) == 1


def test_completed_review_public_snapshot_keeps_checked_exact_bytes(building):
    folder = complete(building)
    checked = plan_reviews.load_completed_review(building, PLAN_ID, "review_0001")
    data, record = plan_reviews.load_reviewed_plan(building, PLAN_ID, "review_0001")
    assert checked.data == data and checked.record == record
    assert checked.source_run == json.loads(checked.files["source_run.json"])
    assert checked.files == {name: (building / folder / name).read_bytes() for name in plan_reviews.REVIEW_FILES}


@pytest.mark.parametrize("product", ["reviewed_plan", "heat_action_dataset"])
def test_new_cli_validators_are_read_only_and_reject_changed_artifacts(building, capsys, product):
    review = complete(building)
    if product == "reviewed_plan":
        args = ["validate_reviewed_plan", PLAN_ID, "--review-id", "review_0001"]
        file = building / review / "reviewed_plan.json"
    else:
        dataset = dataset_assembly.build_heat_action_dataset(building, [review])
        args = ["validate_heat_action_dataset", "dataset_0001"]
        file = building / dataset / "heat_action_dataset.json"
    args += ["--project-root", str(building)]
    before = snapshot(building)
    assert cli.main(args) == 0
    assert "validation passed" in capsys.readouterr().out
    assert snapshot(building) == before
    data = json.loads(file.read_text())
    data["unexpected"] = "Invalid edit"
    file.write_text(json.dumps(data))
    before = snapshot(building)
    assert cli.main(args) == 1
    assert "Error:" in capsys.readouterr().err
    assert snapshot(building) == before


def test_every_registered_cli_command_has_one_handler():
    parser = cli._build_parser()
    commands = next(action for action in parser._actions if action.dest == "command").choices
    assert set(commands) == set(cli._command_handlers())
