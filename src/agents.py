"""Load profiles and prepare the extractor's complete, source-bound input.

These are the input-assembly parts of DESIGN.md's planned agent module. They
read selected project files without generating answers or saving research runs.
models.py supplies transport, compatible schemas, and token-budget checking;
the agent loop, MCP client, and run integration remain future work.
"""

import json
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from models import prepare_ollama_response_schema
from storage import (
    PreparationValidationError, RegistryValidationError, load_plan_preparation, resolve_project_path,
)
from validation import ValidationProblem, parse_profiles_json


class ProfileValidationError(ValueError):
    """Keep structured problems as well as a readable configuration error."""

    def __init__(self, problems: list[ValidationProblem]) -> None:
        self.problems = problems
        details = "\n".join(
            f"{problem.location or '$'}: {problem.message}" for problem in problems
        )
        super().__init__(f"Profile configuration validation failed:\n{details}")


class ExtractorInputError(ValueError):
    """The selected source cannot safely be assembled into an extractor input."""

    def __init__(self, problems: list[ValidationProblem]) -> None:
        self.problems = problems
        details = "\n".join(f"{problem.location or '$'}: {problem.message}" for problem in problems)
        super().__init__(f"Extractor input validation failed:\n{details}")


@dataclass(frozen=True)
class ExtractorInput:
    """One in-memory input snapshot, ready for preview or a later model caller.

    source_path and page_count identify the exact preparation for future run
    records and response validation. Pass settings, messages, and response_format
    to models.py for a separate count-only check or model request. Building this
    object does not count tokens, certify tool/image access, or start a run.
    Frozen attributes still contain editable dictionaries/lists; save the actual
    sent request when execution is implemented, rather than relying on this flag.
    """

    plan_id: str
    source_path: str
    page_count: int
    settings: dict
    messages: list[dict[str, str]]
    response_format: dict


def load_profiles(
    project_root: Path | str, *, config_path: str = "configs/profiles.json"
) -> dict:
    """Read the complete strict configuration, without opening prompt files.

    Field validation covers every profile, not just the one selected later.
    It establishes configuration consistency, not that a model or OCR backend
    is installed, that its controls are supported, or that the document fits.
    """
    try:
        # Resolve against the supplied project, not the current terminal folder.
        # resolve_project_path also prevents a symlink escaping that project.
        path = resolve_project_path(project_root, config_path)
        text = path.read_bytes().decode("utf-8")
    except (OSError, ValueError) as error:
        raise ProfileValidationError([ValidationProblem(
            "other", config_path, f"Cannot read profile configuration: {error}"
        )]) from error
    configuration, problems = parse_profiles_json(text)
    if problems:
        raise ProfileValidationError(problems)
    return configuration


def load_profile(
    project_root: Path | str,
    profile_name: str,
    *,
    stage: Literal["extractor", "verifier"],
    config_path: str = "configs/profiles.json",
) -> dict:
    """Return the chosen profile plus shared tools and exact ordered prompt texts.

    The returned dictionary supplies the configuration portion of saved run
    settings. The future runner must add observed environment details before
    creating a run record. We do not fabricate versions, hardware, or Git state.
    No profile is selected by position, guessed from a stage, or silently reused.
    """
    if stage not in ("extractor", "verifier"):
        raise ProfileValidationError([ValidationProblem(
            "other", "stage", "Select stage 'extractor' or 'verifier'."
        )])
    configuration = load_profiles(project_root, config_path=config_path)
    selected = next(
        (profile for profile in configuration["profiles"] if profile["name"] == profile_name), None
    )
    if selected is None:
        raise ProfileValidationError([ValidationProblem(
            "reference", "profile_name", f"No profile named {profile_name!r}; select an exact configured name."
        )])
    if selected["stage"] != stage:
        raise ProfileValidationError([ValidationProblem(
            "reference", "profile_name",
            f"Profile {profile_name!r} is for {selected['stage']}, not {stage}."
        )])

    prompt_texts = []
    for index, prompt_path in enumerate(selected["prompt_paths"]):
        try:
            path = resolve_project_path(project_root, prompt_path)
            # read_text() normally changes CRLF line endings to LF. Decode bytes
            # explicitly to preserve the exact text supplied to the future model.
            text = path.read_bytes().decode("utf-8")
        except (OSError, ValueError) as error:
            raise ProfileValidationError([ValidationProblem(
                "reference", f"$.prompt_paths[{index}]", f"Cannot read prompt {prompt_path!r}: {error}"
            )]) from error
        if not text.strip():
            raise ProfileValidationError([ValidationProblem(
                "structure", f"$.prompt_paths[{index}]", f"Prompt {prompt_path!r} must contain nonblank instructions."
            )])
        # Do not strip, combine, reorder, or deduplicate prompts. Paths and texts
        # must correspond one-for-one, including deliberate repeated paths.
        prompt_texts.append(text)

    # Deep copies include nested dictionaries/lists. The caller gets its own
    # snapshot; later file edits cannot change this already-loaded dictionary.
    # It remains editable in memory until run storage freezes chosen settings.
    settings = deepcopy(selected)
    settings["document_tools"] = deepcopy(configuration["document_tools"])
    settings["prompt_texts"] = prompt_texts
    return settings


def build_extractor_input(
    project_root: Path | str,
    plan_id: str,
    *,
    source_path: str,
    profile_name: str,
    config_path: str = "configs/profiles.json",
) -> ExtractorInput:
    """Assemble every page of the selected preparation without writing files.

    Only the source preparation and its registered PDF are read as evidence.
    Current collection corrections or a newer preparation cannot replace the
    selected snapshot. A failed or inconsistent preparation stops assembly.
    ProfileValidationError and OllamaSchemaError retain their existing interfaces;
    source-file failures become ExtractorInputError with structured locations.
    This increment builds text messages for local Ollama, without tools/images.
    """
    settings = load_profile(project_root, profile_name, stage="extractor", config_path=config_path)
    if settings["model"]["execution_mode"] != "local":
        raise ExtractorInputError([ValidationProblem(
            "other", "$.settings.model.execution_mode", "This input builder currently supports local Ollama profiles."
        )])
    try:
        _, preparation, pages = load_plan_preparation(project_root, plan_id, source_path)
    except (PreparationValidationError, RegistryValidationError) as error:
        raise ExtractorInputError(error.problems) from error
    except (OSError, ValueError) as error:
        raise ExtractorInputError([ValidationProblem("other", "$.source_path", str(error))]) from error

    # The system message is exactly the loaded instruction texts in their saved
    # order. Source text and preparation notes stay in a separate user message.
    messages = [
        {"role": "system", "content": "\n\n".join(settings["prompt_texts"])},
        {"role": "user", "content": _format_extractor_source(preparation, pages)},
    ]
    # Catch text that cannot form a normal UTF-8 request before returning an
    # apparently usable package. This check neither trims nor rewrites strings.
    try:
        json.dumps(messages, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except ValueError as error:
        raise ExtractorInputError([ValidationProblem("structure", "$.messages", str(error))]) from error
    return ExtractorInput(
        plan_id=plan_id, source_path=source_path, page_count=preparation["page_count"],
        settings=settings, messages=messages, response_format=prepare_ollama_response_schema(),
    )


def _format_extractor_source(preparation: dict, pages: list[dict]) -> str:
    """Label metadata separately and insert each complete text string unchanged."""
    # Metadata is compact JSON so quotes/newlines cannot introduce fake fields.
    # The page text itself is inserted verbatim, with original line endings, OCR
    # supplements, punctuation, and whitespace preserved for later evidence use.
    def metadata(value) -> str:
        return json.dumps(value, ensure_ascii=False, allow_nan=False)

    # Make deterministic page boundaries that cannot already occur in the data.
    # This keeps a source's example page label from masquerading as our wrapper,
    # without deleting or escaping anything in the source itself.
    boundary = "=== ORIGINAL PDF"
    source_strings = [preparation["problem"] or ""] + [
        value for page in pages for value in (page["text"] or "", page["problem"] or "")
    ]
    while any(boundary in value for value in source_strings):
        boundary = "=" + boundary

    sections = [
        "Collection metadata from the selected saved preparation:\n" + metadata({
            "source_url": preparation["source_url"], "date_accessed": preparation["date_accessed"],
        }),
        f"Original PDF page count: {preparation['page_count']}",
        "Preparation summary (metadata, not source quotations):\n" + metadata({
            "status": preparation["status"], "problem": preparation["problem"],
            "image_render_dpi": preparation["settings"]["image_render_dpi"],
        }),
    ]
    for page in pages:
        text = page["text"]
        # Blank and unavailable are different source observations. Keep both
        # visible in metadata, without fabricating a quotation for either state.
        text_state = "unavailable" if text is None else "known_blank" if text == "" else "available"
        notes = {
            "text_state": text_state, "text_source": page["text_source"],
            "readable": page["readable"], "image_available": page["image_available"],
            # Version 2 did not save region screening; null means unknown, not 0.
            "candidate_image_region_count": len(page["image_regions"]) if "image_regions" in page else None,
            "problem": page["problem"],
        }
        sections.append(
            f"{boundary} PAGE {page['page_number']} BEGIN ===\n"
            + "Page preparation notes (metadata): " + metadata(notes) + "\n"
            + (text if text is not None else "")
            + f"\n{boundary} PAGE {page['page_number']} END ==="
        )
    return "\n\n".join(sections)
