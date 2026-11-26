"""Validate fictional review files without judging source meaning or paid calls.

The source fixture exercises the saved C runner and strict E/V/C loaders. Manual
judgments below are invented to test data integrity, never extraction quality.
"""

from copy import deepcopy
import csv
import hashlib
import json

import pytest

import assessments
import assessment_validation as review
import cli
import storage
import validation
from test_agent_loop import PLAN_ID, SOURCE, project
from test_assessment_creation import (
    clone_c, create, metadata, publish, rows, snapshot, study, template_directory,
)
from test_collaboration_contracts import configured
from test_saved_collaboration import ready
from test_saved_extractor import facts


@pytest.fixture
def assessment(study):
    return study, create(study)


def check(root, path):
    return review.validate_assessment(root, PLAN_ID, path.rsplit("/", 1)[-1])


def write_rows(root, path, name, records, *, columns=None, encoding="utf-8", newline="\n"):
    with (root / path / name).open("w", newline="", encoding=encoding) as stream:
        writer = csv.DictWriter(stream, fieldnames=columns or review.TABLE_COLUMNS[name], lineterminator=newline)
        writer.writeheader()
        writer.writerows(records)


def change_row(root, path, name, **changes):
    records = rows(root, path, name)
    records[0].update(changes)
    write_rows(root, path, name, records)


def change_metadata(root, path, transform):
    data = metadata(root, path)
    transform(data)
    (root / path / "metadata.json").write_text(json.dumps(data), encoding="utf-8")


def finish(root, path):
    records = rows(root, path, "action_scores.csv")
    for row in records:
        matched = row["reference_action_id"] == "action_0001"
        row.update(matched_output_action_ids='["action_0001"]' if matched else "[]",
                   score="1" if matched else "0", reason="Fictional rubric judgment.")
    write_rows(root, path, "action_scores.csv", records)
    records = rows(root, path, "output_review.csv")
    for row in records:
        row.update(activity_supported="yes", evidence_adequate="yes", reason="Fictional source judgment.")
    write_rows(root, path, "output_review.csv", records)
    records = rows(root, path, "verifier_resolutions.csv")
    for row in records:
        row.update(confirmed="yes", reason="Fictional check of all grouped concerns.")
    write_rows(root, path, "verifier_resolutions.csv", records)


def assert_invalid(report, message):
    assert not report.valid and not report.complete and report.data is None
    assert any(message in problem.message for problem in report.problems), report.problems


def test_new_assessment_is_valid_pending_and_read_only(assessment, monkeypatch):
    root, path = assessment
    monkeypatch.delenv("HF_TOKEN", raising=False)
    before = snapshot(root)
    report = check(root, path)
    assert report.valid and not report.complete and report.problems == []
    assert report.pending and "included_attempts" not in report.data.metadata
    first = report.data.tables["action_scores.csv"][0]
    assert first["score"] is None and first["matched_output_action_ids"] is None
    assert report.data.tables["output_review.csv"][0]["activity_supported"] is None
    assert all(not ready for ready in report.readiness["reference_actions"].values())
    assert report.readiness["verifier_resolutions"] is False
    assert report.data.fingerprints == {
        name: hashlib.sha256((root / path / name).read_bytes()).hexdigest()
        for name in ("metadata.json", *review.TABLE_COLUMNS)
    }
    assert snapshot(root) == before


def test_complete_review_retains_zero_and_omission(assessment):
    root, path = assessment
    finish(root, path)
    before = snapshot(root)
    report = check(root, path)
    assert report.complete and report.pending == [] and report.problems == []
    assert all(all(value.values()) if isinstance(value, dict) else value for value in report.readiness.values())
    scores = report.data.tables["action_scores.csv"]
    assert scores[1]["score"] == 0 and scores[1]["matched_output_action_ids"] == []
    assert scores[0]["score"] == 1 and scores[0]["matched_output_action_ids"] == ["action_0001"]
    assert "included_attempts" not in report.data.metadata
    assert snapshot(root) == before


@pytest.mark.parametrize("score,parsed", [(".50", .5), ("1.0", 1), ("0.00", 0)])
def test_numeric_scores_and_normalized_judgments_are_parsed_only_in_memory(assessment, score, parsed):
    root, path = assessment
    finish(root, path)
    change_row(root, path, "action_scores.csv", score=score)
    change_row(root, path, "output_review.csv", activity_supported=" YES ", evidence_adequate="Yes")
    before = snapshot(root)
    report = check(root, path)
    assert report.complete
    assert report.data.tables["action_scores.csv"][0]["score"] == parsed
    assert report.data.tables["output_review.csv"][0]["activity_supported"] == "yes"
    assert snapshot(root) == before


@pytest.mark.parametrize("score", ["NaN", "Infinity", "0.25", "2", "True", "-1"])
def test_invalid_scores_cannot_be_calculated(assessment, score):
    root, path = assessment
    change_row(root, path, "action_scores.csv", score=score)
    assert_invalid(check(root, path), "Score must be")


@pytest.mark.parametrize("value,message", [
    ('["action_9999"]', "Unknown output IDs"), ('["action_0001", "action_0001"]', "duplicates"),
    ('"action_0001"', "JSON list"), ('[1]', "nonblank string"), ('[""]', "nonblank string"),
    ('["action_0001",]', "JSON list"), ('[NaN]', "JSON list"),
])
def test_invalid_match_links(assessment, value, message):
    root, path = assessment
    change_row(root, path, "action_scores.csv", matched_output_action_ids=value)
    assert_invalid(check(root, path), message)


def test_omission_cannot_have_positive_score_but_zero_can_link_a_wrong_answer(assessment):
    root, path = assessment
    change_row(root, path, "action_scores.csv", matched_output_action_ids="[]", score="0.5")
    assert_invalid(check(root, path), "omission")
    change_row(root, path, "action_scores.csv", matched_output_action_ids='["action_0001"]', score="0")
    assert check(root, path).valid


@pytest.mark.parametrize("table", ["action_scores.csv", "output_review.csv"])
@pytest.mark.parametrize("field,value", [("configuration", "V"), ("run_id", "run_extract_9999")])
def test_csv_rows_must_identify_the_selected_configuration(assessment, table, field, value):
    root, path = assessment
    change_row(root, path, table, **{field: value})
    report = check(root, path)
    assert_invalid(report, "Use E" if field == "configuration" else "Run ID")


@pytest.mark.parametrize("damage,message", [
    ("missing", "Missing scoring row"), ("duplicate", "exactly one row"), ("unknown", "Unknown frozen-reference"),
    ("text", "Copied context"), ("evidence", "Reference evidence"),
])
def test_fixed_reference_rows_and_copied_context_are_protected(assessment, damage, message):
    root, path = assessment
    records = rows(root, path, "action_scores.csv")
    if damage == "missing":
        records.pop()
    elif damage == "duplicate":
        records.append(records[0])
    elif damage == "unknown":
        records[0]["reference_action_id"] = "action_9999"
    elif damage == "text":
        records[0]["reference_action"] = "A rewritten reference."
    else:
        records[0]["reference_evidence"] = "[]"
    write_rows(root, path, "action_scores.csv", records)
    assert_invalid(check(root, path), message)


def test_all_output_records_need_group_coverage_but_missing_groups_remain_pending(assessment):
    root, path = assessment
    finish(root, path)
    write_rows(root, path, "output_review.csv", [])
    report = check(root, path)
    assert report.valid and not report.complete
    assert len(report.pending) == 3
    assert all("do not yet cover" in pending.message for pending in report.pending)
    assert not any(report.readiness["output_support"].values())


def test_one_bundled_output_record_may_be_split_into_distinct_activities(assessment):
    root, path = assessment
    finish(root, path)
    records = rows(root, path, "output_review.csv")
    split = {**records[0], "output_activity_id": "activity_0002", "activity_description": "Second bundled activity.", "evidence": "[]"}
    records.append(split)
    write_rows(root, path, "output_review.csv", records)
    assert check(root, path).complete
    # Reusing a model record is valid; reusing the group ID within E is not.
    records[-1]["output_activity_id"] = records[0]["output_activity_id"]
    write_rows(root, path, "output_review.csv", records)
    assert_invalid(check(root, path), "unique within a configuration")


def test_split_output_records_may_be_merged_and_matched_as_a_group(study):
    e = storage.load_run_record(study, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    another = deepcopy(e["plan_data"]["actions"][0])
    another.update(action_id="action_0002", action="A second record of the same fictional activity.")
    e["plan_data"]["actions"].append(another)
    publish(study, e, "extractor", 2)
    v = storage.load_run_record(study, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    v["plan_data"]["actions"].append(another)
    publish(study, v, "verifier", 2, input_run_id="run_extract_0002")
    path = create(study)
    finish(study, path)
    records = rows(study, path, "output_review.csv")
    merged = []
    for row in records:
        if row["configuration"] in {"E", "E+V"}:
            if row["output_activity_id"] == "activity_0002":
                continue
            row.update(output_action_ids='["action_0001", "action_0002"]', activity_description="Merged activity.")
        merged.append(row)
    write_rows(study, path, "output_review.csv", merged)
    change_row(study, path, "action_scores.csv", matched_output_action_ids='["action_0001", "action_0002"]')
    assert check(study, path).complete
    # An ID valid in E is still unknown in independent C.
    merged[-1]["output_action_ids"] = '["action_0002"]'
    write_rows(study, path, "output_review.csv", merged)
    assert_invalid(check(study, path), "Unknown output IDs")


@pytest.mark.parametrize("field,value,message", [
    ("output_activity_id", " ", "nonblank"), ("output_action_ids", "[]", "at least one"),
    ("output_action_ids", '["action_9999"]', "Unknown output IDs"),
    ("activity_supported", "true", "yes, no, or undetermined"),
    ("evidence_adequate", "false", "yes, no, or undetermined"),
    ("evidence", "{}", "JSON list"), ("evidence", "[", "Invalid copied evidence"),
    ("evidence", '[{"quote":"Invented","page_numbers":[1]}]', "come from the linked"),
    ("evidence", '[{"quote":"We will plant 20 trees.","page_numbers":[true]}]', "come from the linked"),
])
def test_invalid_output_review_values(assessment, field, value, message):
    root, path = assessment
    change_row(root, path, "output_review.csv", **{field: value})
    assert_invalid(check(root, path), message)


def test_unsupported_activity_cannot_have_adequate_evidence(assessment):
    root, path = assessment
    finish(root, path)
    change_row(root, path, "output_review.csv", activity_supported="no")
    assert_invalid(check(root, path), "unsupported activity")
    change_row(root, path, "output_review.csv", evidence_adequate="no")
    assert check(root, path).complete


@pytest.mark.parametrize("table,field", [
    ("action_scores.csv", "reason"), ("action_scores.csv", "matched_output_action_ids"),
    ("output_review.csv", "reason"), ("output_review.csv", "output_action_ids"),
    ("output_review.csv", "activity_description"), ("verifier_resolutions.csv", "reason"),
])
def test_missing_manual_values_are_pending_and_never_zero(assessment, table, field):
    root, path = assessment
    finish(root, path)
    change_row(root, path, table, **{field: "  "})
    report = check(root, path)
    assert report.valid and not report.complete
    assert any(pending.location.endswith("." + field) for pending in report.pending)


@pytest.mark.parametrize("table,field,readiness", [
    ("output_review.csv", "activity_supported", "output_support"),
    ("output_review.csv", "evidence_adequate", "output_evidence"),
    ("verifier_resolutions.csv", "confirmed", "verifier_resolutions"),
])
def test_undetermined_judgment_is_valid_uncertainty_and_still_pending(assessment, table, field, readiness):
    root, path = assessment
    finish(root, path)
    change_row(root, path, table, **{field: "undetermined"})
    report = check(root, path)
    assert report.valid and not report.complete
    assert len(report.pending) == 1 and "undetermined" in report.pending[0].message
    assert not (report.readiness[readiness]["E"] if readiness != "verifier_resolutions" else report.readiness[readiness])


@pytest.mark.parametrize("damage,message", [
    ("missing", "Missing eligible"), ("duplicate", "must not be duplicated"),
    ("already_closed_e", "not an eligible"), ("new_v_issue", "not an eligible"),
    ("changed_resolution", "Copied context"), ("changed_link", "Copied context"),
    ("invalid_confirmation", "yes, no, or undetermined"),
])
def test_only_exact_eligible_v_claims_can_be_reviewed(assessment, damage, message):
    root, path = assessment
    records = rows(root, path, "verifier_resolutions.csv")
    if damage == "missing":
        records.clear()
    elif damage == "duplicate":
        records.append(records[0])
    elif damage in {"already_closed_e", "new_v_issue"}:
        records[0]["issue_id"] = "issue_0002" if damage == "already_closed_e" else "issue_0003"
    else:
        field, value = {"changed_resolution": ("claimed_resolution", "Rewritten claim"),
                        "changed_link": ("related_action_id", "action_0001"),
                        "invalid_confirmation": ("confirmed", "true")}[damage]
        records[0][field] = value
    write_rows(root, path, "verifier_resolutions.csv", records)
    assert_invalid(check(root, path), message)


def test_no_v_resolution_claims_is_valid_without_fabricated_judgments(study):
    v = storage.load_run_record(study, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    v["plan_issues"]["issues"][0].update(issue_status="open", resolved_by=None, resolution=None)
    publish(study, v, "verifier", 2, input_run_id="run_extract_0001")
    path = create(study)
    finish(study, path)
    report = check(study, path)
    assert report.complete and report.data.tables["verifier_resolutions.csv"] == []


def test_newer_runs_do_not_change_the_assessment_selection(assessment):
    root, path = assessment
    e = storage.load_run_record(root, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    v = storage.load_run_record(root, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    publish(root, e, "extractor", 2)
    publish(root, v, "verifier", 2, input_run_id="run_extract_0002")
    clone_c(root, 2)
    report = check(root, path)
    assert report.valid
    assert report.data.runs["E"]["run_id"] == "run_extract_0001"
    assert report.data.runs["E+V"]["run_id"] == "run_verify_0001"
    assert report.data.runs["C"]["run_id"] == "run_collaboration_0001"


def test_a_changed_e_v_pair_is_invalid_even_with_updated_run_fingerprints(assessment):
    root, path = assessment
    e = storage.load_run_record(root, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    publish(root, e, "extractor", 2)
    def change(data):
        selected = data["runs"]["E"]
        selected.update(run_id="run_extract_0002", record_path=f"runs/{PLAN_ID}/run_extract_0002/output.json")
        selected["record_sha256"] = hashlib.sha256((root / selected["record_path"]).read_bytes()).hexdigest()
    change_metadata(root, path, change)
    assert_invalid(check(root, path), "not linked")


def test_v_only_selection_provenance_is_accepted(study):
    path = create(study, verifier_run_id="run_verify_0001")
    assert metadata(study, path)["runs"]["E"]["selected_via"] == "verifier_link"
    assert check(study, path).valid


def test_sample_membership_does_not_change_a_comparison_assessment(assessment):
    root, path = assessment
    registry = storage.load_registry(root)
    registry["plans"][0]["study_set"] = "comparison"
    (root / "data/registry/plans.json").write_text(json.dumps(registry))
    before = snapshot(root)
    assert check(root, path).valid
    assert snapshot(root) == before


def test_zero_output_records_needs_no_invented_review_rows(study):
    e = storage.load_run_record(study, f"runs/{PLAN_ID}/run_extract_0001/output.json")
    v = storage.load_run_record(study, f"runs/{PLAN_ID}/run_verify_0001/output.json")
    for record in (e, v):
        record["plan_data"]["actions"] = []
        record["plan_issues"]["issues"] = []
    publish(study, e, "extractor", 2)
    publish(study, v, "verifier", 2, input_run_id="run_extract_0002")
    path = create(study)
    finish(study, path)
    records = rows(study, path, "action_scores.csv")
    for row in records:
        if row["configuration"] in {"E", "E+V"}:
            row.update(matched_output_action_ids="[]", score="0")
    write_rows(study, path, "action_scores.csv", records)
    report = check(study, path)
    assert report.complete
    assert len(report.data.tables["output_review.csv"]) == 1
    assert report.readiness["output_support"]["E"] is True


@pytest.mark.parametrize("damage", [
    "wrong_plan", "wrong_id", "extra", "reference_path", "freeze_path", "run_path", "run_hash",
    "source_hash", "source_count", "source_path", "v_link_selection", "e_link_without_explicit_v",
])
def test_invalid_metadata_and_provenance_are_rejected(assessment, damage):
    root, path = assessment
    def change(data):
        if damage == "wrong_plan": data["plan_id"] = "plan_9999"
        elif damage == "wrong_id": data["assessment_id"] = "assessment_0002"
        elif damage == "extra": data["extra"] = 1
        elif damage == "reference_path": data["reference"]["path"] = "elsewhere.json"
        elif damage == "freeze_path": data["reference"]["freeze_path"] = "elsewhere.json"
        elif damage == "run_path": data["runs"]["E"]["record_path"] = "elsewhere.json"
        elif damage == "run_hash": data["runs"]["C"]["record_sha256"] = "0" * 64
        elif damage == "source_hash": data["source"]["fingerprint"] = "0" * 64
        elif damage == "source_count": data["source"]["page_count"] += 1
        elif damage == "source_path": data["source"]["preparation_path"] = "elsewhere.json"
        elif damage == "v_link_selection": data["runs"]["E+V"]["selected_via"] = "verifier_link"
        else: data["runs"]["E"]["selected_via"] = "verifier_link"
    change_metadata(root, path, change)
    assert not check(root, path).valid


@pytest.mark.parametrize("damage", ["duplicate_key", "utf8", "nested", "nan", "trailing"])
def test_metadata_is_strict_json_with_readable_failures(assessment, damage):
    root, path = assessment
    file = root / path / "metadata.json"
    raw = file.read_bytes()
    if damage == "duplicate_key": file.write_bytes(raw.replace(b'"schema_version": 2', b'"schema_version": 2, "schema_version": 2'))
    elif damage == "utf8": file.write_bytes(b"\xff")
    elif damage == "nested": file.write_bytes(b"[" * 1100 + b"]" * 1100)
    elif damage == "nan": file.write_bytes(raw.replace(b'"notes": null', b'"notes": NaN'))
    else: file.write_bytes(raw + b"trailing")
    assert not check(root, path).valid


@pytest.mark.parametrize("name", ["metadata.json", *review.TABLE_COLUMNS])
def test_missing_assessment_files_are_invalid(assessment, name):
    root, path = assessment
    (root / path / name).unlink()
    assert not check(root, path).valid


@pytest.mark.parametrize("damage", [
    "run", "reference", "freeze", "pages", "original", "supporting_evidence",
    "E_candidate", "E+V_candidate", "E_code", "E+V_code",
])
def test_changed_saved_inputs_and_evidence_are_invalid(assessment, damage):
    root, path = assessment
    data = metadata(root, path)
    if damage == "run": file = root / data["runs"]["C"]["record_path"]
    elif damage == "reference": file = root / data["reference"]["path"]
    elif damage == "freeze": file = root / data["reference"]["freeze_path"]
    elif damage == "supporting_evidence":
        file = next((root / f"runs/{PLAN_ID}/run_collaboration_0001/artifacts").glob("collaboration_input.json"))
    elif damage.endswith(("_candidate", "_code")):
        configuration, kind = damage.rsplit("_", 1)
        folder = (root / data["runs"][configuration]["record_path"]).parent
        if kind == "candidate":
            report = json.loads((folder / "validation_report.json").read_text())
            file = root / (report["repaired_response_path"] or report["raw_response_path"])
            candidate = json.loads(file.read_text())
            candidate["plan_data"]["actions"][0]["action"] = "Changed preserved answer."
            file.write_text(json.dumps(candidate))
        else:
            manifest = json.loads((folder / "artifacts/code_fingerprints.json").read_text())
            (folder / "artifacts/code" / next(iter(manifest["sha256"]))).write_bytes(b"changed archive")
        assert not check(root, path).valid
        return
    else:
        _, prep, _ = storage.load_plan_preparation(root, PLAN_ID, SOURCE)
        file = root / prep["pages_path"] if damage == "pages" else root / prep["pdf_path"]
    if damage == "pages":
        file.write_text(file.read_text().replace("We will plant 20 trees.", "Changed prepared text."))
    else:
        file.write_bytes(file.read_bytes() + (b"corrupted" if damage in {"original", "supporting_evidence"} else b"\n"))
    assert not check(root, path).valid


@pytest.mark.parametrize("name", ["metadata.json", "action_scores.csv", "directory"])
def test_assessment_symlinks_are_rejected_even_inside_project(assessment, name):
    root, path = assessment
    file = root / path if name == "directory" else root / path / name
    target = root / ("alternate-folder" if name == "directory" else "alternate.csv")
    file.rename(target)
    file.symlink_to(target, target_is_directory=name == "directory")
    assert not check(root, path).valid


@pytest.mark.parametrize("identifier", ["../assessment_0001", "assessment_0000", "missing", None])
def test_invalid_assessment_ids_are_rejected(study, identifier):
    report = review.validate_assessment(study, PLAN_ID, identifier)
    assert_invalid(report, "numbered assessment")


@pytest.mark.parametrize("damage", ["missing_header", "extra_header", "duplicate_header", "short_row", "long_row", "unterminated", "utf8"])
def test_malformed_csv_cannot_silently_drop_review_data(assessment, damage):
    root, path = assessment
    file = root / path / "action_scores.csv"
    records = rows(root, path, "action_scores.csv")
    columns = list(assessments.ACTION_COLUMNS)
    if damage in {"missing_header", "extra_header", "duplicate_header"}:
        if damage == "missing_header":
            columns.pop()
            for row in records: row.pop("reason")
        elif damage == "extra_header": columns.append("extra")
        else: columns.append("score")
        write_rows(root, path, "action_scores.csv", records, columns=columns)
    elif damage in {"short_row", "long_row"}:
        file.write_text(",".join(columns) + "\n" + ",".join(["cell"] * (len(columns) + (1 if damage == "long_row" else -1))) + "\n")
    elif damage == "unterminated": file.write_text(",".join(columns) + '\n"not closed')
    else: file.write_bytes(b"\xff")
    assert not check(root, path).valid


def test_spreadsheet_bom_crlf_reordered_columns_and_long_cells_roundtrip(assessment):
    root, path = assessment
    finish(root, path)
    for name, columns in review.TABLE_COLUMNS.items():
        records = rows(root, path, name)
        records[0]["reason"] = "Long fictional reason — " * 7000
        if name == "action_scores.csv":
            records[0]["reference_action"] = records[0]["reference_action"].replace("\n", "\r\n")
        write_rows(root, path, name, records, columns=list(reversed(columns)), encoding="utf-8-sig", newline="\r\n")
    previous_limit = csv.field_size_limit()
    before = snapshot(root)
    assert check(root, path).complete
    assert csv.field_size_limit() == previous_limit
    assert snapshot(root) == before


@pytest.mark.parametrize("target", ["csv", "run"])
def test_changes_during_validation_require_a_retry(assessment, monkeypatch, target):
    root, path = assessment
    original = review._read_csv
    def edited(*args, **kwargs):
        result = original(*args, **kwargs)
        file = root / path / "action_scores.csv" if target == "csv" else root / f"runs/{PLAN_ID}/run_extract_0001/output.json"
        file.write_bytes(file.read_bytes() + b"\n")
        return result
    monkeypatch.setattr(review, "_read_csv", edited)
    assert not check(root, path).valid


def test_cli_pending_complete_strict_and_invalid_exit_statuses(assessment, capsys):
    root, path = assessment
    command = ["validate_assessment", PLAN_ID, "--assessment-id", "assessment_0001", "--project-root", str(root)]
    assert cli.main(command) == 0
    output = capsys.readouterr().out
    assert "Manual review: pending" in output
    assert "Validation does not establish scientific correctness." in output
    assert "Failure-reporting" not in output
    assert cli.main([*command, "--require-complete"]) == 1
    assert "requires all manual judgments" in capsys.readouterr().err
    finish(root, path)
    assert cli.main([*command, "--require-complete"]) == 0
    assert "Manual review: complete" in capsys.readouterr().out
    change_row(root, path, "action_scores.csv", score="999")
    assert cli.main(command) == 1
    assert "Score must be" in capsys.readouterr().err


def test_cli_requires_explicit_assessment_id(study):
    with pytest.raises(SystemExit) as error:
        cli.main(["validate_assessment", PLAN_ID, "--project-root", str(study)])
    assert error.value.code == 2


def test_strict_metadata_parser_withholds_invalid_data():
    assert validation.parse_assessment_metadata_json('{"schema_version":1,"schema_version":1}')[0] is None
