"""Create and check independent expert references against registered source PDFs.

Only collection metadata is copied. Experts supply the actions and remaining
metadata from the original PDF; model outputs never seed the reference.
"""

import hashlib
import re
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import DependencyError, PyPdfError

import documents
import storage
import validation
from expert_templates import REFERENCE_INSTRUCTIONS, blank_action, blank_issue


def create_expert_reference(project_root: Path | str, plan_id: str) -> str:
    """Save a guided starter form once and return its project-relative path.

    Registration is required, but preparation and model runs are not. Reuse the
    collection workflow's source-integrity checks without accessing model data.
    The form is a starting point, not a completed or factually validated reference.
    """
    entry = _registered_plan(project_root, plan_id)
    reference = {
        "schema_version": 1,
        "plan_id": entry["plan_id"],
        "id_counters": {"action": 1, "issue": 1},
        "instructions": list(REFERENCE_INSTRUCTIONS),
        "plan_data": {
            "metadata": {
                "plan_title": entry["plan_title"],
                "jurisdiction_name": None,
                "country": None,
                "plan_scale": None,
                "plan_type": None,
                "publication_year": None,
                "lead_agencies": [],
                "source_url": entry["source_url"],
                "date_accessed": entry["date_accessed"],
                # The study and shared data contract include English plans only.
                "language": "English",
            },
            "actions": [blank_action("action_0001")],
        },
        "plan_issues": {"issues": [blank_issue("issue_0001")]},
    }
    return storage.save_new_expert_reference(project_root, reference)


def validate_expert_reference(project_root: Path | str, plan_id: str) -> dict:
    """Return a checked form or raise a readable error, without writing any files.

    Page bounds come from the registered original, not a claim in the reference or
    a preparation. Source checks do not establish factual accuracy or completeness.
    """
    entry, page_count = _reference_source_context(project_root, plan_id)
    freeze = storage.load_expert_reference_freeze(project_root, plan_id)
    if freeze is not None:
        for field, expected in (
            ("document_sha256", entry["document_sha256"].lower()),
            ("source_url", entry["source_url"]), ("date_accessed", entry["date_accessed"]),
            ("page_count", page_count),
        ):
            if freeze[field] != expected:
                raise ValueError(f"The frozen expert reference's {field} no longer matches its registered source.")
    return storage.load_expert_reference(
        project_root, plan_id, source_url=entry["source_url"],
        date_accessed=entry["date_accessed"], page_count=page_count,
    )


def freeze_expert_reference(project_root: Path | str, plan_id: str) -> str:
    """Confirm a completed reference is ready and retain its assessment identity.

    Invoking this command confirms scientific readiness. Software checks fields,
    source links, and page bounds; it cannot establish completeness or independence.
    No model output is read and no additional reference version is created.
    """
    storage.require_unfrozen_expert_reference(project_root, plan_id)
    entry, page_count = _reference_source_context(project_root, plan_id)
    original_bytes = storage.read_expert_reference_bytes(project_root, plan_id)
    _, problems = validation.parse_expert_reference_json(
        original_bytes.decode("utf-8"), plan_id=plan_id, source_url=entry["source_url"],
        date_accessed=entry["date_accessed"], page_count=page_count,
    )
    if problems:
        raise storage.ExpertReferenceValidationError(problems)
    freeze = {
        "schema_version": 1, "plan_id": plan_id,
        "reference_path": f"data/comparison/expert_references/{plan_id}/expert_reference.json",
        "reference_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "document_sha256": entry["document_sha256"].lower(),
        "source_url": entry["source_url"], "date_accessed": entry["date_accessed"],
        "page_count": page_count,
        "frozen_at": datetime.now(timezone.utc).isoformat(),
        "confirmed_complete": True,
    }
    return storage.save_new_expert_reference_freeze(
        project_root, plan_id, freeze, expected_bytes=original_bytes,
    )


def edit_expert_reference(
    project_root: Path | str, plan_id: str, *, operation: str, record_id: str | None = None,
) -> tuple[str, str]:
    """Add a guided record, or remove an exact ID/the highest-ID untouched blank.

    Explicit removal can target filled records. Default removal never guesses
    that partially edited work is blank, and linked issues prevent action removal.
    """
    if operation not in {"add_action", "add_issue", "remove_action", "remove_issue"}:
        raise ValueError("Select add_action, add_issue, remove_action, or remove_issue.")
    adding = operation.startswith("add_")
    if record_id is not None and (adding or not isinstance(record_id, str) or not record_id.strip()):
        raise ValueError("A nonblank record ID is allowed only for explicit removal.")
    storage.require_unfrozen_expert_reference(project_root, plan_id)
    entry, page_count = _reference_source_context(project_root, plan_id)
    original_bytes = storage.read_expert_reference_bytes(project_root, plan_id)
    context = {
        "plan_id": plan_id, "source_url": entry["source_url"],
        "date_accessed": entry["date_accessed"], "page_count": page_count,
        "allow_templates": True,
    }
    reference, problems = validation.parse_expert_reference_json(original_bytes.decode("utf-8"), **context)
    if problems:
        raise storage.ExpertReferenceValidationError(problems)
    # Remember the highest observed numbers before any removal. Legacy drafts
    # acquire counters here; deleted historical IDs cannot be inferred from them.
    counters = reference.setdefault("id_counters", {"action": 0, "issue": 0})
    for counter_kind, items in (
        ("action", reference["plan_data"]["actions"]),
        ("issue", reference.get("plan_issues", {}).get("issues", [])),
    ):
        # JSON Schema accepts integral numeric forms such as 1.0. Persist an
        # integer so the next ID can always use integer formatting.
        counters[counter_kind] = max(int(counters[counter_kind]), max(
            (_record_number(item[f"{counter_kind}_id"], counter_kind) for item in items), default=0))
    kind = "action" if operation.endswith("_action") else "issue"
    factory = blank_action if kind == "action" else blank_issue
    if kind == "action":
        records = reference["plan_data"]["actions"]
    else:
        records = reference.setdefault("plan_issues", {"issues": []})["issues"]
    id_field = f"{kind}_id"
    if adding:
        number = counters[kind] + 1
        counters[kind] = number
        affected_id = f"{kind}_{number:04d}"
        records.append(factory(affected_id))
        reference.setdefault("instructions", list(REFERENCE_INSTRUCTIONS))
    else:
        if record_id is None:
            # A changed field is expert work, even if other TODO guidance remains.
            candidates = [item for item in records if item == factory(item[id_field])]
        else:
            candidates = [item for item in records if item[id_field] == record_id]
        if not candidates:
            target = f"ID {record_id!r}" if record_id is not None else "an untouched blank record"
            raise ValueError(f"No {kind} matches {target}; the reference was not changed.")
        selected = max(candidates, key=lambda item: _record_number(item[id_field], kind))
        affected_id = selected[id_field]
        if kind == "action":
            linked = [issue["issue_id"] for issue in reference.get("plan_issues", {}).get("issues", [])
                      if issue["related_action_id"] == affected_id]
            if linked:
                raise ValueError(f"Action {affected_id} is linked by {', '.join(linked)}; remove or relink those issues first.")
        records.remove(selected)
    problems = validation.validate_expert_reference(reference, **context)
    if problems:
        raise storage.ExpertReferenceValidationError(problems)
    path = storage.save_expert_reference_edit(
        project_root, plan_id, reference, expected_bytes=original_bytes,
    )
    return path, affected_id


def _record_number(record_id: str, kind: str) -> int:
    """Compare numbered IDs numerically, including IDs above four digits."""
    match = re.fullmatch(rf"{kind}_([0-9]+)", record_id)
    return int(match[1]) if match else 0


def _reference_source_context(project_root: Path | str, plan_id: str) -> tuple[dict, int]:
    """Use checked original bytes for page counts in both validation and editing."""
    entry = _registered_plan(project_root, plan_id)
    pdf_path = storage.resolve_project_path(project_root, entry["pdf_path"])
    pdf_bytes = pdf_path.read_bytes()
    # Count the same bytes checked here, avoiding a separate PDF reopen after
    # fingerprinting. The original might have changed since the registry check.
    if hashlib.sha256(pdf_bytes).hexdigest() != entry["document_sha256"].lower():
        raise ValueError("The registered original changed before reference validation.")
    try:
        with BytesIO(pdf_bytes) as stream, PdfReader(stream, strict=True) as reader:
            if reader.is_encrypted:
                raise ValueError("Encrypted PDFs are not supported for reference validation.")
            page_count = len(reader.pages)
            if page_count < 1:
                raise ValueError("The registered PDF contains no identifiable pages.")
    except (PyPdfError, DependencyError, ValueError, NotImplementedError) as error:
        raise ValueError(f"Could not count physical pages in the registered PDF: {error}") from error

    return entry, page_count


def _registered_plan(project_root: Path | str, plan_id: str) -> dict:
    """Reuse collection integrity checks without accessing any model outputs."""
    entries = documents.list_documents(project_root)
    entry = next((entry for entry in entries if entry["plan_id"] == plan_id), None)
    if entry is None:
        raise ValueError("Select an existing registered plan ID.")
    return entry
