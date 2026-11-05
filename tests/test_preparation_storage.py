"""Check preparation storage in isolated temporary projects.

These tests save fictional JSON data, not research PDFs. Besides ordinary saves,
they exercise damaged inputs and interrupted writes to check preservation rules.
"""
# The preparation pair is tested independently of registration. These functions
# validate and preserve page JSON/images; checking the registered original PDF
# identity belongs to documents.py and the run-loading workflow.

import copy
import json
from pathlib import Path

import pytest

import storage


@pytest.fixture
def preparation() -> dict:
    """Give each test a fresh record pointing to its first preparation folder."""
    # Keep a version-2 fixture to exercise backward readability. Its older page
    # format has no preserved image_path/image_regions fields; newer image behavior
    # is covered by the version-3 candidate-region tests.
    return {
        "schema_version": 2,
        "plan_id": "plan_0001",
        "pdf_path": "data/raw/plan_0001.pdf",
        "document_sha256": "a" * 64,
        "source_url": "https://example.org/heat-plan.pdf",
        "date_accessed": "2026-11-02",
        "prepared_at": "2026-11-02T10:30:00Z",
        "pages_path": "data/processed/plan_0001/preparation_01/pages.json",
        "page_count": 3,
        "settings": {
            "ocr_enabled": False,
            "ocr_engine": None,
            "ocr_version": None,
            "ocr_language": None,
            "image_render_dpi": 150,
        },
        "status": "ready",
        "problem": None,
    }


@pytest.fixture
def pages() -> list[dict]:
    return [
        {
            "page_number": 1,
            "text": 'Heat, "Adaptation" — Example City\nOpen cooling spaces.',
            "text_source": "native",
            "readable": True,
            "image_available": True,
            "problem": None,
        },
        {
            "page_number": 2,
            "text": "",  # Keep a known blank page in the saved sequence.
            "text_source": "native",
            "readable": True,
            "image_available": True,
            "problem": None,
        },
        {
            "page_number": 3,
            "text": "Plant trees around schools.",
            "text_source": "native",
            "readable": True,
            "image_available": True,
            "problem": None,
        },
    ]


def test_first_preparation_suggestion_does_not_create_files(tmp_path: Path) -> None:
    directory = storage.next_preparation_directory(tmp_path, "plan_0001")

    assert directory == "data/processed/plan_0001/preparation_01"
    assert list(tmp_path.iterdir()) == []


def test_suggestion_skips_existing_numbers_and_incomplete_attempts(tmp_path: Path) -> None:
    parent = tmp_path / "data/processed/plan_0001"
    (parent / "preparation_01").mkdir(parents=True)
    (parent / "preparation_03").mkdir()
    # An unexpected file also occupies a numbered name. Do not reuse it.
    occupied_file = parent / "preparation_05"
    occupied_file.write_text("retain this file", encoding="utf-8")
    (parent / "notes").mkdir()

    assert storage.next_preparation_directory(tmp_path, "plan_0001") == (
        "data/processed/plan_0001/preparation_06"
    )
    assert occupied_file.read_text(encoding="utf-8") == "retain this file"


def test_preparation_numbering_is_separate_for_each_plan(tmp_path: Path) -> None:
    (tmp_path / "data/processed/plan_0001/preparation_07").mkdir(parents=True)

    assert storage.next_preparation_directory(tmp_path, "plan_0002") == (
        "data/processed/plan_0002/preparation_01"
    )
    assert not (tmp_path / "data/processed/plan_0002").exists()


def test_preparation_numbering_can_grow_beyond_two_digits(tmp_path: Path) -> None:
    (tmp_path / "data/processed/plan_0001/preparation_99").mkdir(parents=True)

    assert storage.next_preparation_directory(tmp_path, "plan_0001") == (
        "data/processed/plan_0001/preparation_100"
    )


@pytest.mark.parametrize("plan_id", ["../plan_0001", "plan_0001/other", "legacy-plan"])
def test_suggestion_rejects_ids_that_cannot_name_generated_folders(
    tmp_path: Path, plan_id: str
) -> None:
    with pytest.raises(ValueError, match="generated plan_<number>"):
        storage.next_preparation_directory(tmp_path, plan_id)
    assert list(tmp_path.iterdir()) == []


def test_saves_and_loads_pair_without_changing_supplied_values(
    tmp_path: Path, preparation: dict, pages: list[dict]
) -> None:
    preparation.update(status="ready_with_gaps", problem="Page 3 needs the tested image route.")
    pages[2].update(text=None, text_source=None, problem="Native text unavailable; use page image.")
    before = copy.deepcopy((preparation, pages))

    record_path = storage.save_preparation(tmp_path, preparation, pages)
    loaded = storage.load_preparation(tmp_path, record_path)

    assert record_path == "data/processed/plan_0001/preparation_01/preparation.json"
    assert loaded == before
    assert (preparation, pages) == before
    # UTF-8 storage keeps Unicode readable while preserving quotes and newlines
    # when JSON is decoded. Null and known blank text remain distinct values.
    saved_pages = (tmp_path / preparation["pages_path"]).read_text(encoding="utf-8")
    assert "—" in saved_pages
    assert json.loads(saved_pages)[1]["text"] == ""
    assert json.loads(saved_pages)[2]["text"] is None
    assert not (tmp_path / "data/registry").exists()
    assert not (tmp_path / "data/raw").exists()


@pytest.mark.parametrize("known_count", [False, True], ids=["unknown-count", "known-count"])
def test_preserves_failed_preparation_attempts(
    tmp_path: Path, preparation: dict, pages: list[dict], known_count: bool
) -> None:
    preparation.update(status="failed", problem="No usable reading route.")
    if known_count:
        for page in pages:
            page.update(text=None, text_source=None, readable=False, image_available=False, problem="Unreadable.")
    else:
        preparation["page_count"] = None
        pages = []

    record_path = storage.save_preparation(tmp_path, preparation, pages)

    assert storage.load_preparation(tmp_path, record_path) == (preparation, pages)


def test_new_attempt_keeps_previous_files_and_registry_unchanged(
    tmp_path: Path, preparation: dict, pages: list[dict]
) -> None:
    storage.save_registry(tmp_path, {"schema_version": 1, "plans": []})
    registry_file = tmp_path / "data/registry/plans.json"
    registry_bytes = registry_file.read_bytes()
    first_path = storage.save_preparation(tmp_path, preparation, pages)
    first_record_bytes = (tmp_path / first_path).read_bytes()
    first_pages_bytes = (tmp_path / preparation["pages_path"]).read_bytes()

    new_directory = storage.next_preparation_directory(tmp_path, preparation["plan_id"])
    second_preparation = dict(
        preparation,
        pages_path=f"{new_directory}/pages.json",
        prepared_at="2026-11-02T11:00:00Z",
    )
    second_pages = copy.deepcopy(pages)
    second_pages[0]["text"] = "Text from the second preparation attempt."

    second_path = storage.save_preparation(tmp_path, second_preparation, second_pages)

    assert second_path == "data/processed/plan_0001/preparation_02/preparation.json"
    assert storage.load_preparation(tmp_path, second_path) == (second_preparation, second_pages)
    # Explicitly choosing the first path must still return the first attempt.
    assert storage.load_preparation(tmp_path, first_path) == (preparation, pages)
    assert (tmp_path / first_path).read_bytes() == first_record_bytes
    assert (tmp_path / preparation["pages_path"]).read_bytes() == first_pages_bytes
    assert registry_file.read_bytes() == registry_bytes


@pytest.mark.parametrize("existing_kind", ["empty", "complete", "damaged", "file"])
def test_save_refuses_any_occupied_attempt_name(
    tmp_path: Path, preparation: dict, pages: list[dict], existing_kind: str
) -> None:
    directory = tmp_path / "data/processed/plan_0001/preparation_01"
    if existing_kind == "complete":
        storage.save_preparation(tmp_path, preparation, pages)
    elif existing_kind == "file":
        directory.parent.mkdir(parents=True)
        directory.write_bytes(b"retain occupied name")
    else:
        directory.mkdir(parents=True)
        if existing_kind == "damaged":
            (directory / "preparation.json").write_bytes(b"damaged record")

    # Snapshot every existing file so refused writes cannot hide data changes.
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    with pytest.raises(FileExistsError):
        storage.save_preparation(tmp_path, preparation, pages)

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert storage.next_preparation_directory(tmp_path, "plan_0001").endswith("preparation_02")


@pytest.mark.parametrize("invalid_part", ["record", "page", "page-sequence"])
def test_invalid_data_is_rejected_before_creating_files(
    tmp_path: Path, preparation: dict, pages: list[dict], invalid_part: str
) -> None:
    if invalid_part == "record":
        preparation["unexpected"] = True
    elif invalid_part == "page":
        pages[0]["text"] = 123
    else:
        pages[1]["page_number"] = 1
    before = copy.deepcopy((preparation, pages))

    with pytest.raises(storage.PreparationValidationError) as error:
        storage.save_preparation(tmp_path, preparation, pages)

    assert error.value.problems
    assert (preparation, pages) == before
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "pages_path",
    [
        pytest.param("data/processed/plan_0002/preparation_01/pages.json", id="other-plan"),
        pytest.param("pages.json", id="wrong-directory"),
        pytest.param("../pages.json", id="parent-traversal"),
        pytest.param("/tmp/pages.json", id="absolute-path"),
        pytest.param("data\\processed\\plan_0001\\pages.json", id="backslashes"),
        pytest.param("data/processed/plan_0001/preparation_00/pages.json", id="zero-attempt"),
        pytest.param("data/processed/plan_0001/preparation_01/other.json", id="wrong-filename"),
        pytest.param("data/processed/plan_0001/preparation_01/extra/pages.json", id="nested-pages"),
    ],
)
def test_save_requires_pages_in_the_selected_plans_preparation_folder(
    tmp_path: Path, preparation: dict, pages: list[dict], pages_path: str
) -> None:
    preparation["pages_path"] = pages_path

    with pytest.raises(storage.PreparationValidationError) as error:
        storage.save_preparation(tmp_path, preparation, pages)

    assert error.value.problems[0].category == "reference"
    assert error.value.problems[0].location == "preparation.json:$.pages_path"
    assert list(tmp_path.iterdir()) == []


def test_utf8_encoding_failure_happens_before_creating_files(
    tmp_path: Path, preparation: dict, pages: list[dict]
) -> None:
    # An isolated surrogate can exist in a Python string but cannot be encoded as
    # normal UTF-8. It must not cause a partial save or silently lose characters.
    pages[0]["text"] = "\ud800"

    with pytest.raises(UnicodeEncodeError):
        storage.save_preparation(tmp_path, preparation, pages)

    assert list(tmp_path.iterdir()) == []


def test_missing_record_is_not_created_or_replaced_with_a_newer_attempt(
    tmp_path: Path, preparation: dict, pages: list[dict]
) -> None:
    preparation["pages_path"] = "data/processed/plan_0001/preparation_02/pages.json"
    second_path = storage.save_preparation(tmp_path, preparation, pages)
    missing_path = "data/processed/plan_0001/preparation_01/preparation.json"

    with pytest.raises(FileNotFoundError):
        storage.load_preparation(tmp_path, missing_path)

    assert not (tmp_path / missing_path).parent.exists()
    assert storage.load_preparation(tmp_path, second_path) == (preparation, pages)


def test_missing_pages_are_reported_without_recreating_them(
    tmp_path: Path, preparation: dict, pages: list[dict]
) -> None:
    record_path = storage.save_preparation(tmp_path, preparation, pages)
    record_bytes = (tmp_path / record_path).read_bytes()
    pages_file = tmp_path / preparation["pages_path"]
    pages_file.unlink()  # Simulate damage only in this test's temporary project.

    with pytest.raises(FileNotFoundError):
        storage.load_preparation(tmp_path, record_path)

    assert not pages_file.exists()
    assert (tmp_path / record_path).read_bytes() == record_bytes


@pytest.mark.parametrize("filename", ["preparation.json", "pages.json"])
@pytest.mark.parametrize(
    ("damaged_text", "category"),
    [
        pytest.param('{"unfinished":', "syntax", id="malformed-json"),
        pytest.param('{"text": "one", "text": "two"}', "syntax", id="duplicate-key"),
        pytest.param('"wrong data shape"', "structure", id="invalid-structure"),
    ],
)
def test_damaged_json_is_reported_with_its_file_and_left_unchanged(
    tmp_path: Path,
    preparation: dict,
    pages: list[dict],
    filename: str,
    damaged_text: str,
    category: str,
) -> None:
    record_path = storage.save_preparation(tmp_path, preparation, pages)
    directory = (tmp_path / record_path).parent
    damaged_file = directory / filename
    damaged_file.write_text(damaged_text, encoding="utf-8")
    before = {path.name: path.read_bytes() for path in directory.iterdir()}

    with pytest.raises(storage.PreparationValidationError) as error:
        storage.load_preparation(tmp_path, record_path)

    assert error.value.problems[0].category == category
    assert filename in error.value.problems[0].location
    assert {path.name: path.read_bytes() for path in directory.iterdir()} == before


def test_loading_checks_page_count_against_saved_entries(
    tmp_path: Path, preparation: dict, pages: list[dict]
) -> None:
    record_path = storage.save_preparation(tmp_path, preparation, pages)
    pages_file = tmp_path / preparation["pages_path"]
    pages_file.write_text(json.dumps(pages[:2]), encoding="utf-8")
    damaged_bytes = pages_file.read_bytes()

    with pytest.raises(storage.PreparationValidationError) as error:
        storage.load_preparation(tmp_path, record_path)

    assert error.value.problems[0].category == "reference"
    assert "declares 3 pages" in error.value.problems[0].message
    assert pages_file.read_bytes() == damaged_bytes


def test_loading_rejects_a_link_to_another_attempts_pages(
    tmp_path: Path, preparation: dict, pages: list[dict]
) -> None:
    first_path = storage.save_preparation(tmp_path, preparation, pages)
    second_preparation = dict(
        preparation, pages_path="data/processed/plan_0001/preparation_02/pages.json"
    )
    second_path = storage.save_preparation(tmp_path, second_preparation, pages)
    # Simulate an accidental edit that makes the first record use the second
    # attempt's pages. Both files can pass their schemas and still be mislinked.
    (tmp_path / first_path).write_text(json.dumps(second_preparation), encoding="utf-8")

    with pytest.raises(storage.PreparationValidationError) as error:
        storage.load_preparation(tmp_path, first_path)

    assert error.value.problems[0].category == "reference"
    assert error.value.problems[0].location == first_path
    assert "same plan and folder" in error.value.problems[0].message
    assert storage.load_preparation(tmp_path, second_path) == (second_preparation, pages)


@pytest.mark.parametrize("operation", ["sync", "publish"])
@pytest.mark.parametrize("failed_filename", ["pages.json", "preparation.json"])
def test_interrupted_save_retains_the_attempt_and_preserves_older_files(
    tmp_path: Path,
    preparation: dict,
    pages: list[dict],
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failed_filename: str,
) -> None:
    # Inject a write failure partway through the new attempt. Its retained folder
    # must reserve the number, while the earlier complete preparation remains
    # unchanged and available by its explicit path.
    first_path = storage.save_preparation(tmp_path, preparation, pages)
    first_directory = (tmp_path / first_path).parent
    original_bytes = {path.name: path.read_bytes() for path in first_directory.iterdir()}
    second_preparation = dict(
        preparation, pages_path="data/processed/plan_0001/preparation_02/pages.json"
    )
    second_directory = tmp_path / "data/processed/plan_0001/preparation_02"

    if operation == "sync":
        real_sync = storage.os.fsync
        sync_calls = 0

        def fail_selected_sync(file_descriptor: int) -> None:
            # Pages are written first. The second file-sync belongs to the record.
            nonlocal sync_calls
            sync_calls += 1
            selected_call = 1 if failed_filename == "pages.json" else 2
            if sync_calls == selected_call:
                raise OSError("Simulated preparation sync failure")
            real_sync(file_descriptor)

        monkeypatch.setattr(storage.os, "fsync", fail_selected_sync)
    else:
        real_link = storage.os.link

        def fail_selected_publication(source: Path, destination: Path) -> None:
            assert Path(source).parent == Path(destination).parent
            if Path(destination).name == failed_filename:
                raise OSError("Simulated preparation publication failure")
            real_link(source, destination)

        monkeypatch.setattr(storage.os, "link", fail_selected_publication)

    with pytest.raises(OSError, match="Simulated preparation") as error:
        storage.save_preparation(tmp_path, second_preparation, pages)

    assert {path.name: path.read_bytes() for path in first_directory.iterdir()} == original_bytes
    assert second_directory.is_dir()
    assert not (second_directory / "preparation.json").exists()
    assert (second_directory / "pages.json").exists() == (failed_filename == "preparation.json")
    assert list(second_directory.glob(".*.tmp")) == []
    assert "folder retained" in " ".join(error.value.__notes__)
    assert storage.next_preparation_directory(tmp_path, "plan_0001").endswith("preparation_03")
    with pytest.raises(FileNotFoundError):
        storage.load_preparation(
            tmp_path, "data/processed/plan_0001/preparation_02/preparation.json"
        )


def test_error_after_record_publication_does_not_delete_completed_pair(
    tmp_path: Path,
    preparation: dict,
    pages: list[dict],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_link = storage.os.link

    def publish_then_report_error(source: Path, destination: Path) -> None:
        real_link(source, destination)
        if Path(destination).name == "preparation.json":
            raise OSError("Simulated uncertain publication outcome")

    monkeypatch.setattr(storage.os, "link", publish_then_report_error)

    with pytest.raises(OSError, match="uncertain publication"):
        storage.save_preparation(tmp_path, preparation, pages)

    # An error does not prove nothing was saved. Preserve the completed pair so a
    # caller can inspect it explicitly instead of deleting possibly committed data.
    record_path = "data/processed/plan_0001/preparation_01/preparation.json"
    assert storage.load_preparation(tmp_path, record_path) == (preparation, pages)
    assert storage.next_preparation_directory(tmp_path, "plan_0001").endswith("preparation_02")


@pytest.mark.parametrize("operation", ["suggest", "save", "load"])
def test_preparation_storage_cannot_follow_data_directory_outside_the_project(
    tmp_path: Path, preparation: dict, pages: list[dict], operation: str
) -> None:
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()
    (project / "data").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="outside the project root"):
        if operation == "suggest":
            storage.next_preparation_directory(project, "plan_0001")
        elif operation == "save":
            storage.save_preparation(project, preparation, pages)
        else:
            storage.load_preparation(
                project, "data/processed/plan_0001/preparation_01/preparation.json"
            )

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize("filename", ["preparation.json", "pages.json"])
def test_load_cannot_follow_individual_json_file_outside_the_project(
    tmp_path: Path, preparation: dict, pages: list[dict], filename: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    record_path = storage.save_preparation(project, preparation, pages)
    selected_file = (project / record_path).parent / filename
    outside_file = tmp_path / "outside.json"
    outside_bytes = selected_file.read_bytes()
    outside_file.write_bytes(outside_bytes)
    selected_file.unlink()
    selected_file.symlink_to(outside_file)

    with pytest.raises(ValueError, match="outside the project root"):
        storage.load_preparation(project, record_path)

    assert selected_file.is_symlink()
    assert outside_file.read_bytes() == outside_bytes
