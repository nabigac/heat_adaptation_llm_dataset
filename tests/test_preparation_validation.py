"""Check application validation of preparation records and page entries.

Schema tests cover individual field rules separately. These tests check parsing,
problem reports, agreement between documents, and preservation of supplied data.
All examples are fictional; no PDFs or saved research preparations are needed.
"""
# The validators receive Python dictionaries/lists or JSON strings and perform
# no filesystem access. Pair tests add relationships between preparation metadata
# and page entries after both documents pass their individual field rules.

import copy
import json
from pathlib import Path

import pytest

import validation


# Each test receives fresh data so changes in one example cannot affect another.
@pytest.fixture
def valid_preparation() -> dict:
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
def valid_pages() -> list[dict]:
    # Include a known blank page using an empty native string. Later cases use
    # None for unavailable text; those states must not be silently interchanged.
    return [
        {
            "page_number": 1,
            "text": 'Heat, "Adaptation" — Example City\nKeep cooling spaces open.',
            "text_source": "native",
            "readable": True,
            "image_available": True,
            "problem": None,
        },
        {
            "page_number": 2,
            "text": "",  # A known blank page must still have its own entry.
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


def test_accepts_valid_decoded_preparation_and_pages(
    valid_preparation: dict, valid_pages: list[dict]
) -> None:
    assert validation.validate_preparation_structure(valid_preparation) == []
    assert validation.validate_pages_structure(valid_pages) == []
    assert validation.validate_preparation_pages(valid_preparation, valid_pages) == []


def test_parses_preparation_without_changing_values(valid_preparation: dict) -> None:
    text = json.dumps(valid_preparation)

    data, problems = validation.parse_preparation_json(text)

    assert data == valid_preparation
    assert problems == []


def test_parses_pages_preserving_text_blank_and_unavailable_values(
    valid_pages: list[dict],
) -> None:
    valid_pages[2].update(
        text=None, text_source=None, readable=False, problem="Text is unavailable on this page."
    )
    text = json.dumps(valid_pages, ensure_ascii=False)

    data, problems = validation.parse_pages_json(text)

    # Equality includes punctuation, Unicode, line breaks, empty text, and null.
    # The parser must not normalize quotations or silently replace missing text.
    assert data == valid_pages
    assert problems == []


def test_parses_empty_pages_list() -> None:
    data, problems = validation.parse_pages_json("[]")

    assert data == []
    assert problems == []


def test_reports_multiple_preparation_field_errors(valid_preparation: dict) -> None:
    valid_preparation["date_accessed"] = "2026-02-29"
    valid_preparation["prepared_at"] = "2026-11-02T25:00:00Z"

    problems = validation.validate_preparation_structure(valid_preparation)

    assert len(problems) == 2
    assert all(problem.category == "structure" for problem in problems)
    assert [problem.location for problem in problems] == [
        "$.date_accessed",
        "$.prepared_at",
    ]


def test_reports_multiple_page_field_errors(valid_pages: list[dict]) -> None:
    valid_pages[0].update(page_number=0, readable="yes")

    problems = validation.validate_pages_structure(valid_pages)

    assert len(problems) == 2
    assert all(problem.category == "structure" for problem in problems)
    assert [problem.location for problem in problems] == [
        "$[0].page_number",
        "$[0].readable",
    ]


def test_invalid_preparation_is_not_returned_as_usable_data(
    valid_preparation: dict,
) -> None:
    valid_preparation["status"] = "succeeded"

    data, problems = validation.parse_preparation_json(json.dumps(valid_preparation))

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "structure"
    assert problems[0].location == "$.status"


def test_invalid_pages_are_not_returned_as_usable_data(valid_pages: list[dict]) -> None:
    del valid_pages[0]["text"]

    data, problems = validation.parse_pages_json(json.dumps(valid_pages))

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "structure"
    assert problems[0].location == "$[0]"
    assert "text" in problems[0].message


# These parameters are functions, not their results. Pytest passes each reader
# into the test, which then calls it with the supplied JSON text.
@pytest.mark.parametrize(
    "reader",
    [validation.parse_preparation_json, validation.parse_pages_json],
    ids=["preparation", "pages"],
)
@pytest.mark.parametrize(
    "text",
    [
        pytest.param('{"page_number": 1, "page_number": 2}', id="duplicate-field"),
        pytest.param('[{"page_number": 1, "page_number": 2}]', id="nested-duplicate"),
        pytest.param("NaN", id="nan"),
        pytest.param("Infinity", id="positive-infinity"),
        pytest.param("-Infinity", id="negative-infinity"),
        pytest.param('```json\n{}\n```', id="code-fence-is-not-repaired"),
    ],
)
def test_readers_reject_ambiguous_or_nonstandard_json(reader, text: str) -> None:
    data, problems = reader(text)

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "syntax"
    assert problems[0].message


@pytest.mark.parametrize(
    "reader",
    [validation.parse_preparation_json, validation.parse_pages_json],
    ids=["preparation", "pages"],
)
def test_readers_report_syntax_line_and_column(reader) -> None:
    text = '{\n  "status": "ready",\n}'  # The final comma is invalid JSON.

    data, problems = reader(text)

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "syntax"
    assert problems[0].location == "line 3, column 1"


@pytest.mark.parametrize(
    ("reader", "text"),
    [
        pytest.param(validation.parse_preparation_json, "null", id="null-preparation"),
        pytest.param(validation.parse_preparation_json, "[]", id="list-preparation"),
        pytest.param(validation.parse_pages_json, "null", id="null-pages"),
        pytest.param(validation.parse_pages_json, "{}", id="object-pages"),
    ],
)
def test_readers_reject_valid_json_with_the_wrong_shape(reader, text: str) -> None:
    data, problems = reader(text)

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "structure"
    assert problems[0].location == "$"


@pytest.mark.parametrize(
    ("validator", "path_attribute", "schema_filename"),
    [
        pytest.param(
            validation.validate_preparation_structure,
            "_PREPARATION_SCHEMA_PATH",
            "preparation.schema.json",
            id="preparation",
        ),
        pytest.param(
            validation.validate_pages_structure,
            "_PAGES_SCHEMA_PATH",
            "pages.schema.json",
            id="pages",
        ),
    ],
)
@pytest.mark.parametrize(
    "schema_text",
    [
        pytest.param(None, id="missing-file"),
        pytest.param('{"type":', id="malformed-json"),
        pytest.param('{"type": "unknown_type"}', id="invalid-schema"),
    ],
)
def test_unusable_schema_is_a_setup_problem(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    validator,
    path_attribute: str,
    schema_filename: str,
    schema_text: str | None,
) -> None:
    # Redirect loading to an isolated temporary file. The real schema is untouched.
    schema_path = tmp_path / schema_filename
    if schema_text is not None:
        schema_path.write_text(schema_text, encoding="utf-8")
    monkeypatch.setattr(validation, path_attribute, schema_path)

    problems = validator({})

    assert len(problems) == 1
    assert problems[0].category == "other"
    assert problems[0].location == str(schema_path)
    assert "Cannot load" in problems[0].message


@pytest.mark.parametrize("format_name", ["date", "date-time"])
def test_missing_format_support_withholds_parsed_preparation(
    valid_preparation: dict, monkeypatch: pytest.MonkeyPatch, format_name: str
) -> None:
    # Remove a checker from one temporary instance, simulating an incomplete
    # installation. Do not change jsonschema's shared, class-level checker table.
    checker = validation.FormatChecker()
    del checker.checkers[format_name]
    monkeypatch.setattr(validation, "FormatChecker", lambda: checker)

    data, problems = validation.parse_preparation_json(json.dumps(valid_preparation))

    assert data is None
    assert len(problems) == 1
    assert problems[0].category == "other"
    assert problems[0].location.endswith("preparation.schema.json")
    assert "required format checkers are unavailable" in problems[0].message
    assert format_name in problems[0].message


def test_pair_reports_field_errors_in_both_documents(
    valid_preparation: dict, valid_pages: list[dict]
) -> None:
    valid_preparation["page_count"] = "3"
    valid_pages[0]["page_number"] = 0

    problems = validation.validate_preparation_pages(valid_preparation, valid_pages)

    # The documents are checked independently before any cross-document checks.
    # A string count must not cause a comparison exception in the next stage.
    assert all(problem.category == "structure" for problem in problems)
    assert {problem.location for problem in problems} == {
        "preparation.json:$.page_count",
        "pages.json:$[0].page_number",
    }


def test_pair_rejects_wrong_input_shapes_without_crashing() -> None:
    problems = validation.validate_preparation_pages(None, {})

    assert len(problems) == 2
    assert all(problem.category == "structure" for problem in problems)
    assert [problem.location for problem in problems] == [
        "preparation.json:$",
        "pages.json:$",
    ]


def test_pair_preserves_schema_setup_error_location(
    valid_preparation: dict,
    valid_pages: list[dict],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    schema_path = tmp_path / "missing.schema.json"
    monkeypatch.setattr(validation, "_PREPARATION_SCHEMA_PATH", schema_path)

    problems = validation.validate_preparation_pages(valid_preparation, valid_pages)

    assert len(problems) == 1
    assert problems[0].category == "other"
    assert problems[0].location == str(schema_path)


@pytest.mark.parametrize("status", ["ready", "ready_with_gaps"])
@pytest.mark.parametrize("schema_version", [2, 3])
def test_pair_rejects_unreadable_pages_for_ready_statuses(
    valid_preparation: dict,
    valid_pages: list[dict],
    status: str,
    schema_version: int,
) -> None:
    # Stacked parametrization covers two readiness labels times two format
    # versions. Two nonadjacent unreadable flags ensure every affected page is
    # reported, and the deep copy checks that validation does not repair the input.
    valid_preparation.update(schema_version=schema_version, status=status)
    if schema_version == 3:
        valid_preparation["settings"]["candidate_image_min_area"] = 0.10
        for page in valid_pages:
            page.update(image_available=False, image_path=None, image_regions=[])

    # Only change readability: even retained text cannot override an explicit
    # unreadable flag. Report every affected page, including nonadjacent ones.
    for index in (0, 2):
        valid_pages[index]["readable"] = False
    before = copy.deepcopy((valid_preparation, valid_pages))

    problems = validation.validate_preparation_pages(valid_preparation, valid_pages)

    assert problems == [
        validation.ValidationProblem(
            category="reference",
            location=f"pages.json:$[{index}].readable",
            message=(
                f"Preparation status '{status}' requires every page to be readable; "
                f"PDF page {page_number} is marked unreadable."
            ),
        )
        for index, page_number in ((0, 1), (2, 3))
    ]
    # Validation reports the contradiction without changing its status or pages.
    assert (valid_preparation, valid_pages) == before


def test_pair_accepts_failed_attempt_with_unknown_count(valid_preparation: dict) -> None:
    valid_preparation.update(
        status="failed", page_count=None, problem="Could not open the PDF."
    )

    assert validation.validate_preparation_pages(valid_preparation, []) == []


def test_pair_accepts_failed_attempt_with_known_count(
    valid_preparation: dict, valid_pages: list[dict]
) -> None:
    valid_preparation.update(status="failed", problem="No usable reading route.")
    for page in valid_pages:
        page.update(text=None, text_source=None, readable=False, image_available=False, problem="Unreadable.")

    # The failed outcome is preserved, with one entry for every identified page.
    assert validation.validate_preparation_pages(valid_preparation, valid_pages) == []


def test_pair_accepts_gaps_without_discarding_unavailable_text(
    valid_preparation: dict, valid_pages: list[dict]
) -> None:
    valid_preparation.update(
        status="ready_with_gaps", problem="Page 3 needs the tested image route."
    )
    valid_pages[2].update(text=None, text_source=None, problem="Native text unavailable; use page image.")
    before = copy.deepcopy(valid_pages)

    assert validation.validate_preparation_pages(valid_preparation, valid_pages) == []
    assert valid_pages == before


def test_pair_rejects_pages_with_unknown_count(
    valid_preparation: dict, valid_pages: list[dict]
) -> None:
    valid_preparation.update(status="failed", page_count=None, problem="Counting failed.")

    problems = validation.validate_preparation_pages(valid_preparation, valid_pages)

    assert len(problems) == 1
    assert problems[0].category == "reference"
    assert problems[0].location == "pages.json:$"
    assert "must be empty" in problems[0].message


# The declared count stays at 3. Each case changes only the supplied page numbers
# to exercise missing, extra, duplicated, out-of-order, and out-of-range pages.
@pytest.mark.parametrize(
    ("page_numbers", "expected_error_location"),
    [
        pytest.param([], "pages.json:$", id="missing-all-pages"),
        pytest.param([1, 2], "pages.json:$", id="missing-final-page"),
        pytest.param([1, 3], "pages.json:$[1].page_number", id="missing-middle-page"),
        pytest.param([1, 2, 3, 4], "pages.json:$[3].page_number", id="extra-page"),
        pytest.param([1, 1, 3], "pages.json:$[1].page_number", id="duplicated-page"),
        pytest.param([1, 3, 2], "pages.json:$[1].page_number", id="out-of-order-pages"),
        pytest.param([2, 3, 4], "pages.json:$[0].page_number", id="missing-first-page"),
        pytest.param([1, 2, 4], "pages.json:$[2].page_number", id="out-of-range-page"),
    ],
)
def test_pair_rejects_inconsistent_page_sequences(
    valid_preparation: dict,
    valid_pages: list[dict],
    page_numbers: list[int],
    expected_error_location: str,
) -> None:
    # Copy the first fictional page's fields into each example entry. Only its
    # page number matters here; this test makes no claims about PDF content.
    pages = [dict(valid_pages[0], page_number=number) for number in page_numbers]
    before = copy.deepcopy((valid_preparation, pages))

    problems = validation.validate_preparation_pages(valid_preparation, pages)

    assert problems
    assert all(problem.category == "reference" for problem in problems)
    assert expected_error_location in {problem.location for problem in problems}
    # A report must not silently sort, remove, renumber, or invent page entries.
    assert (valid_preparation, pages) == before


def test_pair_reports_count_mismatch_clearly(
    valid_preparation: dict, valid_pages: list[dict]
) -> None:
    problems = validation.validate_preparation_pages(valid_preparation, valid_pages[:2])

    assert len(problems) == 1
    assert problems[0].message == (
        "Preparation declares 3 pages, but pages.json contains 2 entries."
    )


def test_ocr_source_requires_enabled_preparation_settings(
    valid_preparation: dict, valid_pages: list[dict]
) -> None:
    valid_pages[0]["text_source"] = "ocr"

    problems = validation.validate_preparation_pages(valid_preparation, valid_pages)

    assert len(problems) == 1
    assert problems[0].category == "reference"
    assert problems[0].location == "pages.json:$[0].text_source"
    assert "OCR-enabled" in problems[0].message


def test_ocr_source_and_matching_settings_are_accepted(
    valid_preparation: dict, valid_pages: list[dict]
) -> None:
    valid_pages[0]["text_source"] = "ocr"
    valid_preparation["settings"].update(
        ocr_enabled=True, ocr_engine="easyocr", ocr_version="test-version", ocr_language="en"
    )

    assert validation.validate_preparation_pages(valid_preparation, valid_pages) == []
