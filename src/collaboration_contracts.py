"""Read C configuration and validate tasks, findings, and complete answers.

This module never starts a model, OCR, or MCP server. C has separate contracts
so enabling worker identities cannot relax baseline E/V validation.
"""

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path

from agents import _format_plan_source, load_profile
from huggingface_api import _huggingface_profile
from models import _json_object, prepare_collaboration_schema
from storage import load_plan_preparation, preparation_text_fingerprint, resolve_project_path
from validation import (
    require_run_purpose, validate_run_purpose,
    _nonfinite_json_numbers, _validate_page_count, _validate_structure, _validate_response_references,
)


SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
WORKERS = ("worker_1", "worker_2")
ACTORS = ("coordinator", *WORKERS)
DEFAULT_COLLABORATION_PROFILE = "glm5_3_flash_hf_collaboration"


class CollaborationContractError(ValueError):
    """Reject invalid or inconsistent configuration/model data without repairs."""


@dataclass(frozen=True)
class CollaborationInput:
    """A source-only snapshot; controller startup detaches nested dictionaries."""

    plan_id: str
    source_path: str
    source_fingerprint: str
    page_count: int
    source_message: dict
    source_metadata: dict
    configuration: dict
    profiles: dict


def require_contract(data: object, filename: str) -> None:
    """Apply the original schema, including rules omitted from API grammars."""
    if filename not in {"collaboration_config.schema.json", "collaboration_task.schema.json",
                        "collaboration_result.schema.json", "collaboration_response.schema.json"}:
        raise CollaborationContractError("Select a known local collaboration contract.")
    problems = _validate_structure(
        data, SCHEMAS / filename, "collaboration", required_formats=("date",),
        schema_references=(("urn:heat-adaptation:plan-data", SCHEMAS / "plan_data.schema.json"),),
    )
    problems += _nonfinite_json_numbers(data)
    if problems:
        raise CollaborationContractError("; ".join(f"{p.location}: {p.message}" for p in problems))


def load_collaboration_profiles(
    project_root: Path | str, *, config_path: str = "configs/collaboration.json",
) -> dict:
    """Read and validate named C bindings without loading prompts or plans."""
    document = _json_object(resolve_project_path(project_root, config_path).read_bytes())
    require_contract(document, "collaboration_config.schema.json")
    names = [entry["name"] for entry in document["profiles"]]
    if len(set(names)) != len(names):
        raise CollaborationContractError("Collaboration profile names must be unique.")
    return document


def load_collaboration_configuration(
    project_root: Path | str, profile_name: str = DEFAULT_COLLABORATION_PROFILE, *,
    config_path: str = "configs/collaboration.json",
    model_config_path: str = "configs/profiles.json",
) -> tuple[dict, dict]:
    """Bind three explicit profiles without selecting by position or fallback."""
    root = Path(project_root)
    document = load_collaboration_profiles(root, config_path=config_path)
    config = next((entry for entry in document["profiles"] if entry["name"] == profile_name), None)
    if config is None:
        raise CollaborationContractError(f"No collaboration profile named {profile_name!r}.")
    profiles = {
        actor: load_profile(root, config["agents"][actor],
                            stage="coordinator" if actor == "coordinator" else "worker",
                            config_path=model_config_path)
        for actor in ACTORS
    }
    validate_bindings(config, profiles)
    return deepcopy(config), profiles


def validate_bindings(config: dict, profiles: dict) -> None:
    """Check the same binding policy at file loading and controller startup."""
    require_contract({"schema_version": 1, "profiles": [config]}, "collaboration_config.schema.json")
    if set(profiles) != set(ACTORS):
        raise CollaborationContractError("C requires its coordinator and two workers.")
    for actor, profile in profiles.items():
        _huggingface_profile(profile)
        if profile["name"] != config["agents"][actor] or profile["stage"] != (
            "coordinator" if actor == "coordinator" else "worker"
        ):
            raise CollaborationContractError("Agent bindings must match profile names and roles.")
    if len({p["model"]["name"].casefold() for p in profiles.values()}) != 3:
        raise CollaborationContractError("C requires three distinct configured model identities.")
    shared = profiles["coordinator"]["document_tools"]
    if any(p["document_tools"] != shared or p["image_input_enabled"]
           or p["model"]["provider"] != "deepinfra" for p in profiles.values()):
        raise CollaborationContractError("C requires shared text/document tools and the pinned DeepInfra host.")
    if any(profiles[WORKERS[0]][field] != profiles[WORKERS[1]][field]
           for field in ("prompt_paths", "prompt_texts")):
        raise CollaborationContractError("Both C workers must load the same ordered prompts.")
    limits = config["limits"]
    coordinator = profiles["coordinator"]
    if limits["max_estimated_tokens"] <= coordinator["context_limit"]:
        raise CollaborationContractError("Reserve coordinator final capacity plus investigation tokens.")
    final_seconds = limits.get("final_generation_seconds", coordinator["model_timeout_seconds"])
    if limits["max_elapsed_seconds"] <= final_seconds:
        raise CollaborationContractError("Reserve coordinator final time plus investigation time.")


def _require_page_count(page_count: int) -> None:
    if _validate_page_count(page_count):
        raise CollaborationContractError("A positive integer source page count is required.")


def build_collaboration_input(
    project_root: Path | str, plan_id: str, *, source_path: str,
    purpose: str = "comparison",
    profile_name: str = DEFAULT_COLLABORATION_PROFILE,
    config_path: str = "configs/collaboration.json",
    model_config_path: str = "configs/profiles.json",
) -> CollaborationInput:
    """Read one explicit study preparation, never baseline/expert outputs.

    The saved runner wraps this source-only builder; original PDF/preparation
    integrity checks are shared with E/V.
    """
    require_run_purpose(purpose)
    config, profiles = load_collaboration_configuration(
        project_root, profile_name, config_path=config_path, model_config_path=model_config_path,
    )
    entry, preparation, pages = load_plan_preparation(project_root, plan_id, source_path)
    problems = validate_run_purpose(purpose, entry["study_set"])
    if problems:
        raise CollaborationContractError("; ".join(problem.message for problem in problems))
    return CollaborationInput(
        plan_id, source_path, preparation_text_fingerprint(preparation, pages),
        preparation["page_count"], {"role": "user", "content": _format_plan_source(preparation, pages)},
        {name: preparation[name] for name in ("source_url", "date_accessed")}, config, profiles,
    )


def validate_task(task: dict, *, page_count: int, completed_tasks: set[str]) -> None:
    _require_page_count(page_count)
    require_contract(task, "collaboration_task.schema.json")
    if any(page > page_count for page in task["source_pages"]):
        raise CollaborationContractError("Task scope exceeds the physical PDF page range.")
    if not set(task["context_task_ids"]) <= completed_tasks:
        raise CollaborationContractError("Task context must identify completed tasks.")
    if task["independent"] and task["context_task_ids"]:
        raise CollaborationContractError("Independent checks cannot receive peer findings.")


def validate_worker_result(result: dict, task: dict, *, page_count: int, action_ids: set[str]) -> None:
    _require_page_count(page_count)
    require_contract(result, "collaboration_result.schema.json")
    if any(result[name] != task[name] for name in ("task_id", "worker_id", "draft_version")):
        raise CollaborationContractError("Worker result must match its assigned task, identity, and draft version.")
    pages = list(result["checked_pages"])
    for finding in result["findings"]:
        if finding["related_action_id"] is not None and finding["related_action_id"] not in action_ids:
            raise CollaborationContractError("A worker finding references an unknown draft action.")
        pages.extend(page for evidence in finding["evidence"] for page in evidence["page_numbers"])
    if any(page > page_count for page in pages):
        raise CollaborationContractError("Worker findings exceed the physical PDF page range.")


def validate_collaboration_response(data: dict, *, page_count: int, source_metadata: dict) -> None:
    _require_page_count(page_count)
    require_contract(data, "collaboration_response.schema.json")
    # Reuse action IDs, issue links, empty-field issues and evidence-page checks.
    # The separate C schema restricts origins/resolvers to fixed C identities.
    problems = _validate_response_references(data, page_count=page_count, stage="collaboration")
    if problems:
        raise CollaborationContractError("; ".join(f"{p.location}: {p.message}" for p in problems))
    metadata = data["plan_data"]["metadata"]
    if any(metadata[name] != source_metadata[name] for name in ("source_url", "date_accessed")):
        raise CollaborationContractError("The answer must retain the selected preparation's collection metadata.")


def coordinator_tools() -> list[dict]:
    """Expose one batched delegation interface and explicit draft/completion steps."""
    task = prepare_collaboration_schema("collaboration_task.schema.json")
    assignment = deepcopy(task)
    for key in ("task_id", "draft_version"):
        del assignment["properties"][key]
        assignment["required"].remove(key)
    final = prepare_collaboration_schema("collaboration_response.schema.json")
    specs = [
        ("assign_tasks", "Assign one task to each selected worker; independent tasks run in parallel.",
         {"assignments": {"type": "array", "minItems": 1, "maxItems": 2, "items": assignment}}),
        ("submit_draft", "Save a complete working answer based on the current draft version.",
         {"based_on_version": {"type": "integer", "minimum": 0}, "draft": final}),
        ("finish_investigation", "Finish after both workers contribute and a checked draft is saved.", {}),
    ]
    return [{"type": "function", "function": {"name": name, "description": description,
              "parameters": {"type": "object", "required": list(properties),
                             "additionalProperties": False, "properties": properties}}}
            for name, description, properties in specs]
