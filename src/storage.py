"""Read and save collection metadata, original PDFs, and prepared page data.

The registry is editable collection metadata, so saving deliberately replaces its
previous version. Original PDFs and preparation attempts use new destinations.
Completed run-file storage comes later. Use one writer at a time.
"""

import hashlib
import json
import os
import re
import shutil
import tempfile
from io import BytesIO
from pathlib import Path, PurePosixPath, PureWindowsPath

from validation import (
    ValidationProblem,
    parse_pages_json,
    parse_preparation_json,
    parse_registry_json,
    validate_preparation_pages,
    validate_registry_structure,
)


class RegistryValidationError(ValueError):
    """Stop a storage operation while retaining its structured validation problems."""

    def __init__(self, problems: list[ValidationProblem]) -> None:
        # Keep the records for the future CLI, as well as a readable exception message.
        self.problems = problems
        details = "\n".join(
            f"{problem.location or '$'}: {problem.message}" for problem in problems
        )
        # Initialize the ValueError part of this exception with our explanation.
        super().__init__(f"Registry validation failed:\n{details}")


class PreparationValidationError(ValueError):
    """Stop preparation storage while retaining the structured problem report."""

    def __init__(self, problems: list[ValidationProblem]) -> None:
        # Match the registry exception's interface so callers can inspect problems
        # while still distinguishing which kind of saved data could not be used.
        self.problems = problems
        details = "\n".join(
            f"{problem.location or '$'}: {problem.message}" for problem in problems
        )
        super().__init__(f"Preparation validation failed:\n{details}")


def load_registry(project_root: Path | str) -> dict:
    """Read and structure-check data/registry/plans.json, or raise an error.

    Missing files raise FileNotFoundError; malformed data raises
    RegistryValidationError. Reading never initializes or repairs the registry.
    """
    registry_path = resolve_project_path(project_root, "data/registry/plans.json")
    text = registry_path.read_text(encoding="utf-8")
    registry, problems = parse_registry_json(text)
    if problems:
        raise RegistryValidationError(problems)

    # This is the parser's internal success contract, not an input-validation rule.
    assert registry is not None
    return registry


def save_registry(project_root: Path | str, registry: dict) -> None:
    """Structure-check and atomically save the mutable registry.

    An initial save explicitly creates the registry. Existing damaged registries
    must be restored before this function will replace them. Cross-record and
    source-file checks remain the responsibility of the growing registration flow.
    """
    _require_valid_structure(registry)

    # Serialize before touching files. allow_nan=False keeps output strict JSON;
    # ensure_ascii=False preserves readable Unicode titles in the saved text.
    text = json.dumps(registry, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    registry_path = resolve_project_path(project_root, "data/registry/plans.json")
    if registry_path.exists():
        # A normal save must not silently erase evidence of a damaged registry.
        load_registry(project_root)
    registry_path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = None
    try:
        # The temporary file must share the destination's directory: os.replace
        # can then publish the complete file atomically on the same filesystem.
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=registry_path.parent,
            prefix=".plans-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(text)
            # Move buffered text to the OS, then request that its file data be synced.
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # Readers see the previous complete registry or the new complete registry.
        # This is an atomic replacement, not a backup or a multi-writer transaction.
        os.replace(temporary_path, registry_path)
    finally:
        # Run cleanup after success or a caught/unhandled exception. An abrupt
        # process kill may leave a temporary file, but it does not publish that file.
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def next_plan_id(project_root: Path | str, registry: dict) -> str:
    """Suggest an ID above existing numbered records and stored PDF filenames.

    This function does not reserve the ID or create files. Registration must use
    it in the one-document-at-a-time workflow and refuse to overwrite originals.
    """
    _require_valid_structure(registry)
    used_ids = {plan["plan_id"] for plan in registry["plans"]}

    raw_directory = resolve_project_path(project_root, "data/raw")
    if raw_directory.exists():
        # A previous interrupted import may have saved its PDF before the registry.
        # Consider filenames even if the corresponding registry entry is missing.
        for path in raw_directory.iterdir():
            if path.suffix.lower() == ".pdf":
                used_ids.add(path.stem)

    largest_number = 0
    for plan_id in used_ids:
        # The schema allows string IDs. Only our generated plan_<number> names
        # contribute to this sequence; another valid string ID cannot collide.
        match = re.fullmatch(r"plan_([0-9]+)", plan_id)
        if match:
            largest_number = max(largest_number, int(match.group(1)))

    # :04d pads to at least four digits; plan_10000 still works after plan_9999.
    return f"plan_{largest_number + 1:04d}"


def preserve_original_pdf(
    project_root: Path | str,
    source_path: Path | str,
    plan_id: str,
    expected_sha256: str,
) -> str:
    """Copy the source bytes to a new raw PDF and return its project-relative path.

    A checksum mismatch or filename collision fails before publication. This
    preserves bytes, but does not check PDF readability or study eligibility.
    """
    if re.fullmatch(r"plan_[0-9]+", plan_id) is None:
        raise ValueError("A stored PDF needs a generated plan_<number> ID.")
    relative_path = f"data/raw/{plan_id}.pdf"
    destination = resolve_project_path(project_root, relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = None
    try:
        # Copy into an independent file first. Linking the supplied source itself
        # would let later source edits change our supposedly preserved original.
        with tempfile.NamedTemporaryFile(
            mode="wb", dir=destination.parent, prefix=".pdf-", suffix=".tmp", delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            with Path(source_path).open("rb") as source_file:
                shutil.copyfileobj(source_file, temporary_file)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        # Check the completed copy against the fingerprint used for registration.
        # This also detects source changes between initial hashing and copying.
        with temporary_path.open("rb") as copied_file:
            copied_sha256 = hashlib.file_digest(copied_file, "sha256").hexdigest()
        if copied_sha256 != expected_sha256.lower():
            raise ValueError("The copied PDF differs from its expected checksum; retry import.")

        # A hard link gives our completed temporary file its final name. Unlike
        # os.replace, os.link fails if the destination already exists. Both names
        # refer to our independent copy until the temporary name is removed below.
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return relative_path


def next_preparation_directory(project_root: Path | str, plan_id: str) -> str:
    """Suggest a new project-relative preparation folder without creating it.

    Count existing numbered entries, including incomplete attempts. This does not
    reserve a name; save_preparation must still refuse an occupied destination.
    """
    if re.fullmatch(r"plan_[0-9]+", plan_id) is None:
        raise ValueError("A preparation needs a generated plan_<number> ID.")
    relative_parent = f"data/processed/{plan_id}"
    parent = resolve_project_path(project_root, relative_parent)

    largest_number = 0
    if parent.exists():
        for path in parent.iterdir():
            # Consider names even if they are incomplete folders or unexpected
            # files. Never reuse an occupied preparation number or fill old gaps.
            match = re.fullmatch(r"preparation_([0-9]+)", path.name)
            if match:
                largest_number = max(largest_number, int(match.group(1)))

    # :02d means at least two digits; the sequence can continue past preparation_99.
    return f"{relative_parent}/preparation_{largest_number + 1:02d}"


def save_preparation(
    project_root: Path | str, preparation: dict, pages: list[dict],
    *, artifacts: dict[str, bytes] | None = None,
) -> str:
    """Validate and preserve a new preparation and images, returning its record path.

    The preparation's pages_path selects its new folder. Existing folders are
    never reused, even if empty or damaged. This function does not edit the
    registry, check the original PDF, or establish that an OCR route works.
    """
    problems = validate_preparation_pages(preparation, pages)
    if problems:
        raise PreparationValidationError(problems)
    record_path = _preparation_record_path(preparation)
    relative_directory = str(PurePosixPath(record_path).parent)
    directory = resolve_project_path(project_root, relative_directory)
    artifacts = {} if artifacts is None else artifacts
    # Validate paths, PNGs, and crop dimensions before publishing any files. Every
    # referenced image must be supplied, and unreferenced images are refused.
    _check_preparation_images(project_root, preparation, pages, artifacts=artifacts)

    # Serialize both documents before creating the folder. Encoding and strict
    # JSON failures must not leave an attempt that never started writing data.
    record_text = json.dumps(preparation, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    pages_text = json.dumps(pages, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    # Check UTF-8 encoding now too; isolated Unicode surrogate characters cannot
    # be saved as normal UTF-8, even though Python can hold them in a string.
    record_text.encode("utf-8")
    pages_text.encode("utf-8")

    # exist_ok=False claims a fresh directory and refuses any previous attempt.
    # A suggestion from next_preparation_directory alone does not claim the name.
    directory.mkdir(parents=True, exist_ok=False)
    try:
        for relative_path, image_bytes in artifacts.items():
            destination = resolve_project_path(project_root, relative_path)
            destination.parent.mkdir(parents=True, exist_ok=True)
            _publish_new_bytes(destination, image_bytes)
        _publish_new_json(directory / "pages.json", pages_text)
        # Publish the record last. A loader needs this file before it can read the
        # pair, so an interrupted pages write cannot look like a completed pair.
        _publish_new_json(directory / "preparation.json", record_text)
    except Exception as error:
        # Keep completed files if a later write fails or publication is uncertain.
        # The next allocation skips this folder rather than overwriting evidence.
        error.add_note(
            f"Preparation folder retained at {relative_directory}. "
            "Inspect its files before recovery; a retry must use a new folder."
        )
        raise
    return record_path


def load_preparation(
    project_root: Path | str, preparation_path: str
) -> tuple[dict, list[dict]]:
    """Read and validate an explicitly selected preparation record and its pages.

    Return (preparation, pages). Missing files raise FileNotFoundError; invalid
    saved JSON or inconsistent data raises PreparationValidationError. Reading
    never repairs data, chooses a newer attempt, or creates missing files.
    """
    record_file = resolve_project_path(project_root, preparation_path)
    preparation, problems = parse_preparation_json(record_file.read_text(encoding="utf-8"))
    if problems:
        raise PreparationValidationError(
            _problems_in_preparation_file(preparation_path, problems)
        )
    assert preparation is not None  # The parser's success contract.

    expected_record_path = _preparation_record_path(preparation)
    if preparation_path != expected_record_path:
        raise PreparationValidationError(
            [
                ValidationProblem(
                    category="reference",
                    location=preparation_path,
                    message=(
                        "Preparation record and pages must belong to the same "
                        f"plan and folder; expected record at {expected_record_path}."
                    ),
                )
            ]
        )

    pages_path = preparation["pages_path"]
    pages_file = resolve_project_path(project_root, pages_path)
    pages, problems = parse_pages_json(pages_file.read_text(encoding="utf-8"))
    if problems:
        raise PreparationValidationError(_problems_in_preparation_file(pages_path, problems))
    assert pages is not None

    problems = validate_preparation_pages(preparation, pages)
    if problems:
        raise PreparationValidationError(problems)
    _check_preparation_images(project_root, preparation, pages)
    return preparation, pages


def _check_preparation_images(
    project_root: Path | str, preparation: dict, pages: list[dict],
    *, artifacts: dict[str, bytes] | None = None,
) -> None:
    """Check preserved image references, using supplied bytes on save and disk on load.

    Fixed filenames keep each page and crop inside its own preparation. Earlier
    version 2 records have no image artifacts and keep their original behavior.
    """
    from PIL import Image

    directory = str(PurePosixPath(preparation["pages_path"]).parent)
    expected_paths = set()
    problems = []

    def inspect_png(path: str, expected_path: str) -> tuple[int, int]:
        if path != expected_path or path in expected_paths:
            raise ValueError(f"Expected a unique preparation image at {expected_path}.")
        expected_paths.add(path)
        resolved = resolve_project_path(project_root, path)
        data = artifacts[path] if artifacts is not None else resolved.read_bytes()
        if not isinstance(data, bytes):
            raise ValueError(f"Image artifact must contain PNG bytes: {path}")
        with Image.open(BytesIO(data)) as image:
            if image.format != "PNG":
                raise ValueError(f"Preparation images must be PNG: {path}")
            size = image.size
            image.verify()
        return size

    for index, page in enumerate(pages):
        if preparation["schema_version"] == 2:
            continue
        stem = f"{directory}/images/page_{page['page_number']:04d}"
        try:
            size = None
            if page["image_path"] is not None:
                size = inspect_png(page["image_path"], f"{stem}.png")
            for region_index, region in enumerate(page["image_regions"], start=1):
                left, top, right, bottom = region["bounds"]
                if size is not None and (right > size[0] or bottom > size[1]):
                    raise ValueError("Candidate bounds extend outside the preserved page image.")
                if region["image_path"] is not None:
                    crop_size = inspect_png(
                        region["image_path"], f"{stem}_region_{region_index:02d}.png"
                    )
                    if crop_size != (right - left, bottom - top):
                        raise ValueError("Candidate PNG dimensions differ from its recorded bounds.")
        except (KeyError, ValueError, OSError) as error:
            # Missing files on load retain the normal FileNotFoundError interface.
            if isinstance(error, FileNotFoundError):
                raise
            problems.append(ValidationProblem("reference", f"pages.json:$[{index}]", str(error)))
    if artifacts is not None and set(artifacts) != expected_paths:
        problems.append(ValidationProblem("reference", "pages.json:$",
            "Supplied image artifacts must match every referenced image, with no extra files."))
    if problems:
        raise PreparationValidationError(problems)


def _preparation_record_path(preparation: dict) -> str:
    """Check the storage layout after schema validation, then derive the record path."""
    # The two captured groups are the plan ID and preparation number. Checking
    # the whole path prevents accidental cross-plan links and unexpected layouts.
    match = re.fullmatch(
        r"data/processed/(plan_[0-9]+)/preparation_([0-9]+)/pages\.json",
        preparation["pages_path"],
    )
    if (
        match is None
        or match.group(1) != preparation["plan_id"]
        or int(match.group(2)) < 1
    ):
        raise PreparationValidationError(
            [
                ValidationProblem(
                    category="reference",
                    location="preparation.json:$.pages_path",
                    message=(
                        "Pages must be stored at data/processed/<plan_id>/"
                        "preparation_<positive number>/pages.json for this plan."
                    ),
                )
            ]
        )
    return str(PurePosixPath(preparation["pages_path"]).with_name("preparation.json"))


def _publish_new_json(destination: Path, text: str) -> None:
    """Publish one completed UTF-8 file without replacing an existing filename."""
    _publish_new_bytes(destination, text.encode("utf-8"))


def _publish_new_bytes(destination: Path, data: bytes) -> None:
    """Publish completed JSON or PNG bytes without overwriting earlier evidence."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(data)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        # As with original PDF storage, a hard link publishes our independent
        # complete temporary file and refuses to replace an occupied filename.
        os.link(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _problems_in_preparation_file(
    relative_path: str, problems: list[ValidationProblem]
) -> list[ValidationProblem]:
    """Identify which saved document has an error, preserving schema setup locations."""
    return [
        ValidationProblem(
            problem.category,
            f"{relative_path}:{problem.location or '$'}",
            problem.message,
        )
        if problem.category in {"syntax", "structure"}
        else problem
        for problem in problems
    ]


def _require_valid_structure(registry: dict) -> None:
    """Translate validation reports into an exception that stops the operation."""
    problems = validate_registry_structure(registry)
    if problems:
        raise RegistryValidationError(problems)


def resolve_project_path(project_root: Path | str, relative_path: str) -> Path:
    """Resolve a project-relative path while keeping file operations inside the root."""
    # Stored paths use forward slashes. Check Windows drives even on macOS so
    # a path does not change meaning if the project is moved to another platform.
    relative = Path(relative_path)
    if (
        not relative_path.strip()
        or relative == Path(".")
        or relative.is_absolute()
        or PureWindowsPath(relative_path).drive
        or "\\" in relative_path
        or ".." in relative.parts
    ):
        raise ValueError(f"Expected a project-relative path without parent traversal: {relative_path}")
    root = Path(project_root).resolve()
    path = root / relative
    # resolve follows existing symbolic links too, so a linked data directory
    # cannot accidentally redirect registry operations outside the project.
    if not path.resolve().is_relative_to(root):
        raise ValueError(f"Project path resolves outside the project root: {path}")
    return path
