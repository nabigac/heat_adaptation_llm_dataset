"""Check local page rendering independently of any MCP server or OCR engine."""
# These tests inspect decoded PNG pixels/dimensions and resource handling. They
# exercise local PDFium/Pillow helpers, not model tool calls. OCR setting tests
# replace version detection where needed so expected metadata is controlled.

from io import BytesIO

import pytest
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

import document_tools


@pytest.fixture
def pdf_bytes() -> bytes:
    """Make two pages with different known marks, entirely in memory."""
    # Two different drawn marks reveal whether the requested page was rendered.
    # Using BytesIO keeps the fixture in memory; callers receive encoded PDF bytes.
    with PdfWriter() as writer:
        for drawing in (b"20 20 60 40 re f", b"160 100 40 30 re f"):
            page = writer.add_blank_page(width=300, height=200)
            contents = DecodedStreamObject()
            contents.set_data(drawing)
            page[NameObject("/Contents")] = writer._add_object(contents)
        with BytesIO() as output:
            writer.write(output)
            return output.getvalue()


def test_renders_requested_pages_as_distinct_complete_pngs(pdf_bytes: bytes) -> None:
    with document_tools.PdfPageRenderer(pdf_bytes, image_render_dpi=72) as renderer:
        assert renderer.page_count == 2
        first_png = renderer.render_page(1)
        second_png = renderer.render_page(2)

    # Decode the actual PNGs, not just their filename/header. PDF coordinates
    # start at the bottom; image coordinates start at the top of the page.
    with Image.open(BytesIO(first_png)) as first, Image.open(BytesIO(second_png)) as second:
        assert first.format == second.format == "PNG"
        assert first.size == second.size == (300, 200)
        first_rgb, second_rgb = first.convert("RGB"), second.convert("RGB")
        try:
            assert first_rgb.getpixel((30, 160)) == (0, 0, 0)
            assert second_rgb.getpixel((30, 160)) == (255, 255, 255)
            assert first_rgb.getpixel((170, 80)) == (255, 255, 255)
            assert second_rgb.getpixel((170, 80)) == (0, 0, 0)
        finally:
            first_rgb.close()
            second_rgb.close()


def test_requested_dpi_controls_dimensions_without_cropping(pdf_bytes: bytes) -> None:
    png = document_tools.render_page_image(pdf_bytes, 1, image_render_dpi=144)

    with Image.open(BytesIO(png)) as image:
        assert image.size == (600, 400)
        assert image.info["dpi"][0] == pytest.approx(144, abs=0.1)


def test_on_demand_rendering_returns_bytes_without_saving_files(pdf_bytes: bytes, tmp_path) -> None:
    original_bytes = bytes(pdf_bytes)

    result = document_tools.render_page_image(pdf_bytes, 2)

    assert isinstance(result, bytes)
    assert result.startswith(b"\x89PNG\r\n\x1a\n")
    assert pdf_bytes == original_bytes
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("page_number", [0, -1, 3, True, "1", None])
def test_rejects_invalid_page_numbers(pdf_bytes: bytes, page_number: object) -> None:
    with document_tools.PdfPageRenderer(pdf_bytes) as renderer:
        with pytest.raises(ValueError, match="Page number"):
            renderer.render_page(page_number)


@pytest.mark.parametrize("dpi", [0, -1, True, "150", 1.5])
def test_rejects_invalid_dpi_before_opening_a_pdf(dpi: object) -> None:
    with pytest.raises(ValueError, match="DPI"):
        document_tools.PdfPageRenderer(b"not a PDF", image_render_dpi=dpi)


@pytest.mark.parametrize("data", [b"", b"not a PDF"])
def test_reports_unreadable_pdf_as_a_rendering_error(data: bytes) -> None:
    with pytest.raises(document_tools.PageRenderingError, match="Cannot open"):
        document_tools.render_page_image(data, 1)


def test_context_manager_closes_document_and_repeated_close_is_safe(pdf_bytes: bytes) -> None:
    renderer = document_tools.PdfPageRenderer(pdf_bytes)
    with renderer:
        assert renderer.render_page(1)

    renderer.close()
    with pytest.raises(document_tools.PageRenderingError, match="closed"):
        renderer.render_page(1)


def test_refuses_oversized_render_without_allocating_or_downsampling() -> None:
    # The limit must be checked before allocating a huge bitmap. Passing this case
    # means the request fails visibly, not that the renderer quietly lowers DPI.
    with PdfWriter() as writer:
        writer.add_blank_page(width=14400, height=14400)
        with BytesIO() as output:
            writer.write(output)
            data = output.getvalue()

    # Check the allocation guard on a genuine large PDF page before bitmap creation.
    with pytest.raises(document_tools.PageRenderingError, match="would exceed"):
        document_tools.render_page_image(data, 1)


def test_disabled_preparation_settings_do_not_claim_unused_ocr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_version_lookup(package: str) -> str:
        raise AssertionError("Disabled OCR must not inspect or initialize an OCR package.")

    monkeypatch.setattr(document_tools, "version", unexpected_version_lookup)

    assert document_tools.build_preparation_settings(ocr_enabled=False) == {
        "ocr_enabled": False,
        "ocr_engine": None,
        "ocr_version": None,
        "ocr_language": None,
        "image_render_dpi": 150,
        "candidate_image_min_area": 0.10,
    }


@pytest.mark.parametrize("installed_version", ["fixture-version-a", "fixture-version-b"])
def test_enabled_settings_detect_installed_ocr_version_and_default_to_english(
    monkeypatch: pytest.MonkeyPatch, installed_version: str
) -> None:
    def package_version(package: str) -> str:
        assert package == "easyocr"
        return installed_version

    # Metadata is simulated here; this does not install or run an OCR engine.
    monkeypatch.setattr(document_tools, "version", package_version)

    assert document_tools.build_preparation_settings(ocr_enabled=True) == {
        "ocr_enabled": True,
        "ocr_engine": "easyocr",
        "ocr_version": installed_version,
        "ocr_language": "en",
        "image_render_dpi": 150,
        "candidate_image_min_area": 0.10,
    }


def test_settings_accept_explicit_render_and_language_choices(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(document_tools, "version", lambda package: "fixture-version")

    settings = document_tools.build_preparation_settings(
        ocr_enabled=True, ocr_language="fr", image_render_dpi=300
    )

    assert settings["ocr_language"] == "fr"
    assert settings["image_render_dpi"] == 300


def test_enabled_settings_fail_if_ocr_package_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    def missing_package(package: str) -> str:
        raise document_tools.PackageNotFoundError(package)

    monkeypatch.setattr(document_tools, "version", missing_package)

    with pytest.raises(ValueError, match="installed EasyOCR package"):
        document_tools.build_preparation_settings(ocr_enabled=True)


@pytest.mark.parametrize("dpi", [0, -1, True, "150", 1.5])
def test_preparation_settings_reject_invalid_dpi(dpi: object) -> None:
    with pytest.raises(ValueError, match="DPI"):
        document_tools.build_preparation_settings(image_render_dpi=dpi)


@pytest.mark.parametrize("enabled", [0, 1, "true"])
def test_preparation_settings_require_actual_enabled_boolean(enabled: object) -> None:
    with pytest.raises(ValueError, match="Boolean"):
        document_tools.build_preparation_settings(ocr_enabled=enabled)


@pytest.mark.parametrize("language", [None, "", "   "])
def test_enabled_settings_require_language_before_looking_up_ocr(language: object) -> None:
    with pytest.raises(ValueError, match="language"):
        document_tools.build_preparation_settings(ocr_enabled=True, ocr_language=language)
