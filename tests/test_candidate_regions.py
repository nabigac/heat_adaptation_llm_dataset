"""Check image screening, preserved crops, and OCR that supplements native text.

The PDF fixtures deliberately place images and text at known coordinates. This
lets us check the selection rule independently of OCR's recognition accuracy.
"""

import copy
import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject,
)

import document_tools
import documents
import storage
import validation


def make_pdf(
    *, matrices=((200, 0, 0, 200, 100, 100),),
    native_text="KEEP NATIVE", text_position=(20, 375),
    rotation=0, crop_box=None, nested=False, image=None,
) -> bytes:
    """Draw image placements on a 400-point square, optionally inside a group."""
    with PdfWriter() as writer:
        page = writer.add_blank_page(width=400, height=400)
        bitmap = DecodedStreamObject()
        # Solid red is useful for checking that coordinate conversion crops the
        # actual image rather than a neighboring blank area of the page.
        bitmap.set_data(image.tobytes() if image is not None else bytes((255, 0, 0)) * 100 * 100)
        bitmap.update({
            NameObject("/Type"): NameObject("/XObject"),
            NameObject("/Subtype"): NameObject("/Image"),
            NameObject("/Width"): NumberObject(image.width if image is not None else 100),
            NameObject("/Height"): NumberObject(image.height if image is not None else 100),
            NameObject("/ColorSpace"): NameObject("/DeviceRGB"),
            NameObject("/BitsPerComponent"): NumberObject(8),
        })
        image_ref = writer._add_object(bitmap)
        xobjects = DictionaryObject({NameObject("/Im0"): image_ref})
        drawings = []
        if nested:
            # The image is 100x100 inside a group scaled by two on the page. Its
            # visible area is therefore 200x200, or 25% of the page.
            form = DecodedStreamObject()
            form.set_data(b"q 100 0 0 100 0 0 cm /Im0 Do Q")
            form.update({
                NameObject("/Type"): NameObject("/XObject"),
                NameObject("/Subtype"): NameObject("/Form"),
                NameObject("/BBox"): ArrayObject([NumberObject(n) for n in (0, 0, 100, 100)]),
                NameObject("/Resources"): DictionaryObject({NameObject("/XObject"): xobjects}),
            })
            xobjects = DictionaryObject({NameObject("/Group"): writer._add_object(form)})
            drawings.append("q 2 0 0 2 100 100 cm /Group Do Q")
        else:
            for matrix in matrices:
                drawings.append("q " + " ".join(str(n) for n in matrix) + " cm /Im0 Do Q")
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/XObject"): xobjects,
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
        })
        if native_text:
            drawings.append(f"BT /F1 12 Tf {text_position[0]} {text_position[1]} Td ({native_text}) Tj ET")
        contents = DecodedStreamObject()
        contents.set_data("\n".join(drawings).encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(contents)
        if crop_box is not None:
            page[NameObject("/CropBox")] = ArrayObject([FloatObject(n) for n in crop_box])
        if rotation:
            page.rotate(rotation)
        with BytesIO() as output:
            writer.write(output)
            return output.getvalue()


@pytest.mark.parametrize(("width", "expected_count"), [(159, 0), (160, 1), (161, 1)])
def test_individual_image_area_threshold_includes_exactly_10_percent(width, expected_count):
    # A 160x100 image occupies exactly 10% of this 400x400 page. Check just
    # below and above that boundary without approximating a square root.
    with document_tools.PdfPageRenderer(make_pdf(matrices=((width, 0, 0, 100, 100, 100),)),
                                        image_render_dpi=72) as renderer:
        regions = renderer.find_candidate_regions(1)
    assert len(regions) == expected_count
    if regions:
        assert regions[0]["area_fraction"] == pytest.approx(width * 100 / 160000)


def test_two_smaller_images_are_not_added_together_to_meet_threshold():
    # Each image occupies 6.25%; their combined 12.5% must not trigger the rule.
    data = make_pdf(matrices=((100, 0, 0, 100, 0, 20), (100, 0, 0, 100, 210, 20)))
    with document_tools.PdfPageRenderer(data) as renderer:
        assert renderer.find_candidate_regions(1) == []


def test_background_image_with_native_text_is_not_a_candidate():
    with document_tools.PdfPageRenderer(make_pdf(matrices=((400, 0, 0, 400, 0, 0),))) as renderer:
        assert renderer.find_candidate_regions(1) == []


def test_existing_text_layer_inside_an_image_prevents_regional_ocr():
    with document_tools.PdfPageRenderer(make_pdf(text_position=(120, 180))) as renderer:
        assert renderer.find_candidate_regions(1) == []


def test_off_page_portion_does_not_count_toward_area():
    with document_tools.PdfPageRenderer(make_pdf(matrices=((160, 0, 0, 100, -80, 100),))) as renderer:
        assert renderer.find_candidate_regions(1) == []


def test_tilted_image_uses_polygon_area_instead_of_exaggerated_bounding_box():
    # A 100x100 image rotated 45 degrees has a bounding box covering 12.5% of
    # this page, while its actual area remains only 6.25%, below the 10% rule.
    diagonal = 100 / (2 ** 0.5)
    data = make_pdf(matrices=((diagonal, diagonal, -diagonal, diagonal, 200, 60),))
    with document_tools.PdfPageRenderer(data) as renderer:
        assert renderer.find_candidate_regions(1) == []


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_crop_coordinates_follow_rotated_and_cropped_page(rotation):
    data = make_pdf(matrices=((100, 0, 0, 100, 100, 100),), native_text="",
                    crop_box=(100, 100, 300, 300), rotation=rotation)
    with document_tools.PdfPageRenderer(data, image_render_dpi=72) as renderer:
        region, = renderer.find_candidate_regions(1)
        full_page = renderer.render_page(1)
    assert region["area_fraction"] == pytest.approx(0.25)
    crop = document_tools.crop_page_image(full_page, region["bounds"], dpi=72)
    with Image.open(BytesIO(crop)) as image:
        assert image.size == (100, 100)
        assert image.convert("RGB").getpixel((50, 50)) == (255, 0, 0)


def test_nested_image_group_transform_is_applied_before_area_and_position():
    with document_tools.PdfPageRenderer(make_pdf(nested=True), image_render_dpi=72) as renderer:
        region, = renderer.find_candidate_regions(1)
    assert region["area_fraction"] == pytest.approx(0.25)
    assert region["bounds"] == [100, 100, 300, 300]


def test_repeated_identical_image_placements_do_not_duplicate_regions():
    matrix = (200, 0, 0, 200, 100, 100)
    with document_tools.PdfPageRenderer(make_pdf(matrices=(matrix, matrix))) as renderer:
        assert len(renderer.find_candidate_regions(1)) == 1


@pytest.mark.parametrize("minimum", [0, -1, 1.01, True, None, "0.10", float("nan")])
def test_invalid_area_threshold_is_rejected(minimum):
    with document_tools.PdfPageRenderer(make_pdf()) as renderer:
        with pytest.raises(ValueError, match="minimum area"):
            renderer.find_candidate_regions(1, min_area=minimum)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    return root


def register_pdf(project, tmp_path, data=None):
    source = tmp_path / "source.pdf"
    source.write_bytes(make_pdf() if data is None else data)
    return documents.register_document(project, source, plan_title="Image chart fixture",
        source_url="https://example.org/plan.pdf", date_accessed="2026-11-02",
        study_set="development")[0]


@pytest.fixture
def controlled_ocr(monkeypatch):
    state = SimpleNamespace(loads=0, images=[], result="CHART LABEL 42")

    class Reader:
        def __init__(self, **kwargs):
            state.loads += 1

        def read_text(self, image_bytes):
            state.images.append(image_bytes)
            if isinstance(state.result, Exception):
                raise state.result
            return state.result

    monkeypatch.setattr(documents, "EasyOcrReader", Reader)
    return state


def test_detection_and_rendering_work_when_ocr_is_explicitly_disabled(project, tmp_path, controlled_ocr):
    entry = register_pdf(project, tmp_path)
    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    _, pages = storage.load_preparation(project, record_path)
    page, = pages
    region, = page["image_regions"]
    assert preparation["schema_version"] == 3
    assert preparation["settings"]["candidate_image_min_area"] == 0.10
    assert preparation["status"] == "ready_with_gaps"
    assert page["text"] == "KEEP NATIVE" and page["text_source"] == "native"
    assert page["image_available"] is True
    assert "10%" in page["problem"]
    assert (project / page["image_path"]).is_file()
    assert (project / region["image_path"]).is_file()
    assert controlled_ocr.loads == 0


def test_mixed_ocr_preserves_native_text_and_uses_only_the_region_crop(project, tmp_path, controlled_ocr):
    entry = register_pdf(project, tmp_path)
    original = (project / entry["pdf_path"]).read_bytes()
    preparation, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    page, = pages
    region, = page["image_regions"]
    assert preparation["status"] == "ready_with_gaps"  # OCR still needs source review.
    assert page["text_source"] == "mixed"
    assert page["text"].startswith("KEEP NATIVE\n\n[OCR supplement from image region 1;")
    assert page["text"].count("KEEP NATIVE") == 1
    assert page["text"].count("CHART LABEL 42") == 1
    assert controlled_ocr.loads == 1
    assert controlled_ocr.images == [(project / region["image_path"]).read_bytes()]
    assert controlled_ocr.images[0] != (project / page["image_path"]).read_bytes()
    assert "native_text" not in page and "ocr_text" not in page
    assert (project / entry["pdf_path"]).read_bytes() == original


def test_failed_regional_ocr_keeps_native_text_and_saved_images(project, tmp_path, controlled_ocr):
    entry = register_pdf(project, tmp_path)
    controlled_ocr.result = document_tools.OcrError("No recognized text")
    preparation, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert pages[0]["text"] == "KEEP NATIVE" and pages[0]["text_source"] == "native"
    assert pages[0]["image_available"] is True
    assert "No recognized text" in pages[0]["problem"]


def test_separate_regions_reuse_one_reader_and_keep_separate_source_labels(project, tmp_path, controlled_ocr):
    data = make_pdf(matrices=((200, 0, 0, 200, 0, 100), (200, 0, 0, 200, 200, 100)))
    entry = register_pdf(project, tmp_path, data)
    _, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    assert len(pages[0]["image_regions"]) == 2
    assert controlled_ocr.loads == 1 and len(controlled_ocr.images) == 2
    assert pages[0]["text"].count("KEEP NATIVE") == 1
    assert "OCR supplement from image region 1" in pages[0]["text"]
    assert "OCR supplement from image region 2" in pages[0]["text"]


@pytest.mark.parametrize("failure", ["inspection", "page-render", "crop"])
def test_image_failures_are_saved_visibly_without_discarding_native_text(
    project, tmp_path, controlled_ocr, monkeypatch, failure,
):
    entry = register_pdf(project, tmp_path)

    def fail(*args, **kwargs):
        error = document_tools.PageInspectionError if failure == "inspection" else document_tools.PageRenderingError
        raise error(f"Simulated {failure} failure")

    if failure == "inspection":
        monkeypatch.setattr(documents.PdfPageRenderer, "find_candidate_regions", fail)
    elif failure == "page-render":
        monkeypatch.setattr(documents.PdfPageRenderer, "render_page", fail)
    else:
        monkeypatch.setattr(documents, "crop_page_image", fail)
    preparation, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == ("failed" if failure == "page-render" else "ready_with_gaps")
    assert pages[0]["text"] == "KEEP NATIVE" and pages[0]["text_source"] == "native"
    assert f"Simulated {failure} failure" in pages[0]["problem"]
    assert controlled_ocr.loads == 0


def test_interrupted_image_publication_preserves_previous_attempt_and_registry(
    project, tmp_path, controlled_ocr, monkeypatch,
):
    entry = register_pdf(project, tmp_path)
    _, first_path = documents.prepare_document(project, entry["plan_id"])
    first_directory = (project / first_path).parent
    before = {str(path.relative_to(first_directory)): path.read_bytes()
              for path in first_directory.rglob("*") if path.is_file()}
    registry_before = (project / "data/registry/plans.json").read_bytes()
    publish = storage._publish_new_bytes

    def fail_crop(destination, data):
        if destination.name.endswith("_region_01.png"):
            raise OSError("Simulated image-publication failure")
        publish(destination, data)

    monkeypatch.setattr(storage, "_publish_new_bytes", fail_crop)
    with pytest.raises(OSError, match="image-publication failure") as caught:
        documents.prepare_document(project, entry["plan_id"])
    second = project / "data/processed/plan_0001/preparation_02"
    assert (second / "images/page_0001.png").is_file()
    assert not (second / "pages.json").exists()
    assert not (second / "preparation.json").exists()
    assert (project / "data/registry/plans.json").read_bytes() == registry_before
    assert {str(path.relative_to(first_directory)): path.read_bytes()
            for path in first_directory.rglob("*") if path.is_file()} == before
    assert "folder retained" in " ".join(caught.value.__notes__)
    assert storage.next_preparation_directory(project, entry["plan_id"]).endswith("preparation_03")


@pytest.mark.parametrize("damage", ["wrong-directory", "wrong-crop-size", "outside-page"])
def test_image_references_and_crop_dimensions_are_checked_on_load(
    project, tmp_path, controlled_ocr, damage,
):
    entry = register_pdf(project, tmp_path)
    preparation, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    region = pages[0]["image_regions"][0]
    if damage == "wrong-directory":
        region["image_path"] = "data/raw/elsewhere.png"
    elif damage == "wrong-crop-size":
        with Image.new("RGB", (5, 5)) as image:
            image.save(project / region["image_path"])
    else:
        region["bounds"][2] = 10000
    (project / preparation["pages_path"]).write_text(json.dumps(pages), encoding="utf-8")
    with pytest.raises(storage.PreparationValidationError):
        storage.load_preparation(project, record_path)


def test_missing_page_or_crop_png_is_reported_on_load(project, tmp_path, controlled_ocr):
    entry = register_pdf(project, tmp_path)
    _, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    (project / pages[0]["image_regions"][0]["image_path"]).unlink()
    with pytest.raises(FileNotFoundError):
        storage.load_preparation(project, record_path)


def test_damaged_crop_is_reported_on_load(project, tmp_path, controlled_ocr):
    entry = register_pdf(project, tmp_path)
    _, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    (project / pages[0]["image_regions"][0]["image_path"]).write_bytes(b"not a PNG")
    with pytest.raises(storage.PreparationValidationError):
        storage.load_preparation(project, record_path)


def test_version_2_preparations_remain_readable_without_rewriting(project, tmp_path, controlled_ocr):
    entry = register_pdf(project, tmp_path)
    preparation, record_path = documents.prepare_document(project, entry["plan_id"], ocr_enabled=False)
    _, pages = storage.load_preparation(project, record_path)
    legacy = copy.deepcopy(preparation)
    legacy["schema_version"] = 2
    legacy["settings"].pop("candidate_image_min_area")
    legacy["pages_path"] = "data/processed/plan_0001/preparation_02/pages.json"
    legacy_pages = copy.deepcopy(pages)
    for page in legacy_pages:
        page.pop("image_path")
        page.pop("image_regions")
    legacy_path = storage.save_preparation(project, legacy, legacy_pages)
    before = (project / legacy_path).read_bytes()
    assert storage.load_preparation(project, legacy_path) == (legacy, legacy_pages)
    assert (project / legacy_path).read_bytes() == before


@pytest.mark.parametrize("mutation", ["mixed-no-ocr", "mixed-no-crop", "low-area", "invalid-bounds", "no-review-note"])
def test_validation_rejects_inconsistent_region_records(project, tmp_path, controlled_ocr, mutation):
    entry = register_pdf(project, tmp_path)
    preparation, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    if mutation == "mixed-no-ocr":
        preparation["settings"].update(ocr_enabled=False, ocr_engine=None, ocr_version=None, ocr_language=None)
    elif mutation == "mixed-no-crop":
        pages[0]["image_regions"][0]["image_path"] = None
    elif mutation == "low-area":
        pages[0]["image_regions"][0]["area_fraction"] = 0.09
    elif mutation == "invalid-bounds":
        pages[0]["image_regions"][0]["bounds"] = [5, 5, 4, 4]
    else:
        pages[0]["problem"] = None
    assert validation.validate_preparation_pages(preparation, pages)


_CACHED_MODELS = all((document_tools.DEFAULT_OCR_MODEL_DIRECTORY / name).is_file()
                     for name in ("craft_mlt_25k.pth", "english_g2.pth"))


@pytest.mark.skipif(not _CACHED_MODELS, reason="Requires explicitly downloaded English OCR models.")
def test_real_ocr_supplements_native_caption_with_image_text(project, tmp_path):
    # This checks the actual neural OCR integration on a clear, known phrase. It
    # does not establish recognition accuracy for real chart labels or tables.
    expected = "OPEN 3 COOLING CENTRES BY 2028"
    with Image.new("RGB", (1200, 300), "white") as image:
        ImageDraw.Draw(image).text((35, 100), expected, font=ImageFont.load_default(size=48), fill="black")
        data = make_pdf(image=image, matrices=((400, 0, 0, 110, 0, 100),))
    entry = register_pdf(project, tmp_path, data)
    _, record_path = documents.prepare_document(project, entry["plan_id"])
    _, pages = storage.load_preparation(project, record_path)
    assert pages[0]["text_source"] == "mixed"
    assert pages[0]["text"].startswith("KEEP NATIVE\n\n")
    assert expected in " ".join(pages[0]["text"].split()).upper()
