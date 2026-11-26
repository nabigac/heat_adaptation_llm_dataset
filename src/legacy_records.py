"""Read retired study labels and data paths without changing historical files.

Current commands use comparison or dataset_building. A validation view maps known v1
registry/run classification fields; source data, prompt text, IDs, and recorded
fingerprints retain their original values. Callers return the original object
after validation so saved parent snapshots still match exactly.
"""

from copy import deepcopy


LEGACY_SAMPLE = "development"
LEGACY_PURPOSE = "development"
LEGACY_EXTERNAL_PURPOSE = "exploratory"

# These directories contained real saved evidence. Readers locate moved bytes
# through these aliases, retaining the path strings inside archived JSON.
DATA_DIRECTORY_MOVES = (
    ("data/raw", "data/source_pdfs"),
    ("data/processed", "data/prepared_plans"),
    ("data/expert_references", "data/comparison/expert_references"),
    ("expert_references", "data/comparison/expert_references"),
)


def canonical_data_path(value):
    """Translate known directory prefixes only; leave all other values intact."""
    if isinstance(value, str):
        for old, new in DATA_DIRECTORY_MOVES:
            if value == old or value.startswith(old + "/"):
                return new + value[len(old):]
    return value


def comparison_membership(value):
    """Interpret the retired sample label as membership in the current study."""
    return "comparison" if value == LEGACY_SAMPLE else value


def effective_run_purpose(value):
    """Interpret archived labels as comparison without relabeling saved records."""
    return "comparison" if value in (LEGACY_PURPOSE, LEGACY_EXTERNAL_PURPOSE) else value


def is_archived_external_run(purpose, study_set):
    """Preserve readability of old exploratory work outside the study sample."""
    return purpose == LEGACY_EXTERNAL_PURPOSE and study_set == "expansion"


def validation_view(data, kind):
    """Return an isolated view for known v1 labels, retaining strict schemas.

    Unrecognized labels, missing fields, wrong types, and unsupported versions
    pass through unchanged and must fail the ordinary schema checks. This is a
    reader adapter, not a repair or a change to scientific content.
    """
    if (not isinstance(data, dict) or isinstance(data.get("schema_version"), bool)
            or data.get("schema_version") != 1):
        return data
    if kind == "registry":
        if not isinstance(data.get("plans"), list):
            return data
        changed = any(isinstance(plan, dict) and plan.get("study_set") == LEGACY_SAMPLE for plan in data["plans"])
        if not changed:
            return data
        view = deepcopy(data)
        for plan in view["plans"]:
            if isinstance(plan, dict) and plan.get("study_set") == LEGACY_SAMPLE:
                plan["study_set"] = "comparison"
        return view
    if kind not in {"run", "collaboration"}:
        raise ValueError("Unknown historical record kind.")
    allowed = (LEGACY_PURPOSE, LEGACY_EXTERNAL_PURPOSE) if kind == "run" else (LEGACY_PURPOSE,)
    return {**data, "purpose": "comparison"} if data.get("purpose") in allowed else data
