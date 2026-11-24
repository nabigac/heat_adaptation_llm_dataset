"""Exercise guided drafts, record selection, and preservation through real files."""

from copy import deepcopy
import json

import pytest
from pypdf import PdfWriter

import cli
import documents
import expert_files
import storage
import validation


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "expert study"
    root.mkdir()
    original = tmp_path / "source.pdf"
    with PdfWriter() as writer:
        for _ in range(3):
            writer.add_blank_page(width=300, height=300)
        writer.write(original)
    documents.register_document(
        root, original, plan_title="Fictional heat plan",
        source_url="https://example.org/plan.pdf", date_accessed="2026-11-21",
        study_set="comparison",
    )
    expert_files.create_expert_reference(root, "plan_0001", prepared_by=["reviewer"])
    return root


def reference_path(root):
    return root / "data/expert_references/plan_0001/expert_reference.json"


def read(root):
    return json.loads(reference_path(root).read_text())


def write(root, reference):
    reference_path(root).write_text(json.dumps(reference, ensure_ascii=False, indent=2) + "\n")


def records(reference, kind):
    return reference["plan_data"]["actions"] if kind == "action" else reference["plan_issues"]["issues"]


def edit(root, operation, record_id=None):
    return expert_files.edit_expert_reference(root, "plan_0001", operation=operation, record_id=record_id)


def context():
    return dict(plan_id="plan_0001", source_url="https://example.org/plan.pdf",
                date_accessed="2026-11-21", page_count=3)


@pytest.mark.parametrize("kind", ["action", "issue"])
def test_add_appends_next_id_preserving_existing_reference_and_other_files(project, kind, monkeypatch):
    monkeypatch.delenv("HF_TOKEN", raising=False)
    model = project / "runs/plan_0001/run_extract_0001/output.json"
    model.parent.mkdir(parents=True)
    model.write_text("Invalid model content must not be accessed.")
    before = read(project)
    other_files = {p: p.read_bytes() for p in project.rglob("*")
                   if p.is_file() and p != reference_path(project)}

    path, record_id = edit(project, f"add_{kind}")

    assert path == "data/expert_references/plan_0001/expert_reference.json"
    assert record_id == f"{kind}_0002"
    after = read(project)
    added = records(after, kind).pop()
    assert added[f"{kind}_id"] == record_id
    assert added["action" if kind == "action" else "issue_description"].startswith("TODO:")
    before["id_counters"][kind] = 2
    assert after == before
    assert all(p.read_bytes() == contents for p, contents in other_files.items())


@pytest.mark.parametrize("kind", ["action", "issue"])
@pytest.mark.parametrize("legacy", [False, True])
def test_deleted_ids_are_not_reused_even_when_all_records_are_removed(project, kind, legacy):
    if legacy:
        reference = read(project)
        reference.pop("id_counters")
        write(project, reference)
    assert edit(project, f"add_{kind}")[1] == f"{kind}_0002"
    reference = read(project)
    records(reference, kind)[-1]["action" if kind == "action" else "issue_description"] = "Expert text."
    write(project, reference)
    edit(project, f"remove_{kind}", f"{kind}_0002")
    edit(project, f"remove_{kind}")
    assert records(read(project), kind) == []
    assert edit(project, f"add_{kind}")[1] == f"{kind}_0003"
    other = "issue" if kind == "action" else "action"
    assert read(project)["id_counters"] == {kind: 3, other: 1}


@pytest.mark.parametrize("kind", ["action", "issue"])
def test_removing_a_manually_added_high_id_retains_its_number(project, kind):
    reference = read(project)
    records(reference, kind)[0][f"{kind}_id"] = f"{kind}_10000"
    write(project, reference)
    edit(project, f"remove_{kind}")
    assert edit(project, f"add_{kind}")[1] == f"{kind}_10001"


def test_integral_json_counter_numbers_remain_editable(project):
    reference = read(project)
    reference["id_counters"] = {"action": 1.0, "issue": 1.0}
    write(project, reference)
    assert edit(project, "add_action")[1] == "action_0002"
    assert read(project)["id_counters"] == {"action": 2, "issue": 1}
    assert all(type(number) is int for number in read(project)["id_counters"].values())


@pytest.mark.parametrize("counters", [
    {"action": -1, "issue": 0}, {"action": True, "issue": 1},
    {"action": 1.5, "issue": 1}, {"action": 1},
    {"action": 1, "issue": 1, "other": 1}, None,
])
def test_invalid_counters_cannot_be_edited_or_replaced(project, counters):
    reference = read(project)
    reference["id_counters"] = counters
    write(project, reference)
    before = reference_path(project).read_bytes()
    with pytest.raises(storage.ExpertReferenceValidationError):
        edit(project, "add_action")
    assert reference_path(project).read_bytes() == before


@pytest.mark.parametrize("kind", ["action", "issue"])
def test_numbering_and_default_removal_use_numeric_ids_not_list_or_lexical_order(project, kind):
    reference = read(project)
    items = records(reference, kind)
    later = deepcopy(items[0])
    later[f"{kind}_id"] = f"{kind}_10000"
    items.insert(0, later)
    items[1][f"{kind}_id"] = f"{kind}_9999"
    write(project, reference)

    assert edit(project, f"add_{kind}")[1] == f"{kind}_10001"
    assert edit(project, f"remove_{kind}")[1] == f"{kind}_10001"
    assert edit(project, f"remove_{kind}")[1] == f"{kind}_10000"
    assert records(read(project), kind)[0][f"{kind}_id"] == f"{kind}_9999"


@pytest.mark.parametrize("kind", ["action", "issue"])
def test_default_removal_skips_partially_edited_higher_id(project, kind):
    edit(project, f"add_{kind}")
    reference = read(project)
    edited = records(reference, kind)[1]
    edited["action" if kind == "action" else "issue_description"] = "An expert has started coding this record."
    write(project, reference)

    assert edit(project, f"remove_{kind}")[1] == f"{kind}_0001"
    assert records(read(project), kind) == [edited]
    before = reference_path(project).read_bytes()
    with pytest.raises(ValueError, match="untouched blank"):
        edit(project, f"remove_{kind}")
    assert reference_path(project).read_bytes() == before


@pytest.mark.parametrize("kind", ["action", "issue"])
def test_explicit_removal_can_select_an_edited_record(project, kind):
    reference = read(project)
    records(reference, kind)[0]["action" if kind == "action" else "issue_description"] = "Expert text."
    write(project, reference)
    assert edit(project, f"remove_{kind}", f"{kind}_0001")[1] == f"{kind}_0001"
    assert records(read(project), kind) == []


def test_action_removal_does_not_create_a_dangling_issue_link(project):
    reference = read(project)
    reference["plan_issues"]["issues"][0]["related_action_id"] = "action_0001"
    write(project, reference)
    before = reference_path(project).read_bytes()
    for record_id in (None, "action_0001"):
        with pytest.raises(ValueError, match="linked by issue_0001"):
            edit(project, "remove_action", record_id)
        assert reference_path(project).read_bytes() == before
    edit(project, "remove_issue", "issue_0001")
    edit(project, "remove_action", "action_0001")


@pytest.mark.parametrize("operation,record_id", [
    ("unknown", None), ("add_action", "action_0002"), ("remove_action", ""),
    ("remove_action", "missing"), ("remove_issue", "missing"),
])
def test_bad_edit_requests_preserve_the_original_bytes(project, operation, record_id):
    before = reference_path(project).read_bytes()
    with pytest.raises(ValueError):
        edit(project, operation, record_id)
    assert reference_path(project).read_bytes() == before


@pytest.mark.parametrize("damage", ["json", "duplicate_action", "duplicate_issue", "unknown_link", "page", "source"])
def test_invalid_existing_drafts_are_not_repaired_or_overwritten(project, damage):
    reference = read(project)
    if damage == "json":
        reference_path(project).write_text('{"unfinished":')
    else:
        if damage == "duplicate_action":
            reference["plan_data"]["actions"] *= 2
        elif damage == "duplicate_issue":
            reference["plan_issues"]["issues"] *= 2
        elif damage == "unknown_link":
            reference["plan_issues"]["issues"][0]["related_action_id"] = "missing"
        elif damage == "page":
            reference["plan_data"]["actions"][0]["evidence"] = [{"quote": "Fictional quote.", "page_numbers": [4]}]
        else:
            reference["plan_data"]["metadata"]["source_url"] = "https://example.org/other.pdf"
        write(project, reference)
    before = reference_path(project).read_bytes()
    with pytest.raises(storage.ExpertReferenceValidationError):
        edit(project, "add_action")
    assert reference_path(project).read_bytes() == before


def test_intervening_expert_edits_are_not_overwritten(project, monkeypatch):
    save = storage.save_expert_reference_edit
    intervening = read(project)
    intervening["prepared_by"].append("another_reviewer")

    def save_after_another_editor(root, plan_id, reference, *, expected_bytes):
        write(root, intervening)
        return save(root, plan_id, reference, expected_bytes=expected_bytes)

    monkeypatch.setattr(storage, "save_expert_reference_edit", save_after_another_editor)
    with pytest.raises(ValueError, match="changed while editing"):
        edit(project, "add_action")
    assert read(project) == intervening


def test_failed_atomic_replacement_preserves_reference_and_cleans_temporary_file(project, monkeypatch):
    before = reference_path(project).read_bytes()

    def fail_replace(*args):
        raise OSError("Fictional publication failure")

    monkeypatch.setattr(storage.os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication failure"):
        edit(project, "add_action")
    assert reference_path(project).read_bytes() == before
    assert list(reference_path(project).parent.iterdir()) == [reference_path(project)]


@pytest.mark.parametrize("redirect", ["file", "folder"])
def test_edits_reject_symbolic_link_redirection(project, redirect):
    path = reference_path(project)
    target = project / "other-reference"
    selected = path if redirect == "file" else path.parent
    selected.rename(target)
    selected.symlink_to(target, target_is_directory=redirect == "folder")
    original = target.read_bytes() if redirect == "file" else (target / path.name).read_bytes()
    with pytest.raises(ValueError, match="symbolic links"):
        edit(project, "add_action")
    assert (target.read_bytes() if redirect == "file" else (target / path.name).read_bytes()) == original


def test_guided_starter_is_editable_but_cannot_pass_completed_reference_checks(project, capsys):
    reference = read(project)
    assert validation.validate_expert_reference(reference, **context(), allow_templates=True) == []
    assert cli.main(["validate_expert_reference", "plan_0001", "--project-root", str(project)]) == 1
    output = capsys.readouterr()
    assert "Unfinished TODO guidance" in output.err
    assert "$.plan_data.actions[0].action" in output.err
    assert "$.plan_issues.issues[0].issue_description" in output.err
    assert reference == read(project)


def test_completed_reference_can_include_an_independent_expert_issue(project):
    reference = read(project)
    reference["plan_data"]["actions"][0].update(
        action="Fictional tree planting activity.", action_type=["nature-based"],
        action_location=None, action_recipient=None, action_cost=None, action_benefit=None,
        # A quotation can faithfully start with TODO without being form guidance.
        evidence=[{"quote": "TODO: Plant more street trees.", "page_numbers": [1]}],
    )
    reference["plan_issues"]["issues"][0].update(
        issue_description="The source leaves the implementation period unclear.",
        related_action_id="action_0001",
    )
    write(project, reference)
    assert expert_files.validate_expert_reference(project, "plan_0001") == reference
    reference["plan_issues"]["issues"][0].update(
        issue_status="resolved", resolved_by="expert", resolution="A source footnote states the period.",
    )
    assert validation.validate_expert_reference(reference, **context()) == []


@pytest.mark.parametrize("field,value", [
    ("issue_origin", "extractor"), ("issue_origin", "worker_1"),
    ("issue_status", "unknown"), ("resolved_by", "coordinator"),
    ("resolved_by", "expert"),
])
def test_expert_reference_issue_rules_remain_strict(project, field, value):
    reference = read(project)
    reference["plan_issues"]["issues"][0][field] = value
    assert validation.validate_expert_reference_structure(reference)


def test_legacy_reference_without_guidance_or_issues_remains_readable_and_editable(project):
    reference = read(project)
    reference.pop("instructions")
    reference.pop("plan_issues")
    reference["plan_data"]["actions"] = []
    write(project, reference)
    assert expert_files.validate_expert_reference(project, "plan_0001") == reference
    edit(project, "add_issue")
    assert read(project)["plan_issues"]["issues"][0]["issue_origin"] == "expert"


@pytest.mark.parametrize("flag,record_id", [
    ("--add-action", None), ("--add-issue", None),
    ("--remove-action", None), ("--remove-issue", None),
    ("--remove-action", "action_0001"), ("--remove-issue", "issue_0001"),
])
def test_edit_cli_selects_reference_and_operation(project, capsys, flag, record_id):
    args = ["edit_expert_reference", "--plan-id", "plan_0001", flag]
    if record_id:
        args.append(record_id)
    args.extend(["--project-root", str(project)])
    assert cli.main(args) == 0
    output = capsys.readouterr()
    assert "Expert reference: data/expert_references/plan_0001/expert_reference.json" in output.out
    expected_verb = "Added blank" if flag.startswith("--add") else "Removed"
    assert expected_verb in output.out
    assert output.err == ""


@pytest.mark.parametrize("args", [
    [], ["--add-action"], ["--plan-id", "plan_0001"],
    ["--plan-id", "plan_0001", "--add-action", "--add-issue"],
])
def test_cli_requires_one_plan_and_one_operation(args):
    with pytest.raises(SystemExit) as error:
        cli.main(["edit_expert_reference", *args])
    assert error.value.code == 2


def test_missing_reference_is_not_recreated_by_edit(project):
    reference_path(project).unlink()
    with pytest.raises(FileNotFoundError):
        edit(project, "add_action")
    assert not reference_path(project).exists()
