# Implementation: Heat Adaptation LLM Dataset

**Implementation guide · updated 2026-11-18**

This guide maps the repository and specifies execution, preservation, and the remaining implementation work. [DESIGN.md](DESIGN.md) defines the research protocol, coding rules, and evaluation formulas; [README.md](README.md) provides setup and terminal commands. Existing JSON schemas are the authoritative field contracts. Proposed expert-file contracts appear at the end of this guide because their schemas are not implemented yet.

## 1. File directory

```text
heat_adaptation_llm_dataset/
├── src/                         # Application modules; see the responsibility map below
├── tests/                       # Automated checks with fictional inputs and controlled HTTP
├── configs/profiles.json         # Inkling routing, generation limits, prompts, shared tools
├── prompts/
│   ├── shared_coding.md          # Activity grouping, inclusion, evidence, and issue rules
│   ├── field_definitions.md      # Meaning of every answer field and missing value
│   └── extractor.md              # Extractor task and investigation instructions
├── schemas/                     # JSON field contracts; see the contract map below
├── data/                        # Tracked registry and separately preserved research inputs
│   ├── registry/plans.json       # Tracked identity, collection metadata, preparation links
│   ├── raw/<plan_id>.pdf         # Preserved original PDF; excluded from Git
│   └── processed/<plan_id>/preparation_NN/  # Excluded from Git
│       ├── preparation.json     # Settings, source identity, status, and page-file link
│       ├── pages.json           # Ordered physical pages, exact text, and review notes
│       └── images/              # Preserved page PNGs and candidate-region crops
├── runs/<plan_id>/run_extract_NNNN/
│   ├── output.json              # Saved run status, settings, measurements, accepted answer
│   ├── responses/               # Prepared requests, received responses, capacity reports
│   ├── artifacts/               # Source/code snapshots, MCP diagnostics, tool requests, OCR
│   ├── tool_log.json            # Ordered tool activity, when present
│   └── validation_report.json   # Final-answer checks, when attempted
├── artifacts/huggingface_checks/ # Explicit compatibility diagnostics, outside study runs
├── .cache/easyocr/               # Cached English OCR models
├── .venv/                       # Installed project environment
├── pyproject.toml / uv.lock      # CLI entry point, dependencies, and locked versions
├── .python-version              # Python selection
├── .gitignore                   # Exclusions for research files, caches, credentials
├── DESIGN.md / IMPLEMENTATION.MD / README.md / CHANGELOG.md
└── AGENTS.md                     # Local development agreements; excluded from Git
```

Git tracks code, schemas, prompts, profiles, registry metadata, and project documents. Back up PDFs, prepared text, runs, diagnostics, and OCR models separately. Some directories exist only after use. Credentials stay outside saved project artifacts.

### Module responsibilities

| Module | Owns |
| --- | --- |
| [src/cli.py](src/cli.py) | Arguments, command dispatch, terminal feedback, comparison disclosure restrictions, exit codes. |
| [src/documents.py](src/documents.py) | Registration, collection-metadata updates, native text preparation, and selective OCR coordination. |
| [src/document_tools.py](src/document_tools.py) | PDF rendering/image inspection, EasyOCR, source-bound page/quotation tools, and the local MCP server. |
| [src/agents.py](src/agents.py) | Profile/prompt loading, complete source input, bounded extractor execution, and incremental run recording. |
| [src/huggingface_api.py](src/huggingface_api.py) | Prepared HTTP requests, fixed provider routing, schema adaptation, size estimates, response interpretation, and usage. |
| [src/models.py](src/models.py) | Shared response/tool schemas, conversation validation, and model-result evidence types; no network operations. |
| [src/validation.py](src/validation.py) | Strict JSON parsing, schema checks, record relationships, source context, and permitted-repair coordination. |
| [src/repair.py](src/repair.py) | The four allowed formatting repairs, producing a separate candidate and audit trail. |
| [src/storage.py](src/storage.py) | Paths, identities, atomic publication, immutable evidence, active-record updates, and loading/integrity checks. |
| [src/huggingface_check.py](src/huggingface_check.py) | Explicit fictional-input compatibility checks, saved separately from research extractions. |

Planned modules are `src/expert_files.py` for references and assessments, and `src/metrics.py` for shared calculations/exports. Planned research paths are `runs/<plan_id>/run_verify_NNNN/`, `drafts/`, `reference_initial.json`, `reference_final.json`, `assessment_e.json`, `assessment_ev.json`, and `runs/analysis/`; optional notebooks will call the same calculation code.

### JSON contracts

Read the relevant schema before changing its producer, validator, or consumer. Python validators add cross-record and filesystem-context checks; a schema alone cannot establish source fidelity.

| Schema in `schemas/` | Contract |
| --- | --- |
| [registry.schema.json](schemas/registry.schema.json) | Registered document identity, metadata, study set, preparation link. |
| [preparation.schema.json](schemas/preparation.schema.json), [pages.schema.json](schemas/pages.schema.json) | Preparation settings/status, complete ordered pages, text/image routes and region metadata. |
| [profiles.schema.json](schemas/profiles.schema.json) | Editable profiles and shared document-tool settings; only hosted Hugging Face execution is active. |
| [plan_data.schema.json](schemas/plan_data.schema.json) | `plan_data.metadata`, `plan_data.actions`, evidence, categories, and missing values. |
| [agent_response.schema.json](schemas/agent_response.schema.json) | Complete model answer: `plan_data` and `plan_issues`, including issue-status constraints. |
| [curated_dataset.schema.json](schemas/curated_dataset.schema.json) | Shared answer format with expert resolutions allowed. |
| [run.schema.json](schemas/run.schema.json) | Saved wrapper, settings/environment, generation measurements, status, and accepted answer. |
| [tool_log.schema.json](schemas/tool_log.schema.json), [validation_report.schema.json](schemas/validation_report.schema.json) | Tool activity and final-response errors/repairs. |

Dates use `YYYY-MM-DD`, timestamps use UTC, durations use seconds, and stored paths are project-relative. Registry, profile, and extraction formats use version 1. New preparation uses version 3; version 2 remains readable. Historical local-model run settings remain readable under the run schema but cannot be selected as active local profiles. There are no aliases for obsolete extraction fields.

## 2. Execution path and current scope

The CLI entry point is `cli.main()`:

| Command | Application entry point | Result |
| --- | --- | --- |
| `add_plan` | `documents.register_document()` | Preserved PDF and registry entry. |
| `update_plan_data` | `documents.update_document_metadata()` | Validated partial registry update. |
| `prepare_plan` | `documents.prepare_document()` | New preparation folder and registry link. |
| `run_extract_mode` | `agents.run_extractor()` | One new extraction attempt and its evidence. |
| `list_plans` | `documents.list_documents()` | Read-only registration/preparation listing. |

Extraction follows `CLI → saved runner → extractor loop → Hugging Face API`, with `extractor loop → local MCP tools` for source checks. `validation.py` checks answers and relationships; `storage.py` owns publication and file integrity. The model never writes research files directly.

Inkling 2 Small (`thinkingmachines/Inkling-2-Small`), accessed through Hugging Face Inference Providers with DeepInfra pinned, produces E. E+V will start with that exact saved extraction and add a different hosted open-weight verifier through Hugging Face, which remains unselected and unimplemented. Registration, preparation, extraction, response validation, saving/loading, and expert-curated answer validation are implemented. Verification, expert references/assessments, metrics, comparison execution, and instruction export remain planned. Formal comparison is currently blocked.

## 3. Document collection and preparation

Experts screen eligibility using [DESIGN.md](DESIGN.md#eligible-plans) before registration. Registration assigns a document-version ID and SHA-256 checksum, preserves the original, and reuses an existing record for identical bytes. Revised contents receive a new ID. Duplicate registration cannot change metadata or study set.

`update_plan_data` accepts only title, source URL, access date, and study set. Validate the whole proposal before saving. Omitted fields stay unchanged. Development assignments remain fixed; other study-set changes require no saved model work. Registry corrections do not rewrite metadata snapshots in earlier preparations or runs.

### Prepare text automatically, investigate gaps with tools

1. Extract native text with pypdf and retain physical PDF page order.
2. Inspect every page for individual images covering at least 10% of its visible area with no native text inside their bounds. Preserve affected full-page PNGs and candidate crops.
3. Use full-page OCR for unavailable/unreliable native text. Append labeled regional OCR to good native text instead of replacing it; record the source as `mixed`.
4. Save a new `preparation_NN/`, then update its registry link. Retain failed attempts and previous preparations.

EasyOCR uses cached English models on the CPU at 150 DPI. Preparation downloads no models. `--no-ocr` skips recognition while retaining image checks. Known blank text is `""`; unavailable text is null. Every known page appears exactly once, in order. Preserve OCR warnings and source gaps even after recognition succeeds. Pixel region bounds use left, top, right, bottom from the saved image's top-left.

| Status | Meaning |
| --- | --- |
| `ready` | Automatic checks found no problems or review flags. |
| `ready_with_gaps` | A reading route exists for every page, with review notes. |
| `failed` | Counting or a required reading route failed. |

Readiness does not establish accurate text. Image screening can include photographs or miss small charts/partial text layers, and OCR does not guarantee table reading order. Experts inspect evidence against the original PDF.

### Source-bound document tools

The runner starts the MCP server over stdin/stdout using the same Python environment. A source fingerprint binds it to the selected preparation. The model can select page numbers or quotations, never another file or source.

| Tool | Behavior |
| --- | --- |
| `get_page_text(page_number)` | Exact selected page entry and source notes; no new recognition. |
| `find_quote(quote)` | Exact, case-sensitive, per-page substring search in initial prepared text, preserving spaces and line breaks. No normalization or cross-page joining. |
| `run_ocr(page_number)` | Fresh full-page EasyOCR from checked original bytes, using the active run's frozen settings and saving artifacts to that run. |

Quotation matching locates wording; it does not establish claim support or OCR fidelity. Fresh OCR never replaces the preparation or extends `find_quote`'s search corpus. Rendering/recognition runs sequentially with a reused OCR reader. Recognition failures can return to the model as diagnostic results; timeouts, protocol failures, and evidence-saving failures stop execution. Direct model image delivery and tool-requested regional OCR are deferred.

## 4. Hugging Face configuration and requests

`configs/profiles.json` contains shared `document_tools` plus named model profiles. Select `--profile` explicitly for extraction. Each run saves the selected values and ordered prompt texts.

| Setting | Current value |
| --- | --- |
| Extractor profile | `inkling2_small_hf_extractor_development` |
| Model | `thinkingmachines/Inkling-2-Small` |
| Service and fixed host | Hugging Face Inference Providers; `deepinfra` |
| Endpoint and routing ID | `https://router.huggingface.co/v1`; `thinkingmachines/Inkling-2-Small:deepinfra` |
| Context/output limits | 1,048,576 context tokens; 32,768 output tokens per request, including reported reasoning. |
| Generation controls | Temperature, top-p, and seed null: use provider defaults and record that choice. |
| Execution limits | 10 submitted document-tool calls per extraction; 1,800 seconds per model request; 120 seconds per tool request. |
| Tool/input settings | EasyOCR, English, CPU, 150 DPI; text input with local tools; direct image input disabled. |

Authentication reads `HF_TOKEN` at execution. Require it before allocating a run; never save authentication headers or credentials. `.env` files are not loaded automatically. [README.md](README.md#api-access) explains setup. Local LLM weights and serving software are unnecessary; OCR and document processing remain local.

### Input and request preparation

`build_extractor_input()` checks the exact preparation and original PDF, snapshots prompts/settings, and assembles the whole source without model/OCR calls or file writes. Join `shared_coding.md`, `field_definitions.md`, and `extractor.md` with two newlines in one system message. A user message contains collection metadata, preparation notes, and all unchanged page text with distinct physical-page boundaries. Document text and tool results are evidence, not instructions.

`build_huggingface_request()` creates a `PreparedHuggingFaceRequest`. Its serialized bytes, endpoint, timeout, expected model, and capacity limits are fixed. The runner saves its decoded body, the capacity check measures those bytes, and `request_huggingface_chat()` sends them without rebuilding the request. Internal tool arguments are objects; API arguments are JSON strings with unique call IDs. Return every tool result in call order, retaining the matching ID. Preserve reasoning in raw evidence while omitting it from API conversation replay.

Investigation exposes function definitions in `tools`. Final generation removes tools and requests strict `json_schema` output. `models.prepare_response_schema()` expands the authoritative schemas. DeepInfra receives a separate copy omitting `uniqueItems` and `if`/`then`/`else`; field names, required fields, types, permitted values, and other constraints remain. Adapt only schema positions, never literal property names or enum/const data. Complete Python validation retains all acceptance rules. Save the authoritative contract in the input snapshot and the adapted contract in the sent request.

Coding rules live in DESIGN.md and the prompts: group repeated occurrences of one specific activity, separate distinct primary tasks/outputs, retain neighborhood/phase associations, default status to `unspecified` without clear overall support, and copy continuous quotations with every relevant physical page. Structural acceptance does not assess these judgments.

### Capacity and response checks

Before every request, require:

```text
estimated_input_tokens = len(prepared_request.body_bytes) + 8192
estimated_input_tokens + max_output_tokens <= context_limit
```

Save the estimate, byte size, margin, limits, and fit decision separately from actual usage. Capacity reports use `counting_mode: conservative_estimate`, `input_tokens: null`, and `verified_provider_count: false`. This is a loose size screen, not a certified bound on hidden provider formatting. Stop oversized requests without shortening the source or reducing the selected output reservation.

Actual input/output totals come only from API `prompt_tokens`/`completion_tokens`; unavailable usage remains null and reported zero stays zero. Reject malformed usage or tool-call containers, invalid arguments, changed returned model identity, unknown completion reasons, reported truncation, and reported usage above configured limits. Preserve received bytes and valid observations even when the request fails. Provider error messages include the nested explanation when available. HTTP has no automatic retries, redirects, model switches, or provider fallback.

### Compatibility diagnostics

`uv run --locked python -m huggingface_check` defaults to Inkling and deliberately makes paid requests. Run it before adopting a changed serving setup, rather than before each plan. It stops at the first failed check:

| Check | Requested output cap |
| --- | --- |
| Small strict schema with a conflicting requested field | 2,048 tokens |
| Adapted project schema on a fictional complete one-page plan | 4,096 tokens |
| Deliberately short output-limit probe | 64 tokens |

Limits are capped by the profile, with at most 300 seconds per request. Requested caps are not guaranteed billing ceilings. Only the last probe permits truncation; missing output usage makes it inconclusive. Validate the fictional answer against the original contract. Save settings, exact requests, responses, estimates, usage, and results under `artifacts/huggingface_checks/`. These checks do not modify study files or establish real-plan accuracy or future provider behavior.

## 5. Extractor execution and preservation

### Extractor control

`run_extractor()` wraps the in-memory `run_extractor_loop()` with checkpoint saving:

1. Validate explicit plan/preparation/profile/purpose choices and authentication; observe client software/Git state, snapshot code/contracts, and allocate a new `running` record.
2. Assemble the complete input and discover the selected-source MCP catalogue.
3. Prepare, record, budget, and send an investigation request. Accept valid tool calls or `READY_FOR_FINAL_RESPONSE` with optional outer whitespace. Other control text fails without another model call.
4. Execute calls sequentially. Every submitted MCP call consumes budget, including failures; excess requests receive logged non-execution errors. Catalogue discovery consumes no slot. Continue until readiness or budget exhaustion.
5. Send one final request with tools disabled and the response schema enabled. Validate completion and answer, apply only allowed repairs, and recheck source, collection metadata, and application snapshots.
6. Stop the MCP subprocess and preserve its diagnostics before final publication. Return the last successfully saved status, even if the answer was valid in memory.

The readiness turn counts as a generation. Blocked preflight is retained as an attempt but contributes no generation usage. Whole-stage elapsed time includes setup, tools, validation, saving, and cleanup. Request deadlines cover connection, response reads, and in-request evidence callbacks; tool deadlines also cover SDK waiting/decoding.

### Saved run

`output.json` follows [run.schema.json](schemas/run.schema.json). It records plan/run identity, stage/purpose, source path, retry/input links, UTC start/end, measured duration, frozen settings/environment, generation calls, tool-log path, status/error, and accepted `plan_data`/`plan_issues`. Only saved success retains the accepted answer; failures retain evidence with null accepted output. Unknown measurements remain null.

A `plan_id` identifies one PDF version, and a `run_id` identifies one execution. Action/issue IDs are local to linked outputs and persist through verification/curation. Each manual invocation gets a new numbered run directory, including retries. `--retry-of-run-id` links a failed attempt; it does not resume or overwrite it. Keep the first successful output under fixed settings for comparison; label deliberate successful repeats exploratory.

### Saved extractor execution

| Evidence | Location within the run |
| --- | --- |
| Frozen source input and tool catalogue | `artifacts/extractor_input.json`, `artifacts/mcp_catalogue.json` |
| Application code, schemas, setup files, SHA-256 manifest | `artifacts/code/`, `artifacts/code_fingerprints.json` |
| Environment notes | `artifacts/environment/observations.json` |
| Exact request, capacity reports, headers, received chunks, result summary | `responses/attempt_NN/` |
| Decoded HTTP body and exact assistant text | `responses/response_NN.json`, `responses/response_NN.txt`, when available |
| Normalized assistant message | `responses/attempt_NN/assistant_message.json` |
| Pending/completed tool activity | `artifacts/tool_requests/`, `tool_log.json` |
| Fresh OCR request, PNG, text, report with hashes/settings/times/errors | `artifacts/ocr/request_NNNN/` |
| Full conversation and subprocess stderr | `artifacts/conversation.json`, `artifacts/mcp_stderr.log` |
| Validation and separate repaired candidate | `validation_report.json`, `responses/repaired_final.txt` when changed |

Observe local client versions and Git state. Remote weight revision, runtime version, quantization, model hardware, and loaded state remain null because the adapter cannot inspect them. Source/code snapshots establish what was used, including uncommitted code; they do not identify an undisclosed remote weight revision.

Storage validates paths, source identity, selected preparation, and linked records. Successful runs require the frozen input; loading compares its fingerprint with the preparation and page text. Completed records/artifacts cannot be overwritten. Active records and ordered logs can grow atomically without changing fixed settings or earlier known observations. Use one writer at a time.

Checkpoint failure stops execution and triggers best-effort failed publication. Preserve available bytes and usage. A failed save or abrupt termination may leave `running`, partial artifacts, and null end/duration; recovery is manual after confirming process termination. Cancellation preserves available evidence and returns 130. Other CLI outcomes are 0 for saved success, 1 for operational failure, and 2 for invalid arguments.

Comparison-plan feedback remains restricted, including exploratory runs: hide claims, issues, response fragments, repair details, and client logs until a validated independent-reference workflow exists. Files remain on disk. If troubleshooting exposes outputs, an unexposed expert must prepare the initial reference.

### Validation and permitted repair

`validation.py` checks strict JSON, fields/values, unique IDs, action links, physical page ranges, source/collection consistency, issue roles, and run relationships. Problems use `syntax`, `structure`, `reference`, or `other`. It neither inserts defaults nor interprets factual support. `validate_and_repair_agent_response()` coordinates these four repairs through `repair.py`:

| Repair | Boundary |
| --- | --- |
| Whole-response JSON code fence | One complete answer, without surrounding commentary. |
| Trailing comma | Immediately before a closing bracket/brace, outside strings. |
| Missing closing delimiters | Unambiguous nesting after a complete value and confirmed normal completion. |
| Single page number | Positive integer converted to a one-item `page_numbers` list, then range-checked. |

Preserve the original and candidate separately and repeat every acceptance check. Failed/truncated requests receive no repairs. Missing fields, unsupported details, duplicates, and other substantive violations require a separately initiated attempt.

Issue checks enforce one linked issue per affected action, valid IDs/links, and resolver/status relationships. Open issues require null resolver/resolution; resolved issues require a permitted resolver and nonblank explanation. E uses extractor origin/resolver. V retains original identities/origins, may reopen issues, and uses verifier origin for additions and verifier resolver for its fixes. Expert resolutions belong only in curated copies, validated with `validate_curated_dataset()`. Removed/merged actions require updated links and an explanation of retired targets where a link becomes null.

## 6. Remaining implementation

### Verifier control — planned

Select and validate a different hosted model through Hugging Face. Add its profile, prompt, structured-output/tool checks, and runner. Load the exact successful Inkling E run, source fingerprint, answer/issues, and shared tool settings. Supply the whole source and check all fields, grouping, unflagged content, omissions, and evidence through the same bounded investigation/final-answer pattern.

Save a separate verifier run with `input_run_id` pointing to E. Preserve continuing action/issue IDs and issue origins, allocate IDs for additions, and explain resolutions of every grouped concern. Check source/tool consistency and issue continuity with existing validators. A failed V retry stays linked to the same E run. Freeze both configurations, including clean committed code, before enabling formal comparison.

### Expert files and measurement — planned

1. Require a successful linked E/E+V pair. Generate an empty reference template with collection metadata. Experts code the original PDF independently before viewing outputs; validate and preserve `reference_initial.json`.
2. Inspect both outputs for supported content missing from that reference. Save one shared `reference_final.json` with justified revisions and source evidence, retaining the initial file.
3. Assess each output against every final reference activity with 0/0.5/1 and reasons. Group split/duplicate output records by activity; a bundled record may contribute to several groups. Record all contributing IDs, source support, reference links, and one evidence judgment per group.
4. Review every initially open E issue marked resolved by V before expert curation. Confirm that every grouped concern was addressed. E has no resolution checks. Record other useful issue behavior in review notes.
5. Complete assessments only after full reference/output/resolution coverage and non-null judgments. Preserve revisions as new named files and select exact completed files for analysis. Record reviewer identities, expertise, roles, and disagreement procedures during development.

An invented/ineligible activity is unsupported, has no reference link, and fails evidence adequacy. Wrong details within a supported activity affect its score/evidence judgment. Pending support is `undetermined`; pending scores and evidence/resolution judgments are null. All supplied quotations, physical pages, and support for recorded details require PDF review.

#### Worked scoring example

A fictional plan reports 100 trees planted in North Ward in 2025 and 200 planned for South Ward in 2027. The reference has one tree-planting action, type `nature-based`, retaining both phases and their associated details. Overall status is `unspecified` because no overall status is given.

| Score | Example output |
| --- | --- |
| 1 | Both phases, wards, quantities, dates, and statuses are correct; unstated fields use the defined missing values. |
| 0.5 | North Ward is correct but South Ward is omitted, or all 300 trees are described as already planted. |
| 0 | Tree planting is omitted or has no correct substantive description. |

### Measurement capture and calculation — planned

`metrics.py` will use validated selected files and [DESIGN.md appendix G](DESIGN.md#g-evaluation-measures-and-calculations): three quality measures (action score percentage, unsupported action count with total distinct activities, adequate-evidence percentage), two issue measures (open issues and expert-confirmed/claimed verifier resolutions), plus runtime, provider-reported tokens, and failures. Expert grouping supplies distinct-activity units. Match resolutions by issue ID; later expert fixes are outside the model comparison.

E+V shares E and adds V duration/tokens. Report failed attempts separately: E at 100 seconds, failed V at 30, successful V at 60 gives successful-processing times of 100 and 160 seconds plus one separately reported V failure. EasyOCR contributes duration, not LLM tokens. Missing required observations or pending judgments make a measure unavailable; zero denominators are not applicable. Export per-plan values, numerators/denominators, and paired changes. Optional notebooks use the same calculations.

### Instruction dataset assembly — planned

After assessment, experts curate separate supported answers while preserving assessed outputs. Each whole-plan example pairs extraction instructions, sufficient source text/page links and reviewed recovery, and an expert-curated answer. Correct/exclude unsupported content, preserve reasons/source links, and validate targets with the curated-answer contract. Expert fixes retain issue IDs/origins and record expert authorship/resolution; confirmation of a V fix remains in `resolution_checks`. Pilot the export format and report plans, examples, and grouped actions separately. Fine-tuning remains future work.

## 7. Development checkpoint and next steps

### Current development checkpoint

The Inkling diagnostic passed all three checks. Freetown `run_extract_0005` succeeded without repairs in about 193 seconds, with 14 actions and one extractor-claimed resolved issue requiring expert confirmation. Preliminary review found improved quotation matching and remaining evidence gaps. Formal quality scores and E+V performance are **Not yet tested**. Earlier trials and decisions remain in [CHANGELOG.md](CHANGELOG.md).

The full suite passed 1,660 tests with 11 OCR dependency warnings after the request/readability refactor. Offline comparisons preserved request bytes, routing, timeouts, and capacity estimates across four representative request cases. All 734 preservation-baseline files remained unchanged, and all five historical Freetown records loaded. No paid calls were made. These checks establish software behavior, not extraction accuracy or future provider behavior.

Next: finish development-plan review and the second development plan; implement/validate the different hosted verifier; pilot expert-file validation and the agreed measures; freeze settings and run the five-plan paired comparison; then curate/export instruction examples. Direct model images, richer status listing, expansion, and fine-tuning are deferred.

## Appendix: supporting JSON files

Existing workflow fields are defined in the [JSON contract map](#json-contracts) and their schemas. The following expert-file definitions remain implementation specifications until their schemas and workflow are added. Fields are required unless explicitly optional or nullable.

### Expert references — planned

Use this planned format for the independent initial reference and shared final reference. Validate both against the current plan data schema. Record reviewer roles and disagreement procedures during the pilot.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | positive integer | Expert reference format version. |
| `plan_id` | string | Registered document. |
| `prepared_by` | nonempty list of strings | Names or study codes identifying the experts who prepared this version. |
| `plan_data` | object | Same plan information and actions as DESIGN.md. |
| `revisions` | list of revision objects | Empty for the initial reference. The final reference records accepted changes from that initial version. |
| `revisions[].record_ids` | list of strings | Reference actions affected by the revision. |
| `revisions[].reason` | string | Why the change/addition is justified. |
| `revisions[].evidence` | list of evidence objects | Supporting source passages and pages. |

### Expert assessments — planned

Each file assesses one saved output. Completion requires a shared final reference, non-null judgments, complete activity coverage, and checks for every initially open E issue marked resolved by V. The pair's final-reference paths must agree.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | positive integer | Assessment format version. |
| `plan_id` | string | Registered document. |
| `configuration` | enum | `extractor_only` or `extractor_verifier`. |
| `run_id` | string | Exact assessed output. |
| `initial_reference_path` | string | Preserved independent reference. |
| `final_reference_path` | string or null | Shared final reference; nullable while draft. |
| `status` | enum | `draft` or `complete`. |
| `completed_at` | timestamp string or null | Completion time; null while draft. |
| `assessed_by` | nonempty list of strings | Names or study codes identifying the experts assessing this output. |
| `record_scores` | list of score objects | One per final reference action. |
| `output_groups` | list of objects | Each distinct output activity, its source support, and its combined evidence judgment. |
| `resolution_checks` | list of resolution-check objects | Initially open E issues with `issue_status` set to `resolved` and `resolved_by` set to `verifier` in saved E+V. Empty for E. |
| `review_notes` | list of strings | Explanatory examples and observations, including useful corrections or issue behavior. Empty when none are needed. |

Each record score applies the rubric in DESIGN.md.

| Field | Type | Meaning |
| --- | --- | --- |
| `reference_record_id` | string | Final reference action. |
| `output_record_ids` | list of strings | Matching output actions. |
| `score` | 0, 0.5, 1, or null | Rubric judgment; null while pending. Omission scores 0 once assessed. |
| `reason` | string | Explanation of the score, including missing, incorrect, or unsupported details. |

Each output group represents one specific activity. Combine split or duplicate records and retain every contributing record ID. A bundled record may contribute to more than one group.

| Field | Type | Meaning |
| --- | --- | --- |
| `description` | string | Specific activity represented by the group and the content it covers. |
| `output_record_ids` | nonempty list of unique strings | Raw output action IDs contributing to this activity. |
| `reference_record_id` | string or null | Corresponding final reference activity when supported. Null for an unsupported activity or pending match. |
| `support_status` | enum | Whether the source supports an eligible heat adaptation activity, using `supported`, `unsupported`, or `undetermined` while pending. Detail errors within supported activities affect the action score. |
| `evidence_adequate` | Boolean or null | True when the group's supplied evidence meets every requirement in DESIGN.md. False for missing or inadequate evidence, null while pending. |
| `reason` | string | Explanation of activity support and evidence adequacy, identifying important claim, quotation, OCR, or page errors. |

Every raw output action must appear in an assessed group. Supported groups must link to unique final reference activities, with score matches agreeing with those groups. An omitted reference activity has an empty match list and score 0 once assessed. An unsupported group requires a null reference link and `evidence_adequate` false. Record source passages and page references in the explanation when needed to substantiate judgments.

Each resolution check assesses an initially open E issue that V marked resolved in its saved output, before expert curation.

| Field | Type | Meaning |
| --- | --- | --- |
| `issue_id` | string | Initially open issue V marked resolved. |
| `justified` | Boolean or null | Expert judgment of the claimed resolution; null while pending. |
| `reason` | string | Explanation addressing the issue's grouped concerns. |
