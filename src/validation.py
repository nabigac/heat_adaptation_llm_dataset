"""Check JSON syntax, field rules, and preparation page consistency.

These functions return problems without repairing or changing their inputs.
They do not open PDFs or establish that prepared text is accurate. Model-response
repairs belong to the later repair module, not these saved-data readers.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn

from jsonschema import Draft202012Validator, FormatChecker, SchemaError


# Resolve the schema relative to this module, independently of the terminal's path.
_REGISTRY_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "registry.schema.json"
)
_PREPARATION_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "preparation.schema.json"
)
_PAGES_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "pages.schema.json"
)


# A dataclass groups related values into one record. frozen=True prevents later
# reassignment of its fields. These three fields match DESIGN.md Appendix F.
@dataclass(frozen=True)
class ValidationProblem:
    """One reported problem; use dataclasses.asdict when saving it as JSON."""

    category: Literal["syntax", "structure", "reference", "other"]
    location: str | None
    message: str


def validate_registry_structure(data: object) -> list[ValidationProblem]:
    """Return schema problems for decoded data, or an empty list when it passes.

    Passing these checks establishes structure only. It does not establish that
    paths resolve, records are unique, or a fingerprint matches an original PDF.
    """
    return _validate_structure(
        data, _REGISTRY_SCHEMA_PATH, "registry", required_formats=("date",)
    )


def validate_preparation_structure(data: object) -> list[ValidationProblem]:
    """Check preparation fields, including calendar dates and UTC timestamps.

    This checks one record only. Use validate_preparation_pages to also check its
    agreement with decoded page entries. Neither function reads the linked files.
    """
    return _validate_structure(
        data,
        _PREPARATION_SCHEMA_PATH,
        "preparation",
        required_formats=("date", "date-time"),
    )


def validate_pages_structure(data: object) -> list[ValidationProblem]:
    """Check the pages list and each page's fields, without changing page text."""
    return _validate_structure(data, _PAGES_SCHEMA_PATH, "pages")


def validate_preparation_pages(
    preparation: object, pages: object
) -> list[ValidationProblem]:
    """Check both decoded documents and their page count and numbering agreement.

    A valid failed attempt is allowed: valid metadata does not mean preparation
    succeeded. Checking the original PDF, registry links, or a working image/OCR
    route belongs to the later document workflow.
    """
    problems = []
    for document_name, document_problems in (
        ("preparation.json", validate_preparation_structure(preparation)),
        ("pages.json", validate_pages_structure(pages)),
    ):
        for problem in document_problems:
            # Both documents can contain errors. Label field locations with their
            # document, while keeping setup-error locations at the schema file.
            location = problem.location
            if problem.category == "structure":
                location = f"{document_name}:{location}"
            problems.append(
                ValidationProblem(problem.category, location, problem.message)
            )

    # Only inspect fields after both schemas pass. Otherwise a missing key or a
    # wrong input type could cause a Python exception instead of a useful report.
    if problems:
        return problems

    page_count = preparation["page_count"]
    if page_count is None:
        # The preparation schema already requires a failed status in this case.
        # With no identified page count, the design requires an empty pages list.
        if pages:
            problems.append(
                ValidationProblem(
                    category="reference",
                    location="pages.json:$",
                    message="Pages must be empty when preparation page_count is null.",
                )
            )
        return problems

    if len(pages) != page_count:
        problems.append(
            ValidationProblem(
                category="reference",
                location="pages.json:$",
                message=(
                    f"Preparation declares {page_count} pages, "
                    f"but pages.json contains {len(pages)} entries."
                ),
            )
        )

    # The page label records actual use, while settings describe the configured
    # fallback. An OCR-sourced page cannot belong to an OCR-disabled preparation.
    if not preparation["settings"]["ocr_enabled"]:
        for index, page in enumerate(pages):
            if page["text_source"] in {"ocr", "mixed"}:
                problems.append(
                    ValidationProblem(
                        category="reference",
                        location=f"pages.json:$[{index}].text_source",
                        message="OCR-sourced text requires OCR-enabled preparation settings.",
                    )
                )

    # Older preparations have no preserved image references. Validate new fields
    # against their format version without silently inserting them into old data.
    for index, page in enumerate(pages):
        location = f"pages.json:$[{index}]"
        if preparation["schema_version"] == 2:
            if "image_path" in page or "image_regions" in page or page["text_source"] == "mixed":
                problems.append(ValidationProblem("reference", location,
                    "Image artifacts and mixed text require preparation format version 3."))
            continue
        if "image_path" not in page or "image_regions" not in page:
            problems.append(ValidationProblem("reference", location,
                "Version 3 pages require image_path and image_regions."))
            continue
        if page["image_available"] != (page["image_path"] is not None):
            problems.append(ValidationProblem("reference", location + ".image_path",
                "Version 3 image availability must agree with a preserved page-image path."))
        regions = page["image_regions"]
        if page["text_source"] == "mixed" and not any(region["image_path"] for region in regions):
            problems.append(ValidationProblem("reference", location + ".text_source",
                "Mixed text requires a preserved candidate-region image."))
        seen_bounds = set()
        for region_index, region in enumerate(regions):
            bounds = tuple(region["bounds"])
            region_location = f"{location}.image_regions[{region_index}]"
            if bounds[0] >= bounds[2] or bounds[1] >= bounds[3] or bounds in seen_bounds:
                problems.append(ValidationProblem("reference", region_location + ".bounds",
                    "Candidate bounds must have positive extent and must not be duplicated."))
            seen_bounds.add(bounds)
            if region["area_fraction"] < preparation["settings"]["candidate_image_min_area"]:
                problems.append(ValidationProblem("reference", region_location + ".area_fraction",
                    "Candidate area is below the saved detection threshold."))
            if region["image_path"] is not None and page["image_path"] is None:
                problems.append(ValidationProblem("reference", region_location + ".image_path",
                    "A candidate crop requires its preserved full-page image."))
        if regions and page["problem"] is None:
            problems.append(ValidationProblem("reference", location + ".problem",
                "Candidate regions require a review note, including after OCR recovery."))

    # enumerate supplies each list position. Position 0 must hold page 1, and so
    # on. Together with the length check, this enforces complete, unique, ordered
    # numbering without sorting, filling gaps, or building a potentially huge range.
    for index, page in enumerate(pages):
        page_number = page["page_number"]
        expected_number = index + 1
        if page_number > page_count:
            message = f"Page number {page_number} is outside the range 1 to {page_count}."
        elif page_number != expected_number:
            message = (
                f"Expected page {expected_number} at this position, "
                f"found page {page_number}; include every PDF page once in order."
            )
        else:
            continue
        problems.append(
            ValidationProblem(
                category="reference",
                location=f"pages.json:$[{index}].page_number",
                message=message,
            )
        )
    return problems


def parse_registry_json(
    text: str,
) -> tuple[dict | None, list[ValidationProblem]]:
    """Parse and check registry text, returning (data, problems).

    Data is returned only when syntax and schema checks pass. On failure, return
    None and the problems; callers must not save or use an invalid registry.
    This function reads no registry file and performs no repairs or writes.
    """
    return _parse_and_validate(text, validate_registry_structure)


def parse_preparation_json(
    text: str,
) -> tuple[dict | None, list[ValidationProblem]]:
    """Return (preparation, problems), withholding data if syntax or fields fail.

    Passing does not check page agreement; use validate_preparation_pages after
    both this record and its pages have been decoded.
    """
    return _parse_and_validate(text, validate_preparation_structure)


def parse_pages_json(
    text: str,
) -> tuple[list[dict] | None, list[ValidationProblem]]:
    """Return (pages, problems), preserving text, nulls, and the supplied order."""
    return _parse_and_validate(text, validate_pages_structure)


# A leading underscore marks helpers intended for use inside this module.
def _validate_structure(
    data: object,
    schema_path: Path,
    schema_name: str,
    *,
    required_formats: tuple[str, ...] = (),
) -> list[ValidationProblem]:
    """Apply a schema using the same setup checks and reporting for each format."""
    try:
        # An unreadable or malformed rule file must never result in silently
        # accepting unchecked data. Unicode decoding errors are ValueErrors too.
        schema = _decode_json(schema_path.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as error:
        return [
            ValidationProblem(
                category="other",
                location=str(schema_path),
                message=f"Cannot load the {schema_name} schema: {error}",
            )
        ]

    checker = FormatChecker()
    # jsonschema ignores unsupported formats. Explicitly report missing support
    # so unavailable date-time checking cannot let an invalid timestamp pass.
    missing_formats = sorted(set(required_formats) - checker.checkers.keys())
    if missing_formats:
        return [
            ValidationProblem(
                category="other",
                location=str(schema_path),
                message=(
                    f"Cannot validate the {schema_name} schema: "
                    f"required format checkers are unavailable: {', '.join(missing_formats)}."
                ),
            )
        ]

    validator = Draft202012Validator(schema, format_checker=checker)
    # Collect all field violations and keep their presentation order stable.
    errors = sorted(
        validator.iter_errors(data), key=lambda error: (error.json_path, error.message)
    )
    return [
        ValidationProblem(
            category="structure", location=error.json_path, message=error.message
        )
        for error in errors
    ]


def _parse_and_validate(
    text: str,
    structure_validator: Callable[[object], list[ValidationProblem]],
) -> tuple[Any, list[ValidationProblem]]:
    """Decode strict JSON, then call the supplied field-checking function."""
    # Callable describes a function argument: this one takes decoded data and
    # returns a list of problems. Passing the function lets the three public
    # readers share syntax handling while each chooses its own schema rules.
    try:
        data = _decode_json(text)
    except json.JSONDecodeError as error:
        # The decoder provides an exact location for ordinary JSON syntax errors.
        return None, [
            ValidationProblem(
                category="syntax",
                location=f"line {error.lineno}, column {error.colno}",
                message=error.msg,
            )
        ]
    except ValueError as error:
        # Our strict-decoding hooks report ambiguous or non-standard JSON below.
        # Those hooks do not supply positions, so preserve the unknown location.
        return None, [
            ValidationProblem(category="syntax", location=None, message=str(error))
        ]

    # Syntax must pass before field checks can run. Invalid data stays unavailable
    # to the caller, while the original input text remains unchanged.
    problems = structure_validator(data)
    if problems:
        return None, problems
    return data, []


def _decode_json(text: str) -> Any:
    """Decode strict JSON; the schema then determines which data shape is allowed."""
    # Decoding can produce different Python types, hence the Any return hint.
    # Hooks replace the default handling of duplicate keys and non-standard numbers.
    return json.loads(
        text,
        object_pairs_hook=_object_without_duplicate_keys,
        parse_constant=_reject_nonstandard_number,
    )


def _object_without_duplicate_keys(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    """Build one decoded object, failing if a key occurs more than once."""
    result = {}
    for key, value in pairs:
        # The default decoder keeps the last value. Reject duplicates instead of
        # silently discarding an earlier value; this applies to nested objects too.
        if key in result:
            raise ValueError(f"Duplicate JSON field {key!r} is not allowed.")
        result[key] = value
    return result


def _reject_nonstandard_number(value: str) -> NoReturn:
    """Reject NaN and infinities, which Python accepts but JSON does not permit."""
    # NoReturn documents that this function always raises instead of returning data.
    raise ValueError(f"Non-standard JSON number {value!r} is not allowed.")
