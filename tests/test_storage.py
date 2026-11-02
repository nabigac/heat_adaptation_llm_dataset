"""Exercise registry storage using isolated temporary project directories."""

import copy
from pathlib import Path

import pytest

import storage


@pytest.fixture
def registry() -> dict:
    """Return fictional metadata; no actual PDF or project registry is created here."""
    return {
        "schema_version": 1,
        "plans": [
            {
                "plan_id": "plan_0001",
                "plan_title": "Example City's Heat Plan — 2026",
                "pdf_path": "data/raw/plan_0001.pdf",
                "document_sha256": "a" * 64,
                "source_url": "https://example.org/heat-plan.pdf",
                "date_accessed": "2026-11-01",
                "study_set": "development",
                "prepared_source_path": None,
            }
        ],
    }


def test_saves_and_loads_registry_without_changing_values(
    tmp_path: Path, registry: dict
) -> None:
    # tmp_path acts as a project root; each test gets its own directory.
    before = copy.deepcopy(registry)

    storage.save_registry(tmp_path, registry)
    loaded = storage.load_registry(tmp_path)

    assert loaded == before
    assert registry == before


def test_explicit_save_can_initialize_an_empty_registry(tmp_path: Path) -> None:
    registry = {"schema_version": 1, "plans": []}

    storage.save_registry(tmp_path, registry)

    assert storage.load_registry(tmp_path) == registry


def test_missing_registry_is_not_silently_recreated(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        storage.load_registry(tmp_path)

    assert not (tmp_path / "data").exists()


def test_updates_collection_metadata(tmp_path: Path, registry: dict) -> None:
    storage.save_registry(tmp_path, registry)
    registry["plans"][0]["plan_title"] = "Corrected collection title"

    storage.save_registry(tmp_path, registry)

    assert storage.load_registry(tmp_path)["plans"][0]["plan_title"] == (
        "Corrected collection title"
    )


def test_invalid_update_preserves_existing_registry(tmp_path: Path, registry: dict) -> None:
    storage.save_registry(tmp_path, registry)
    registry_path = tmp_path / "data/registry/plans.json"
    original_bytes = registry_path.read_bytes()
    registry["plans"][0]["study_set"] = "pilot"

    with pytest.raises(storage.RegistryValidationError) as error:
        storage.save_registry(tmp_path, registry)

    assert error.value.problems[0].category == "structure"
    assert registry_path.read_bytes() == original_bytes


@pytest.mark.parametrize(
    ("text", "category"),
    [
        pytest.param('{"schema_version":', "syntax", id="broken-json"),
        pytest.param('{"schema_version": 2, "plans": []}', "structure", id="bad-version"),
        pytest.param(
            '{"schema_version": 1, "schema_version": 2, "plans": []}',
            "syntax",
            id="duplicate-key",
        ),
    ],
)
def test_damaged_registry_is_reported_and_preserved(
    tmp_path: Path, text: str, category: str
) -> None:
    registry_path = tmp_path / "data/registry/plans.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text(text, encoding="utf-8")

    with pytest.raises(storage.RegistryValidationError) as error:
        storage.load_registry(tmp_path)

    assert error.value.problems[0].category == category
    assert registry_path.read_text(encoding="utf-8") == text


def test_save_does_not_overwrite_a_damaged_registry(tmp_path: Path, registry: dict) -> None:
    registry_path = tmp_path / "data/registry/plans.json"
    registry_path.parent.mkdir(parents=True)
    registry_path.write_text("damaged registry", encoding="utf-8")

    with pytest.raises(storage.RegistryValidationError):
        storage.save_registry(tmp_path, registry)

    assert registry_path.read_text(encoding="utf-8") == "damaged registry"


@pytest.mark.parametrize("existing_registry", [False, True], ids=["initial-save", "update"])
def test_failed_replacement_does_not_publish_partial_data(
    tmp_path: Path,
    registry: dict,
    monkeypatch: pytest.MonkeyPatch,
    existing_registry: bool,
) -> None:
    registry_path = tmp_path / "data/registry/plans.json"
    if existing_registry:
        storage.save_registry(tmp_path, registry)
    original_bytes = registry_path.read_bytes() if existing_registry else None
    registry["plans"][0]["plan_title"] = "Incoming update"

    def fail_replace(source: Path, destination: Path) -> None:
        # The pending complete file must be beside the destination for replacement.
        assert Path(source).parent == Path(destination).parent
        raise OSError("Simulated failure before atomic replacement")

    # Temporarily make the OS replacement fail; pytest restores it afterward.
    monkeypatch.setattr(storage.os, "replace", fail_replace)

    with pytest.raises(OSError, match="Simulated failure"):
        storage.save_registry(tmp_path, registry)

    if existing_registry:
        assert registry_path.read_bytes() == original_bytes
    else:
        assert not registry_path.exists()
    assert list(registry_path.parent.glob(".plans-*.tmp")) == []


def test_failed_file_sync_preserves_existing_registry(
    tmp_path: Path, registry: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    storage.save_registry(tmp_path, registry)
    registry_path = tmp_path / "data/registry/plans.json"
    original_bytes = registry_path.read_bytes()

    def fail_sync(file_descriptor: int) -> None:
        raise OSError("Simulated file-sync failure")

    monkeypatch.setattr(storage.os, "fsync", fail_sync)

    with pytest.raises(OSError, match="Simulated file-sync failure"):
        storage.save_registry(tmp_path, registry)

    assert registry_path.read_bytes() == original_bytes
    assert list(registry_path.parent.glob(".plans-*.tmp")) == []


def test_first_plan_id_does_not_create_files(tmp_path: Path) -> None:
    registry = {"schema_version": 1, "plans": []}

    assert storage.next_plan_id(tmp_path, registry) == "plan_0001"
    assert list(tmp_path.iterdir()) == []


def test_plan_id_uses_highest_existing_number_without_filling_gaps(
    tmp_path: Path, registry: dict
) -> None:
    second_plan = copy.deepcopy(registry["plans"][0])
    second_plan["plan_id"] = "plan_0002"
    second_plan["pdf_path"] = "data/raw/plan_0002.pdf"
    second_plan["document_sha256"] = "b" * 64
    registry["plans"][0]["plan_id"] = "plan_0008"
    registry["plans"][0]["pdf_path"] = "data/raw/plan_0008.pdf"
    registry["plans"].append(second_plan)
    before = copy.deepcopy(registry)

    assert storage.next_plan_id(tmp_path, registry) == "plan_0009"
    assert registry == before


def test_plan_id_skips_a_pdf_missing_from_registry(tmp_path: Path) -> None:
    raw_directory = tmp_path / "data/raw"
    raw_directory.mkdir(parents=True)
    # Only the filename matters here. These bytes are not a usable research PDF.
    saved_pdf = raw_directory / "plan_0042.PDF"
    saved_pdf.write_bytes(b"placeholder for a previously saved file")

    plan_id = storage.next_plan_id(tmp_path, {"schema_version": 1, "plans": []})

    assert plan_id == "plan_0043"
    assert saved_pdf.read_bytes() == b"placeholder for a previously saved file"


def test_plan_id_can_grow_beyond_four_digits(tmp_path: Path, registry: dict) -> None:
    registry["plans"][0]["plan_id"] = "plan_9999"
    registry["plans"][0]["pdf_path"] = "data/raw/plan_9999.pdf"

    assert storage.next_plan_id(tmp_path, registry) == "plan_10000"


def test_other_string_ids_do_not_break_the_numbered_sequence(
    tmp_path: Path, registry: dict
) -> None:
    registry["plans"][0]["plan_id"] = "legacy-document"

    assert storage.next_plan_id(tmp_path, registry) == "plan_0001"


def test_plan_id_allocation_rejects_malformed_registry(tmp_path: Path) -> None:
    with pytest.raises(storage.RegistryValidationError):
        storage.next_plan_id(tmp_path, {"schema_version": 1, "plans": None})


@pytest.mark.parametrize("operation", ["load", "save", "allocate"])
def test_storage_paths_cannot_resolve_outside_the_project(
    tmp_path: Path, operation: str
) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "data").symlink_to(outside, target_is_directory=True)
    registry = {"schema_version": 1, "plans": []}

    with pytest.raises(ValueError, match="outside the project root"):
        if operation == "load":
            storage.load_registry(project)
        elif operation == "save":
            storage.save_registry(project, registry)
        else:
            storage.next_plan_id(project, registry)

    assert list(outside.iterdir()) == []
