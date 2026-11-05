"""Check the preparation and page data contracts from DESIGN.md Appendix A.

These fictional examples do not open PDFs or create saved preparations. They
check field rules. Later Python validation must check agreement between files,
page numbering, and links to the registered original.
"""
# These are field-level schema checks. Python cross-document checks and file
# loading have separate tests. Parametrized values keep one rule under test at a
# time, including the difference between a missing key and a present null value.

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


# Each module-scoped fixture loads a real schema once for this test file.
# check_schema checks the rules themselves; validate later checks example data.
@pytest.fixture(scope="module")
def preparation_validator() -> Draft202012Validator:
    # Check the rule document itself, then enable optional format checking.
    # Without FormatChecker, date/date-time annotations alone would not reject
    # impossible calendar values.
    schema_path = (
        Path(__file__).resolve().parents[1] / "schemas" / "preparation.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)

    checker = FormatChecker()
    # Unknown formats are silently ignored by jsonschema. Require both checkers
    # here so a missing optional dependency cannot make timestamp tests misleading.
    assert {"date", "date-time"} <= checker.checkers.keys()
    return Draft202012Validator(schema, format_checker=checker)


@pytest.fixture(scope="module")
def pages_validator() -> Draft202012Validator:
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "pages.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


# Default fixture scope creates fresh dictionaries and lists for each test.
# A test can edit its example without changing another test's starting data.
@pytest.fixture
def valid_preparation() -> dict:
    return {
        "schema_version": 2,
        "plan_id": "plan_0001",
        "pdf_path": "data/raw/plan_0001.pdf",
        "document_sha256": "a" * 64,  # A fictional fingerprint, not a real PDF hash.
        "source_url": "https://example.org/heat-plan.pdf",
        "date_accessed": "2026-11-02",
        "prepared_at": "2026-11-02T10:30:00Z",
        "pages_path": "data/processed/plan_0001/preparation_01/pages.json",
        "page_count": 2,
        "settings": {
            "ocr_enabled": False,
            "ocr_engine": None,
            "ocr_version": None,
            "ocr_language": None,
            "image_render_dpi": 150,
        },
        "status": "ready",
        "problem": None,  # Python's None represents JSON null.
    }


@pytest.fixture
def valid_pages() -> list[dict]:
    # These dictionaries model saved page fields; they are not extracted here
    # from a PDF. Tests change their values to check the schema's individual rules.
    return [
        {
            "page_number": 1,
            "text": "Example Heat Adaptation Plan\nKeep public cooling spaces open.",
            "text_source": "native",
            "readable": True,
            "image_available": True,
            "problem": None,
        },
        {
            "page_number": 2,
            "text": "",  # This fictional page is known to be blank.
            "text_source": "native",
            "readable": True,
            "image_available": True,
            "problem": None,
        },
    ]


# Each row replaces selected fields in the otherwise valid preparation.
# Successful validation returns normally; an unexpected error fails the test.
@pytest.mark.parametrize(
    "changes",
    [
        pytest.param({}, id="ready"),
        pytest.param(
            {"status": "ready_with_gaps", "problem": "One page needs the tested image route."},
            id="ready-with-gaps",
        ),
        pytest.param(
            {"status": "failed", "problem": "No usable reading route was established."},
            id="failed-with-known-count",
        ),
        pytest.param(
            {"status": "failed", "page_count": None, "problem": "Could not open PDF."},
            id="failed-with-unknown-count",
        ),
        pytest.param({"document_sha256": "A" * 64}, id="uppercase-checksum"),
        pytest.param(
            {"date_accessed": "2024-02-29", "prepared_at": "2024-02-29T00:00:00Z"},
            id="valid-leap-day",
        ),
        pytest.param(
            {"prepared_at": "2026-11-02T10:30:00.123456Z"}, id="fractional-seconds"
        ),
        pytest.param(
            {"prepared_at": "2026-11-02T10:30:00+00:00"}, id="explicit-utc-offset"
        ),
        pytest.param({"prepared_at": "2026-11-02t10:30:00z"}, id="lowercase-utc"),
    ],
)
def test_accepts_valid_preparation_variations(
    preparation_validator: Draft202012Validator,
    valid_preparation: dict,
    changes: dict,
) -> None:
    valid_preparation.update(changes)
    preparation_validator.validate(valid_preparation)


# Required means the key must exist, even when its allowed value includes null.
@pytest.mark.parametrize(
    "field_name",
    [
        "schema_version",
        "plan_id",
        "pdf_path",
        "document_sha256",
        "source_url",
        "date_accessed",
        "prepared_at",
        "pages_path",
        "page_count",
        "settings",
        "status",
        "problem",
    ],
)
def test_rejects_missing_preparation_field(
    preparation_validator: Draft202012Validator,
    valid_preparation: dict,
    field_name: str,
) -> None:
    del valid_preparation[field_name]
    with pytest.raises(ValidationError) as error:
        preparation_validator.validate(valid_preparation)

    # Checking the reason ensures an unrelated error cannot satisfy this test.
    assert error.value.validator == "required"
    assert list(error.value.absolute_path) == []


def test_rejects_unknown_preparation_field(
    preparation_validator: Draft202012Validator, valid_preparation: dict
) -> None:
    valid_preparation["page_total"] = 2  # A misspelled or invented field must fail.
    with pytest.raises(ValidationError) as error:
        preparation_validator.validate(valid_preparation)
    assert error.value.validator == "additionalProperties"


@pytest.mark.parametrize("invalid_data", [[], "preparation", None])
def test_rejects_preparation_that_is_not_an_object(
    preparation_validator: Draft202012Validator, invalid_data: object
) -> None:
    with pytest.raises(ValidationError):
        preparation_validator.validate(invalid_data)


# Introduce one invalid field at a time to make each rejection easy to interpret.
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        pytest.param("schema_version", 1, id="old-preparation-format"),
        pytest.param("schema_version", "1", id="string-version"),
        # Python bool is an int subclass; JSON Schema still distinguishes them.
        pytest.param("schema_version", True, id="boolean-version"),
        pytest.param("document_sha256", "a" * 63, id="short-checksum"),
        pytest.param("document_sha256", "a" * 65, id="long-checksum"),
        pytest.param("document_sha256", "g" * 64, id="non-hexadecimal-checksum"),
        pytest.param("document_sha256", "a" * 63 + "\n", id="checksum-newline"),
        pytest.param("date_accessed", "2026-02-29", id="impossible-access-date"),
        pytest.param("date_accessed", "11-02-2026", id="wrong-date-order"),
        pytest.param("date_accessed", "2026-11-02T10:30:00Z", id="access-date-is-timestamp"),
        pytest.param("page_count", 0, id="zero-page-count"),
        pytest.param("page_count", -1, id="negative-page-count"),
        pytest.param("page_count", 1.5, id="fractional-page-count"),
        pytest.param("page_count", True, id="boolean-page-count"),
        pytest.param("page_count", "2", id="string-page-count"),
        pytest.param("status", "succeeded", id="unsupported-status"),
        pytest.param("problem", [], id="problem-must-be-text-or-null"),
    ],
)
def test_rejects_invalid_preparation_values(
    preparation_validator: Draft202012Validator,
    valid_preparation: dict,
    field_name: str,
    invalid_value: object,
) -> None:
    valid_preparation[field_name] = invalid_value
    with pytest.raises(ValidationError):
        preparation_validator.validate(valid_preparation)


@pytest.mark.parametrize("status", ["ready", "ready_with_gaps"])
def test_requires_known_page_count_for_usable_preparation(
    preparation_validator: Draft202012Validator, valid_preparation: dict, status: str
) -> None:
    # A null count is permitted only for failed attempts, not usable preparations.
    valid_preparation.update(status=status, page_count=None)
    with pytest.raises(ValidationError) as error:
        preparation_validator.validate(valid_preparation)
    assert list(error.value.absolute_path) == ["page_count"]


# Stacked parametrization tests every combination of field and invalid value.
@pytest.mark.parametrize("field_name", ["plan_id", "pdf_path", "source_url", "pages_path"])
@pytest.mark.parametrize("invalid_value", ["", None, 123], ids=["empty", "null", "number"])
def test_rejects_invalid_required_preparation_text(
    preparation_validator: Draft202012Validator,
    valid_preparation: dict,
    field_name: str,
    invalid_value: object,
) -> None:
    valid_preparation[field_name] = invalid_value
    with pytest.raises(ValidationError):
        preparation_validator.validate(valid_preparation)


@pytest.mark.parametrize(
    "timestamp",
    [
        pytest.param("2026-02-29T10:30:00Z", id="impossible-calendar-date"),
        pytest.param("2026-11-02T25:30:00Z", id="impossible-hour"),
        pytest.param("2026-11-02T10:60:00Z", id="impossible-minute"),
        pytest.param("2026-11-02", id="date-without-time"),
        pytest.param("2026-11-02T10:30:00", id="missing-timezone"),
        pytest.param("2026-11-02T10:30:00+01:00", id="positive-non-utc-offset"),
        pytest.param("2026-11-02T10:30:00-05:00", id="negative-non-utc-offset"),
        pytest.param("2026-11-02T10:30:00-00:00", id="unknown-local-offset"),
        pytest.param("2026-11-02T10:30:00Z\n", id="trailing-newline"),
        pytest.param("2026-11-02 10:30:00Z", id="space-instead-of-t"),
        pytest.param(None, id="null-timestamp"),
    ],
)
def test_rejects_invalid_or_non_utc_timestamp(
    preparation_validator: Draft202012Validator,
    valid_preparation: dict,
    timestamp: object,
) -> None:
    valid_preparation["prepared_at"] = timestamp
    with pytest.raises(ValidationError) as error:
        preparation_validator.validate(valid_preparation)
    assert list(error.value.absolute_path) == ["prepared_at"]


def test_accepts_page_text_and_known_blank_page(
    pages_validator: Draft202012Validator, valid_pages: list[dict]
) -> None:
    pages_validator.validate(valid_pages)


def test_accepts_page_with_unavailable_text(
    pages_validator: Draft202012Validator, valid_pages: list[dict]
) -> None:
    # Preserve a known page even if text preparation fails. Null is different
    # from the empty string used for a known blank page in valid_pages.
    valid_pages[0].update(
        text=None,
        text_source=None,
        readable=False,
        image_available=False,
        problem="Text extraction and page rendering failed.",
    )
    pages_validator.validate(valid_pages)


def test_accepts_empty_pages_when_count_is_unavailable(
    pages_validator: Draft202012Validator,
) -> None:
    # Pairing this list with a failed preparation and null count is checked later
    # by Python, because the pages schema cannot inspect preparation.json.
    pages_validator.validate([])


@pytest.mark.parametrize(
    "field_name", ["page_number", "text", "text_source", "readable", "image_available", "problem"]
)
def test_rejects_missing_page_field(
    pages_validator: Draft202012Validator, valid_pages: list[dict], field_name: str
) -> None:
    del valid_pages[0][field_name]
    with pytest.raises(ValidationError) as error:
        pages_validator.validate(valid_pages)
    assert error.value.validator == "required"
    assert list(error.value.absolute_path) == [0]  # First entry in the pages list.


def test_rejects_unknown_page_field(
    pages_validator: Draft202012Validator, valid_pages: list[dict]
) -> None:
    valid_pages[0]["printed_page_label"] = "i"
    with pytest.raises(ValidationError) as error:
        pages_validator.validate(valid_pages)
    assert error.value.validator == "additionalProperties"


@pytest.mark.parametrize("invalid_data", [{"pages": []}, "pages", None])
def test_rejects_pages_that_are_not_a_list(
    pages_validator: Draft202012Validator, invalid_data: object
) -> None:
    with pytest.raises(ValidationError):
        pages_validator.validate(invalid_data)


@pytest.mark.parametrize("invalid_page", ["page one", None, []])
def test_rejects_page_that_is_not_an_object(
    pages_validator: Draft202012Validator, invalid_page: object
) -> None:
    with pytest.raises(ValidationError):
        pages_validator.validate([invalid_page])


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        pytest.param("page_number", 0, id="zero-page-number"),
        pytest.param("page_number", -1, id="negative-page-number"),
        pytest.param("page_number", 1.5, id="fractional-page-number"),
        pytest.param("page_number", True, id="boolean-page-number"),
        pytest.param("page_number", "1", id="string-page-number"),
        pytest.param("text", 123, id="number-instead-of-text"),
        pytest.param("text", [], id="list-instead-of-text"),
        pytest.param("problem", {}, id="object-instead-of-problem-text"),
    ],
)
def test_rejects_invalid_page_values(
    pages_validator: Draft202012Validator,
    valid_pages: list[dict],
    field_name: str,
    invalid_value: object,
) -> None:
    valid_pages[0][field_name] = invalid_value
    with pytest.raises(ValidationError) as error:
        pages_validator.validate(valid_pages)
    assert list(error.value.absolute_path) == [0, field_name]


@pytest.mark.parametrize("field_name", ["readable", "image_available"])
@pytest.mark.parametrize("invalid_value", ["true", 1, None], ids=["text", "number", "null"])
def test_requires_actual_page_booleans(
    pages_validator: Draft202012Validator,
    valid_pages: list[dict],
    field_name: str,
    invalid_value: object,
) -> None:
    # JSON true/false must not be confused with the string "true" or the number 1.
    valid_pages[0][field_name] = invalid_value
    with pytest.raises(ValidationError):
        pages_validator.validate(valid_pages)


def test_accepts_ocr_source_with_recognized_text(
    pages_validator: Draft202012Validator, valid_pages: list[dict]
) -> None:
    # This checks the format only, not an actual OCR engine or its accuracy.
    valid_pages[0]["text_source"] = "ocr"
    pages_validator.validate(valid_pages)


@pytest.mark.parametrize(
    ("text", "source"),
    [
        pytest.param("Native text", None, id="text-without-source"),
        pytest.param(None, "native", id="native-source-without-text"),
        pytest.param(None, "ocr", id="ocr-source-without-text"),
        pytest.param("", "ocr", id="empty-ocr-is-not-known-blank"),
        pytest.param(" \n", "ocr", id="whitespace-ocr-is-not-known-blank"),
        pytest.param("Some text", "manual", id="unknown-source"),
        pytest.param("Some text", True, id="boolean-source"),
    ],
)
def test_rejects_inconsistent_text_source(
    pages_validator: Draft202012Validator,
    valid_pages: list[dict],
    text: object,
    source: object,
) -> None:
    valid_pages[0].update(text=text, text_source=source)
    with pytest.raises(ValidationError):
        pages_validator.validate(valid_pages)


def test_accepts_enabled_ocr_settings(
    preparation_validator: Draft202012Validator, valid_preparation: dict
) -> None:
    valid_preparation["settings"].update(
        ocr_enabled=True, ocr_engine="easyocr", ocr_version="test-version", ocr_language="en"
    )
    preparation_validator.validate(valid_preparation)


@pytest.mark.parametrize(
    "field_name", ["ocr_enabled", "ocr_engine", "ocr_version", "ocr_language", "image_render_dpi"]
)
def test_requires_each_shared_preparation_setting(
    preparation_validator: Draft202012Validator, valid_preparation: dict, field_name: str
) -> None:
    del valid_preparation["settings"][field_name]
    with pytest.raises(ValidationError) as error:
        preparation_validator.validate(valid_preparation)
    assert error.value.validator == "required"
    assert list(error.value.absolute_path) == ["settings"]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        pytest.param("ocr_enabled", "false", id="enabled-is-not-text"),
        pytest.param("image_render_dpi", 0, id="zero-dpi"),
        pytest.param("image_render_dpi", -1, id="negative-dpi"),
        pytest.param("image_render_dpi", True, id="boolean-dpi"),
        pytest.param("image_render_dpi", 1.5, id="fractional-dpi"),
        pytest.param("ocr_engine", "easyocr", id="disabled-engine-must-be-null"),
        pytest.param("ocr_version", "test-version", id="disabled-version-must-be-null"),
        pytest.param("ocr_language", "en", id="disabled-language-must-be-null"),
    ],
)
def test_rejects_invalid_preparation_settings(
    preparation_validator: Draft202012Validator,
    valid_preparation: dict,
    field_name: str,
    value: object,
) -> None:
    valid_preparation["settings"][field_name] = value
    with pytest.raises(ValidationError):
        preparation_validator.validate(valid_preparation)


@pytest.mark.parametrize("field_name", ["ocr_engine", "ocr_version", "ocr_language"])
@pytest.mark.parametrize("value", [None, ""], ids=["null", "empty"])
def test_enabled_ocr_requires_its_engine_version_and_language(
    preparation_validator: Draft202012Validator,
    valid_preparation: dict,
    field_name: str,
    value: object,
) -> None:
    valid_preparation["settings"].update(
        ocr_enabled=True, ocr_engine="easyocr", ocr_version="test-version", ocr_language="en"
    )
    valid_preparation["settings"][field_name] = value
    with pytest.raises(ValidationError):
        preparation_validator.validate(valid_preparation)


def test_rejects_unknown_preparation_setting(
    preparation_validator: Draft202012Validator, valid_preparation: dict
) -> None:
    valid_preparation["settings"]["unknown"] = True
    with pytest.raises(ValidationError) as error:
        preparation_validator.validate(valid_preparation)
    assert error.value.validator == "additionalProperties"
