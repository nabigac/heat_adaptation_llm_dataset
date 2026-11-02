"""Check the registry data rules from DESIGN.md Appendix A.

These examples exercise structure and field values. Filesystem checks and
duplicate detection need workflow code; experts screen eligibility before import.
"""

# These modules come with Python: json parses JSON text, and Path handles paths.
import json
from pathlib import Path

# These installed libraries run the tests and check data against the schema.
import pytest
from jsonschema import Draft202012Validator, FormatChecker, ValidationError


# A fixture supplies setup to tests that request it by name in their arguments.
# scope="module" reuses this validator throughout the file; its schema is unchanged.
# Type hints such as -> Draft202012Validator describe what a function returns.
@pytest.fixture(scope="module")
def registry_validator() -> Draft202012Validator:
    """Load the actual schema once and enable calendar-date validation."""
    # __file__ identifies this test file; parents[1] selects the project directory.
    # Building the path from here also works when the terminal is elsewhere.
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "registry.schema.json"

    # read_text loads the file; json.loads converts its text into Python objects.
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Check that the schema's rules are well formed before using them on data.
    Draft202012Validator.check_schema(schema)

    # Calendar checks require FormatChecker; format="date" alone does not enable them.
    return Draft202012Validator(schema, format_checker=FormatChecker())


# The default fixture scope creates fresh data for each test case. Tests can
# modify their registry without those changes affecting another test's input.
@pytest.fixture
def valid_registry() -> dict:
    """Give every test a fresh fictional registry, without creating research files."""
    return {
        "schema_version": 1,
        "plans": [
            {
                "plan_id": "plan_0001",
                "plan_title": "Example Heat Adaptation Plan",
                "pdf_path": "data/raw/plan_0001.pdf",
                "document_sha256": "a" * 64,  # A fictional 64-character fingerprint.
                "source_url": "https://example.org/heat-plan.pdf",
                "date_accessed": "2026-11-01",
                "study_set": "development",
                "prepared_source_path": None,  # Python's None represents JSON null.
            }
        ],
    }


def test_accepts_empty_registry(registry_validator: Draft202012Validator) -> None:
    # A newly created registry must work before any PDFs have been imported.
    registry_validator.validate({"schema_version": 1, "plans": []})


# Parametrize runs the test once for each row. Each dictionary changes selected
# fields in the valid example; id gives the case a readable name in test reports.
@pytest.mark.parametrize(
    "plan_changes",
    [
        pytest.param({}, id="unprepared-development-plan"),
        pytest.param(
            {
                "prepared_source_path": (
                    "data/processed/plan_0001/preparation_01/preparation.json"
                )
            },
            id="prepared-plan",
        ),
        pytest.param({"study_set": "comparison"}, id="comparison-plan"),
        pytest.param({"study_set": "expansion"}, id="expansion-plan"),
        pytest.param({"document_sha256": "A" * 64}, id="uppercase-checksum"),
        pytest.param({"date_accessed": "2024-02-29"}, id="valid-leap-day"),
    ],
)
def test_accepts_valid_plan_variations(
    registry_validator: Draft202012Validator,
    valid_registry: dict,
    plan_changes: dict,
) -> None:
    # ["plans"][0] selects the first plan; update replaces only the supplied fields.
    valid_registry["plans"][0].update(plan_changes)

    # Successful validation returns normally; a validation error fails the test.
    registry_validator.validate(valid_registry)


# Remove each required field from the outer registry object in a separate case.
@pytest.mark.parametrize("field_name", ["schema_version", "plans"])
def test_rejects_missing_registry_field(
    registry_validator: Draft202012Validator,
    valid_registry: dict,
    field_name: str,
) -> None:
    # del removes the key entirely, which differs from setting its value to None.
    del valid_registry[field_name]

    # The block must raise ValidationError. Accepting this input fails the test.
    # "as error" captures the exception so we can inspect why validation rejected it.
    with pytest.raises(ValidationError) as error:
        registry_validator.validate(valid_registry)

    # assert fails a test when its condition is false. Check the reason and location
    # so an unrelated validation problem cannot make this rejection look correct.
    assert error.value.validator == "required"
    # An empty path means the error belongs to the outermost registry object.
    assert list(error.value.absolute_path) == []


# All eight plan keys are required, including prepared_source_path when it is null.
@pytest.mark.parametrize(
    "field_name",
    [
        "plan_id",
        "plan_title",
        "pdf_path",
        "document_sha256",
        "source_url",
        "date_accessed",
        "study_set",
        "prepared_source_path",
    ],
)
def test_rejects_missing_plan_field(
    registry_validator: Draft202012Validator,
    valid_registry: dict,
    field_name: str,
) -> None:
    del valid_registry["plans"][0][field_name]

    with pytest.raises(ValidationError) as error:
        registry_validator.validate(valid_registry)

    assert error.value.validator == "required"
    # This path identifies the first plan object inside the registry's plans list.
    assert list(error.value.absolute_path) == ["plans", 0]


def test_rejects_unknown_registry_field(
    registry_validator: Draft202012Validator, valid_registry: dict
) -> None:
    # Unexpected keys can be typos or an incompatible data format; reject them.
    valid_registry["unexpected"] = True

    with pytest.raises(ValidationError) as error:
        registry_validator.validate(valid_registry)

    assert error.value.validator == "additionalProperties"


def test_rejects_unknown_plan_field(
    registry_validator: Draft202012Validator, valid_registry: dict
) -> None:
    # Unknown-field protection must also apply inside each plan object.
    valid_registry["plans"][0]["unexpected"] = True

    with pytest.raises(ValidationError) as error:
        registry_validator.validate(valid_registry)

    assert error.value.validator == "additionalProperties"


# These cases keep the field present but give it an unsupported value or shape.
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        pytest.param("schema_version", 2, id="unsupported-version"),
        pytest.param("schema_version", "1", id="string-version"),
        # Python treats bool as an int subclass, but JSON Schema must reject True here.
        pytest.param("schema_version", True, id="boolean-version"),
        pytest.param("plans", {}, id="plans-must-be-a-list"),
        pytest.param("plans", ["plan_0001"], id="plan-must-be-an-object"),
    ],
)
def test_rejects_invalid_registry_values(
    registry_validator: Draft202012Validator,
    valid_registry: dict,
    field_name: str,
    invalid_value: object,
) -> None:
    valid_registry[field_name] = invalid_value

    with pytest.raises(ValidationError):
        registry_validator.validate(valid_registry)


# Start from valid data and introduce one field-level problem per case. That keeps
# the intended cause of rejection clear when a case fails during later edits.
@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        pytest.param("study_set", "pilot", id="unsupported-study-set"),
        pytest.param("document_sha256", "a" * 63, id="short-checksum"),
        pytest.param("document_sha256", "a" * 65, id="long-checksum"),
        pytest.param("document_sha256", "g" * 64, id="non-hexadecimal-checksum"),
        # Regression case: a final newline once passed the original pattern.
        pytest.param("document_sha256", "a" * 63 + "\n", id="checksum-with-newline"),
        pytest.param("date_accessed", "2026-02-29", id="impossible-calendar-date"),
        pytest.param("date_accessed", "11-01-2026", id="date-in-wrong-order"),
        pytest.param(
            "date_accessed", "2026-11-01T12:00:00Z", id="timestamp-instead-of-date"
        ),
        pytest.param(
            "prepared_source_path", 123, id="prepared-path-must-be-text-or-null"
        ),
        pytest.param(
            "prepared_source_path", "", id="prepared-path-must-not-be-empty"
        ),
    ],
)
def test_rejects_invalid_plan_values(
    registry_validator: Draft202012Validator,
    valid_registry: dict,
    field_name: str,
    invalid_value: object,
) -> None:
    valid_registry["plans"][0][field_name] = invalid_value

    with pytest.raises(ValidationError):
        registry_validator.validate(valid_registry)


# Stacking these parameter lists creates every combination: four fields times
# two invalid values gives eight cases. Empty text and null are different states.
@pytest.mark.parametrize("field_name", ["plan_id", "plan_title", "pdf_path", "source_url"])
@pytest.mark.parametrize("invalid_value", ["", None], ids=["empty", "null"])
def test_rejects_empty_or_null_required_text(
    registry_validator: Draft202012Validator,
    valid_registry: dict,
    field_name: str,
    invalid_value: object,
) -> None:
    valid_registry["plans"][0][field_name] = invalid_value

    with pytest.raises(ValidationError):
        registry_validator.validate(valid_registry)
