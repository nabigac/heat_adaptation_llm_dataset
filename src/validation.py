"""Check JSON syntax, field rules, and document and extraction consistency.

The strict parsers and validators return problems without changing their inputs.
The explicitly named validate_and_repair_agent_response function additionally
uses repair.py to create a separate candidate and report. Neither path establishes
source support, quotation fidelity, or completeness, fills fields, or normalizes IDs.
"""

import json
import math
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Literal, NoReturn

from jsonschema import Draft202012Validator, FormatChecker, SchemaError
from referencing import Registry
from referencing.exceptions import Unresolvable
from referencing.jsonschema import DRAFT202012

from repair import COMPLETION_STATUSES, CompletionStatus, repair_agent_response
from expert_templates import placeholder_locations


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
_PLAN_DATA_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "plan_data.schema.json"
_EXPERT_REFERENCE_SCHEMA_PATH = (
    _PLAN_DATA_SCHEMA_PATH.parent / "expert_reference.schema.json"
)
_AGENT_RESPONSE_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "agent_response.schema.json"
)
_RUN_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "run.schema.json"
_PROFILES_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "profiles.schema.json"
_TOOL_LOG_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "tool_log.schema.json"
_VALIDATION_REPORT_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1] / "schemas" / "validation_report.schema.json"
)
_PLAN_DATA_SCHEMA_URI = "urn:heat-adaptation:plan-data"
_AGENT_RESPONSE_SCHEMA_URI = "urn:heat-adaptation:agent-response"
_RUN_SCHEMA_URI = "urn:heat-adaptation:run"
# These URNs are names for rule documents, not websites or run/document IDs.
# _validate_structure maps them to explicitly selected local files for $ref.
_CURATED_SCHEMA_PATH = _PLAN_DATA_SCHEMA_PATH.parent / "curated_dataset.schema.json"


# A dataclass groups related values into one record. frozen=True prevents later
# reassignment of its fields. Saved problem fields are defined in IMPLEMENTATION.MD.
@dataclass(frozen=True)
class ValidationProblem:
    """One reported problem; use dataclasses.asdict when saving it as JSON."""

    category: Literal["syntax", "structure", "reference", "other"]
    location: str | None
    message: str


@dataclass(frozen=True)
class FinalResponseValidation:
    """An answer only if accepted, both text versions, and a saveable report.

    This function result stays in memory. The run workflow must preserve raw_text
    first, candidate_text separately if changed, and then report through storage.
    A frozen dataclass prevents field reassignment, not edits inside its dicts.
    """

    response: dict | None
    raw_text: str
    candidate_text: str
    report: dict


# Reading guide: parse_* functions read JSON text; *_structure functions apply
# schema field rules; full validators additionally check relationships/context.
# An empty problems list means those checks passed. It does not mean a source
# quotation is faithful or an extracted claim is scientifically correct.
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


def validate_plan_data_structure(data: object) -> list[ValidationProblem]:
    """Check the metadata and action fields in the single plan data format."""
    return _validate_structure(
        data, _PLAN_DATA_SCHEMA_PATH, "plan data", required_formats=("date",)
    )


def validate_agent_response_structure(data: object) -> list[ValidationProblem]:
    """Check plan data and issues, including open/resolved issue field rules."""
    return _validate_structure(
        data, _AGENT_RESPONSE_SCHEMA_PATH, "agent response",
        required_formats=("date",),
        schema_references=((_PLAN_DATA_SCHEMA_URI, _PLAN_DATA_SCHEMA_PATH),),
    )


def validate_expert_reference_structure(data: object) -> list[ValidationProblem]:
    """Check reference fields without source context or factual assessment."""
    return _validate_structure(
        data, _EXPERT_REFERENCE_SCHEMA_PATH, "expert reference",
        required_formats=("date",),
        schema_references=(
            (_PLAN_DATA_SCHEMA_URI, _PLAN_DATA_SCHEMA_PATH),
            (_AGENT_RESPONSE_SCHEMA_URI, _AGENT_RESPONSE_SCHEMA_PATH),
        ),
    )


def validate_expert_reference_freeze(data: object) -> list[ValidationProblem]:
    """Check freeze metadata; storage checks its paths and exact reference bytes."""
    return _validate_structure(
        data, _PLAN_DATA_SCHEMA_PATH.parent / "expert_reference_freeze.schema.json",
        "expert reference freeze", required_formats=("date", "date-time"),
    )


def validate_run_record_structure(data: object) -> list[ValidationProblem]:
    """Check run fields, saved run settings, state requirements, and finite numbers.

    Unknown measurements remain null. The schema reuses the data and issue
    definitions, including their required fields, without copying those rules.
    """
    problems = _validate_structure(
        data, _RUN_SCHEMA_PATH, "run record", required_formats=("date", "date-time"),
        schema_references=(
            (_PLAN_DATA_SCHEMA_URI, _PLAN_DATA_SCHEMA_PATH),
            (_AGENT_RESPONSE_SCHEMA_URI, _AGENT_RESPONSE_SCHEMA_PATH),
        ),
    )
    if problems:
        return problems

    # JSON numeric exponents can overflow Python floats (for example 1e400).
    # Reject nonfinite values before they can become unsavable measurements.
    settings = data["settings"]
    problems.extend(_validate_execution_allowances(settings, "$.settings"))
    for location, value in (
        ("$.elapsed_seconds", data["elapsed_seconds"]),
        ("$.settings.generation.temperature", settings["generation"]["temperature"]),
        ("$.settings.generation.top_p", settings["generation"]["top_p"]),
        ("$.settings.model_timeout_seconds", settings["model_timeout_seconds"]),
        ("$.settings.max_elapsed_seconds", settings.get("max_elapsed_seconds")),
        ("$.settings.final_generation_seconds", settings.get("final_generation_seconds")),
        ("$.settings.document_tools.tool_timeout_seconds", settings["document_tools"]["tool_timeout_seconds"]),
    ):
        if isinstance(value, float) and not math.isfinite(value):
            problems.append(ValidationProblem("structure", location, "A numeric value must be finite or null where permitted."))
    return problems


def validate_tool_log(data: object) -> list[ValidationProblem]:
    """Check the ordered tool log, including finite numbers in arbitrary results."""
    problems = _validate_structure(data, _TOOL_LOG_SCHEMA_PATH, "tool log")
    return problems if problems else _nonfinite_json_numbers(data)


def validate_validation_report(data: object) -> list[ValidationProblem]:
    """Check saved errors/repair descriptions; do not perform repairs or judge claims."""
    return _validate_structure(data, _VALIDATION_REPORT_SCHEMA_PATH, "validation report")


def _validate_execution_allowances(settings: dict, location: str) -> list[ValidationProblem]:
    """Reject controls that cannot reserve the requested final capacity."""
    problems = []
    if (settings.get("max_estimated_tokens") is not None
            and settings["max_estimated_tokens"] < settings["context_limit"]):
        problems.append(ValidationProblem(
            "reference", location + ".max_estimated_tokens", "Reserve at least one full context for final generation."
        ))
    final_seconds = settings.get("final_generation_seconds")
    if final_seconds is not None:
        total_seconds = settings.get("max_elapsed_seconds")
        if total_seconds is None or final_seconds > total_seconds:
            problems.append(ValidationProblem(
                "reference", location + ".final_generation_seconds",
                "A protected final window requires an overall deadline at least as long as that window.",
            ))
    return problems


def validate_profiles(data: object) -> list[ValidationProblem]:
    """Check editable settings, unique names, and portable prompt paths.

    Profile fields reuse the saved-run rules except editable stage, which also
    permits C coordinator/worker roles. This check does not read prompts,
    contact an endpoint, detect model capabilities, or measure usable context.
    An empty profiles list is allowed, but cannot supply a selected profile.
    """
    problems = _validate_structure(
        data, _PROFILES_SCHEMA_PATH, "profiles",
        schema_references=((_RUN_SCHEMA_URI, _RUN_SCHEMA_PATH),),
    )
    if problems:
        return problems
    problems = _nonfinite_json_numbers(data)
    names = set()
    for index, profile in enumerate(data["profiles"]):
        location = f"$.profiles[{index}]"
        if profile["name"] in names:
            problems.append(ValidationProblem(
                "reference", location + ".name", f"Duplicate profile name {profile['name']!r}."
            ))
        names.add(profile["name"])
        problems.extend(_validate_execution_allowances(profile, location))
        for prompt_index, path in enumerate(profile["prompt_paths"]):
            problems.extend(_validate_project_relative_path(
                path, f"{location}.prompt_paths[{prompt_index}]"
            ))
    return problems


def validate_run_links(
    record: dict, *, input_run: dict | None = None, retry_run: dict | None = None
) -> list[ValidationProblem]:
    """Check resolved links after all supplied records have passed their schemas.

    Storage loads the exact same-plan target paths. Different model profiles are
    expected for verification, while the preparation and shared tools must match.
    An exploratory verifier repeat may still use a comparison extractor output.
    """
    problems = []
    # The caller has loaded these target dictionaries from explicitly selected
    # run files. This function checks their relationship; it does not find files.
    if record["input_run_id"] is not None:
        if input_run is None:
            problems.append(ValidationProblem("reference", "$.input_run_id", "The selected extractor run is missing."))
        else:
            if (
                input_run["run_id"] != record["input_run_id"]
                or input_run["plan_id"] != record["plan_id"]
                or input_run["stage"] != "extractor" or input_run["status"] != "succeeded"
            ):
                problems.append(ValidationProblem("reference", "$.input_run_id", "Verification requires the selected successful extractor run for the same plan."))
            if input_run["source_path"] != record["source_path"]:
                problems.append(ValidationProblem("reference", "$.source_path", "Verification must use its extractor's exact saved preparation."))
            if input_run["settings"]["document_tools"] != record["settings"]["document_tools"]:
                problems.append(ValidationProblem("reference", "$.settings.document_tools", "Verification and extraction must use the same shared document-tool settings."))
            ceiling = record["settings"].get("max_elapsed_seconds")
            if ceiling is not None and record["status"] == "succeeded":
                durations = (input_run["elapsed_seconds"], record["elapsed_seconds"])
                if any(value is None for value in durations) or sum(durations) > ceiling:
                    problems.append(ValidationProblem("reference", "$.elapsed_seconds", "Successful E+V execution must fit its shared time allowance, including the linked extraction."))
                reserve = record["settings"].get("final_generation_seconds")
                if (reserve is not None and input_run["elapsed_seconds"] is not None
                        and input_run["elapsed_seconds"] > ceiling - reserve):
                    problems.append(ValidationProblem("reference", "$.input_run_id", "The selected E must leave the protected final window for V."))
            if record["purpose"] == "comparison" and input_run["purpose"] != "comparison":
                # Preserve deliberate exploratory repeats without allowing one
                # to replace the main comparison extraction through this link.
                problems.append(ValidationProblem("reference", "$.input_run_id", "A comparison verifier requires a comparison extractor run."))
            if (
                record["plan_issues"] is not None
                and input_run["plan_issues"] is not None
            ):
                problems.extend(validate_verifier_issue_continuity(
                    record["plan_issues"], input_run["plan_issues"],
                ))
    if record["retry_of_run_id"] is not None:
        # Retrying a failed verifier must retain the same extractor baseline.
        # Switching its input would be a different verification attempt, not a
        # retry of checking that exact extraction.
        if retry_run is None:
            problems.append(ValidationProblem("reference", "$.retry_of_run_id", "The selected failed attempt is missing."))
        elif (
            retry_run["run_id"] != record["retry_of_run_id"]
            or retry_run["plan_id"] != record["plan_id"]
            or retry_run["stage"] != record["stage"] or retry_run["status"] != "failed"
            or (record["stage"] == "verifier" and retry_run["input_run_id"] != record["input_run_id"])
        ):
            problems.append(ValidationProblem("reference", "$.retry_of_run_id", "Retry the failed same-plan, same-stage attempt; verifier retries must retain its exact extractor input."))
    return problems


def validate_verifier_issue_continuity(
    plan_issues: dict, baseline: dict
) -> list[ValidationProblem]:
    """Check issue provenance against E after both issue lists pass field checks.

    Shared by final-response checking and saved-run loading. These checks retain
    identities and claimed-resolution provenance; experts judge semantic support.
    """
    baseline_issues = {issue["issue_id"]: issue for issue in baseline["issues"]}
    retained_issue_ids = {issue["issue_id"] for issue in plan_issues["issues"]}
    issues_location = "$.plan_issues.issues"
    problems = []
    if not baseline_issues.keys() <= retained_issue_ids:
        problems.append(ValidationProblem(
            "reference", issues_location,
            "Verification must retain every extractor issue ID."
        ))
    for index, issue in enumerate(plan_issues["issues"]):
        location = f"{issues_location}[{index}]"
        previous = baseline_issues.get(issue["issue_id"])
        expected_origin = previous["issue_origin"] if previous is not None else "verifier"
        if issue["issue_origin"] != expected_origin:
            problems.append(ValidationProblem(
                "reference", location + ".issue_origin",
                "Continuing issues retain their origin; new verifier issues originate with verifier."
            ))
        if issue["resolved_by"] == "extractor" and (
            previous is None
            or previous["issue_status"] != "resolved"
            or previous["resolved_by"] != "extractor"
            or previous["resolution"] != issue["resolution"]
        ):
            problems.append(ValidationProblem(
                "reference", location + ".resolved_by",
                "A resolution made during verification must identify verifier."
            ))
    return problems


def validate_plan_data(
    data: object, *, page_count: int
) -> list[ValidationProblem]:
    """Check plan data fields, record IDs, and physical PDF page ranges.

    Supply the original PDF's known page count, not a number claimed by the model.
    Expert reference validation reuses the same action-ID and page-range rules.
    """
    problems = (
        validate_plan_data_structure(data)
        + _validate_page_count(page_count)
    )
    # List concatenation combines field errors with caller-context errors. Only
    # proceed to nested dictionary/list access after both sets of checks pass.
    if problems:
        return problems
    return _validate_plan_data_references(
        data, page_count=page_count, location="$"
    )


def validate_expert_reference(
    data: object, *, plan_id: str, source_url: str, date_accessed: str, page_count: int,
    allow_templates: bool = False,
) -> list[ValidationProblem]:
    """Check a reference against trusted registration details and the original PDF.

    The caller supplies checked collection data and a counted PDF page total.
    The editor permits TODO guidance while retaining field/link checks. Normal
    validation rejects it. Older references without issues remain readable.
    Expert review establishes completeness and claim support; no fields change.
    """
    problems = validate_expert_reference_structure(data) + _validate_page_count(page_count)
    if problems:
        return problems

    if data["plan_id"] != plan_id:
        problems.append(ValidationProblem(
            "reference", "$.plan_id", "Reference plan ID must match the selected registered plan."
        ))
    metadata = data["plan_data"]["metadata"]
    for field, expected in (("source_url", source_url), ("date_accessed", date_accessed)):
        if metadata[field] != expected:
            problems.append(ValidationProblem(
                "reference", f"$.plan_data.metadata.{field}",
                f"Reference {field} must match the registered collection metadata."
            ))
    if not allow_templates:
        # An omitted optional container means no issues, just like an empty list.
        # Normalize only this check; reading never rewrites the expert's form.
        checked = {**data, "plan_issues": data.get("plan_issues", {"issues": []})}
        problems.extend(_validate_response_references(checked, page_count=page_count, stage="expert"))
    else:
        problems.extend(_validate_plan_data_references(
            data["plan_data"], page_count=page_count, location="$.plan_data"
        ))
        if "plan_issues" in data:
            problems.extend(_validate_plan_issues_references(
                data["plan_issues"],
                record_ids={action["action_id"] for action in data["plan_data"]["actions"]},
                stage="expert",
            ))
    if not allow_templates:
        for location in placeholder_locations(data):
            problems.append(ValidationProblem(
                "reference", location,
                "Unfinished TODO guidance: fill this field or remove the unused blank record.",
            ))
    return problems


def validate_agent_response(
    data: object, *, page_count: int, stage: Literal["extractor", "verifier"],
) -> list[ValidationProblem]:
    """Check one complete answer against the source page count and executing role.

    Here we check the answer's internal consistency. validate_run_links checks
    issue continuity against a saved extractor run when both records are available.
    """
    problems = (
        validate_agent_response_structure(data)
        + _validate_page_count(page_count)
    )
    if stage not in ("extractor", "verifier"):
        problems.append(ValidationProblem(
            "other", "stage", "Validation requires stage 'extractor' or 'verifier'."
        ))
    if problems:
        return problems

    return _validate_response_references(
        data, page_count=page_count, stage=stage
    )


def validate_curated_dataset(data: object, *, page_count: int) -> list[ValidationProblem]:
    """Check curated E/V or C answers, allowing expert-authored resolutions.

    Each answer uses one workflow's issue identities. Shared field and reference
    checks still apply, and validation never changes the supplied answer.
    Format and references are checked here. Source meaning and expert approval
    remain research judgments recorded separately from validation success.
    """
    problems = _validate_structure(
        data, _CURATED_SCHEMA_PATH, "curated dataset", required_formats=("date",),
        schema_references=(
            (_PLAN_DATA_SCHEMA_URI, _PLAN_DATA_SCHEMA_PATH),
            (_AGENT_RESPONSE_SCHEMA_URI, _AGENT_RESPONSE_SCHEMA_PATH),
        ),
    ) + _validate_page_count(page_count)
    if problems:
        return problems
    return _validate_response_references(data, page_count=page_count, stage="expert")


def _validate_response_references(
    data: dict, *, page_count: int, stage: str
) -> list[ValidationProblem]:
    """Apply shared data and issue checks to a complete answer."""
    actions = data["plan_data"]["actions"]
    problems = _validate_plan_data_references(
        data["plan_data"], page_count=page_count, location="$.plan_data"
    )
    record_ids = {action["action_id"] for action in actions}
    problems.extend(_validate_plan_issues_references(
        data["plan_issues"], record_ids=record_ids, stage=stage
    ))
    linked_issues = {issue["related_action_id"] for issue in data["plan_issues"]["issues"]}
    for index, action in enumerate(actions):
        for field in ("action_type", "evidence"):
            if not action[field] and action["action_id"] not in linked_issues:
                problems.append(ValidationProblem(
                    "reference", f"$.plan_data.actions[{index}].{field}",
                    f"An empty {field} requires a linked issue."
                ))
    return problems


def _validate_plan_issues_references(
    plan_issues: dict, *, record_ids: set[str], stage: str
) -> list[ValidationProblem]:
    """Share issue checks between agent responses and nullable failed-run outputs."""
    problems = []
    seen_issue_ids = set()
    affected_record_ids = set()
    # Separate sets answer separate questions: is this issue ID repeated, and
    # have two issues split the concerns for the same affected content record?
    for index, issue in enumerate(plan_issues["issues"]):
        location = f"$.plan_issues.issues[{index}]"
        if issue["issue_id"] in seen_issue_ids:
            problems.append(ValidationProblem(
                "reference", location + ".issue_id", f"Duplicate issue ID {issue['issue_id']!r}."
            ))
        seen_issue_ids.add(issue["issue_id"])

        related_id = issue["related_action_id"]
        if related_id is not None:
            # Null links are deliberately exempt from one-issue-per-record:
            # distinct omissions or source gaps may each need an unlinked issue.
            if related_id not in record_ids:
                problems.append(ValidationProblem(
                    "reference", location + ".related_action_id",
                    f"Related record ID {related_id!r} does not identify a content record."
                ))
            if related_id in affected_record_ids:
                problems.append(ValidationProblem(
                    "reference", location + ".related_action_id",
                    "Group problems for one affected record in a single issue."
                ))
            affected_record_ids.add(related_id)

        # The extractor cannot create verifier issues or claim verifier repairs.
        # A verifier-origin issue likewise cannot have been resolved earlier by
        # the extractor. These checks do not judge whether a resolution is sound.
        if stage == "extractor" and issue["issue_origin"] != "extractor":
            problems.append(ValidationProblem(
                "reference", location + ".issue_origin",
                "An extractor response can contain only extractor-origin issues."
            ))
        if (
            (stage == "extractor" and issue["resolved_by"] == "verifier")
            or (issue["issue_origin"] == "verifier" and issue["resolved_by"] == "extractor")
            or (stage != "expert" and issue["resolved_by"] == "expert")
        ):
            problems.append(ValidationProblem(
                "reference", location + ".resolved_by",
                "The resolving stage is inconsistent with this run or the issue's origin."
            ))
    return problems


def validate_run_record(
    data: object, *, page_count: int | None = None
) -> list[ValidationProblem]:
    """Check run consistency without opening source, prompt, artifact, or run files.

    A source page count is required whenever plan data is retained. Failed/running
    records without plan data can be checked before source context is available.
    Path syntax and layout are checked here; file existence, PDF identity, linked
    run status/settings, and completed-file preservation belong to storage/workflow.
    """
    problems = validate_run_record_structure(data)
    if problems:
        return problems
    if page_count is not None or data["plan_data"] is not None:
        # Failed/running records may have no accepted content or known count.
        # Retained content always needs a real source count for citation checks.
        problems.extend(_validate_page_count(page_count))
    if problems:
        return problems

    settings = data["settings"]
    # "Saved run settings" is our explanatory name for this settings object.
    if (settings.get("max_model_requests") is not None
            and len(data["model_calls"]) > settings["max_model_requests"]):
        problems.append(ValidationProblem("reference", "$.model_calls", "Recorded model requests exceed the stage allowance."))
    ceiling = settings.get("max_elapsed_seconds")
    if (ceiling is not None and data["status"] == "succeeded"
            and data["elapsed_seconds"] is not None and data["elapsed_seconds"] > ceiling):
        problems.append(ValidationProblem("reference", "$.elapsed_seconds", "Successful execution exceeds its configuration time allowance."))
    # It preserves the chosen profile, shared tools, prompt texts, and environment.
    if settings["stage"] != data["stage"]:
        problems.append(ValidationProblem(
            "reference", "$.settings.stage", "Saved run settings must use the same stage as the run record."
        ))
    if len(settings["prompt_paths"]) != len(settings["prompt_texts"]):
        # Check the saved lists, not today's prompt-file contents. Editing a
        # prompt later must not make an older snapshot change or become invalid.
        problems.append(ValidationProblem(
            "reference", "$.settings.prompt_texts", "Save one prompt text for each prompt path, in the selected order."
        ))

    for field in ("input_run_id", "retry_of_run_id"):
        if data[field] == data["run_id"]:
            problems.append(ValidationProblem("reference", "$." + field, "A run cannot link to itself."))
    if data["input_run_id"] is not None and data["input_run_id"] == data["retry_of_run_id"]:
        problems.append(ValidationProblem(
            "reference", "$.retry_of_run_id", "A successful extractor input cannot also be the failed attempt being retried."
        ))

    if data["ended_at"] is not None:
        # UTC/calendar syntax has already passed the schema. Parse only to check
        # ordering; never fill elapsed_seconds from wall-clock timestamps.
        start = datetime.fromisoformat(data["started_at"].upper().replace("Z", "+00:00"))
        end = datetime.fromisoformat(data["ended_at"].upper().replace("Z", "+00:00"))
        if end < start:
            problems.append(ValidationProblem("reference", "$.ended_at", "A run cannot end before it starts."))

    for index, call in enumerate(data["model_calls"]):
        # Provider-reported truncation is an execution failure even when the
        # returned text happens to be syntactically complete JSON.
        if call["truncated"] is True and data["status"] != "failed":
            problems.append(ValidationProblem(
                "reference", f"$.model_calls[{index}].truncated", "Reported output truncation requires a failed run status."
            ))
    problems.extend(_validate_run_record_paths(data))

    if data["plan_data"] is not None and data["plan_issues"] is not None:
        # Complete outputs use the same checks as standalone model answers.
        return problems + _validate_response_references(
            data, page_count=page_count, stage=data["stage"]
        )
    # Failed runs can retain data or issues independently. Without data, an issue
    # may describe an unlinked gap but cannot link to a record.
    record_ids = set()
    if data["plan_data"] is not None:
        problems.extend(_validate_plan_data_references(
            data["plan_data"], page_count=page_count, location="$.plan_data",
        ))
        record_ids = {
            action["action_id"] for action in data["plan_data"]["actions"]
        }
    if data["plan_issues"] is not None:
        problems.extend(_validate_plan_issues_references(
            data["plan_issues"], record_ids=record_ids, stage=data["stage"],
        ))
    return problems


def validate_preparation_pages(
    preparation: object, pages: object
) -> list[ValidationProblem]:
    """Check decoded fields, page numbering, and readiness consistency.

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

    for index, page in enumerate(pages):
        location = f"pages.json:$[{index}]"
        # Both usable statuses require every page to be marked readable. Report
        # contradictions without rewriting the saved status or any page fields.
        if preparation["status"] in {"ready", "ready_with_gaps"} and not page["readable"]:
            problems.append(
                ValidationProblem(
                    category="reference",
                    location=location + ".readable",
                    message=(
                        f"Preparation status '{preparation['status']}' requires every page "
                        f"to be readable; PDF page {page['page_number']} is marked unreadable."
                    ),
                )
            )

        # Older preparations have no preserved image references. Validate new
        # fields without silently inserting them into old data.
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


def parse_plan_data_json(
    text: str, *, page_count: int
) -> tuple[dict | None, list[ValidationProblem]]:
    """Parse strict plan data JSON and withhold it if field or reference checks fail."""
    # The lambda is a small function retaining this call's source page count.
    # _parse_and_validate invokes it only after JSON syntax has been read safely.
    return _parse_and_validate(
        text, lambda data: validate_plan_data(
            data, page_count=page_count
        )
    )


def parse_expert_reference_json(
    text: str, *, plan_id: str, source_url: str, date_accessed: str, page_count: int,
    allow_templates: bool = False,
) -> tuple[dict | None, list[ValidationProblem]]:
    """Parse strict reference JSON and check its source links without any repairs."""
    try:
        return _parse_and_validate(
            text, lambda data: validate_expert_reference(
                data, plan_id=plan_id, source_url=source_url,
                date_accessed=date_accessed, page_count=page_count,
                allow_templates=allow_templates,
            )
        )
    except RecursionError:
        return None, [ValidationProblem("syntax", None, "Reference JSON is nested too deeply.")]


def parse_expert_reference_freeze_json(text: str) -> tuple[dict | None, list[ValidationProblem]]:
    """Read an existing freeze without accepting duplicate keys or invalid fields."""
    try:
        return _parse_and_validate(text, validate_expert_reference_freeze)
    except RecursionError:
        return None, [ValidationProblem("syntax", None, "Reference freeze JSON is nested too deeply.")]


def parse_agent_response_json(
    text: str, *, page_count: int, stage: Literal["extractor", "verifier"],
) -> tuple[dict | None, list[ValidationProblem]]:
    """Parse a final answer without repairs, preserving the raw text for its caller.

    Passing these checks alone does not establish normal model completion. Use
    validate_and_repair_agent_response for completion checks and permitted repairs.
    """
    return _parse_and_validate(
        text, lambda data: validate_agent_response(
            data, page_count=page_count, stage=stage
        )
    )


def is_agent_response_draft(text: str) -> bool:
    """Inspect a complete JSON draft's containers without accepting its content.

    Require strict, finite JSON with the expected answer containers and object
    records. This inspection does not control the investigation handoff and is
    NOT acceptance validation: metadata/action/issue fields may still be missing
    or invalid. The runner must request a separate final answer
    under the full schema and validate it. No repairs or file operations occur.
    """
    try:
        data = _decode_json(text)
        if _nonfinite_json_numbers(data):
            return False
    except (ValueError, RecursionError):
        return False
    if not isinstance(data, dict) or set(data) != {"plan_data", "plan_issues"}:
        return False
    plan_data, plan_issues = data["plan_data"], data["plan_issues"]
    if (not isinstance(plan_data, dict) or set(plan_data) != {"metadata", "actions"}
            or not isinstance(plan_issues, dict) or set(plan_issues) != {"issues"}):
        return False
    return (
        isinstance(plan_data["metadata"], dict)
        and isinstance(plan_data["actions"], list)
        and all(isinstance(action, dict) for action in plan_data["actions"])
        and isinstance(plan_issues["issues"], list)
        and all(isinstance(issue, dict) for issue in plan_issues["issues"])
    )


def validate_and_repair_agent_response(
    text: str,
    *,
    page_count: int,
    stage: Literal["extractor", "verifier"],
    completion_status: CompletionStatus,
    raw_response_path: str,
) -> FinalResponseValidation:
    """Check completion, validate, apply permitted repairs, and validate again.

    raw_response_path is the intended project-relative file under responses/.
    A changed candidate belongs beside it as repaired_final.txt. No files are
    read or written here; storage checks file existence and run boundaries.
    """
    if completion_status not in COMPLETION_STATUSES:
        raise ValueError("Completion status must be normal, unknown, truncated, or failed.")
    path_problems = _validate_project_relative_path(raw_response_path, "raw_response_path")
    raw_path = PurePosixPath(raw_response_path)
    if path_problems or raw_path.parent.name != "responses" or raw_path.name == "repaired_final.txt":
        raise ValueError("Choose a project-relative raw response file directly under responses/, reserving repaired_final.txt for repairs.")

    # Stop before syntax handling on operational failure. A complete-looking
    # JSON response cannot override a timeout, failure, or reported truncation.
    if completion_status in ("truncated", "failed"):
        message = (
            "The provider reported output truncation; no repairs or answer acceptance are permitted."
            if completion_status == "truncated" else
            "The model request failed; no repairs or answer acceptance are permitted."
        )
        initial_errors = remaining_errors = [ValidationProblem("other", None, message)]
        response, candidate, repairs = None, text, []
    else:
        response, initial_errors = parse_agent_response_json(
            text, page_count=page_count, stage=stage
        )
        candidate, repairs = text, []
        remaining_errors = initial_errors
        if initial_errors:
            repaired = repair_agent_response(text, completion_status=completion_status)
            candidate = repaired.candidate_text
            repairs = [asdict(change) for change in repaired.repairs]
            # Run the SAME strict syntax, structure, ID/link, issue, and page
            # checks. Formatting repairs never bypass a reference error.
            response, remaining_errors = parse_agent_response_json(
                candidate, page_count=page_count, stage=stage
            )

    report = {
        "raw_response_path": raw_response_path,
        "repaired_response_path": str(raw_path.parent / "repaired_final.txt") if repairs else None,
        "initial_errors": [asdict(problem) for problem in initial_errors],
        "remaining_errors": [asdict(problem) for problem in remaining_errors],
        "repairs": repairs,
        "valid": not remaining_errors,
    }
    return FinalResponseValidation(response, text, candidate, report)


def parse_run_record_json(
    text: str, *, page_count: int | None = None
) -> tuple[dict | None, list[ValidationProblem]]:
    """Read a strict run record, withholding invalid data and leaving values unchanged."""
    return _parse_and_validate(text, lambda data: validate_run_record(data, page_count=page_count))


def parse_run_record_structure_json(text: str) -> tuple[dict | None, list[ValidationProblem]]:
    """Read fields before storage loads the source needed for full run validation."""
    # Storage first needs source_path from the record to load its preparation.
    # It uses this narrower parser, then performs full checks with that page count.
    return _parse_and_validate(text, validate_run_record_structure)


def parse_tool_log_json(text: str) -> tuple[list[dict] | None, list[ValidationProblem]]:
    return _parse_and_validate(text, validate_tool_log)


def parse_validation_report_json(text: str) -> tuple[dict | None, list[ValidationProblem]]:
    return _parse_and_validate(text, validate_validation_report)


def parse_profiles_json(text: str) -> tuple[dict | None, list[ValidationProblem]]:
    """Read strict configuration JSON without repairs or implicit setting defaults."""
    return _parse_and_validate(text, validate_profiles)


def _nonfinite_json_numbers(data: object, location: str = "$") -> list[ValidationProblem]:
    """Catch overflowed exponents even inside a tool's arbitrary JSON arguments."""
    if isinstance(data, float) and not math.isfinite(data):
        return [ValidationProblem("structure", location, "JSON numbers must be finite.")]
    problems = []
    # Recursion follows nested objects/lists until it reaches individual values.
    # Locations are diagnostic strings only; the tool arguments/results are not
    # rewritten, rounded, or used to infer missing numeric measurements.
    if isinstance(data, dict):
        for key, value in data.items():
            problems.extend(_nonfinite_json_numbers(value, f"{location}[{json.dumps(key)}]"))
    elif isinstance(data, list):
        for index, value in enumerate(data):
            problems.extend(_nonfinite_json_numbers(value, f"{location}[{index}]"))
    return problems


def _validate_project_relative_path(value: str, location: str) -> list[ValidationProblem]:
    """Check portable path syntax without filesystem access or circular storage imports."""
    path = PurePosixPath(value)
    if (
        path.is_absolute() or PureWindowsPath(value).drive or "\\" in value
        or ".." in path.parts or path == PurePosixPath(".") or "\x00" in value
    ):
        return [ValidationProblem(
            "reference", location, "Expected a project-relative path without parent traversal, Windows drives, backslashes, or null bytes."
        )]
    return []


def _validate_run_record_paths(record: dict) -> list[ValidationProblem]:
    """Keep source links in the plan's preparation and artifacts in this run's folder."""
    problems = []
    for field in ("plan_id", "run_id", "input_run_id", "retry_of_run_id"):
        value = record[field]
        if value is not None and (
            value in {".", ".."} or "/" in value or "\\" in value
            or PureWindowsPath(value).drive or "\x00" in value
        ):
            problems.append(ValidationProblem(
                "reference", "$." + field, "An ID must be one portable path component; it cannot contain a drive, slash, or traversal."
            ))

    source_problems = _validate_project_relative_path(record["source_path"], "$.source_path")
    problems.extend(source_problems)
    if not source_problems:
        match = re.fullmatch(
            rf"data/processed/{re.escape(record['plan_id'])}/preparation_([0-9]+)/preparation\.json",
            record["source_path"],
        )
        # fullmatch requires the entire expected layout. strip("0") distinguishes
        # a positive preparation number from all-zero spellings without converting
        # an arbitrarily long digit string into an integer.
        if match is None or not match.group(1).strip("0"):
            problems.append(ValidationProblem(
                "reference", "$.source_path", "Source must identify this plan's preparation_<positive number>/preparation.json under data/processed/."
            ))

    for index, path in enumerate(record["settings"]["prompt_paths"]):
        problems.extend(_validate_project_relative_path(path, f"$.settings.prompt_paths[{index}]"))

    artifact_paths = [("$.tool_log_path", record["tool_log_path"])] + [
        (f"$.model_calls[{index}].response_path", call["response_path"])
        for index, call in enumerate(record["model_calls"])
    ]
    expected_parent = ("runs", record["plan_id"], record["run_id"])
    # A run may preserve several response files. Each link must remain inside its
    # own run folder; a valid-looking path into another attempt is still invalid.
    for location, path in artifact_paths:
        if path is None:
            continue
        path_problems = _validate_project_relative_path(path, location)
        problems.extend(path_problems)
        if not path_problems:
            parts = PurePosixPath(path).parts
            if parts[:3] != expected_parent or len(parts) <= 3:
                problems.append(ValidationProblem(
                    "reference", location, "Saved response and tool-log paths must remain inside this plan's selected run folder."
                ))
    return problems


def _validate_page_count(page_count: object) -> list[ValidationProblem]:
    """Reject unavailable or invalid source context instead of skipping range checks."""
    if isinstance(page_count, bool) or not isinstance(page_count, int) or page_count < 1:
        return [ValidationProblem(
            "other", "page_count", "Validation requires a known positive integer PDF page count."
        )]
    return []


def _validate_plan_data_references(
    plan_data: dict, *, page_count: int, location: str
) -> list[ValidationProblem]:
    """Validate action IDs and page ranges without interpreting claims."""
    problems = []
    seen_ids = set()
    for index, action in enumerate(plan_data["actions"]):
        action_location = f"{location}.actions[{index}]"
        if action["action_id"] in seen_ids:
            problems.append(ValidationProblem(
                "reference", action_location + ".action_id",
                "Action IDs must be unique within the plan."
            ))
        seen_ids.add(action["action_id"])
        for evidence_index, evidence in enumerate(action["evidence"]):
            for page_index, page_number in enumerate(evidence["page_numbers"]):
                if page_number > page_count:
                    problems.append(ValidationProblem(
                        "reference", f"{action_location}.evidence[{evidence_index}].page_numbers[{page_index}]",
                        f"Page number {page_number} is outside the range 1 to {page_count}."
                    ))
    return problems





# A leading underscore marks helpers intended for use inside this module.
def _validate_structure(
    data: object,
    schema_path: Path,
    schema_name: str,
    *,
    required_formats: tuple[str, ...] = (),
    schema_references: tuple[tuple[str, Path], ...] = (),
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

    # Register only explicitly supplied local schemas. An unresolved reference
    # becomes a setup error; validation never downloads rules over the network.
    registry = Registry()
    for reference_uri, reference_path in schema_references:
        # This small registry is a schema-name lookup, separate from plans.json.
        # Its resources are loaded from disk here; no remote retrieval is enabled.
        try:
            referenced_schema = _decode_json(reference_path.read_text(encoding="utf-8"))
            Draft202012Validator.check_schema(referenced_schema)
        except (OSError, ValueError, SchemaError) as error:
            return [ValidationProblem(
                "other", str(reference_path), f"Cannot load referenced schema: {error}"
            )]
        registry = registry.with_resource(reference_uri, DRAFT202012.create_resource(referenced_schema))

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

    validator = Draft202012Validator(schema, format_checker=checker, registry=registry)
    # The validator's errors can be sorted for stable reporting without sorting
    # the user's content, evidence lists, or saved model/tool activity.
    # Collect all field violations and keep their presentation order stable.
    try:
        errors = sorted(
            validator.iter_errors(data), key=lambda error: (error.json_path, error.message)
        )
    except Unresolvable as error:
        return [ValidationProblem(
            "other", str(schema_path), f"Cannot resolve local schema reference: {error}"
        )]
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
    # returns a list of problems. Passing the function lets the public readers
    # share syntax handling while each chooses its own validation rules.
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
        # Withhold the entire parsed result instead of passing a partly accepted
        # object to storage. The caller still has its original response text.
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
