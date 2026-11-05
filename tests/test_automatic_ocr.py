"""Check selective OCR, error reporting, and one cached-model integration example.

Most cases replace the OCR backend with controlled results: no downloads or
neural inference are needed for those tests. The final case uses real cached
English models on a known image-only PDF and skips if setup has not been run.
"""
# Follow the controlled backend tests first, then the preparation tests, then
# the cached-model example at the end. monkeypatch temporarily replaces selected
# functions/imports and pytest restores them after each case.

import logging
import sys
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PageObject, PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject, NumberObject

import cli
import document_tools
import documents
import storage


@pytest.fixture
def image_bytes() -> bytes:
    with Image.new("RGB", (80, 40), "white") as image, BytesIO() as output:
        image.save(output, format="PNG")
        return output.getvalue()


@pytest.fixture
def fake_easyocr(monkeypatch: pytest.MonkeyPatch):
    # SimpleNamespace groups observable test state. The fake backend records
    # constructor arguments and recognition calls, so tests can inspect settings
    # and inject a failure without loading neural models.
    state = SimpleNamespace(
        loads=[], calls=[], result=["Open 3 cooling centres", "by 2028."],
        load_error=None, read_error=None,
    )

    class Backend:
        def __init__(self, languages, **kwargs):
            state.loads.append((languages, kwargs))
            if state.load_error is not None:
                raise state.load_error

        def readtext(self, image, **kwargs):
            state.calls.append((image, kwargs))
            if state.read_error is not None:
                raise state.read_error
            return state.result

    # Replace only the Python import for this test. Pytest restores any real
    # module afterward; no model weights or library installation are changed.
    monkeypatch.setitem(sys.modules, "easyocr", SimpleNamespace(Reader=Backend))
    return state


def test_ocr_reader_uses_offline_cpu_models_and_preserves_fragments(
    fake_easyocr, image_bytes: bytes, tmp_path: Path
) -> None:
    reader = document_tools.EasyOcrReader(model_directory=tmp_path)

    assert document_tools.ocr_page_image(image_bytes, reader=reader) == (
        "Open 3 cooling centres\nby 2028."
    )
    assert reader.read_text(image_bytes) == "Open 3 cooling centres\nby 2028."
    assert len(fake_easyocr.loads) == 1
    languages, settings = fake_easyocr.loads[0]
    assert languages == ["en"]
    assert settings["gpu"] is False
    assert settings["download_enabled"] is False
    assert settings["model_storage_directory"] == str(tmp_path.resolve())
    assert fake_easyocr.calls[0][1] == {
        "detail": 0, "paragraph": False, "batch_size": 1, "workers": 0,
    }


def test_model_downloads_require_an_explicit_setup_choice(fake_easyocr, tmp_path: Path) -> None:
    document_tools.EasyOcrReader(model_directory=tmp_path, download_models=True)
    assert fake_easyocr.loads[0][1]["download_enabled"] is True


def test_missing_model_cache_reports_setup_action_without_creating_it(
    fake_easyocr, tmp_path: Path
) -> None:
    missing = tmp_path / "missing-models"
    with pytest.raises(document_tools.OcrError, match="Initialize it once"):
        document_tools.EasyOcrReader(model_directory=missing)
    assert fake_easyocr.loads == []
    assert not missing.exists()


@pytest.mark.parametrize("error", [OSError("missing weights"), RuntimeError("runtime failure")])
def test_ocr_initialization_errors_are_reported(fake_easyocr, tmp_path: Path, error: Exception) -> None:
    fake_easyocr.load_error = error
    with pytest.raises(document_tools.OcrError, match="Cannot initialize EasyOCR"):
        document_tools.EasyOcrReader(model_directory=tmp_path)


@pytest.mark.parametrize("error", [OSError("image failure"), RuntimeError("inference failure")])
def test_recognition_errors_are_reported(
    fake_easyocr, image_bytes: bytes, tmp_path: Path, error: Exception
) -> None:
    fake_easyocr.read_error = error
    reader = document_tools.EasyOcrReader(model_directory=tmp_path)
    with pytest.raises(document_tools.OcrError, match="Could not recognize"):
        reader.read_text(image_bytes)


@pytest.mark.parametrize(
    "result", [[], ["", "  "], "not-a-list", [123], ["bad \ufffd"], ["bad \ud800"]]
)
def test_unusable_ocr_results_do_not_become_selected_text(
    fake_easyocr, image_bytes: bytes, tmp_path: Path, result: object
) -> None:
    fake_easyocr.result = result
    reader = document_tools.EasyOcrReader(model_directory=tmp_path)
    with pytest.raises(document_tools.OcrError):
        reader.read_text(image_bytes)


@pytest.mark.parametrize("data", [b"", b"not an image", None])
def test_invalid_image_input_is_reported_without_recognition(
    fake_easyocr, tmp_path: Path, data: object
) -> None:
    reader = document_tools.EasyOcrReader(model_directory=tmp_path)
    with pytest.raises(document_tools.OcrError):
        reader.read_text(data)
    assert fake_easyocr.calls == []


def _add_stream(writer: PdfWriter, page: PageObject, contents: bytes) -> None:
    stream = DecodedStreamObject()
    stream.set_data(contents)
    page[NameObject("/Contents")] = writer._add_object(stream)


def _write_mixed_pdf(path: Path, *, gap_pages: int = 1) -> None:
    """Create native text, a known blank page, and non-text drawing pages."""
    with PdfWriter() as writer:
        page = writer.add_blank_page(width=300, height=300)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        _add_stream(writer, page, b"BT /F1 12 Tf 20 200 Td (KEEP NATIVE) Tj ET")
        writer.add_blank_page(width=300, height=300)
        for _ in range(gap_pages):
            page = writer.add_blank_page(width=300, height=300)
            _add_stream(writer, page, b"20 20 100 100 re f")
        writer.write(path)


def _register(project: Path, source: Path) -> dict:
    return documents.register_document(
        project, source, plan_title="Controlled OCR fixture",
        source_url="https://example.org/plan.pdf", date_accessed="2026-11-02",
        study_set="development",
    )[0]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
def mixed_plan(project: Path, tmp_path: Path) -> dict:
    source = tmp_path / "mixed.pdf"
    _write_mixed_pdf(source)
    return _register(project, source)


@pytest.fixture
def controlled_ocr(monkeypatch: pytest.MonkeyPatch):
    # This replacement controls only the OCR reader used by preparation. The PDF
    # and saved preparation still go through the real document/storage functions.
    state = SimpleNamespace(loads=0, images=[], result="RECOVERED OCR TEXT", load_error=None)

    class Reader:
        def __init__(self, *, language: str):
            assert language == "en"
            state.loads += 1
            if state.load_error is not None:
                raise state.load_error

        def read_text(self, image: bytes) -> str:
            assert image.startswith(b"\x89PNG")
            state.images.append(image)
            if isinstance(state.result, Exception):
                raise state.result
            return state.result

    monkeypatch.setattr(documents, "EasyOcrReader", Reader)
    return state


def test_automatic_ocr_is_selective_and_saves_text_once(
    project: Path, mixed_plan: dict, controlled_ocr
) -> None:
    original = (project / mixed_plan["pdf_path"]).read_bytes()

    preparation, record_path = documents.prepare_document(project, mixed_plan["plan_id"])

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["settings"]["ocr_enabled"] is True
    assert preparation["settings"]["ocr_engine"] == "easyocr"
    assert preparation["settings"]["ocr_version"] == document_tools.version("easyocr")
    assert preparation["status"] == "ready_with_gaps"
    assert [page["text_source"] for page in pages] == ["native", "native", "ocr"]
    assert [page["text"] for page in pages] == ["KEEP NATIVE", "", "RECOVERED OCR TEXT"]
    assert controlled_ocr.loads == 1
    assert len(controlled_ocr.images) == 1
    assert "blankness is unconfirmed" in pages[2]["problem"]
    assert "OCR supplied prepared text" in pages[2]["problem"]
    assert all("native_text" not in page and "ocr_text" not in page for page in pages)
    assert (project / mixed_plan["pdf_path"]).read_bytes() == original


def test_clean_native_text_and_known_blanks_do_not_load_ocr(
    project: Path, tmp_path: Path, controlled_ocr
) -> None:
    source = tmp_path / "native.pdf"
    _write_mixed_pdf(source, gap_pages=0)
    entry = _register(project, source)

    preparation, _ = documents.prepare_document(project, entry["plan_id"])

    assert preparation["status"] == "ready"
    assert preparation["settings"]["ocr_enabled"] is True
    assert controlled_ocr.loads == 0
    assert controlled_ocr.images == []


def test_multiple_gap_pages_reuse_one_ocr_reader(
    project: Path, tmp_path: Path, controlled_ocr
) -> None:
    source = tmp_path / "several-gaps.pdf"
    _write_mixed_pdf(source, gap_pages=2)
    entry = _register(project, source)

    _, record_path = documents.prepare_document(project, entry["plan_id"])

    _, pages = storage.load_preparation(project, record_path)
    assert controlled_ocr.loads == 1
    assert len(controlled_ocr.images) == 2
    assert [page["text_source"] for page in pages] == ["native", "native", "ocr", "ocr"]


def test_ocr_failure_preserves_image_route_and_original_problem(
    project: Path, mixed_plan: dict, controlled_ocr
) -> None:
    controlled_ocr.result = document_tools.OcrError("No recognized text in this image")

    preparation, record_path = documents.prepare_document(project, mixed_plan["plan_id"])

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert pages[2]["text"] is None and pages[2]["text_source"] is None
    assert pages[2]["image_available"] is True and pages[2]["readable"] is True
    assert "No recognized text" in pages[2]["problem"]
    assert "blankness is unconfirmed" in pages[2]["problem"]


def test_ocr_initialization_failure_is_not_retried_for_every_page(
    project: Path, tmp_path: Path, controlled_ocr
) -> None:
    source = tmp_path / "several-gaps.pdf"
    _write_mixed_pdf(source, gap_pages=2)
    entry = _register(project, source)
    controlled_ocr.load_error = document_tools.OcrError("Models unavailable")

    preparation, record_path = documents.prepare_document(project, entry["plan_id"])

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert controlled_ocr.loads == 1
    assert controlled_ocr.images == []
    assert all("Models unavailable" in page["problem"] for page in pages[2:])


def test_render_failure_prevents_ocr_and_remains_failed(
    project: Path, mixed_plan: dict, controlled_ocr, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_render(*args, **kwargs):
        raise document_tools.PageRenderingError("No usable page image")

    monkeypatch.setattr(documents.PdfPageRenderer, "render_page", fail_render)

    preparation, record_path = documents.prepare_document(project, mixed_plan["plan_id"])

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "failed"
    assert pages[2]["readable"] is False
    assert controlled_ocr.loads == 0


def test_document_warning_alone_does_not_trigger_ocr_of_clean_native_pages(
    project: Path, tmp_path: Path, controlled_ocr, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "native.pdf"
    _write_mixed_pdf(source, gap_pages=0)
    entry = _register(project, source)

    def warn_then_open(*args, **kwargs):
        logging.getLogger("pypdf.fixture").warning("Simulated document warning")
        return PdfReader(*args, **kwargs)

    monkeypatch.setattr(documents, "PdfReader", warn_then_open)

    preparation, _ = documents.prepare_document(project, entry["plan_id"])

    assert preparation["status"] == "ready_with_gaps"
    assert controlled_ocr.loads == 0


def test_automatic_ocr_uses_a_new_preparation_without_changing_the_previous_one(
    project: Path, mixed_plan: dict, controlled_ocr
) -> None:
    first, first_path = documents.prepare_document(project, mixed_plan["plan_id"], ocr_enabled=False)
    first_directory = (project / first_path).parent
    # Include saved PNGs as well as JSON when checking preservation of an attempt.
    before = {str(path.relative_to(first_directory)): path.read_bytes()
              for path in first_directory.rglob("*") if path.is_file()}

    second, second_path = documents.prepare_document(project, mixed_plan["plan_id"])

    assert first["settings"]["ocr_enabled"] is False
    assert second["settings"]["ocr_enabled"] is True
    assert second_path.endswith("preparation_02/preparation.json")
    assert {str(path.relative_to(first_directory)): path.read_bytes()
            for path in first_directory.rglob("*") if path.is_file()} == before
    assert storage.load_preparation(project, second_path)[1][2]["text_source"] == "ocr"


@pytest.mark.parametrize("enabled", [True, False], ids=["default-ocr", "explicit-no-ocr"])
def test_cli_enables_selective_ocr_by_default_and_supports_opt_out(
    project: Path, mixed_plan: dict, controlled_ocr, capsys: pytest.CaptureFixture, enabled: bool
) -> None:
    arguments = ["prepare", mixed_plan["plan_id"], "--project-root", str(project)]
    if not enabled:
        arguments.append("--no-ocr")

    assert cli.main(arguments) == 0
    output = capsys.readouterr()
    record_path = storage.load_registry(project)["plans"][0]["prepared_source_path"]
    preparation, pages = storage.load_preparation(project, record_path)
    assert preparation["settings"]["ocr_enabled"] is enabled
    assert pages[2]["text_source"] == ("ocr" if enabled else None)
    assert controlled_ocr.loads == (1 if enabled else 0)
    assert "Status: ready_with_gaps" in output.out


def _write_image_only_pdf(path: Path, image: Image.Image) -> None:
    with PdfWriter() as writer:
        page = writer.add_blank_page(width=600, height=150)
        bitmap = DecodedStreamObject()
        bitmap.set_data(image.tobytes())
        bitmap.update(
            {
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Image"),
                NameObject("/Width"): NumberObject(image.width),
                NameObject("/Height"): NumberObject(image.height),
                NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
                NameObject("/BitsPerComponent"): NumberObject(8),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/XObject"): DictionaryObject({NameObject("/Im0"): writer._add_object(bitmap)})}
        )
        _add_stream(writer, page, b"q 600 0 0 150 0 0 cm /Im0 Do Q")
        writer.write(path)


_CACHED_MODELS = all(
    (document_tools.DEFAULT_OCR_MODEL_DIRECTORY / name).is_file()
    for name in ("craft_mlt_25k.pth", "english_g2.pth")
)


@pytest.mark.skipif(not _CACHED_MODELS, reason="Requires the explicitly downloaded English OCR models.")
def test_real_ocr_recovers_known_text_from_an_image_only_pdf(project: Path, tmp_path: Path) -> None:
    # A deliberately clear example checks real integration, not the accuracy of
    # OCR on complex plans, tables, or low-quality scans. It performs no downloads.
    # This case uses cached English weights on a generated known phrase. It checks
    # the real OCR connection, while chart/table accuracy on research plans remains
    # a separate empirical question.
    expected = "OPEN 3 COOLING CENTRES BY 2028"
    source = tmp_path / "scanned.pdf"
    with Image.new("RGB", (1200, 300), "white") as image:
        draw = ImageDraw.Draw(image)
        draw.text((35, 100), expected, font=ImageFont.load_default(size=48), fill="black")
        _write_image_only_pdf(source, image)
    entry = _register(project, source)
    original = source.read_bytes()

    preparation, record_path = documents.prepare_document(project, entry["plan_id"])

    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert pages[0]["text_source"] == "ocr"
    assert " ".join(pages[0]["text"].split()).upper() == expected
    assert (project / entry["pdf_path"]).read_bytes() == original
