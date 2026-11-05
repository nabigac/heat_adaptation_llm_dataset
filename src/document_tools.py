"""Render PDF pages and recognize image text for preparation and future MCP tools.

These are local Python functions, not an MCP server yet. The later server can
expose the same rendering and OCR functions and save requested artifacts with a run.
These helpers do not change the PDF or save page text/image artifacts themselves.
PDFium operations must run sequentially, matching our single-document workflow.
"""

import math
from importlib.metadata import PackageNotFoundError, version
from io import BytesIO
from pathlib import Path
from types import TracebackType
from typing import Self

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_raw


# Read this file in three groups: settings/OCR, image geometry, then rendering.
# The functions work with PDF/PNG bytes in memory. documents.py decides when to
# call them; storage.py decides where their returned images/text are preserved.
DEFAULT_IMAGE_RENDER_DPI = 150
DEFAULT_OCR_ENGINE = "easyocr"
DEFAULT_OCR_LANGUAGE = "en"
# This is an individual region's share of the visible page, not a sum of images.
DEFAULT_CANDIDATE_IMAGE_MIN_AREA = 0.10
# Models are separate from installed Python packages and stay out of Git.
DEFAULT_OCR_MODEL_DIRECTORY = Path(__file__).resolve().parents[1] / ".cache" / "easyocr"
# Refuse excessive allocations instead of silently lowering the requested DPI.
# A normal letter-size page at 150 DPI uses about 2.1 million pixels.
_MAX_RENDER_PIXELS = 40_000_000


def build_preparation_settings(
    *,
    image_render_dpi: int = DEFAULT_IMAGE_RENDER_DPI,
    ocr_enabled: bool = True,
    ocr_language: str = DEFAULT_OCR_LANGUAGE,
) -> dict:
    """Build one settings snapshot; this function does not run or enable OCR itself.

    Configuring OCR records the installed package version but does not load its
    models. Engine and language are explicit defaults, not guesses from page contents.
    """
    if (
        isinstance(image_render_dpi, bool)
        or not isinstance(image_render_dpi, int)
        or image_render_dpi < 1
    ):
        # Python considers True an int subclass. Explicitly reject it so a flag
        # cannot accidentally request a one-DPI render.
        raise ValueError("Image rendering DPI must be a positive integer.")
    if not isinstance(ocr_enabled, bool):
        raise ValueError("OCR enabled must be a Boolean.")
    settings = {
        "ocr_enabled": ocr_enabled,
        "ocr_engine": None,
        "ocr_version": None,
        "ocr_language": None,
        "image_render_dpi": image_render_dpi,
        "candidate_image_min_area": DEFAULT_CANDIDATE_IMAGE_MIN_AREA,
    }
    if ocr_enabled:
        if not isinstance(ocr_language, str) or not ocr_language.strip():
            raise ValueError("OCR language must be a nonempty engine language code.")
        try:
            installed_version = version(DEFAULT_OCR_ENGINE)
        except PackageNotFoundError as error:
            # Do not label an unavailable engine as configured or invent its version.
            raise ValueError("EasyOCR settings require an installed EasyOCR package.") from error
        settings.update(
            ocr_engine=DEFAULT_OCR_ENGINE,
            ocr_version=installed_version,
            ocr_language=ocr_language,
        )
    return settings


class OcrError(ValueError):
    """OCR could not initialize or supply usable text for a rendered page."""


class EasyOcrReader:
    """Load English OCR models once and reuse them for one or more page images.

    Normal calls use cached models offline. Pass download_models=True explicitly
    during initial setup; preparation itself does not download missing models.
    CPU mode makes this usable without a GPU service or an LLM model.
    """

    def __init__(
        self,
        *,
        language: str = DEFAULT_OCR_LANGUAGE,
        model_directory: Path | str = DEFAULT_OCR_MODEL_DIRECTORY,
        download_models: bool = False,
    ) -> None:
        if not isinstance(language, str) or not language.strip():
            raise ValueError("OCR language must be a nonempty engine language code.")
        if not isinstance(download_models, bool):
            raise ValueError("Download models must be a Boolean.")
        directory = Path(model_directory).expanduser().resolve()
        if not download_models and not directory.is_dir():
            raise OcrError(
                "EasyOCR model cache is missing. Initialize it once with "
                "EasyOcrReader(download_models=True) before requesting OCR."
            )
        try:
            # Import lazily: native-only preparation and CLI listing should not
            # load PyTorch or allocate neural-network models.
            import easyocr

            self._reader = easyocr.Reader(
                [language],
                gpu=False,
                model_storage_directory=str(directory),
                user_network_directory=str(directory / "user_network"),
                download_enabled=download_models,
                verbose=False,
            )
        except (ImportError, OSError, RuntimeError, ValueError) as error:
            raise OcrError(f"Cannot initialize EasyOCR: {error}") from error

    def read_text(self, image_bytes: bytes) -> str:
        """Recognize encoded page-image bytes and preserve returned text fragments."""
        if not isinstance(image_bytes, bytes) or not image_bytes:
            raise OcrError("OCR requires nonempty encoded page-image bytes.")
        try:
            from PIL import Image

            with Image.open(BytesIO(image_bytes)) as image:
                # BytesIO gives encoded bytes a file-like interface. verify()
                # checks the image container before sending it to recognition.
                image.verify()
            # detail=0 returns text fragments. Keep their reported order and join
            # them with line breaks; do not infer columns or rewrite quotations.
            fragments = self._reader.readtext(
                image_bytes, detail=0, paragraph=False, batch_size=1, workers=0
            )
        except (OSError, RuntimeError, ValueError) as error:
            raise OcrError(f"Could not recognize page text: {error}") from error
        if not isinstance(fragments, list) or not all(isinstance(item, str) for item in fragments):
            raise OcrError("EasyOCR returned an unexpected text result.")
        text = "\n".join(fragments)
        # These checks establish a usable text result, not correct recognition.
        # Plausible but mistaken words/numbers still require source review.
        if not text.strip():
            # No recognized text does not prove that the original page is blank.
            raise OcrError("OCR did not recognize usable text; page blankness remains unconfirmed.")
        try:
            text.encode("utf-8")
        except UnicodeEncodeError as error:
            raise OcrError("OCR text cannot be encoded as UTF-8.") from error
        if "\ufffd" in text:
            raise OcrError("OCR text contains Unicode replacement characters; review is needed.")
        return text


def ocr_page_image(image_bytes: bytes, *, reader: EasyOcrReader | None = None) -> str:
    """OCR one rendered page; pass a shared reader to avoid reloading its models."""
    if reader is None:
        # A caller processing several images can pass one reader to reuse its
        # loaded models. A standalone call constructs its own reader instead.
        reader = EasyOcrReader()
    return reader.read_text(image_bytes)


class PageRenderingError(ValueError):
    """A PDF could not supply a checked page image at the requested settings."""


class PageInspectionError(ValueError):
    """Image-region inspection could not establish a trustworthy candidate list."""


def _clip_polygon(points: list[tuple[float, float]], box: tuple) -> list[tuple[float, float]]:
    """Keep the part of an image polygon inside the visible PDF page rectangle.

    An image can extend beyond a cropped page or be tilted. Counting its entire
    bounding rectangle would exaggerate how much of the visible page it occupies.
    Each pass cuts the polygon at one page edge, retaining intersection points.
    """
    left, bottom, right, top = box
    # Each edge says which coordinate to test (0=x, 1=y), its boundary value,
    # and which side is inside the page. Repeating this clips all four edges.
    edges = ((0, left, True), (0, right, False), (1, bottom, True), (1, top, False))
    for axis, boundary, keep_greater in edges:
        clipped = []
        for start, end in zip(points, points[1:] + points[:1]):
            # Pair each corner with the next, including last-to-first, so the
            # polygon stays closed. When an edge crosses the boundary, retain
            # its intersection point as a new corner of the visible polygon.
            start_inside = start[axis] >= boundary if keep_greater else start[axis] <= boundary
            end_inside = end[axis] >= boundary if keep_greater else end[axis] <= boundary
            if start_inside != end_inside:
                fraction = (boundary - start[axis]) / (end[axis] - start[axis])
                clipped.append(tuple(start[i] + fraction * (end[i] - start[i]) for i in (0, 1)))
            if end_inside:
                clipped.append(end)
        points = clipped
    return points


def _image_polygons(page, form=None, parent_matrix=None, depth: int = 0):
    """Locate images, including images inside positioned PDF object groups.

    A Form XObject is a reusable group of drawing objects. Its transform moves
    its children onto the page; apply every parent transform before measuring.
    Stop with a visible error rather than silently ignoring unusually deep groups.
    """
    if depth > 15:
        raise PageInspectionError("Image groups exceed the supported inspection depth of 15.")
    parent_matrix = parent_matrix if parent_matrix is not None else pdfium.PdfMatrix()
    # A matrix describes scaling/rotation/position. The initial identity matrix
    # leaves coordinates unchanged; nested groups add their own transformations.
    for obj in page.get_objects(form=form, max_depth=1):
        if obj.type == pdfium_raw.FPDF_PAGEOBJ_IMAGE:
            yield [parent_matrix.on_point(*point) for point in obj.get_quad_points()]
        elif obj.type == pdfium_raw.FPDF_PAGEOBJ_FORM:
            # yield from forwards each child image polygon to our caller. It
            # does not collect a second image list or render the group itself.
            yield from _image_polygons(
                page, obj, obj.get_matrix().multiply(parent_matrix), depth + 1
            )


def crop_page_image(image_bytes: bytes, bounds: list[int], *, dpi: int) -> bytes:
    """Crop a rendered PNG using top-left pixel coordinates; never alter its text."""
    from PIL import Image

    try:
        with Image.open(BytesIO(image_bytes)) as image:
            left, top, right, bottom = bounds
            # Reject out-of-image bounds instead of letting Pillow pad the crop
            # with new pixels, which could conceal a coordinate-conversion bug.
            if not (0 <= left < right <= image.width and 0 <= top < bottom <= image.height):
                raise ValueError("Candidate crop lies outside the rendered page.")
            with image.crop((left, top, right, bottom)) as crop, BytesIO() as output:
                crop.save(output, format="PNG", dpi=(dpi, dpi))
                return output.getvalue()
    except (OSError, ValueError) as error:
        raise PageRenderingError(f"Could not crop candidate image: {error}") from error


class PdfPageRenderer:
    """Keep one PDF open while rendering one or more original pages as PNGs."""

    def __init__(
        self, pdf_bytes: bytes, *, image_render_dpi: int = DEFAULT_IMAGE_RENDER_DPI
    ) -> None:
        if isinstance(image_render_dpi, bool) or not isinstance(image_render_dpi, int):
            raise ValueError("Image rendering DPI must be a positive integer.")
        if image_render_dpi < 1:
            raise ValueError("Image rendering DPI must be a positive integer.")
        self.image_render_dpi = image_render_dpi
        self._document = None
        # Opening one renderer per document lets several pages reuse the same
        # PDFium document. The with/close methods below release its resources.
        try:
            self._document = pdfium.PdfDocument(pdf_bytes)
            # Initialize form rendering before retrieving pages, so supported
            # visible form values can appear along with drawing content.
            self._document.init_forms()
            self.page_count = len(self._document)
            if self.page_count < 1:
                raise PageRenderingError("The renderer could not identify any PDF pages.")
        except (pdfium.PdfiumError, OSError, ValueError) as error:
            self.close()
            raise PageRenderingError(f"Cannot open the PDF for rendering: {error}") from error

    def render_page(self, page_number: int) -> bytes:
        """Render a one-based PDF page number, retaining its full page extent."""
        if self._document is None:
            raise PageRenderingError("The PDF renderer is closed.")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or not 1 <= page_number <= self.page_count
        ):
            raise ValueError(f"Page number must be an integer from 1 to {self.page_count}.")

        page = bitmap = image = None
        try:
            page = self._document.get_page(page_number - 1)
            # Our public page numbers start at 1; the rendering library indexes
            # pages from 0. Keep that conversion here, not in saved references.
            width, height = page.get_size()
            scale = self.image_render_dpi / 72  # PDF page units are normally 1/72 inch.
            if not all(math.isfinite(value) and value > 0 for value in (width, height)):
                raise PageRenderingError("The PDF page has invalid dimensions.")
            pixels = math.ceil(width * scale) * math.ceil(height * scale)
            # Check allocation size before page.render creates the bitmap.
            # math.ceil rounds up because a partial pixel still needs storage.
            if pixels > _MAX_RENDER_PIXELS:
                raise PageRenderingError(
                    f"Rendering page {page_number} would exceed {_MAX_RENDER_PIXELS:,} pixels. "
                    "Choose a lower DPI explicitly; the page has not been resized or cropped."
                )
            bitmap = page.render(
                scale=scale, rev_byteorder=True, draw_annots=True, fill_color=(255, 255, 255, 255)
            )
            # A bitmap holds pixels; PNG encoding turns those pixels into the
            # portable image bytes returned to preparation or later tools.
            image = bitmap.to_pil()
            with BytesIO() as output:
                image.save(
                    output, format="PNG", dpi=(self.image_render_dpi, self.image_render_dpi)
                )
                return output.getvalue()
        except (pdfium.PdfiumError, OSError, ValueError) as error:
            raise PageRenderingError(f"Could not render PDF page {page_number}: {error}") from error
        finally:
            # Pillow may share the bitmap's memory. Finish encoding and close the
            # image before releasing that bitmap, then release its PDF page.
            if image is not None:
                image.close()
            if bitmap is not None:
                bitmap.close()
            if page is not None:
                page.close()

    def find_candidate_regions(
        self, page_number: int, *, min_area: float = DEFAULT_CANDIDATE_IMAGE_MIN_AREA
    ) -> list[dict]:
        """Return large image regions with no native text inside their bounds.

        This is a screening rule, not a claim that the images contain text. Photos
        can qualify, and smaller charts or images with partial text layers can be
        missed. Bounds describe crops of the full-page render at this reader's DPI.
        """
        if self._document is None:
            raise PageInspectionError("The PDF renderer is closed.")
        if (
            isinstance(page_number, bool)
            or not isinstance(page_number, int)
            or not 1 <= page_number <= self.page_count
        ):
            raise ValueError(f"Page number must be an integer from 1 to {self.page_count}.")
        if (
            isinstance(min_area, bool)
            or not isinstance(min_area, (int, float))
            or not 0 < min_area <= 1
        ):
            raise ValueError("Candidate minimum area must be a fraction greater than 0 and at most 1.")
        page = textpage = None
        try:
            page = self._document.get_page(page_number - 1)
            box = page.get_bbox()
            width, height = page.get_size()
            if not all(math.isfinite(value) for value in (*box, width, height)):
                raise PageInspectionError("The PDF page has non-finite dimensions.")
            area = (box[2] - box[0]) * (box[3] - box[1])
            if area <= 0 or width <= 0 or height <= 0:
                raise PageInspectionError("The PDF page has invalid dimensions.")
            scale = self.image_render_dpi / 72
            pixels_w, pixels_h = math.ceil(width * scale), math.ceil(height * scale)
            converter = pdfium.PdfPosConv(page, (0, 0, pixels_w, pixels_h, 0))
            # PDF coordinates and top-left image coordinates differ. This
            # converter accounts for page geometry when producing crop bounds.
            textpage = page.get_textpage()
            candidates = []
            seen_bounds = set()
            for polygon in _image_polygons(page):
                if not all(math.isfinite(value) for point in polygon for value in point):
                    raise PageInspectionError("An image has non-finite coordinates.")
                polygon = _clip_polygon(polygon, box)
                # The shoelace formula measures the clipped polygon's area,
                # including a tilted image rather than its larger bounding box.
                image_area = abs(sum(
                    start[0] * end[1] - end[0] * start[1]
                    for start, end in zip(polygon, polygon[1:] + polygon[:1])
                )) / 2
                fraction = image_area / area
                # Test each image independently. Using < retains an image
                # exactly at the threshold; smaller images are not added up.
                if fraction < min_area:
                    continue
                left, right = min(p[0] for p in polygon), max(p[0] for p in polygon)
                bottom, top = min(p[1] for p in polygon), max(p[1] for p in polygon)
                if textpage.get_text_bounded(left, bottom, right, top, errors="strict").strip():
                    # Native text in this rectangle excludes the candidate. This
                    # heuristic can miss partially readable image text; it is a
                    # screening rule rather than a completeness guarantee.
                    continue
                pixels = [converter.to_bitmap(*point) for point in polygon]
                bounds = (
                    max(0, min(point[0] for point in pixels)),
                    max(0, min(point[1] for point in pixels)),
                    min(pixels_w, max(point[0] for point in pixels)),
                    min(pixels_h, max(point[1] for point in pixels)),
                )
                # Clamp the crop to the full-page image. Candidate metadata and
                # later cropping must refer to that same preserved image frame.
                if bounds[0] >= bounds[2] or bounds[1] >= bounds[3]:
                    raise PageInspectionError("Candidate image has no usable crop at the selected DPI.")
                if bounds in seen_bounds:
                    continue  # Repeated PDF image objects must not duplicate OCR text.
                seen_bounds.add(bounds)
                candidates.append({
                    "bounds": list(bounds),
                    "area_fraction": min(fraction, 1.0),
                    "image_path": None,
                })
            return sorted(
                candidates, key=lambda region: (region["bounds"][1], region["bounds"][0])
            )
        except (pdfium.PdfiumError, OSError, ValueError, UnicodeError) as error:
            raise PageInspectionError(f"Could not inspect PDF page {page_number}: {error}") from error
        finally:
            if textpage is not None:
                textpage.close()
            if page is not None:
                page.close()

    def close(self) -> None:
        """Release the document; repeated close calls are harmless."""
        if self._document is not None:
            self._document.close()
            self._document = None

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        # Python calls this when a with block ends, including after an exception.
        self.close()


def render_page_image(
    pdf_bytes: bytes,
    page_number: int,
    *,
    image_render_dpi: int = DEFAULT_IMAGE_RENDER_DPI,
) -> bytes:
    """Render one page on demand; callers can save the returned PNG with their run."""
    with PdfPageRenderer(pdf_bytes, image_render_dpi=image_render_dpi) as renderer:
        return renderer.render_page(page_number)
