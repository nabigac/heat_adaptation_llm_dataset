"""Register prescreened PDFs and preserve their native page-text preparations.

Registration establishes identity and collection metadata. Preparation records
native text first, then checks image regions for potentially missing content.
Selected pages and crops are preserved; OCR replaces failed native extraction or
supplements clean native text. Experts still judge completeness and accuracy.
"""

import hashlib
import logging
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from pypdf import PageObject, PdfReader
from pypdf.errors import DependencyError, PyPdfError

import storage
from document_tools import (
    DEFAULT_IMAGE_RENDER_DPI,
    DEFAULT_OCR_LANGUAGE,
    EasyOcrReader,
    OcrError,
    PageInspectionError,
    PageRenderingError,
    PdfPageRenderer,
    build_preparation_settings,
    crop_page_image,
    ocr_page_image,
)
from validation import validate_registry_structure


def sha256_file(path: Path | str) -> str:
    """Fingerprint file contents, independently of the filename or location."""
    # rb means read binary bytes, avoiding text decoding or newline conversion.
    # file_digest streams the file rather than loading the entire PDF into memory.
    with Path(path).open("rb") as source_file:
        return hashlib.file_digest(source_file, "sha256").hexdigest()


def list_documents(project_root: Path | str) -> list[dict]:
    """Return display records with status read from each linked preparation.

    A genuinely new project returns an empty list without creating files. This is
    shared application code so the CLI does not duplicate registry-reading rules.
    preparation_status is derived for display only; never save it to the registry.
    """
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Project root is not an existing directory: {root}")
    registry = _load_or_start_registry(root)
    _check_registered_records(root, registry)
    entries = []
    for entry in registry["plans"]:
        preparation = _load_registered_preparation(root, entry)
        status = preparation["status"] if preparation is not None else "not_prepared"
        # A new dictionary keeps the extra display field out of registry data.
        entries.append(dict(entry, preparation_status=status))
    return entries


def register_document(
    project_root: Path | str,
    pdf_path: Path | str,
    *,
    plan_title: str,
    source_url: str,
    date_accessed: str,
    study_set: str,
) -> tuple[dict, bool]:
    """Return (plan_entry, created), reusing a matching registered document.

    Arguments after * must be named at the call site. Collection metadata is
    checked before writes. Duplicate imports preserve existing metadata and must
    request the same study set. Use one registration operation at a time.
    """
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Project root is not an existing directory: {root}")
    source = Path(pdf_path).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError(f"The supplied PDF path must identify a file: {source}")

    checksum = sha256_file(source)
    registry = _load_or_start_registry(root)
    _check_registered_records(root, registry)

    # Match on file contents, not titles or filenames. Stored hexadecimal
    # fingerprints may use either case; our newly calculated value is lowercase.
    existing = None
    for plan in registry["plans"]:
        if plan["document_sha256"].lower() == checksum:
            existing = plan
            break  # Stop searching once the matching registered document is found.
    plan_id = existing["plan_id"] if existing else storage.next_plan_id(root, registry)
    entry = {
        "plan_id": plan_id,
        "plan_title": plan_title,
        "pdf_path": existing["pdf_path"] if existing else f"data/raw/{plan_id}.pdf",
        "document_sha256": checksum,
        "source_url": source_url,
        "date_accessed": date_accessed,
        "study_set": study_set,
        "prepared_source_path": existing["prepared_source_path"] if existing else None,
    }
    problems = validate_registry_structure({"schema_version": 1, "plans": [entry]})
    if problems:
        raise storage.RegistryValidationError(problems)
    _check_collection_details(entry)

    if existing is not None:
        if existing["study_set"] != study_set:
            raise ValueError(
                f"This PDF is already registered as {plan_id} in study set "
                f"{existing['study_set']!r}; duplicate import cannot change its study set."
            )
        # Return the saved record, not the incoming metadata candidate. Collection
        # corrections use update_document_metadata instead of duplicate import.
        return existing, False

    entry["pdf_path"] = storage.preserve_original_pdf(root, source, plan_id, checksum)
    updated_registry = {
        "schema_version": 1,
        "plans": registry["plans"] + [entry],
    }
    try:
        storage.save_registry(root, updated_registry)
    except Exception as error:
        # PDF publication and registry replacement are two separate operations.
        # Keep a completed original if the registry save fails or its commit is
        # uncertain; deleting it could damage a registry that actually committed.
        error.add_note(
            f"The completed PDF copy is retained at {entry['pdf_path']}. "
            "Inspect the saved registry before retrying or recovering this import."
        )
        raise
    return entry, True


def update_document_metadata(
    project_root: Path | str,
    plan_id: str,
    *,
    plan_title: str | None = None,
    source_url: str | None = None,
    date_accessed: str | None = None,
    study_set: str | None = None,
) -> tuple[dict, bool]:
    """Return (entry, changed) after an explicit partial collection-metadata edit.

    None means the caller omitted a field; empty strings are supplied values and
    must pass validation. Identity fields and preparation links are not editable
    arguments. Only the registry changes; completed preparations and runs retain
    the metadata they recorded at creation. Use one writer at a time.
    """
    requested = {
        name: value for name, value in {
            "plan_title": plan_title,
            "source_url": source_url,
            "date_accessed": date_accessed,
            "study_set": study_set,
        }.items() if value is not None
    }
    if not requested:
        raise ValueError("Provide at least one collection-metadata field to update.")
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Project root is not an existing directory: {root}")
    registry = storage.load_registry(root)
    _check_registered_records(root, registry)
    selected = next((entry for entry in registry["plans"] if entry["plan_id"] == plan_id), None)
    if selected is None:
        raise ValueError(f"No registered document has plan ID {plan_id!r}.")
    _load_registered_preparation(root, selected)

    updated = dict(selected, **requested)
    problems = validate_registry_structure({"schema_version": 1, "plans": [updated]})
    if problems:
        raise storage.RegistryValidationError(problems)
    _check_collection_details(updated)
    if updated["study_set"] != selected["study_set"]:
        # Keep development exposure from being hidden by relabeling through the
        # expansion set. No extra history file is needed for this fixed assignment.
        if selected["study_set"] == "development":
            raise ValueError("Development plans must remain in the development study set.")
        run_directory = storage.resolve_project_path(root, f"runs/{plan_id}")
        if run_directory.exists() and (
            not run_directory.is_dir() or any(run_directory.iterdir())
        ):
            raise ValueError("Cannot change the study set after model work has been saved for this plan.")
    if updated == selected:
        # An explicit same-value update is a successful no-op. Avoid replacing a
        # registry unnecessarily or implying that saved data changed.
        return selected, False

    updated_plans = [updated if entry["plan_id"] == plan_id else entry for entry in registry["plans"]]
    try:
        storage.save_registry(root, dict(registry, plans=updated_plans))
    except Exception as error:
        # Publication might have completed before an error was reported. Preserve
        # the current registry and let the user inspect it before retrying.
        error.add_note(
            "Metadata update did not report success. Inspect data/registry/plans.json "
            "before retrying; saved PDFs, preparations, and runs were not rewritten."
        )
        raise
    return updated, True


def _load_registered_preparation(project_root: Path, entry: dict) -> dict | None:
    """Load a linked preparation and verify that it describes this original PDF."""
    if entry["prepared_source_path"] is None:
        return None
    preparation, _ = storage.load_preparation(project_root, entry["prepared_source_path"])
    # URL and access-date corrections may differ from an earlier snapshot. These
    # identity fields must still agree; never borrow another plan's readiness.
    if (
        preparation["plan_id"] != entry["plan_id"]
        or preparation["pdf_path"] != entry["pdf_path"]
        or preparation["document_sha256"].lower() != entry["document_sha256"].lower()
    ):
        raise ValueError("The saved preparation does not match the registered PDF identity.")
    return preparation


def prepare_document(
    project_root: Path | str,
    plan_id: str,
    *,
    image_render_dpi: int = DEFAULT_IMAGE_RENDER_DPI,
    ocr_enabled: bool = True,
    ocr_language: str = DEFAULT_OCR_LANGUAGE,
) -> tuple[dict, str]:
    """Return (preparation, record_path) after saving a new attempt and registry link.

    Known PDF-reading failures are saved with status failed. Identity, validation,
    and storage errors raise exceptions. A failed preparation is still a saved
    attempt: inspect its status before model processing. Renderable text gaps
    produce ready_with_gaps; the later model workflow must also check that its
    selected profile supports any image-only gaps that remain. Automatic OCR is
    selective; native text is retained when candidate image regions supply OCR.
    """
    settings = build_preparation_settings(
        image_render_dpi=image_render_dpi, ocr_enabled=ocr_enabled, ocr_language=ocr_language
    )
    root = Path(project_root).resolve()
    if not root.is_dir():
        raise NotADirectoryError(f"Project root is not an existing directory: {root}")
    registry = storage.load_registry(root)
    selected = None
    for entry in registry["plans"]:
        if entry["plan_id"] == plan_id:
            selected = entry
            break
    if selected is None:
        raise ValueError(f"No registered document has plan ID {plan_id!r}.")
    _check_registered_records(root, registry)

    _load_registered_preparation(root, selected)

    pdf_path = storage.resolve_project_path(root, selected["pdf_path"])
    # Keep the exact bytes being processed in memory, so later reads by pypdf do
    # not depend on a file that might change. BytesIO gives those bytes a file-like
    # interface. This is an in-memory input, not another saved copy of the PDF.
    pdf_bytes = pdf_path.read_bytes()
    expected_checksum = selected["document_sha256"].lower()
    if hashlib.sha256(pdf_bytes).hexdigest() != expected_checksum:
        raise ValueError("The PDF changed before preparation; restore the registered original.")

    prepared_at = datetime.now(UTC).isoformat(timespec="seconds")
    page_count, pages, document_problem = _read_pdf_pages(pdf_bytes)
    directory = storage.next_preparation_directory(root, plan_id)
    # A readable caption cannot establish that an image elsewhere on its page
    # contains no text. Inspect every page's image geometry before selecting OCR.
    page_count, pages, image_problem, artifacts = _prepare_page_fallbacks(
        pdf_bytes, page_count, pages, document_problem, settings, directory
    )
    # Also stop if the on-disk original changed while its checked bytes were being
    # processed. A new record must not point to a now-damaged registered input.
    if sha256_file(pdf_path) != expected_checksum:
        raise ValueError("The PDF changed during preparation; restore the registered original.")

    problem = document_problem
    if image_problem is not None:
        problem = f"{problem}\n{image_problem}" if problem else image_problem
    problem_pages = [page["page_number"] for page in pages if page["problem"] is not None]
    if problem_pages:
        page_summary = (
            "Preparation problems are recorded on PDF pages "
            + ", ".join(str(number) for number in problem_pages)
            + "."
        )
        problem = f"{problem}\n{page_summary}" if problem else page_summary

    unreadable_pages = [page["page_number"] for page in pages if not page["readable"]]
    if page_count is None or image_problem is not None or unreadable_pages:
        status = "failed"
        if unreadable_pages:
            route_problem = "No usable reading route for PDF pages " + ", ".join(
                str(number) for number in unreadable_pages
            ) + "."
            problem = f"{problem}\n{route_problem}" if problem else route_problem
    elif problem is not None:
        status = "ready_with_gaps"
        problem += f"\nPage-image rendering checked at {image_render_dpi} DPI; review recorded gaps."
    else:
        status = "ready"

    preparation = {
        "schema_version": 3,
        "plan_id": plan_id,
        "pdf_path": selected["pdf_path"],
        "document_sha256": selected["document_sha256"],
        "source_url": selected["source_url"],
        "date_accessed": selected["date_accessed"],
        "prepared_at": prepared_at,
        "pages_path": f"{directory}/pages.json",
        "page_count": page_count,
        "settings": settings,
        "status": status,
        "problem": problem,
    }
    record_path = storage.save_preparation(root, preparation, pages, artifacts=artifacts)

    # Copy each registry entry before changing the selected link. Completed
    # preparation files remain unchanged, including a previous successful attempt.
    updated_plans = []
    for entry in registry["plans"]:
        updated_entry = dict(entry)
        if entry["plan_id"] == plan_id:
            updated_entry["prepared_source_path"] = record_path
        updated_plans.append(updated_entry)
    try:
        storage.save_registry(root, dict(registry, plans=updated_plans))
    except Exception as error:
        # These are separate saves, not one transaction. Retain the completed pair
        # if linking fails or the registry replacement outcome is uncertain.
        error.add_note(
            f"Completed preparation retained at {record_path}. "
            "Inspect the registry before recovery; a retry uses a new preparation folder."
        )
        raise
    return preparation, record_path


def _prepare_page_fallbacks(
    pdf_bytes: bytes,
    page_count: int | None,
    pages: list[dict],
    document_problem: str | None,
    settings: dict,
    directory: str,
) -> tuple[int | None, list[dict], str | None, dict[str, bytes]]:
    """Inspect regions, render affected pages, and collect images for preservation.

    PNG bytes stay in memory until storage claims a new preparation folder. A
    failed save cannot attach new images to a completed earlier preparation.
    """
    artifacts = {}
    ocr_reader = None
    ocr_initialization_problem = None
    ocr_initialization_attempted = False

    def recognize(image_bytes: bytes) -> str:
        """Load at most one reader, including when initialization fails."""
        # nonlocal updates the variables in this preparation call rather than
        # creating a different reader variable inside this nested function.
        nonlocal ocr_reader, ocr_initialization_problem, ocr_initialization_attempted
        if not ocr_initialization_attempted:
            ocr_initialization_attempted = True
            try:
                ocr_reader = EasyOcrReader(language=settings["ocr_language"])
            except OcrError as error:
                ocr_initialization_problem = str(error)
        if ocr_reader is None:
            raise OcrError(f"OCR unavailable: {ocr_initialization_problem}")
        return ocr_page_image(image_bytes, reader=ocr_reader)

    def note_problem(page: dict, note: str) -> None:
        page["problem"] = f"{page['problem']}\n{note}" if page["problem"] else note

    try:
        with PdfPageRenderer(pdf_bytes, image_render_dpi=settings["image_render_dpi"]) as renderer:
            if page_count is None:
                # A separate reader may identify pages that native parsing could
                # not. Preserve the native failure and make one entry per page.
                page_count = renderer.page_count
                pages = [
                    {
                        "page_number": number,
                        "text": None,
                        "text_source": None,
                        "readable": False,
                        "image_available": False,
                        "image_path": None,
                        "image_regions": [],
                        "problem": "Native text unavailable because opening or counting failed.",
                    }
                    for number in range(1, page_count + 1)
                ]
            elif renderer.page_count != page_count:
                # Different counts make page references ambiguous. Do not align
                # the two readers by guessing, dropping, or renumbering pages.
                raise PageRenderingError(
                    f"Native reader identified {page_count} pages, "
                    f"but image renderer identified {renderer.page_count}."
                )

            for page in pages:
                # Capture the native result before adding a candidate review note.
                # A candidate with good native text needs regional supplements,
                # whereas missing/unreliable native text needs full-page OCR.
                needs_full_ocr = settings["ocr_enabled"] and not page["readable"]
                try:
                    page["image_regions"] = renderer.find_candidate_regions(
                        page["page_number"], min_area=settings["candidate_image_min_area"]
                    )
                except PageInspectionError as error:
                    note_problem(page, f"Image-region inspection problem: {error}")
                if page["image_regions"]:
                    note_problem(
                        page,
                        f"Candidate image regions meet the {settings['candidate_image_min_area']:.0%} "
                        "page-area threshold and have no native text within their bounds; "
                        "potential missing content requires image review.",
                    )
                if document_problem is None and page["problem"] is None:
                    continue
                try:
                    image_bytes = renderer.render_page(page["page_number"])
                except PageRenderingError as error:
                    page["readable"] = False
                    page["problem"] = (
                        f"{page['problem']}\n{error}" if page["problem"] else str(error)
                    )
                else:
                    stem = f"{directory}/images/page_{page['page_number']:04d}"
                    page["image_path"] = f"{stem}.png"
                    artifacts[page["image_path"]] = image_bytes
                    page["image_available"] = True
                    page["readable"] = True
                    for index, region in enumerate(page["image_regions"], start=1):
                        try:
                            crop = crop_page_image(
                                image_bytes, region["bounds"], dpi=settings["image_render_dpi"]
                            )
                        except PageRenderingError as error:
                            note_problem(page, f"Candidate region {index} crop problem: {error}")
                            continue
                        region["image_path"] = f"{stem}_region_{index:02d}.png"
                        artifacts[region["image_path"]] = crop
                        if not settings["ocr_enabled"] or needs_full_ocr:
                            continue
                        try:
                            text = recognize(crop)
                        except OcrError as error:
                            note_problem(page, f"Candidate region {index} OCR problem: {error}")
                        else:
                            # Append only the image region's OCR. Re-OCRing the
                            # full page here would duplicate or degrade native text.
                            page["text"] += (
                                f"\n\n[OCR supplement from image region {index}; "
                                f"verify against page {page['page_number']} image]\n{text}"
                            )
                            page["text_source"] = "mixed"
                            note_problem(page,
                                f"OCR supplemented candidate region {index}; "
                                "verify against the page image.")
                    if needs_full_ocr:
                        try:
                            page["text"] = recognize(image_bytes)
                        except OcrError as error:
                            note_problem(page, f"OCR problem: {error}")
                        else:
                            page["text_source"] = "ocr"
                            note_problem(page,
                                "OCR supplied prepared text; verify it against the page image.")
            return page_count, pages, None, artifacts
    except PageRenderingError as error:
        # When opening/counting fails, or counts disagree, none of the needed
        # image routes has been established. Keep native records and report why.
        for page in pages:
            if document_problem is not None or page["problem"] is not None:
                page["readable"] = False
        return page_count, pages, f"Image fallback unavailable: {error}", artifacts


class _PdfWarningHandler(logging.Handler):
    """Collect pypdf warnings so they become saved preparation problems."""

    def __init__(self) -> None:
        # A logging handler receives messages emitted by a library. Capturing its
        # warnings avoids treating a returned string as an entirely clean read.
        super().__init__(level=logging.WARNING)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _read_pdf_pages(pdf_bytes: bytes) -> tuple[int | None, list[dict], str | None]:
    """Read every identified page, returning (page_count, pages, document_problem)."""
    # These are expected library/input failures. Unexpected programming errors
    # still raise so development does not disguise a bug as a source-text gap.
    read_errors = (PyPdfError, DependencyError, OSError, ValueError, NotImplementedError)
    handler = _PdfWarningHandler()
    logger = logging.getLogger("pypdf")
    previous_level = logger.level
    logger.setLevel(logging.WARNING)
    logger.addHandler(handler)
    try:
        try:
            # Strict mode reports malformed PDFs instead of requesting pypdf's
            # best-effort interpretation. Both contexts release their resources.
            with BytesIO(pdf_bytes) as stream, PdfReader(stream, strict=True) as reader:
                if reader.is_encrypted:
                    return None, [], "Encrypted PDFs are not supported by this preparation step."
                page_count = len(reader.pages)
                if page_count < 1:
                    return None, [], "The PDF contains no identifiable pages."
                opening_warnings = list(handler.messages)
                pages = []
                for index in range(page_count):
                    warning_start = len(handler.messages)
                    try:
                        text, problem = _extract_page_text(reader.pages[index])
                    except read_errors as error:
                        text, problem = None, f"Could not read native page text: {error}"
                    page_warnings = handler.messages[warning_start:]
                    if page_warnings:
                        warning_problem = "PDF reader warnings: " + "; ".join(page_warnings)
                        problem = f"{problem}\n{warning_problem}" if problem else warning_problem
                    pages.append(
                        {
                            "page_number": index + 1,
                            "text": text,
                            # A source label describes origin, including text
                            # retained with warnings; it does not certify accuracy.
                            "text_source": "native" if text is not None else None,
                            "readable": problem is None,
                            # Native extraction does not establish image availability.
                            "image_available": False,
                            "image_path": None,
                            "image_regions": [],
                            "problem": problem,
                        }
                    )
                document_problem = (
                    "PDF reader warnings: " + "; ".join(opening_warnings)
                    if opening_warnings
                    else None
                )
                return page_count, pages, document_problem
        except read_errors as error:
            # Without a reliable count, the design requires null and an empty list.
            return None, [], f"Could not open or count PDF pages: {error}"
    finally:
        # Restrict logging changes to this single-document operation. Do not leave
        # handlers installed or change how later operations configure logging.
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        handler.close()


def _extract_page_text(page: PageObject) -> tuple[str | None, str | None]:
    """Return native text and any detected problem without rewriting the text."""
    text = page.extract_text()
    if not isinstance(text, str):
        return None, "The PDF reader did not return page text."
    if not text.strip():
        contents = page.get_contents()
        has_no_content = contents is None or not contents.get_data().strip()
        # Missing/empty drawing content with no annotations supports a blank-page
        # classification. Images and vector artwork have drawing content too, so
        # empty extracted text alone is never sufficient to call a page blank.
        if has_no_content and not page.get("/Annots"):
            return "", None
        return None, "No usable native text; page blankness is unconfirmed. Image/OCR review is needed."
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return None, "Extracted text cannot be encoded as UTF-8; image/OCR review is needed."
    if "\ufffd" in text:
        # Keep the returned text for inspection, while recording a decoding gap.
        return text, "Extracted text contains Unicode replacement characters; review is needed."
    return text, None


def _load_or_start_registry(project_root: Path) -> dict:
    """Initialize in memory only when no saved research data could be forgotten."""
    registry_path = storage.resolve_project_path(project_root, "data/registry/plans.json")
    if registry_path.exists():
        return storage.load_registry(project_root)

    for relative_path in ("data/raw", "data/processed", "runs"):
        directory = storage.resolve_project_path(project_root, relative_path)
        if directory.exists() and any(directory.iterdir()):
            raise FileNotFoundError(
                f"The registry is missing but {relative_path} contains saved files. "
                "Restore the registry explicitly before importing another PDF."
            )
    return {"schema_version": 1, "plans": []}


def _check_collection_details(entry: dict) -> None:
    """Check text and basic URL syntax after schema types and dates have passed."""
    if not entry["plan_title"].strip():
        raise ValueError("The plan title must contain non-whitespace text.")
    url = entry["source_url"]
    if any(character.isspace() or ord(character) < 32 for character in url):
        raise ValueError("The source URL must not contain whitespace or control characters.")
    try:
        parts = urlsplit(url)
        # Accessing port also checks malformed or out-of-range port numbers.
        _ = parts.port
        valid_url = parts.scheme in {"http", "https"} and bool(parts.hostname)
    except ValueError as error:
        raise ValueError(f"The source URL cannot be parsed: {error}") from error
    if not valid_url:
        raise ValueError("The source URL must be an absolute HTTP or HTTPS URL with a host.")
    # A syntactically plausible URL does not establish official provenance or
    # eligibility. Those are part of expert prescreening; no network request is made.


def _check_registered_records(project_root: Path, registry: dict) -> None:
    """Stop if registered identities, saved PDFs, or preparation paths are damaged."""
    seen_ids = set()
    seen_checksums = set()
    seen_paths = set()
    for entry in registry["plans"]:
        _check_collection_details(entry)
        plan_id = entry["plan_id"]
        checksum = entry["document_sha256"].lower()
        if plan_id in seen_ids or checksum in seen_checksums:
            raise ValueError("The registry contains duplicate plan IDs or PDF checksums.")
        seen_ids.add(plan_id)
        seen_checksums.add(checksum)

        pdf_path = storage.resolve_project_path(project_root, entry["pdf_path"])
        resolved_pdf = pdf_path.resolve()
        if resolved_pdf in seen_paths:
            raise ValueError("Several registry records point to the same saved PDF.")
        seen_paths.add(resolved_pdf)
        if not pdf_path.is_file():
            raise FileNotFoundError(f"The registered original for {plan_id} is missing: {pdf_path}")
        if sha256_file(pdf_path) != checksum:
            raise ValueError(f"The saved original for {plan_id} no longer matches its checksum.")

        if entry["prepared_source_path"] is not None:
            prepared_path = storage.resolve_project_path(
                project_root, entry["prepared_source_path"]
            )
            if not prepared_path.is_file():
                raise FileNotFoundError(
                    f"The saved preparation for {plan_id} is missing: {prepared_path}"
                )
