"""Read registry JSON and check its structure without changing its contents.

This first implementation covers JSON syntax and the registry schema. Checks
between records and against source files will be added as registration is built.
Model-response repairs belong to the later repair module, not this registry reader.
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, NoReturn

from jsonschema import Draft202012Validator, FormatChecker, SchemaError


# Resolve the schema relative to this module, independently of the terminal's path.
_REGISTRY_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "registry.schema.json"
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
    try:
        # Validate our schema too: an unreadable or malformed rule file must never
        # result in silently accepting unchecked registry data.
        schema = _decode_json(_REGISTRY_SCHEMA_PATH.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
    except (OSError, ValueError, SchemaError) as error:
        # This is a problem with our validation setup, rather than with the
        # registry's syntax or fields. Unicode decoding errors are ValueErrors too.
        return [
            ValidationProblem(
                category="other",
                location=str(_REGISTRY_SCHEMA_PATH),
                message=f"Cannot load the registry schema: {error}",
            )
        ]

    # Explicitly enable date checking; format="date" alone is not enforced by default.
    validator = Draft202012Validator(schema, format_checker=FormatChecker())

    # iter_errors collects all schema violations. Sorting gives callers a stable
    # presentation order, even when several fields need attention at once.
    errors = sorted(
        validator.iter_errors(data), key=lambda error: (error.json_path, error.message)
    )
    return [
        ValidationProblem(
            category="structure", location=error.json_path, message=error.message
        )
        for error in errors
    ]


def parse_registry_json(
    text: str,
) -> tuple[dict | None, list[ValidationProblem]]:
    """Parse and check registry text, returning (data, problems).

    Data is returned only when syntax and schema checks pass. On failure, return
    None and the problems; callers must not save or use an invalid registry.
    This function reads no registry file and performs no repairs or writes.
    """
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
    problems = validate_registry_structure(data)
    if problems:
        return None, problems
    return data, []


# A leading underscore marks helpers intended for use inside this module.
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
