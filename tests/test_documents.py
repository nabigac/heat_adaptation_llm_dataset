"""Check document identity, original preservation, and registration failures.

PDF-like byte fixtures test registration only. They do not demonstrate that page
preparation works or that any real plan meets the study's eligibility criteria.
"""

import copy
import hashlib
from pathlib import Path

import pytest

import documents
import storage


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
def incoming_pdf(tmp_path: Path) -> Path:
    path = tmp_path / "incoming.pdf"
    path.write_bytes(b"%PDF-1.4\nFictional registration fixture\n%%EOF\n")
    return path


@pytest.fixture
def metadata() -> dict:
    return {
        "plan_title": "Example Heat Plan — 2026",
        "source_url": "https://example.org/official-plan.pdf",
        "date_accessed": "2026-11-01",
        "study_set": "development",
    }


def test_registers_one_document_and_preserves_source_bytes(
    project: Path, incoming_pdf: Path, metadata: dict
) -> None:
    original_bytes = incoming_pdf.read_bytes()

    # **metadata supplies its dictionary entries as named function arguments.
    # The returned pair separates the plan record from the "new or duplicate" flag.
    entry, created = documents.register_document(project, incoming_pdf, **metadata)

    assert created is True
    assert entry == {
        "plan_id": "plan_0001",
        **metadata,
        "pdf_path": "data/raw/plan_0001.pdf",
        "document_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "prepared_source_path": None,
    }
    assert incoming_pdf.read_bytes() == original_bytes
    assert (project / entry["pdf_path"]).read_bytes() == original_bytes
    assert storage.load_registry(project) == {"schema_version": 1, "plans": [entry]}

    # The preserved copy has independent contents, rather than linking the input.
    incoming_pdf.write_bytes(b"an external edit after registration")
    assert (project / entry["pdf_path"]).read_bytes() == original_bytes


def test_renamed_copy_reuses_existing_record_without_editing_metadata(
    project: Path, incoming_pdf: Path, metadata: dict, tmp_path: Path
) -> None:
    original_entry, _ = documents.register_document(project, incoming_pdf, **metadata)
    registry_path = project / "data/registry/plans.json"
    registry_bytes = registry_path.read_bytes()
    renamed = tmp_path / "renamed-copy.PDF"
    renamed.write_bytes(incoming_pdf.read_bytes())
    metadata["plan_title"] = "A newly supplied title"

    entry, created = documents.register_document(project, renamed, **metadata)

    assert entry == original_entry
    assert created is False
    assert registry_path.read_bytes() == registry_bytes
    assert len(list((project / "data/raw").glob("*.pdf"))) == 1


def test_revised_bytes_receive_a_new_id_without_replacing_original(
    project: Path, incoming_pdf: Path, metadata: dict
) -> None:
    first, _ = documents.register_document(project, incoming_pdf, **metadata)
    original_bytes = (project / first["pdf_path"]).read_bytes()
    incoming_pdf.write_bytes(b"%PDF-1.4\nRevised fictional document\n%%EOF\n")

    revised, created = documents.register_document(project, incoming_pdf, **metadata)

    assert created is True
    assert revised["plan_id"] == "plan_0002"
    assert revised["document_sha256"] != first["document_sha256"]
    assert (project / first["pdf_path"]).read_bytes() == original_bytes
    assert len(storage.load_registry(project)["plans"]) == 2


def test_duplicate_import_cannot_move_a_document_into_comparison(
    project: Path, incoming_pdf: Path, metadata: dict
) -> None:
    documents.register_document(project, incoming_pdf, **metadata)
    registry_path = project / "data/registry/plans.json"
    before = registry_path.read_bytes()
    metadata["study_set"] = "comparison"

    with pytest.raises(ValueError, match="cannot change its study set"):
        documents.register_document(project, incoming_pdf, **metadata)

    assert registry_path.read_bytes() == before


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plan_title", "   "),
        ("plan_title", None),
        ("date_accessed", "2026-02-29"),
        ("study_set", "pilot"),
        ("source_url", "not-a-url"),
        ("source_url", "file:///local/plan.pdf"),
        ("source_url", "https://example.org/plan with space.pdf"),
        ("source_url", "https://example.org:bad/plan.pdf"),
    ],
)
def test_invalid_collection_details_do_not_create_research_files(
    project: Path, incoming_pdf: Path, metadata: dict, field: str, value: object
) -> None:
    metadata[field] = value

    with pytest.raises(ValueError):
        documents.register_document(project, incoming_pdf, **metadata)

    assert list(project.iterdir()) == []


@pytest.mark.parametrize("directory", ["data/raw", "data/processed", "runs"])
def test_missing_registry_with_saved_files_requires_explicit_recovery(
    project: Path, incoming_pdf: Path, metadata: dict, directory: str
) -> None:
    saved_directory = project / directory
    saved_directory.mkdir(parents=True)
    marker = saved_directory / "previous-work"
    marker.write_bytes(b"preserve this")

    with pytest.raises(FileNotFoundError, match="Restore the registry explicitly"):
        documents.register_document(project, incoming_pdf, **metadata)

    assert marker.read_bytes() == b"preserve this"
    assert not (project / "data/registry/plans.json").exists()


@pytest.mark.parametrize("damage", ["missing-pdf", "changed-pdf", "missing-preparation"])
def test_saved_inputs_must_be_restored_before_further_imports(
    project: Path, incoming_pdf: Path, metadata: dict, damage: str
) -> None:
    entry, _ = documents.register_document(project, incoming_pdf, **metadata)
    registry_path = project / "data/registry/plans.json"
    if damage == "missing-pdf":
        (project / entry["pdf_path"]).unlink()
    elif damage == "changed-pdf":
        (project / entry["pdf_path"]).write_bytes(b"damaged saved original")
    else:
        registry = storage.load_registry(project)
        registry["plans"][0]["prepared_source_path"] = "data/processed/missing/preparation.json"
        storage.save_registry(project, registry)
    before = registry_path.read_bytes()

    expected_message = {
        "missing-pdf": "registered original.*missing",
        "changed-pdf": "no longer matches its checksum",
        "missing-preparation": "saved preparation.*missing",
    }[damage]
    with pytest.raises((FileNotFoundError, ValueError), match=expected_message):
        documents.register_document(project, incoming_pdf, **metadata)

    assert registry_path.read_bytes() == before


@pytest.mark.parametrize("duplicate_field", ["plan_id", "document_sha256"])
def test_ambiguous_registry_identities_block_import(
    project: Path, incoming_pdf: Path, metadata: dict, duplicate_field: str
) -> None:
    documents.register_document(project, incoming_pdf, **metadata)
    registry = storage.load_registry(project)
    extra = copy.deepcopy(registry["plans"][0])
    extra["plan_id"] = "plan_0002"
    extra["document_sha256"] = "b" * 64
    extra[duplicate_field] = registry["plans"][0][duplicate_field]
    registry["plans"].append(extra)
    storage.save_registry(project, registry)

    with pytest.raises(ValueError, match="duplicate plan IDs or PDF checksums"):
        documents.register_document(project, incoming_pdf, **metadata)


def test_uppercase_saved_checksum_still_detects_duplicate(
    project: Path, incoming_pdf: Path, metadata: dict
) -> None:
    entry, _ = documents.register_document(project, incoming_pdf, **metadata)
    registry = storage.load_registry(project)
    registry["plans"][0]["document_sha256"] = entry["document_sha256"].upper()
    storage.save_registry(project, registry)

    duplicate, created = documents.register_document(project, incoming_pdf, **metadata)

    assert created is False
    assert duplicate["plan_id"] == entry["plan_id"]


def test_original_destination_is_never_overwritten(
    project: Path, incoming_pdf: Path, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry, _ = documents.register_document(project, incoming_pdf, **metadata)
    original = project / entry["pdf_path"]
    original_bytes = original.read_bytes()
    incoming_pdf.write_bytes(b"different PDF bytes")
    monkeypatch.setattr(storage, "next_plan_id", lambda *args: "plan_0001")

    with pytest.raises(FileExistsError):
        documents.register_document(project, incoming_pdf, **metadata)

    assert original.read_bytes() == original_bytes
    assert len(storage.load_registry(project)["plans"]) == 1
    assert list(original.parent.glob(".pdf-*.tmp")) == []


def test_copy_detects_source_changes_after_initial_fingerprinting(
    project: Path, incoming_pdf: Path, metadata: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    preserve = storage.preserve_original_pdf

    def change_then_copy(*args, **kwargs):
        incoming_pdf.write_bytes(b"source changed while registration was in progress")
        return preserve(*args, **kwargs)

    monkeypatch.setattr(storage, "preserve_original_pdf", change_then_copy)

    with pytest.raises(ValueError, match="differs from its expected checksum"):
        documents.register_document(project, incoming_pdf, **metadata)

    assert not (project / "data/registry/plans.json").exists()
    assert list((project / "data/raw").iterdir()) == []


@pytest.mark.parametrize("committed_before_error", [False, True], ids=["before-save", "after-save"])
def test_registry_save_failure_preserves_completed_pdf_and_reports_its_path(
    project: Path,
    incoming_pdf: Path,
    metadata: dict,
    monkeypatch: pytest.MonkeyPatch,
    committed_before_error: bool,
) -> None:
    save = storage.save_registry

    def fail_save(root: Path, registry: dict) -> None:
        if committed_before_error:
            save(root, registry)
        raise OSError("Simulated registry-save failure")

    monkeypatch.setattr(storage, "save_registry", fail_save)

    with pytest.raises(OSError, match="Simulated registry-save failure") as error:
        documents.register_document(project, incoming_pdf, **metadata)

    assert (project / "data/raw/plan_0001.pdf").read_bytes() == incoming_pdf.read_bytes()
    assert "data/raw/plan_0001.pdf" in error.value.__notes__[0]
    if committed_before_error:
        assert len(storage.load_registry(project)["plans"]) == 1
        # A retry recognizes the committed document and does not attempt another save.
        entry, created = documents.register_document(project, incoming_pdf, **metadata)
        assert entry["plan_id"] == "plan_0001"
        assert created is False
    else:
        assert not (project / "data/registry/plans.json").exists()


@pytest.mark.parametrize(
    "unsafe_path", ["/tmp/outside.pdf", "../outside.pdf", "C:/outside.pdf", "data\\raw\\x.pdf"]
)
def test_registry_pdf_paths_must_be_project_relative(
    project: Path, incoming_pdf: Path, metadata: dict, unsafe_path: str
) -> None:
    documents.register_document(project, incoming_pdf, **metadata)
    registry = storage.load_registry(project)
    registry["plans"][0]["pdf_path"] = unsafe_path
    storage.save_registry(project, registry)

    with pytest.raises(ValueError, match="project-relative path"):
        documents.register_document(project, incoming_pdf, **metadata)
