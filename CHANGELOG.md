# Structured change log

This log records important decisions, changes, unsuccessful attempts, and lessons learned during the project. It preserves the rationale and observed outcomes to support research reporting. Routine tasks do not require an entry.

Copy the template below and add new entries at the bottom.

## Categories

Choose the category that fits best.

| Category | Use for |
| --- | --- |
| Code | Code, tools, and system setup. |
| Model | Model choices, settings, prompts, and agent instructions. |
| Data | Source documents, text preparation, data structure, and corrections. |
| Research | Research questions, study design, evaluation, and findings. |
| Process | Working practices, review procedures, and documentation. |
| Other | Changes that do not fit the categories above. |

## Entry template

Keep each entry concise. Under observed result, record what was observed and learned. Use "Not yet tested" when results are not yet available.

### YYYY-MM-DD — Short title

- **Category:** Code / Model / Data / Research / Process / Other
- **Problem:** What needed to be addressed?
- **Decision/change:** What was decided or changed?
- **Reason:** Why was this approach chosen?
- **Observed result:** What was observed? What was learned?
- **Remaining questions:** What still needs to be answered? Write "None" if there are no open questions.

## Entries

### 2026-11-01 — Set up the document-registration development environment

- **Category:** Code
- **Problem:** The repository contained documentation only, and `uv` could not find Python 3.12. Exact dependency selections were not recorded.
- **Decision/change:** Approved the initial scope of environment setup, a registration CLI, registry validation, and PDF-preservation checks, proceeding file by file with explanations. Created `pyproject.toml`, `.python-version`, and `uv.lock`; used `uv` to install CPython 3.12.14, create `.venv`, and install `jsonschema` 4.26.0, `pytest` 9.2.0, and nine supporting packages.
- **Reason:** Establish a reproducible development environment and reliable document-registration foundation before text preparation and model processing.
- **Observed result:** Interpreter version and paths, environment isolation, Git exclusion, and agreement with the lockfile verified. JSON Schema library smoke checks and pytest startup passed.
- **Remaining questions:** Select the first development PDF. Document-registration behavior is not yet implemented or tested.
