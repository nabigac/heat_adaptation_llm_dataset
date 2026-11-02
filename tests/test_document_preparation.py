"""Check native PDF preparation with controlled PDFs and simulated failures.

Unlike registration's PDF-like byte fixtures, these small PDFs have actual page
trees, fonts, and content streams that pypdf can read. They establish known test
cases for native text and rendering, not accuracy on real plans. These cases
explicitly disable automatic OCR, which is covered in test_automatic_ocr.py.
"""

import copy
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.errors import PdfReadError
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

import documents
import storage


def _set_content(writer: PdfWriter, page: PageObject, data: bytes) -> None:
    """Attach a tiny drawing stream to a test page."""
    stream = DecodedStreamObject()
    stream.set_data(data)
    # PDF streams are stored as separate objects and linked from a page. The
    # writer's internal object helper is used only to build controlled fixtures.
    page[NameObject("/Contents")] = writer._add_object(stream)


def _write_pdf(path: Path, page_texts: list[str | None], *, encrypted: bool = False) -> None:
    """Create ASCII text pages; None means a structurally blank page."""
    with PdfWriter() as writer:
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        for text in page_texts:
            page = writer.add_blank_page(width=300, height=300)
            if text is not None:
                page[NameObject("/Resources")] = DictionaryObject(
                    {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
                )
                # Escape the three characters with special meaning inside a PDF
                # literal string. This helper only needs ASCII fixture text.
                escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
                _set_content(
                    writer, page, f"BT /F1 12 Tf 20 200 Td ({escaped}) Tj ET".encode("ascii")
                )
        if encrypted:
            # RC4 needs no optional crypto dependency. This PDF only tests that
            # encrypted inputs are reported as unsupported; it is not a security example.
            writer.encrypt("fixture-password", algorithm="RC4-128")
        writer.write(path)


def _register(project: Path, source: Path) -> dict:
    """Register controlled input through the real workflow before preparing it."""
    entry, _ = documents.register_document(
        project,
        source,
        plan_title="Example Heat Plan",
        source_url="https://example.org/heat-plan.pdf",
        date_accessed="2026-11-02",
        study_set="development",
    )
    return entry


@pytest.fixture
def registered_plan(tmp_path: Path) -> tuple[Path, dict]:
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "incoming.pdf"
    _write_pdf(source, ["Example Heat Plan", None, "Open 3 cooling centres by 2028."])
    return project, _register(project, source)


def test_prepares_native_text_and_blank_page_and_links_registry(
    registered_plan: tuple[Path, dict],
) -> None:
    project, entry = registered_plan
    original_bytes = (project / entry["pdf_path"]).read_bytes()

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    saved_preparation, pages = storage.load_preparation(project, record_path)
    assert preparation == saved_preparation
    assert record_path == "data/processed/plan_0001/preparation_01/preparation.json"
    assert preparation["status"] == "ready"
    assert preparation["schema_version"] == 3
    assert preparation["settings"] == {
        "ocr_enabled": False,
        "ocr_engine": None,
        "ocr_version": None,
        "ocr_language": None,
        "image_render_dpi": 150,
        "candidate_image_min_area": 0.10,
    }
    assert preparation["problem"] is None
    assert preparation["page_count"] == 3
    assert datetime.fromisoformat(preparation["prepared_at"]).utcoffset() == timedelta(0)
    for field in ("plan_id", "pdf_path", "document_sha256", "source_url", "date_accessed"):
        assert preparation[field] == entry[field]
    assert [page["page_number"] for page in pages] == [1, 2, 3]
    assert [page["text_source"] for page in pages] == ["native", "native", "native"]
    assert [page["text"] for page in pages] == [
        "Example Heat Plan", "", "Open 3 cooling centres by 2028."
    ]
    assert all(page["readable"] and page["problem"] is None for page in pages)
    assert all(page["image_available"] is False for page in pages)
    assert storage.load_registry(project)["plans"] == [dict(entry, prepared_source_path=record_path)]
    assert (project / entry["pdf_path"]).read_bytes() == original_bytes


def test_repeated_preparation_keeps_previous_attempt_unchanged(
    registered_plan: tuple[Path, dict],
) -> None:
    project, entry = registered_plan
    first, first_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    first_files = {
        path.name: path.read_bytes() for path in (project / first_path).parent.iterdir()
    }

    second, second_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert second_path.endswith("preparation_02/preparation.json")
    assert second["status"] == "ready"
    assert {path.name: path.read_bytes() for path in (project / first_path).parent.iterdir()} == first_files
    assert storage.load_preparation(project, first_path)[0] == first
    assert storage.load_registry(project)["plans"][0]["prepared_source_path"] == second_path


@pytest.mark.parametrize("failure", ["malformed", "zero-pages", "encrypted"])
def test_open_or_count_failure_is_saved_with_unknown_count(
    tmp_path: Path, failure: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "incoming.pdf"
    if failure == "malformed":
        source.write_bytes(b"This is not a PDF.")
    else:
        _write_pdf(source, [] if failure == "zero-pages" else ["Secret"], encrypted=failure == "encrypted")
    entry = _register(project, source)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert preparation["status"] == "failed"
    assert preparation["page_count"] is None
    assert preparation["problem"]
    assert storage.load_preparation(project, record_path) == (preparation, [])
    assert storage.load_registry(project)["plans"][0]["prepared_source_path"] == record_path


def test_image_reader_identifies_pages_when_native_count_fails(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan

    def fail_count(self) -> int:
        raise PdfReadError("Simulated page-count failure")

    monkeypatch.setattr(PdfReader, "get_num_pages", fail_count)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert preparation["status"] == "ready_with_gaps"
    assert preparation["page_count"] == 3
    assert "page-count failure" in preparation["problem"]
    pages = storage.load_preparation(project, record_path)[1]
    assert [page["page_number"] for page in pages] == [1, 2, 3]
    assert all(page["text"] is None and page["image_available"] for page in pages)
    assert all(page["text_source"] is None for page in pages)


@pytest.mark.parametrize("operation", ["load-page", "extract-text"])
def test_one_page_failure_keeps_every_known_page_and_later_text(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    project, entry = registered_plan
    if operation == "load-page":
        original_get = PdfReader.get_page

        def fail_first_page(self, page_number: int):
            if page_number == 0:
                raise PdfReadError("Simulated individual page failure")
            return original_get(self, page_number)

        monkeypatch.setattr(PdfReader, "get_page", fail_first_page)
    else:
        original_extract = PageObject.extract_text

        def fail_first_extraction(self, *args, **kwargs):
            if self.page_number == 0:
                raise PdfReadError("Simulated individual page failure")
            return original_extract(self, *args, **kwargs)

        monkeypatch.setattr(PageObject, "extract_text", fail_first_extraction)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert preparation["page_count"] == 3
    assert [page["page_number"] for page in pages] == [1, 2, 3]
    assert pages[0]["text"] is None
    assert pages[0]["text_source"] is None
    assert pages[0]["readable"] is True
    assert pages[0]["image_available"] is True
    assert "individual page failure" in pages[0]["problem"]
    assert pages[1]["text"] == ""
    assert pages[2]["text"] == "Open 3 cooling centres by 2028."


def test_image_only_page_keeps_unavailable_text_and_has_a_checked_image_route(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "image-only.pdf"
    with PdfWriter() as writer:
        page = writer.add_blank_page(width=300, height=300)
        # A one-pixel black image provides an actual image-only PDF fixture. It
        # tests absence of native text, not OCR recognition of scanned wording.
        image = DecodedStreamObject()
        image.set_data(b"\x00\x00\x00")
        image.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(1),
                NameObject("/Height"): NumberObject(1),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): writer._add_object(image)})}
        )
        _set_content(writer, page, b"q 100 0 0 100 20 20 cm /Im0 Do Q")
        writer.write(source)
    entry = _register(project, source)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert preparation["page_count"] == 1
    assert "Page-image rendering checked at 150 DPI" in preparation["problem"]
    assert pages[0]["text"] is None
    assert pages[0]["readable"] is True
    assert pages[0]["image_available"] is True
    assert "blankness is unconfirmed" in pages[0]["problem"]


@pytest.mark.parametrize("page_kind", ["empty-stream", "annotation", "whitespace-text"])
def test_blankness_uses_content_and_annotations_not_only_extracted_text(
    tmp_path: Path, page_kind: str
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    source = tmp_path / "blankness.pdf"
    if page_kind == "whitespace-text":
        _write_pdf(source, ["   "])
    else:
        with PdfWriter() as writer:
            page = writer.add_blank_page(width=300, height=300)
            _set_content(writer, page, b" \n")
            if page_kind == "annotation":
                # Even without drawing content, a page can have a visible annotation.
                annotation = DictionaryObject(
                    {
                        NameObject("/Type"): NameObject("/Annot"),
                        NameObject("/Subtype"): NameObject("/Text"),
                        NameObject("/Rect"): ArrayObject([NumberObject(0)] * 4),
                    }
                )
                page[NameObject("/Annots")] = ArrayObject([writer._add_object(annotation)])
            writer.write(source)
    entry = _register(project, source)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    if page_kind == "empty-stream":
        assert preparation["status"] == "ready"
        assert pages[0]["text"] == ""
        assert pages[0]["readable"] is True
    else:
        assert preparation["status"] == "ready_with_gaps"
        assert pages[0]["text"] is None
        assert pages[0]["readable"] is True
        assert pages[0]["image_available"] is True


@pytest.mark.parametrize(
    ("returned_text", "saved_text", "problem_fragment"),
    [
        pytest.param(None, None, "did not return page text", id="unexpected-null"),
        pytest.param("bad \ufffd text", "bad \ufffd text", "replacement characters", id="decoding-gap"),
        pytest.param("bad \ud800 text", None, "UTF-8", id="unencodable-text"),
    ],
)
def test_unusable_decoding_is_recorded_without_inventing_text(
    registered_plan: tuple[Path, dict],
    monkeypatch: pytest.MonkeyPatch,
    returned_text: str | None,
    saved_text: str | None,
    problem_fragment: str,
) -> None:
    project, entry = registered_plan
    monkeypatch.setattr(PageObject, "extract_text", lambda *args, **kwargs: returned_text)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert all(page["text"] == saved_text for page in pages)
    assert all(page["text_source"] == ("native" if saved_text is not None else None) for page in pages)
    assert all(page["readable"] is True and page["image_available"] for page in pages)
    assert all(problem_fragment in page["problem"] for page in pages)


def test_page_warning_is_saved_and_logging_setup_is_restored(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    logger = logging.getLogger("pypdf")
    original_handlers, original_level = list(logger.handlers), logger.level
    original_extract = PageObject.extract_text

    def warn_on_first_page(self, *args, **kwargs):
        if self.page_number == 0:
            logging.getLogger("pypdf.fixture").warning("Simulated font decoding warning")
        return original_extract(self, *args, **kwargs)

    monkeypatch.setattr(PageObject, "extract_text", warn_on_first_page)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert pages[0]["text"] == "Example Heat Plan"
    assert pages[0]["readable"] is True
    assert pages[0]["image_available"] is True
    assert "font decoding warning" in pages[0]["problem"]
    assert pages[1]["readable"] is True
    assert logger.handlers == original_handlers
    assert logger.level == original_level


def test_document_opening_warning_is_saved_as_a_document_problem(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan

    def reader_with_warning(*args, **kwargs):
        assert kwargs["strict"] is True
        logging.getLogger("pypdf.fixture").warning("Simulated document opening warning")
        return PdfReader(*args, **kwargs)

    monkeypatch.setattr(documents, "PdfReader", reader_with_warning)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert preparation["page_count"] == 3
    assert "document opening warning" in preparation["problem"]
    assert all(page["readable"] is True for page in pages)
    assert all(page["image_available"] is True for page in pages)


def test_unknown_plan_id_does_not_create_preparation_files(
    registered_plan: tuple[Path, dict],
) -> None:
    project, _ = registered_plan
    before = (project / "data/registry/plans.json").read_bytes()

    with pytest.raises(ValueError, match="No registered document"):
        documents.prepare_document(project, "plan_9999")

    assert (project / "data/registry/plans.json").read_bytes() == before
    assert not (project / "data/processed").exists()


def test_preparation_requires_an_existing_project_and_registry(tmp_path: Path) -> None:
    with pytest.raises(NotADirectoryError):
        documents.prepare_document(tmp_path / "missing-project", "plan_0001")
    with pytest.raises(FileNotFoundError):
        documents.prepare_document(tmp_path, "plan_0001")
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("damage", ["missing", "changed"])
def test_damaged_registered_original_blocks_preparation(
    registered_plan: tuple[Path, dict], damage: str
) -> None:
    project, entry = registered_plan
    raw_pdf = project / entry["pdf_path"]
    if damage == "missing":
        raw_pdf.unlink()
    else:
        raw_pdf.write_bytes(b"changed registered input")
    registry_before = (project / "data/registry/plans.json").read_bytes()

    with pytest.raises((FileNotFoundError, ValueError)):
        documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert (project / "data/registry/plans.json").read_bytes() == registry_before
    assert not (project / "data/processed").exists()


def test_original_change_during_preparation_blocks_publication(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    raw_pdf = project / entry["pdf_path"]
    registry_before = (project / "data/registry/plans.json").read_bytes()
    read_pages = documents._read_pdf_pages

    def change_original_after_reading(pdf_bytes: bytes):
        result = read_pages(pdf_bytes)
        raw_pdf.write_bytes(b"Simulated external change during preparation")
        return result

    monkeypatch.setattr(documents, "_read_pdf_pages", change_original_after_reading)

    with pytest.raises(ValueError, match="changed during preparation"):
        documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert (project / "data/registry/plans.json").read_bytes() == registry_before
    assert not (project / "data/processed").exists()


def test_unexpected_programming_error_is_not_hidden_as_a_pdf_gap(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    registry_before = (project / "data/registry/plans.json").read_bytes()
    logger = logging.getLogger("pypdf")
    handlers_before, level_before = list(logger.handlers), logger.level

    def programming_error(*args, **kwargs):
        raise RuntimeError("Simulated unexpected programming error")

    monkeypatch.setattr(PageObject, "extract_text", programming_error)

    with pytest.raises(RuntimeError, match="unexpected programming error"):
        documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert (project / "data/registry/plans.json").read_bytes() == registry_before
    assert not (project / "data/processed").exists()
    assert logger.handlers == handlers_before
    assert logger.level == level_before


def test_failed_retry_preserves_prior_success_and_records_latest_failure(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    first, first_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    first_files = {
        path.name: path.read_bytes() for path in (project / first_path).parent.iterdir()
    }
    monkeypatch.setattr(PageObject, "extract_text", lambda *args, **kwargs: None)

    def fail_render(*args, **kwargs):
        raise documents.PageRenderingError("Simulated unavailable page image")

    # Losing native text is now recoverable through images. This failed retry
    # must lose both routes to remain a genuinely failed preparation.
    monkeypatch.setattr(documents.PdfPageRenderer, "render_page", fail_render)

    failed, failed_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert failed["status"] == "failed"
    assert failed_path.endswith("preparation_02/preparation.json")
    assert {path.name: path.read_bytes() for path in (project / first_path).parent.iterdir()} == first_files
    assert storage.load_preparation(project, first_path)[0] == first
    assert storage.load_registry(project)["plans"][0]["prepared_source_path"] == failed_path


@pytest.mark.parametrize("damage", ["missing-pages", "damaged-pages", "wrong-checksum"])
def test_previous_saved_input_must_be_restored_before_moving_its_registry_link(
    registered_plan: tuple[Path, dict], damage: str
) -> None:
    project, entry = registered_plan
    previous, previous_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    if damage == "missing-pages":
        (project / previous["pages_path"]).unlink()
    elif damage == "damaged-pages":
        (project / previous["pages_path"]).write_text("[broken", encoding="utf-8")
    else:
        previous["document_sha256"] = "b" * 64
        (project / previous_path).write_text(json.dumps(previous), encoding="utf-8")
    registry_before = (project / "data/registry/plans.json").read_bytes()

    with pytest.raises((FileNotFoundError, ValueError)):
        documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert (project / "data/registry/plans.json").read_bytes() == registry_before
    assert not (project / "data/processed/plan_0001/preparation_02").exists()


def test_new_preparation_uses_corrected_metadata_without_editing_previous_record(
    registered_plan: tuple[Path, dict],
) -> None:
    project, entry = registered_plan
    previous, previous_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    registry = storage.load_registry(project)
    registry["plans"][0].update(
        source_url="https://example.org/corrected-collection-url.pdf", date_accessed="2026-11-01"
    )
    storage.save_registry(project, registry)

    current, _ = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert current["source_url"] == registry["plans"][0]["source_url"]
    assert current["date_accessed"] == "2026-11-01"
    assert storage.load_preparation(project, previous_path)[0] == previous


@pytest.mark.parametrize("committed_before_error", [False, True], ids=["before-save", "after-save"])
def test_registry_link_failure_retains_completed_preparation_and_reports_its_path(
    registered_plan: tuple[Path, dict],
    monkeypatch: pytest.MonkeyPatch,
    committed_before_error: bool,
) -> None:
    project, entry = registered_plan
    real_save = storage.save_registry

    def fail_save(root: Path, registry: dict) -> None:
        if committed_before_error:
            real_save(root, registry)
        raise OSError("Simulated preparation registry-link failure")

    monkeypatch.setattr(storage, "save_registry", fail_save)

    with pytest.raises(OSError, match="registry-link failure") as error:
        documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    record_path = "data/processed/plan_0001/preparation_01/preparation.json"
    assert storage.load_preparation(project, record_path)[0]["status"] == "ready"
    assert record_path in error.value.__notes__[0]
    saved_link = storage.load_registry(project)["plans"][0]["prepared_source_path"]
    assert saved_link == (record_path if committed_before_error else None)


def test_preparation_save_failure_does_not_update_registry(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    registry_before = (project / "data/registry/plans.json").read_bytes()

    def fail_preparation_save(*args, **kwargs):
        raise OSError("Simulated preparation-storage failure")

    monkeypatch.setattr(storage, "save_preparation", fail_preparation_save)

    with pytest.raises(OSError, match="preparation-storage failure"):
        documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    assert (project / "data/registry/plans.json").read_bytes() == registry_before
    assert not (project / "data/processed").exists()


def test_preparation_updates_only_the_selected_registry_entry(
    registered_plan: tuple[Path, dict], tmp_path: Path
) -> None:
    project, first_entry = registered_plan
    second_source = tmp_path / "other.pdf"
    _write_pdf(second_source, ["A different registered plan."])
    second_entry = copy.deepcopy(_register(project, second_source))

    _, record_path = documents.prepare_document(project, first_entry["plan_id"], ocr_enabled=False)

    registry = storage.load_registry(project)
    assert registry["plans"][0] == dict(first_entry, prepared_source_path=record_path)
    assert registry["plans"][1] == second_entry


def test_page_with_neither_native_text_nor_image_stays_failed(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    original_extract = PageObject.extract_text

    def lose_first_text(self, *args, **kwargs):
        if self.page_number == 0:
            raise PdfReadError("Simulated native text failure")
        return original_extract(self, *args, **kwargs)

    def lose_image(self, page_number: int) -> bytes:
        raise documents.PageRenderingError("Simulated rendering failure")

    monkeypatch.setattr(PageObject, "extract_text", lose_first_text)
    monkeypatch.setattr(documents.PdfPageRenderer, "render_page", lose_image)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "failed"
    assert preparation["page_count"] == 3
    assert pages[0]["text"] is None
    assert pages[0]["readable"] is False
    assert pages[0]["image_available"] is False
    assert "native text failure" in pages[0]["problem"]
    assert "rendering failure" in pages[0]["problem"]
    assert pages[2]["text"] == "Open 3 cooling centres by 2028."


def test_reader_page_count_disagreement_is_blocking(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    real_renderer = documents.PdfPageRenderer
    monkeypatch.setattr(PageObject, "extract_text", lambda *args, **kwargs: None)

    class WrongCountRenderer(real_renderer):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.page_count = 2  # Simulate disagreement with the three-page native reader.

    monkeypatch.setattr(documents, "PdfPageRenderer", WrongCountRenderer)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "failed"
    assert preparation["page_count"] == 3
    assert len(pages) == 3
    assert "identified 3 pages" in preparation["problem"]
    assert "identified 2" in preparation["problem"]
    assert all(page["image_available"] is False for page in pages)


def test_renderer_open_failure_preserves_native_gaps_and_known_page_count(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    monkeypatch.setattr(PageObject, "extract_text", lambda *args, **kwargs: None)

    def cannot_open_renderer(*args, **kwargs):
        raise documents.PageRenderingError("Simulated renderer opening failure")

    monkeypatch.setattr(documents, "PdfPageRenderer", cannot_open_renderer)

    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "failed"
    assert preparation["page_count"] == 3
    assert len(pages) == 3
    assert all(page["text"] is None and not page["readable"] for page in pages)
    assert "renderer opening failure" in preparation["problem"]


def test_custom_render_dpi_is_used_and_recorded_with_the_gap(
    registered_plan: tuple[Path, dict], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, entry = registered_plan
    monkeypatch.setattr(PageObject, "extract_text", lambda *args, **kwargs: None)

    preparation, _ = documents.prepare_document(project, entry["plan_id"], image_render_dpi=72, ocr_enabled=False)

    assert preparation["status"] == "ready_with_gaps"
    assert "checked at 72 DPI" in preparation["problem"]
    assert preparation["settings"]["image_render_dpi"] == 72
