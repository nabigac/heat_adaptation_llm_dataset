"""Create and check independent expert references against registered source PDFs.

Only collection metadata is copied. Experts supply the actions and remaining
metadata from the original PDF; model outputs never seed the reference.
"""

import hashlib
from io import BytesIO
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import DependencyError, PyPdfError

import documents
import storage


def create_expert_reference(
    project_root: Path | str, plan_id: str, *, prepared_by: list[str]
) -> str:
    """Save an empty reference form once and return its project-relative path.

    Registration is required, but preparation and model runs are not. Reuse the
    collection workflow's source-integrity checks without accessing model data.
    The form is a starting point, not a completed or factually validated reference.
    """
    entry = _registered_plan(project_root, plan_id)
    reference = {
        "schema_version": 1,
        "plan_id": entry["plan_id"],
        "prepared_by": prepared_by,
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
            "actions": [],
        },
    }
    return storage.save_new_expert_reference(project_root, reference)


def validate_expert_reference(project_root: Path | str, plan_id: str) -> dict:
    """Return a checked form or raise a readable error, without writing any files.

    Page bounds come from the registered original, not a claim in the reference or
    a preparation. Source checks do not establish factual accuracy or completeness.
    """
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

    return storage.load_expert_reference(
        project_root, plan_id, source_url=entry["source_url"],
        date_accessed=entry["date_accessed"], page_count=page_count,
    )


def _registered_plan(project_root: Path | str, plan_id: str) -> dict:
    """Reuse collection integrity checks without accessing any model outputs."""
    entries = documents.list_documents(project_root)
    entry = next((entry for entry in entries if entry["plan_id"] == plan_id), None)
    if entry is None:
        raise ValueError("Select an existing registered plan ID.")
    return entry
