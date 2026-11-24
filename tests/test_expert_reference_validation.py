"""Check source-bound expert forms without altering references or model evidence."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfWriter

import cli
import documents
import expert_files
import storage
from validation import parse_expert_reference_json, validate_expert_reference


def _reference_path(root: Path) -> Path:
    return root / "expert_references/plan_0001/expert_reference.json"


def _read_reference(root: Path) -> dict:
    return json.loads(_reference_path(root).read_text(encoding="utf-8"))


def _write_reference(root: Path, reference: dict) -> None:
    _reference_path(root).write_text(
        json.dumps(reference, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*") if path.is_file()
    }


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "reference study"
    root.mkdir()
    pdf = tmp_path / "incoming.pdf"
    with PdfWriter() as writer:
        # Wide pages represent physical spreads. Page bounds count these three
        # PDF objects, regardless of how many printed sides each spread depicts.
        for _ in range(3):
            writer.add_blank_page(width=600, height=300)
        writer.write(pdf)
    documents.register_document(
        root, pdf, plan_title="Fictional plan", source_url="https://example.org/plan.pdf",
        date_accessed="2026-11-21", study_set="comparison",
    )
    expert_files.create_expert_reference(root, "plan_0001", prepared_by=["reviewer_01"])
    reference = _read_reference(root)
    reference["plan_data"]["actions"] = [{
        "action_id": "action_0001",
        "action": "Fictional tree planting activity.",
        "action_type": ["nature-based"],
        "action_status": "unspecified",
        "action_location": None,
        "action_recipient": None,
        "action_cost": None,
        "action_benefit": None,
        "evidence": [{"quote": "Fictional quotation for structural checks.", "page_numbers": [3]}],
    }]
    reference["plan_issues"]["issues"] = []
    # The PDF is deliberately blank: passing these tests establishes file/link
    # consistency, never quotation fidelity or source support.
    _write_reference(root, reference)
    return root


def _context() -> dict:
    return {
        "plan_id": "plan_0001", "source_url": "https://example.org/plan.pdf",
        "date_accessed": "2026-11-21", "page_count": 3,
    }


@pytest.mark.parametrize("missing_field", [None, "evidence", "action_type"])
def test_absent_and_empty_issue_containers_apply_identical_checks(project, missing_field):
    reference = _read_reference(project)
    if missing_field:
        reference["plan_data"]["actions"][0][missing_field] = []
    before = copy.deepcopy(reference)
    with_container = validate_expert_reference(reference, **_context())
    reference.pop("plan_issues")
    without_container = validate_expert_reference(reference, **_context())
    assert without_container == with_container
    assert bool(without_container) == bool(missing_field)
    assert reference == {key: value for key, value in before.items() if key != "plan_issues"}


@pytest.mark.parametrize("missing_field", ["evidence", "action_type"])
def test_linked_expert_issue_explains_missing_type_or_evidence(project, missing_field):
    from expert_templates import blank_issue
    reference = _read_reference(project)
    reference["plan_data"]["actions"][0][missing_field] = []
    issue = blank_issue("issue_0001")
    issue.update(related_action_id="action_0001", issue_description="Source details remain unclear.")
    reference["plan_issues"]["issues"] = [issue]
    assert validate_expert_reference(reference, **_context()) == []


def test_valid_reference_uses_original_pdf_without_preparation_or_model_access(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    model_output = project / "runs/plan_0001/run_extract_0001/output.json"
    model_output.parent.mkdir(parents=True)
    model_output.write_text("Invalid model output must not be read.")
    before = _snapshot(project)

    reference = expert_files.validate_expert_reference(project, "plan_0001")

    assert reference == _read_reference(project)
    assert len(reference["plan_data"]["actions"]) == 1
    assert storage.load_registry(project)["plans"][0]["prepared_source_path"] is None
    assert _snapshot(project) == before


@pytest.mark.parametrize("field,value,location", [
    ("plan_id", "plan_0002", "$.plan_id"),
    ("source_url", "https://example.org/other.pdf", "$.plan_data.metadata.source_url"),
    ("date_accessed", "2026-11-20", "$.plan_data.metadata.date_accessed"),
])
def test_reference_must_match_selected_registration(
    project: Path, field: str, value: str, location: str,
) -> None:
    reference = _read_reference(project)
    target = reference if field == "plan_id" else reference["plan_data"]["metadata"]
    target[field] = value
    _write_reference(project, reference)
    before = _snapshot(project)

    with pytest.raises(storage.ExpertReferenceValidationError) as error:
        expert_files.validate_expert_reference(project, "plan_0001")

    assert [(p.category, p.location) for p in error.value.problems] == [("reference", location)]
    assert _snapshot(project) == before


def test_expert_coded_metadata_can_differ_from_collected_title(project: Path) -> None:
    reference = _read_reference(project)
    reference["plan_data"]["metadata"].update({
        "plan_title": "Title transcribed by the expert", "jurisdiction_name": "Example City",
    })
    _write_reference(project, reference)

    assert expert_files.validate_expert_reference(project, "plan_0001") == reference


def test_duplicate_action_ids_and_out_of_range_pages_are_both_reported(project: Path) -> None:
    reference = _read_reference(project)
    duplicate = copy.deepcopy(reference["plan_data"]["actions"][0])
    duplicate["action"] = "A different fictional activity with a reused ID."
    duplicate["evidence"][0]["page_numbers"] = [4]
    reference["plan_data"]["actions"].append(duplicate)
    before = copy.deepcopy(reference)

    problems = validate_expert_reference(reference, **_context())

    assert {p.location for p in problems} == {
        "$.plan_data.actions[1].action_id",
        "$.plan_data.actions[1].evidence[0].page_numbers[0]",
    }
    assert all(p.category == "reference" for p in problems)
    assert reference == before


def test_page_bounds_count_physical_spreads_not_printed_sides(project: Path) -> None:
    reference = _read_reference(project)
    reference["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [6]
    _write_reference(project, reference)

    with pytest.raises(storage.ExpertReferenceValidationError, match="range 1 to 3"):
        expert_files.validate_expert_reference(project, "plan_0001")


@pytest.mark.parametrize("problem", [
    "missing_field", "invalid_status", "blank_reviewer", "invalid_date", "unknown_field", "repeated_page",
])
def test_shared_schema_rules_are_retained(project: Path, problem: str) -> None:
    reference = _read_reference(project)
    if problem == "missing_field":
        del reference["plan_data"]["actions"][0]["action_benefit"]
    elif problem == "invalid_status":
        reference["plan_data"]["actions"][0]["action_status"] = "probably completed"
    elif problem == "blank_reviewer":
        reference["prepared_by"] = [" "]
    elif problem == "invalid_date":
        reference["plan_data"]["metadata"]["date_accessed"] = "2026-02-29"
    elif problem == "unknown_field":
        reference["assessment"] = {}
    else:
        reference["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [1, 1]

    assert any(p.category == "structure" for p in validate_expert_reference(reference, **_context()))


@pytest.mark.parametrize("page_count", [0, None, True, 3.5])
def test_missing_or_invalid_source_count_cannot_skip_checks(project: Path, page_count: object) -> None:
    context = _context()
    context["page_count"] = page_count
    problems = validate_expert_reference(_read_reference(project), **context)
    assert any(p.location == "page_count" for p in problems)


@pytest.mark.parametrize("problem", ["duplicate_key", "trailing_comma", "code_fence", "NaN", "nested"])
def test_parser_reports_invalid_reference_json(project: Path, problem: str) -> None:
    text = _reference_path(project).read_text()
    if problem == "duplicate_key":
        text = text.replace('"schema_version": 1', '"schema_version": 1, "schema_version": 1')
    elif problem == "trailing_comma":
        text = text.rstrip()[:-1] + ",}"
    elif problem == "code_fence":
        text = "```json\n" + text + "```"
    elif problem == "NaN":
        text = text.replace('"publication_year": null', '"publication_year": NaN')
    else:
        depth = sys.getrecursionlimit() + 100
        text = "[" * depth + "]" * depth

    reference, problems = parse_expert_reference_json(text, **_context())

    assert reference is None
    # Nesting limits vary across Python decoders. A decoded list must still fail
    # the reference-object schema; either rejection path is a readable problem.
    categories = {"syntax", "structure"} if problem == "nested" else {"syntax"}
    assert problems and all(p.category in categories for p in problems)


def test_validation_does_not_repair_or_replace_malformed_json(project: Path) -> None:
    _reference_path(project).write_bytes(b'{"unfinished":')
    before = _snapshot(project)

    with pytest.raises(storage.ExpertReferenceValidationError):
        expert_files.validate_expert_reference(project, "plan_0001")

    assert _snapshot(project) == before


@pytest.mark.parametrize("missing", ["reference", "original"])
def test_missing_required_files_are_not_recreated(project: Path, missing: str) -> None:
    path = _reference_path(project) if missing == "reference" else project / "data/raw/plan_0001.pdf"
    path.unlink()
    before = _snapshot(project)

    with pytest.raises(FileNotFoundError):
        expert_files.validate_expert_reference(project, "plan_0001")

    assert _snapshot(project) == before
    assert not path.exists()


def test_unknown_plan_cannot_validate_another_plans_form(project: Path) -> None:
    before = _snapshot(project)
    with pytest.raises(ValueError, match="registered plan ID"):
        expert_files.validate_expert_reference(project, "plan_0002")
    assert _snapshot(project) == before


def test_changed_registered_original_is_rejected(project: Path) -> None:
    (project / "data/raw/plan_0001.pdf").write_bytes(b"changed original")
    before = _snapshot(project)
    with pytest.raises(ValueError, match="checksum"):
        expert_files.validate_expert_reference(project, "plan_0001")
    assert _snapshot(project) == before


def test_change_between_registration_check_and_count_is_rejected(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered_plan = expert_files._registered_plan

    def change_after_check(root: Path, plan_id: str) -> dict:
        entry = registered_plan(root, plan_id)
        (root / entry["pdf_path"]).write_bytes(b"changed just before counting")
        return entry

    monkeypatch.setattr(expert_files, "_registered_plan", change_after_check)
    with pytest.raises(ValueError, match="changed before reference validation"):
        expert_files.validate_expert_reference(project, "plan_0001")


@pytest.mark.parametrize("kind", ["invalid", "empty", "encrypted"])
def test_uncountable_original_cannot_pass_reference_checks(tmp_path: Path, kind: str) -> None:
    root = tmp_path / "project"
    root.mkdir()
    pdf = tmp_path / "incoming.pdf"
    if kind == "invalid":
        pdf.write_bytes(b"%PDF-1.4\nNot a countable PDF\n%%EOF\n")
    else:
        with PdfWriter() as writer:
            if kind == "encrypted":
                writer.add_blank_page(width=300, height=300)
                writer.encrypt("fictional-password")
            writer.write(pdf)
    documents.register_document(
        root, pdf, plan_title="Fictional plan", source_url="https://example.org/plan.pdf",
        date_accessed="2026-11-21", study_set="development",
    )
    expert_files.create_expert_reference(root, "plan_0001", prepared_by=["reviewer"])
    before = _snapshot(root)

    with pytest.raises(ValueError, match="Could not count physical pages"):
        expert_files.validate_expert_reference(root, "plan_0001")

    assert _snapshot(root) == before


@pytest.mark.parametrize("outside", [False, True])
def test_reference_cannot_redirect_to_another_file(
    project: Path, tmp_path: Path, outside: bool,
) -> None:
    path = _reference_path(project)
    target = tmp_path / "other.json" if outside else project / "other.json"
    path.rename(target)
    path.symlink_to(target)
    before = _snapshot(project)

    with pytest.raises(ValueError):
        expert_files.validate_expert_reference(project, "plan_0001")

    assert _snapshot(project) == before
    assert path.is_symlink()


def test_cli_reports_success_without_claiming_factual_accuracy(
    project: Path, capsys: pytest.CaptureFixture,
) -> None:
    before = _snapshot(project)
    assert cli.main(["validate_expert_reference", "plan_0001", "--project-root", str(project)]) == 0
    output = capsys.readouterr()
    assert "Expert reference validation passed for plan_0001" in output.out
    assert "Actions: 1" in output.out
    assert "Experts still assess accuracy and completeness" in output.out
    assert output.err == ""
    assert _snapshot(project) == before


def test_cli_identifies_an_empty_starter_form(project: Path, capsys: pytest.CaptureFixture) -> None:
    reference = _read_reference(project)
    reference["plan_data"]["actions"] = []
    _write_reference(project, reference)

    assert cli.main(["validate_expert_reference", "plan_0001", "--project-root", str(project)]) == 0
    assert "Actions are empty; the form still needs expert completion" in capsys.readouterr().out


def test_cli_displays_problem_locations_and_nonzero_exit(
    project: Path, capsys: pytest.CaptureFixture,
) -> None:
    reference = _read_reference(project)
    reference["plan_data"]["actions"][0]["evidence"][0]["page_numbers"] = [4]
    _write_reference(project, reference)
    before = _snapshot(project)

    assert cli.main(["validate_expert_reference", "plan_0001", "--project-root", str(project)]) == 1
    output = capsys.readouterr()
    assert "Expert reference validation failed" in output.err
    assert "[reference] $.plan_data.actions[0].evidence[0].page_numbers[0]" in output.err
    assert "range 1 to 3" in output.err
    assert output.out == ""
    assert _snapshot(project) == before


def test_cli_defaults_to_current_project(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(project)
    assert cli.main(["validate_expert_reference", "plan_0001"]) == 0


def test_cli_requires_plan_id() -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["validate_expert_reference"])
    assert error.value.code == 2


def test_real_cli_subprocess_reads_reference_without_api_token(
    project: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HF_TOKEN", raising=False)
    script = Path(cli.__file__).resolve()
    before = _snapshot(project)
    result = subprocess.run(
        [sys.executable, str(script), "validate_expert_reference", "plan_0001",
         "--project-root", str(project)],
        capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0
    assert "Actions: 1" in result.stdout
    assert result.stderr == ""
    assert _snapshot(project) == before
