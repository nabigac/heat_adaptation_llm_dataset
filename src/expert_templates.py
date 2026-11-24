"""Guided blank records for independent expert reference forms.

TODO text is editing guidance, never extracted content. Keeping the templates in
one place lets the editor recognize untouched records without guessing from IDs.
"""

from collections.abc import Iterator


TODO_PREFIX = "TODO:"

REFERENCE_INSTRUCTIONS = [
    "Replace TODO: guidance with source-supported text or null where allowed. Remove unused blank records before validation.",
    "action_type: choose supported values from infrastructural, institutional, behavioral/cultural, nature-based. If no type is justified, keep [] and explain in a linked issue.",
    "evidence: add objects with quote (an exact continuous source passage) and page_numbers (a list of physical PDF positions starting at 1, not printed page labels). Keep [] only with a linked source issue.",
    "issue_type: choose unclear_meaning, conflicting_evidence, source_issue, extraction_process_issue, no_records_found, or null. Group concerns about one action into one issue.",
    "related_action_id: use an existing action ID, or null for a plan/source concern or omission. issue_origin stays expert; resolved issues use resolved_by expert and a source-supported resolution.",
]


def blank_action(action_id: str) -> dict:
    """Return a fresh activity record with valid enum and missing-value defaults."""
    return {
        "action_id": action_id,
        "action": "TODO: Describe one heat-linked activity, retaining implementers, quantities, dates, and phase-specific details.",
        "action_type": [],
        "action_status": "unspecified",
        "action_location": "TODO: List stated locations or coverage; use null if unstated.",
        "action_recipient": "TODO: List stated intended populations or groups; use null if unstated.",
        "action_cost": "TODO: Record stated amounts, units, periods, and cost character; use null if unstated.",
        "action_benefit": "TODO: Record stated outcomes and whether expected, modelled, or observed; use null if unstated.",
        "evidence": [],
    }


def blank_issue(issue_id: str) -> dict:
    """Return an independent expert concern, without inventing a model origin."""
    return {
        "issue_id": issue_id,
        "related_action_id": None,
        "issue_description": "TODO: Describe the uncertainty, conflict, source gap, or possible omission, including relevant physical PDF pages.",
        "issue_type": None,
        "issue_origin": "expert",
        "issue_status": "open",
        "resolved_by": None,
        "resolution": None,
    }


def placeholder_locations(reference: dict) -> Iterator[str]:
    """Check editable guidance fields, leaving verbatim source quotations alone."""
    groups = (
        (reference["plan_data"]["actions"], "$.plan_data.actions",
         ("action", "action_location", "action_recipient", "action_cost", "action_benefit")),
        (reference.get("plan_issues", {}).get("issues", []), "$.plan_issues.issues",
         ("issue_description", "resolution")),
    )
    for records, location, fields in groups:
        for index, record in enumerate(records):
            for field in fields:
                value = record[field]
                if isinstance(value, str) and value.lstrip().startswith(TODO_PREFIX):
                    yield f"{location}[{index}].{field}"
