"""Check metadata edits and preparation status through the real file workflow.

All documents live in temporary projects. The tests protect saved input snapshots
and distinguish a preparation's recorded status from whether its files validate.
"""

import json
from pathlib import Path

import pytest
from pypdf import PageObject, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

import cli
import documents
import storage


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


def register_plan(project: Path, tmp_path: Path, *, kind="blank", study_set="development") -> dict:
    """Use a blank, drawn, or malformed PDF to obtain known preparation outcomes."""
    source = tmp_path / "incoming.pdf"
    if kind == "malformed":
        source.write_bytes(b"%PDF-1.4\nFictional unreadable PDF\n%%EOF\n")
    else:
        with PdfWriter() as writer:
            page = writer.add_blank_page(width=300, height=300)
            if kind == "drawing":
                contents = DecodedStreamObject()
                contents.set_data(b"20 20 60 40 re f")
                page[NameObject("/Contents")] = writer._add_object(contents)
            writer.write(source)
    return documents.register_document(
        project, source, plan_title="Example Heat Plan",
        source_url="https://example.org/plan.pdf", date_accessed="2026-11-01",
        study_set=study_set,
    )[0]


def file_snapshot(root: Path) -> dict[str, bytes]:
    """Include JSON, originals, and PNGs, so unintended writes are observable."""
    return {str(path.relative_to(root)): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


@pytest.mark.parametrize(("kind", "expected_status"), [
    (None, "not_prepared"), ("blank", "ready"),
    ("drawing", "ready_with_gaps"), ("malformed", "failed"),
])
def test_list_displays_the_saved_status_without_changing_files(
    project, tmp_path, capsys, kind, expected_status,
):
    entry = register_plan(project, tmp_path, kind=kind or "blank")
    record_path = None
    if kind is not None:
        _, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    before = file_snapshot(project)

    rows = documents.list_documents(project)
    assert rows[0]["preparation_status"] == expected_status
    assert cli.main(["list", "--project-root", str(project)]) == 0
    output = capsys.readouterr()

    assert expected_status in output.out
    assert "Example Heat Plan" in output.out
    if record_path is not None:
        assert f"Preparation: {record_path}" in output.out
    assert output.err == ""
    assert file_snapshot(project) == before
    assert "preparation_status" not in storage.load_registry(project)["plans"][0]


def test_list_uses_the_registry_link_rather_than_the_newest_attempt(
    project, tmp_path, monkeypatch, capsys,
):
    entry = register_plan(project, tmp_path)
    _, first_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    monkeypatch.setattr(PageObject, "extract_text", lambda *args, **kwargs: None)
    second, second_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    assert second["status"] == "ready_with_gaps"
    registry = storage.load_registry(project)
    registry["plans"][0]["prepared_source_path"] = first_path
    storage.save_registry(project, registry)

    assert cli.main(["list", "--project-root", str(project)]) == 0
    output = capsys.readouterr().out
    assert "ready_with_gaps" not in output
    assert "ready" in output and first_path in output
    assert second_path not in output


@pytest.mark.parametrize("damage", ["json", "identity", "missing-image"])
def test_list_reports_damaged_linked_inputs_instead_of_inventing_readiness(
    project, tmp_path, capsys, damage,
):
    entry = register_plan(project, tmp_path, kind="drawing")
    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    if damage == "json":
        (project / record_path).write_text("{broken", encoding="utf-8")
    elif damage == "identity":
        preparation["document_sha256"] = "b" * 64
        (project / record_path).write_text(json.dumps(preparation), encoding="utf-8")
    else:
        _, pages = storage.load_preparation(project, record_path)
        (project / pages[0]["image_path"]).unlink()
    before = file_snapshot(project)

    assert cli.main(["list", "--project-root", str(project)]) == 1
    output = capsys.readouterr()
    assert output.out == "" and output.err
    assert "Traceback" not in output.err
    assert file_snapshot(project) == before


def test_partial_metadata_update_keeps_identity_other_fields_and_saved_work(project, tmp_path):
    entry = register_plan(project, tmp_path, kind="drawing")
    _, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    before = file_snapshot(project)

    updated, changed = documents.update_document_metadata(
        project, entry["plan_id"], plan_title="Corrected Heat Plan — 2026",
    )

    assert changed is True
    expected = dict(storage.load_registry(project)["plans"][0])
    assert updated == expected
    assert updated["plan_title"] == "Corrected Heat Plan — 2026"
    for field in ("plan_id", "source_url", "date_accessed", "study_set", "pdf_path", "document_sha256"):
        assert updated[field] == entry[field]
    assert updated["prepared_source_path"] == record_path
    after = file_snapshot(project)
    assert {path: data for path, data in after.items() if path != "data/registry/plans.json"} == {
        path: data for path, data in before.items() if path != "data/registry/plans.json"
    }


def test_collection_corrections_affect_new_preparations_without_rewriting_earlier_ones(project, tmp_path):
    entry = register_plan(project, tmp_path)
    first, first_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    before = file_snapshot((project / first_path).parent)
    updated, changed = documents.update_document_metadata(
        project, entry["plan_id"], plan_title="Corrected title",
        source_url="https://example.org/corrected.pdf", date_accessed="2026-11-02",
    )
    assert changed is True
    # Earlier collection details remain a historical snapshot. Different URL or
    # access-date values must not be mistaken for a different original PDF.
    assert storage.load_preparation(project, first_path)[0] == first
    assert file_snapshot((project / first_path).parent) == before
    second, _ = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    assert second["source_url"] == updated["source_url"]
    assert second["date_accessed"] == updated["date_accessed"]
    assert second["document_sha256"] == first["document_sha256"]
    assert documents.list_documents(project)[0]["preparation_status"] == "ready"


def test_same_value_update_does_not_replace_the_registry(project, tmp_path, monkeypatch):
    entry = register_plan(project, tmp_path)
    before = file_snapshot(project)

    def unexpected_save(*args, **kwargs):
        raise AssertionError("Same-value updates must not write files.")

    monkeypatch.setattr(storage, "save_registry", unexpected_save)
    updated, changed = documents.update_document_metadata(
        project, entry["plan_id"], plan_title=entry["plan_title"],
    )
    assert updated == entry and changed is False
    assert file_snapshot(project) == before


@pytest.mark.parametrize("changes", [
    {"plan_title": "   "}, {"plan_title": ""}, {"plan_title": 42},
    {"source_url": "not-a-url"}, {"source_url": "file:///plan.pdf"},
    {"source_url": "https://example.org/a b.pdf"},
    {"date_accessed": "2026-02-29"}, {"study_set": "pilot"},
    {"plan_title": "Valid correction", "source_url": "bad-url"},
])
def test_invalid_updates_save_none_of_the_proposed_changes(project, tmp_path, changes):
    entry = register_plan(project, tmp_path)
    before = file_snapshot(project)
    with pytest.raises(ValueError):
        documents.update_document_metadata(project, entry["plan_id"], **changes)
    assert file_snapshot(project) == before


def test_unknown_plan_and_empty_update_do_not_write_files(project, tmp_path):
    register_plan(project, tmp_path)
    before = file_snapshot(project)
    with pytest.raises(ValueError, match="No registered document"):
        documents.update_document_metadata(project, "plan_9999", plan_title="Corrected title")
    with pytest.raises(ValueError, match="at least one"):
        documents.update_document_metadata(project, "plan_0001")
    assert file_snapshot(project) == before


@pytest.mark.parametrize("target", ["comparison", "expansion"])
def test_development_assignment_cannot_be_relabelled(project, tmp_path, target):
    entry = register_plan(project, tmp_path)
    before = file_snapshot(project)
    with pytest.raises(ValueError, match="Development plans must remain"):
        documents.update_document_metadata(project, entry["plan_id"], study_set=target)
    assert file_snapshot(project) == before


@pytest.mark.parametrize(("initial", "target"), [
    ("expansion", "comparison"), ("comparison", "expansion"), ("expansion", "development"),
])
def test_study_set_can_be_corrected_before_model_work(project, tmp_path, initial, target):
    entry = register_plan(project, tmp_path, study_set=initial)
    updated, changed = documents.update_document_metadata(project, entry["plan_id"], study_set=target)
    assert changed is True and updated["study_set"] == target


def test_saved_model_work_keeps_its_bytes_and_prevents_study_set_changes(project, tmp_path):
    entry = register_plan(project, tmp_path, study_set="expansion")
    run = project / "runs/plan_0001/run_extract_0001/output.json"
    run.parent.mkdir(parents=True)
    run.write_text('{"fixture": "retained model work"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="after model work"):
        documents.update_document_metadata(project, entry["plan_id"], study_set="comparison")
    updated, changed = documents.update_document_metadata(project, entry["plan_id"], plan_title="New title")
    assert changed is True and updated["plan_title"] == "New title"
    assert run.read_text(encoding="utf-8") == '{"fixture": "retained model work"}\n'


def test_cli_updates_multiple_fields_and_reports_same_value_updates(project, tmp_path, capsys):
    entry = register_plan(project, tmp_path)
    arguments = ["update", entry["plan_id"], "--project-root", str(project),
                 "--title", "Corrected title", "--source-url", "https://example.org/new.pdf",
                 "--date-accessed", "2026-11-02"]
    assert cli.main(arguments) == 0
    output = capsys.readouterr()
    assert "Updated collection metadata for plan_0001" in output.out
    assert "Title: Corrected title" in output.out
    assert "Source URL: https://example.org/new.pdf" in output.out
    assert "Access date: 2026-11-02" in output.out
    assert output.err == ""
    assert cli.main(arguments) == 0
    assert "No metadata changes" in capsys.readouterr().out


@pytest.mark.parametrize("arguments", [
    ["update", "plan_0001"], ["update"],
    ["update", "plan_0001", "--pdf-path", "elsewhere.pdf"],
    ["update", "plan_0001", "--study-set", "pilot"],
])
def test_cli_rejects_missing_changes_and_uneditable_fields(project, tmp_path, arguments):
    register_plan(project, tmp_path)
    before = file_snapshot(project)
    with pytest.raises(SystemExit) as caught:
        cli.main(arguments + ["--project-root", str(project)])
    assert caught.value.code == 2
    assert file_snapshot(project) == before


def test_cli_reports_invalid_metadata_without_writing(project, tmp_path, capsys):
    register_plan(project, tmp_path)
    before = file_snapshot(project)
    assert cli.main(["update", "plan_0001", "--date-accessed", "2026-02-29",
                     "--project-root", str(project)]) == 1
    output = capsys.readouterr()
    assert "validation failed" in output.err and "Traceback" not in output.err
    assert output.out == ""
    assert file_snapshot(project) == before


@pytest.mark.parametrize("committed", [False, True])
def test_update_save_failure_retains_registry_outcome_and_reports_recovery(
    project, tmp_path, monkeypatch, capsys, committed,
):
    entry = register_plan(project, tmp_path)
    save = storage.save_registry

    def fail_save(root, registry):
        if committed:
            save(root, registry)
        raise OSError("Simulated metadata-save failure")

    monkeypatch.setattr(storage, "save_registry", fail_save)
    assert cli.main(["update", entry["plan_id"], "--title", "Corrected title",
                     "--project-root", str(project)]) == 1
    output = capsys.readouterr()
    assert "Inspect data/registry/plans.json" in output.err
    assert output.out == ""
    saved = storage.load_registry(project)["plans"][0]
    assert saved["plan_title"] == ("Corrected title" if committed else entry["plan_title"])


def test_update_help_lists_editable_fields(capsys):
    with pytest.raises(SystemExit) as caught:
        cli.main(["update", "--help"])
    assert caught.value.code == 0
    output = capsys.readouterr().out
    for flag in ("--title", "--source-url", "--date-accessed", "--study-set", "--project-root"):
        assert flag in output
