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

### 2026-11-02 — Implement PDF registration and the CLI

- **Category:** Code
- **Problem:** Prescreened PDFs could not yet be registered, preserved, or listed through a working workflow.
- **Decision/change:** Added the registry schema, shared validation and storage functions, document registration, and automated tests. The `heat-adaptation-llm-dataset` CLI provides `add` and `list`; the README documents their use. Registration checks saved originals, reuses identical documents, rejects conflicting study sets, preserves PDF copies without overwriting, and saves registry updates atomically.
- **Reason:** Establish traceable document identity and reliable collection before text preparation and model processing. The project-specific command name distinguishes this workflow from other heat adaptation projects.
- **Observed result:** The full suite passed 130 cases, and installed-command trials confirmed registration, duplicate detection, and listing with temporary fixtures. Freetown Heat Action Plan is registered as `plan_0001` in the development set; its stored checksum matches the supplied download and its preparation path is null.
- **Remaining questions:** Page-text preparation, collection-metadata editing, and the model, expert, and analysis stages remain to be implemented and tested.

### 2026-11-02 — Implement page preparation, selective OCR, and collection updates

- **Category:** Code
- **Problem:** Registered PDFs lacked prepared page text, image recovery, and saved preparation status. Collection metadata could not be corrected explicitly.
- **Decision/change:** Added preparation and page schemas, validation, preserved numbered attempts, native PDF extraction, page rendering, candidate crops, and selective EasyOCR. New format version 3 records image paths and `native`, `ocr`, or `mixed` text sources while retaining version 2 readability. Selected English CPU OCR, 150 DPI rendering, and a 10% individual image-area threshold after considering 25%. Mixed-text recovery retains native text and appends labeled regional OCR once. Added `prepare` with `--no-ocr`, partial metadata `update`, and saved preparation status in `list`. Updates preserve completed work and protect study-set assignments. Reviewed the README and design to distinguish implemented step 1 behavior from planned later stages.
- **Reason:** Establish reproducible document inputs and visible source gaps before model processing, while preserving originals, native text, and earlier attempts.
- **Observed result:** The latest full suite passed 543 cases, including two real cached-model OCR checks, with 11 dependency warnings. Freetown's `preparation_02` saved 46 pages: 34 native and 12 mixed, with 19 candidate regions on 14 pages. Fifteen regions returned text; four photographic regions returned none. Review confirmed native text preservation on all pages, an unchanged PDF checksum, and all 33 saved images matching fresh renders or crops. Content spot checks found useful recovery, garbled words and numbers, a smaller chart excluded by the threshold, and unchanged table reading-order problems. The status is `ready_with_gaps`; nonempty OCR is not an accuracy measure.
- **Remaining questions:** Compare 150 and 300 DPI on fixed regions; higher-DPI OCR improvement is not yet tested. Check the second development plan and targeted recovery of smaller important regions. MCP integration, model processing, expert files, and analysis remain to be built and tested.
