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

### 2026-11-03 — Enforce preparation readiness consistency

- **Category:** Code
- **Problem:** Readiness labels could pass validation despite unreadable pages.
- **Decision/change:** Reject unreadable pages in `ready` and `ready_with_gaps` preparations.
- **Reason:** Prevent contradictory preparation records from being accepted.
- **Observed result:** Four regression cases reproduce and verify the fix; all 547 tests pass.
- **Remaining questions:** None for this fix.

### 2026-11-04 — Build Part 2 foundations and check complete extractor input

- **Category:** Code
- **Problem:** Prepared plans lacked the response contracts, saved run format, model connection, and complete input needed for a reproducible extractor. Instructions alone did not enforce the response structure, and Ollama's context setting alone did not reliably reject oversized requests.
- **Decision/change:** Combined the Part 2 work from November 3–4: added content, agent-response, profile, run, tool-log, and validation-report schemas; strict JSON and reference validation; saved run settings and preservation/loading of run files; the four permitted format repairs; and explanatory Python comments. Added explicit profile selection, ordered prompts with clearer category definitions, a local text-only Ollama adapter, a tested compatible schema copy, and pre-generation token counting. Added complete extractor input assembly from an explicitly selected saved preparation, sharing source-integrity checks with run storage. Increased the development profile to 73,728 context tokens, 16,384 reserved output tokens, and a 1,800-second request timeout, retaining 57,344 tokens for all input. Updated the README and design and preserved a local Part 2 handoff, detailed event history, and diagnostic evidence archive.
- **Reason:** Separate model-authored content and issues from Python-recorded provenance, preserve exact inputs and failures, enforce format and capacity limits without silent truncation, and establish testable components before integrating the agent loop. Generate the provider schema from authoritative schemas rather than maintaining a divergent copy.
- **Observed result:** The latest full suite passed 1,506 tests with 11 existing OCR/PyTorch warnings. Direct structured generation with the original nonblank-string pattern produced excessively short values; its equivalent whole-string form passed compatibility checks. Two maintained-schema synthetic fixtures passed full validation without repairs and retained all nine checked quotations literally, while unnecessary flags and coding questions remained. Corrected render-only response parsing and verified counts against prior provider usage; an oversized diagnostic was blocked before generation, and a separate output-limited calibration was retained as truncated. A 65,536-context generation counted 54,013 input tokens, matched provider usage, returned three source-only markers, and stopped normally after 1,525 output tokens in about 263 seconds. Sampled swap stayed zero and the largest sampled Ollama allocation was about 24.6 GB; this was not a full-capacity benchmark. The exact 46-page Freetown input subsequently counted 23,772 tokens; with 16,384 reserved output tokens, 40,156 fit within 73,728, leaving 33,572. That check generated no extraction.
- **Remaining questions:** Integrate MCP tools, tested tool/history accounting, the bounded agent loop, actual environment and measurement capture, saved request/preflight/response artifacts, and an extraction command. Complete and inspect development extractions, including the second plan. Full 73,728-context and 16,384-output generation is **Not yet tested**. Verifier setup, expert stages, comparison, and the higher-DPI OCR experiment remain pending; structural validity and token fit do not establish extraction accuracy or completeness.

### 2026-11-06 — Integrate saved extraction, MCP tools, OCR, and the CLI

- **Category:** Code
- **Problem:** The Part 2 foundations worked separately but could not coordinate model-selected tools, complete a saved extractor run, or start extraction from the terminal.
- **Decision/change:** Combined the November 5–6 increments: added the official MCP SDK 2.3.0, selected-source page-text and exact-quotation tools, and full-page OCR using the existing cached CPU EasyOCR backend. Added Ollama tool definitions, validated arguments and ordered history, and a bounded tool-investigation phase followed by one final-schema answer. Connected the loop to observed environment capture, code/source checks, incremental request/preflight/response/tool/OCR preservation, validation, and final run publication. Added `extract` with explicit preparation, profile, and purpose, manual retry links, cancellation handling, and actual saved-status reporting. Comparison feedback hides model content and repair details; MCP stderr is preserved with the run. Updated the README and design to reflect the implemented workflow and its limits.
- **Reason:** Connect the tested components while preserving selected inputs, failures, and measurements. Separate tool investigation from final structured generation after a diagnostic showed that the final schema on the first turn could suppress a needed tool request. Keep independent comparison references protected from model-output exposure.
- **Observed result:** Added 288 cases since the previous checkpoint; the latest full suite passed 1,794 tests with 11 existing OCR/PyTorch warnings. Tests cover real MCP subprocesses and cached OCR, tool/history and source checks, budgets/timeouts, saving failures, manual repeats, abrupt termination, Ctrl+C, installed commands, paths containing spaces, and comparison disclosure restrictions. A live fictional prepared-text run succeeded and reloaded in 171.49 seconds with three model turns and one page-text request. An image-only fixture succeeded in 193.78 seconds with three model turns and two tool requests; OCR recovered `OPEN 3 COOLING CENTRES BY 2028` exactly in 3.71 seconds at 150 DPI. Counted/reported inputs matched, checked quotations were literal, and initial source/settings files were unchanged. These fixtures used two tool calls, 4,096 reserved output tokens, and a 600-second timeout. The image-only result classified the statement as both a goal and an action, requiring coding review. CLI model replies were controlled; no complete real development-plan extraction was performed. Documentation checks confirmed local links, command options, and preservation of earlier log entries.
- **Remaining questions:** Run and inspect the first full Freetown extraction and the second development plan. Review goal/action overlap and unnecessary issue flags; evaluate OCR on real layouts and higher DPI. Full configured context/output generation remains **Not yet tested**. Direct image delivery, broader run-status listing, verifier setup, validated expert/reference feedback, assessment, and analysis remain pending. Integration and format checks do not establish extraction accuracy or completeness.

### 2026-11-14 — Validate runtime and clarify prompts after the first Freetown attempt

- **Category:** Model
- **Problem:** Ollama updated beyond the validated runtime version. After compatibility checks, the first full Freetown extraction returned conflicting scope/link fields, and inspection identified additional citation and quotation concerns.
- **Decision/change:** Combined the pending runtime validation, development extraction, and prompt updates. Reviewed official Ollama source and live behavior before adding exact-version support for 0.40.16 alongside 0.40.14, retaining rejection of unvalidated versions and adding ten regression cases. Ran the unchanged development profile once on Freetown's 46-page `preparation_02`; preserved failed `run_extract_0001`, its original answer, and separate diagnostic review artifacts. Subsequently clarified source-supported scope/link consistency in the field definitions and shared instructions, physical PDF page citations using runner/tool page numbers, and exact continuous quotations without inserted ellipses joining separate passages. Added an extractor submission checklist. Validation and permitted format repairs remain unchanged; no retry or editing of the rejected answer was performed.
- **Reason:** Validate the runtime rather than bypass its compatibility guard, inspect real development behavior, and reinforce existing coding requirements without treating source interpretation as automatic format repair. Preserve unsuccessful attempts and distinguish diagnostic findings from expert assessment.
- **Observed result:** A live fictional Ollama/MCP extraction succeeded in 193.92 seconds with matching counted/reported inputs; an oversized request was blocked before generation. The full suite after runtime changes passed 1,804 tests with 11 existing OCR/PyTorch warnings. Freetown then finished in 1,156.61 seconds with five normally completed model requests, matching counted/reported inputs, ten page-text tool calls, and no fresh OCR. Its final answer used 12,575 output tokens without truncation, but validation rejected `mon_eval_0013` and `benefit_0007` for combining `plan_wide` with action links. No permitted repair applied; accepted content and review remain null. Of 51 candidate quotation uses checked diagnostically, 27 matched prepared text on other physical pages, all consistent with citations one page too high; 24 need further source review, and ten contain ellipses. These are text correspondence checks, not expert quality scores. All 41 checked input/source/settings files were unchanged, and the failed record reloaded correctly. After the prompt updates, 436 targeted profile, input, validation, and repair tests passed in 5.73 seconds. The revised prompts' effect on model behavior is **Not yet tested**.
- **Remaining questions:** Test the revised prompts on a small fixture before a separately initiated Freetown retry with a new linked run ID. Establish quotation continuity, citation correctness, and source support; review funding/resource treatment and unnecessary issue flags. No successful full Freetown extraction exists yet. The second development plan, full configured capacity, verifier, expert/reference, assessment, and analysis work remain pending.
