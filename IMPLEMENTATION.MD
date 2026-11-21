# Implementation: Heat Adaptation LLM Dataset

**Implementation guide · updated 2026-11-21**

This guide maps the repository and specifies execution, preservation, and remaining work. [DESIGN.md](DESIGN.md) defines the research protocol, coding rules, and evaluation; [README.md](README.md) provides available commands. Existing JSON schemas are the implemented field contracts. E/V execution and expert reference creation/validation are implemented. Collaboration (C) has an agreed protocol and selected coordinator, GLM-5.3-Flash; its runtime and contract extensions remain planned.

## 1. File directory

```text
heat_adaptation_llm_dataset/
├── src/                         # Application modules; see the responsibility map below
├── tests/                       # Automated checks with fictional inputs and controlled HTTP
├── configs/profiles.json         # Extractor/verifier routing, limits, prompts, shared tools
├── prompts/
│   ├── shared_coding.md          # Activity grouping, inclusion, evidence, and issue rules
│   ├── field_definitions.md      # Meaning of every answer field and missing value
│   ├── extractor.md              # Extractor task and investigation instructions
│   └── verifier.md               # Approved verification task and issue continuity rules
├── schemas/                     # JSON field contracts; see the contract map below
├── data/                        # Tracked registry and separately preserved research inputs
│   ├── registry/plans.json       # Tracked identity, collection metadata, preparation links
│   ├── raw/<plan_id>.pdf         # Preserved original PDF; excluded from Git
│   └── processed/<plan_id>/preparation_NN/  # Excluded from Git
│       ├── preparation.json     # Settings, source identity, status, and page-file link
│       ├── pages.json           # Ordered physical pages, exact text, and review notes
│       └── images/              # Preserved page PNGs and candidate-region crops
├── expert_references/<plan_id>/expert_reference.json # Expert form; excluded from Git
├── runs/<plan_id>/
│   ├── run_extract_NNNN/         # Extractor attempts; same file layout as below
│   ├── run_collaboration_NNNN/   # Planned C attempts, including task/message records
│   └── run_verify_NNNN/          # Verifier attempts linked to an exact extractor input
│       ├── output.json          # Status, settings, measurements, accepted answer
│       ├── responses/           # Requests, responses, capacity reports, repaired candidate
│       ├── artifacts/           # Input/code snapshots, MCP diagnostics, tools, OCR
│       │   └── quotation_page_report.json # Citation repairs and remaining review flags
│       ├── tool_log.json        # Ordered tool activity, when present
│       └── validation_report.json # Final-answer checks, when attempted
├── artifacts/huggingface_checks/ # Explicit compatibility diagnostics, outside study runs
├── .cache/easyocr/               # Cached English OCR models
├── .venv/                       # Installed project environment
├── pyproject.toml / uv.lock      # CLI entry point, dependencies, and locked versions
├── .python-version              # Python selection
├── .gitignore                   # Exclusions for research files, caches, credentials
├── DESIGN.md / IMPLEMENTATION.MD / README.md / CHANGELOG.md
└── AGENTS.md                     # Local development agreements; excluded from Git
```

Git tracks code, schemas, prompts, profiles, registry metadata, and project documents. Back up PDFs, prepared text, expert references, runs, diagnostics, and OCR models separately. Some directories exist only after use. Credentials stay outside saved project artifacts.

### Module responsibilities

| Module | Owns |
| --- | --- |
| [src/cli.py](src/cli.py) | Arguments, command dispatch, terminal feedback, comparison disclosure restrictions, exit codes. |
| [src/documents.py](src/documents.py) | Registration, collection-metadata updates, native text preparation, and selective OCR coordination. |
| [src/expert_files.py](src/expert_files.py) | Independent reference creation and validation against checked collection metadata and the original PDF, without model-output access. |
| [src/document_tools.py](src/document_tools.py) | PDF rendering/image inspection, EasyOCR, source-bound page/quotation tools, and the local MCP server. |
| [src/agents.py](src/agents.py) | Profile/prompt loading, E input selection, complete source input, shared extractor/verifier execution, and incremental recording. |
| [src/huggingface_api.py](src/huggingface_api.py) | Prepared HTTP requests, fixed provider routing, schema adaptation, size estimates, response interpretation, and usage. |
| [src/models.py](src/models.py) | Shared response/tool schemas, conversation validation, and model-result evidence types; no network operations. |
| [src/validation.py](src/validation.py) | Strict JSON parsing, early-draft recognition, schema checks, record relationships, source context, and permitted-repair coordination. |
| [src/repair.py](src/repair.py) | The four allowed formatting repairs, producing a separate candidate and audit trail. |
| [src/quotation_diagnostics.py](src/quotation_diagnostics.py) | Local quotation matching, conservative single-page citation corrections, and remaining review flags; no model calls or file access. |
| [src/storage.py](src/storage.py) | Paths, identities, atomic publication, immutable evidence, active-record updates, and loading/integrity checks. |
| [src/huggingface_check.py](src/huggingface_check.py) | Explicit fictional-input compatibility checks, saved separately from research extractions. |

Planned `src/collaboration.py` will coordinate C's agents, tasks, budgets, and recording using the existing API, tool, validation, and storage modules. Planned `src/metrics.py` will calculate/export measures from manual review results to `runs/analysis/`. Optional notebooks will call the same calculation code.

### JSON contracts

Read the relevant schema before changing its producer, validator, or consumer. Python validators add cross-record and filesystem-context checks; a schema alone cannot establish source fidelity. C's task/message and run contracts, multi-profile configuration, and coordinator issue-role permissions must be added before execution. Current E/V schema rules remain unchanged.

| Schema in `schemas/` | Contract |
| --- | --- |
| [registry.schema.json](schemas/registry.schema.json) | Registered document identity, metadata, study set, preparation link. |
| [preparation.schema.json](schemas/preparation.schema.json), [pages.schema.json](schemas/pages.schema.json) | Preparation settings/status, complete ordered pages, text/image routes and region metadata. |
| [profiles.schema.json](schemas/profiles.schema.json) | Editable profiles and shared document-tool settings; only hosted Hugging Face execution is active. |
| [plan_data.schema.json](schemas/plan_data.schema.json) | `plan_data.metadata`, `plan_data.actions`, evidence, categories, and missing values. |
| [agent_response.schema.json](schemas/agent_response.schema.json) | Complete model answer: `plan_data` and `plan_issues`, including issue-status constraints. |
| [curated_dataset.schema.json](schemas/curated_dataset.schema.json) | Shared answer format with expert resolutions allowed. |
| [expert_reference.schema.json](schemas/expert_reference.schema.json) | One expert reference form: version, plan ID, expert identity, and the shared plan-data fields. Python adds registered-source, action-ID, and PDF page-bound checks. |
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
| `run_verify_mode` | `agents.run_verifier()` | One new verification attempt linked to its selected E, with a full revised answer. |
| `create_expert_reference` | `expert_files.create_expert_reference()` | New blank expert form, with no model calls or overwrite. |
| `validate_expert_reference` | `expert_files.validate_expert_reference()` | Read-only field/source checks against the registered original PDF. |
| `list_plans` | `documents.list_documents()` | Read-only registration/preparation listing. |

Both model commands follow `CLI → saved runner → shared model/tool loop → Hugging Face API`, with local MCP tools for source checks. CLI argument handling and terminal feedback are shared between stages. `validation.py` checks answers and relationships; `quotation_diagnostics.py` corrects qualifying citations and flags remaining concerns; `storage.py` owns publication and file integrity. The shared runner coordinates these steps. The model never writes research files directly.

Inkling 2 Small (`thinkingmachines/Inkling-2-Small`) produces E; DeepSeek V4.1 Flash 1017 (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) checks that exact saved extraction for E+V. Both use Hugging Face Inference Providers with DeepInfra pinned. Registration, preparation, E/V execution, response validation, quotation diagnostics/corrections, saving/loading, and expert-curated answer validation are implemented. Both development plans have completed E and V; Paris runs exercised live quotation diagnostics. Qualifying citation repairs have been tested offline, but none qualified in the reviewed Paris runs.

The current E/V prompts are being held stable. The expert reference schema, creation command, and validation command are implemented. [Collaboration (C)](#planned-collaboration-c), manual assessment, metrics, formal comparison execution, and instruction export remain planned. Comparison execution is disabled pending development and fixed settings. Structural success and quotation matches do not establish factual quality.

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

`configs/profiles.json` contains shared `document_tools` plus named model profiles. A profile defines execution settings independently of the study set; `--purpose` identifies how a run is used. Select `--profile` explicitly for both E and V. Each run saves the selected values and ordered prompt texts.

| Setting | Current extractor value |
| --- | --- |
| Extractor profile | `inkling2_small_hf_extractor` |
| Model | `thinkingmachines/Inkling-2-Small` |
| Service and fixed host | Hugging Face Inference Providers; `deepinfra` |
| Endpoint and routing ID | `https://router.huggingface.co/v1`; `thinkingmachines/Inkling-2-Small:deepinfra` |
| Context/output limits | 1,048,576 context tokens; 131,072 output tokens per request, including reported reasoning. The full output allowance is reserved in each capacity check. |
| Generation controls | Temperature, top-p, and seed null: use provider defaults and record that choice. |
| Execution limits | 20 submitted document-tool calls per stage; 1,800 seconds per model request; 120 seconds per tool request. |
| Tool/input settings | EasyOCR, English, CPU, 150 DPI; text input with local tools; direct image input disabled. |

Both development plans completed successfully at the 131,072-token output allowance. Preliminary findings and remaining extraction errors are recorded in [CHANGELOG.md](CHANGELOG.md); formal quality assessment remains pending.

Verifier profile `deepseek_v4_1_flash_1017_hf_verifier` uses DeepSeek through the same service and fixed host, with the same limits and document tools. It loads the shared coding rules and field definitions followed by the [verifier task](prompts/verifier.md). Each stage allows 20 submitted tool calls and 131,072 output tokens per request. Historical runs retain their saved limits, prompts, and exact requests.

GLM-5.3-Flash (`zai-org/GLM-5.3-Flash`) is selected for C through Hugging Face/DeepInfra, based on low listed cost, long context, and listed tool/structured-output support. Its profile is not yet configured. Compatibility, usable limits, and coordination quality are **Not yet tested**; C's numerical budgets and generation settings will be established during development and fixed before comparison.

Authentication reads `HF_TOKEN` at execution. Require it before allocating a run; never save authentication headers or credentials. `.env` files are not loaded automatically. [README.md](README.md#api-access) explains setup. Local LLM weights and serving software are unnecessary; OCR and document processing remain local.

### Input and request preparation

`build_extractor_input()` checks the exact preparation and original PDF, snapshots prompts/settings, and assembles the whole source without model/OCR calls or file writes. Join `shared_coding.md`, `field_definitions.md`, and `extractor.md` with two newlines in one system message. A user message contains collection metadata, preparation notes, and all unchanged page text with distinct physical-page boundaries. Document text and tool results are evidence, not instructions.

`select_verifier_input_run()` chooses the highest numbered eligible, successful E run that passes saved-run validation, unless `--input-run-id` selects one explicitly. Resolve selection once and preserve it; verifier retries keep their original E input even if a newer extraction exists. The rule applies across study sets and permitted purposes.

`build_verifier_input()` selects one validated E run and uses that run's exact preparation. It loads the three verifier-profile prompts and adds a separate user message containing E's complete `plan_data` and `plan_issues`. E's reasoning, execution logs, and expert files are excluded from the model conversation. The input snapshot also preserves E's full run record and SHA-256 fingerprint. Require a different model and identical shared document-tool settings; stop if the baseline or source changes.

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

Model identity checks are case-insensitive and allow these verified response aliases:

| Requested Hugging Face model | Accepted router response name |
| --- | --- |
| `deepseek-ai/DeepSeek-V4.1-Flash-1017` | `deepseek/deepseek-v4.1-flash-1017` |
| `zai-org/GLM-5.3-Flash` | `z-ai/glm-5.3-flash` |

Requests retain the configured ID, and raw responses retain the reported ID. Other checkpoints, variants, and unlisted namespaces are rejected. Alias recognition leaves schema, usage, completion, and tool checks unchanged; GLM's full live compatibility check remains pending.

### Compatibility diagnostics

`uv run --locked python -m huggingface_check` defaults to the Inkling profile and makes up to three paid requests. `--model namespace/model` overrides only the diagnostic model, retaining the base profile's pinned DeepInfra host, prompts, context limit, and other settings. It does not edit profiles or implement verification. Invalid overrides stop before creating artifacts or sending requests. Run the diagnostic before adopting a changed serving setup, rather than before each plan. It stops at the first failed check:

| Check | Requested output cap |
| --- | --- |
| Small strict schema with a conflicting requested field | 2,048 tokens |
| Adapted project schema on a fictional complete one-page plan | 4,096 tokens |
| Deliberately short output-limit probe | 64 tokens |
| Optional fictional `get_page_text` call (`--check-tools`) | 2,048 tokens |
| Optional result replay and JSON answer (`--check-tools`) | 2,048 tokens |

`--check-tools` adds at most two requests, for five total. Require exactly one call for page 1. Python supplies a fictional result with a fresh confirmation code generated after the call; the next answer must reproduce it. The code appears only in the tool result, not in the output schema. Use the existing adapter's assistant/tool replay without calling MCP, reading PDFs, or running OCR. Save the fictional result alongside both requests and responses. This checks one tool interaction, not the complete document-tool catalogue or verifier workflow.

`--isolate-project-schema` is a separate mode for investigating a rejected project request. It replaces the standard checks with up to two paid requests and cannot be combined with `--check-tools`:

| Variant | Change from the standard project request |
| --- | --- |
| `small_schema_full_instructions` | Retains the full instructions and fictional source; substitutes the small schema. |
| `project_schema_short_instructions` | Retains the full project schema; uses a short user instruction and the same fictional source, followed by the shared JSON instruction. |

Both retain the project check's 4,096-token output cap, limited by the base profile. Each changes only the schema or message input; model, host, and other controls stay fixed. Both are attempted after response/validation failures; cancellation or saving failures stop execution. The short-instruction answer still passes the full Python project validator, including action IDs, page bounds, and issue rules.

Reports identify `mode: project_schema_isolation` and preserve each variant's HTTP status, usage, errors, and request/response files. Overall `passed` requires both variants to pass; exit code 1 can therefore accompany a useful completed comparison. HTTP rejection and a returned answer failing validation are distinct outcomes. These variants narrow possible causes without establishing acceptance of the original request; the standard compatibility check remains necessary after any fix.

Limits are capped by the profile, with at most 300 seconds per request. Requested caps are not guaranteed billing ceilings. Only the 64-token probe permits truncation; missing output usage makes it inconclusive. Validate fictional project answers against the original contract. Save the mode, base profile, actual model/override, selected checks, settings, requests, responses, HTTP status, estimates, usage, and results under `artifacts/huggingface_checks/`. These checks do not establish the full output allowance, whole-plan capacity, extraction/verifier/coordinator quality, or future provider behavior. Study files and credentials remain outside diagnostic artifacts.

## 5. Model execution and preservation

### Shared execution control

`run_extractor()` and `run_verifier()` wrap their respective in-memory entry points with the same checkpoint recorder. `_run_agent_loop()` implements the common tool investigation and final generation; `_run_saved_agent()` implements common publication and failure handling:

1. Validate explicit plan/preparation/profile/purpose choices and authentication; observe client software/Git state, snapshot code/contracts, and allocate a new `running` record.
2. Assemble the complete input and discover the selected-source MCP catalogue.
3. Before each investigation request, refresh one controller message with total, submitted, and remaining document-tool calls and the maximum next batch size. Earlier exact requests remain immutable. Prepare, record, budget, and send the request. Process tool calls first; otherwise recognize `READY_FOR_FINAL_RESPONSE` with optional outer whitespace or a complete JSON answer draft. Unexpected prose and unrecognized JSON fail without another model call.
4. Execute calls sequentially. Every submitted MCP call consumes budget, including failures; excess requests receive logged non-execution errors. Catalogue discovery consumes no slot. Continue until readiness, a recognized draft, or budget exhaustion.
5. Send one final request with tools disabled and the response schema enabled, even after an early draft. Validate completion and answer, apply permitted format repairs, and recheck the source. Verification also checks the preserved E snapshot.
6. Diagnose quotation locations and apply qualifying single-page corrections. Validate any changed candidate again, then check collection metadata and verifier issue continuity. Preserve repairs and remaining flags without adding model/tool calls.
7. Stop the MCP subprocess, preserve its diagnostics, and recheck application snapshots before final publication. Return the last successfully saved status, even if the answer was valid in memory.

The readiness or draft turn counts as a generation. Blocked preflight is retained as an attempt but contributes no generation usage. Whole-stage elapsed time includes setup, tools, validation, saving, and cleanup. Request deadlines cover connection, response reads, and in-request evidence callbacks; tool deadlines also cover SDK waiting/decoding.

#### Early JSON drafts

The readiness signal remains preferred. If a normally completed investigation response has no tool calls, `validation.is_agent_response_draft()` can instead recognize strict, finite JSON with exactly `plan_data` and `plan_issues`. `plan_data` must contain only a metadata object and an actions list of objects; `plan_issues` must contain only an issues list of objects. Duplicate fields, incomplete or code-fenced JSON, wrong container types, and nonfinite numbers do not qualify. Failed, truncated, or unconfirmed responses cannot trigger the transition.

Recognition does not validate individual fields or accept the draft. Unexpected record fields such as `resolution_pages` can remain in a recognized draft, but must pass the unchanged full checks in the final answer. Preserve the draft in its original response files and conversation. The final controller message labels it unvalidated, requires source/schema checking, and requests one complete new answer. Only that final answer can proceed to citation correction and acceptance. There is no repeated final-generation or model-repair loop. An early draft can use more tokens than the readiness signal; normal capacity checks still apply to the final request.

The shared coding prompt specifies activity-level grouping, source-specific quantity/date associations, and meaningful continuous evidence passages. Keep adjacent lines from one passage in one evidence object, preserving line breaks as \n and word-wrap hyphens. Short `find_quote` queries locate passages; saved quotations need enough context to support the recorded details. A clearly supported activity is retained with a linked issue when faithful evidence cannot be recovered.

Both stages check every quotation against source text and physical pages. The final request preserves accurate, sufficiently complete draft excerpts. V also reviews inherited evidence, checks the source section by section for omissions, and compares issue explanations with the final fields. Discrepancies stay open when reconciliation requires an unstated assumption. These are model instructions within the existing call sequence; expert assessment establishes semantic correctness. Observed development results appear in the [checkpoint](#current-development-checkpoint).

### Automatic quotation/page checks and corrections

The sequence is `JSON checks and format repairs → source checks → citation correction → JSON/context checks → saving`. Matching and correction live in `quotation_diagnostics.py`; the shared runner coordinates validation and preservation.

After structural and source checks, Python compares every evidence quotation with the prepared physical pages and successful OCR readings already saved during the run. V also uses OCR readings from its pinned E run locally; E's logs remain outside the verifier conversation. This step launches no OCR or model requests. Matching collapses whitespace only, preserving words, case, punctuation, and hyphens. Repeated wording elsewhere does not flag a valid cited location. Multi-page matches must use text from every cited page in consecutive physical order; uncertain spans remain unconfirmed.

`correct_quotation_pages()` returns a copied `plan_data` and a version 2 diagnostic report. It changes only a single-page citation with available cited text, no quotation match there, and exactly one alternative matching physical page. It never changes quotation wording, action details, metadata, or issues. Repeated matches, unavailable cited text, multi-page citations, and inexact wording remain unchanged; no general page-number offset is inferred. Invalid page ranges fail structural validation before this step.

The shared runner adds each `quotation_page_number` change to `validation_report.json`, serializes a separate `responses/repaired_final.txt`, and validates it again before contextual acceptance. Existing format repairs remain in the same audit trail; the raw model response remains unchanged. V receives the saved, processed E answer. These source-based repairs stay outside the source-independent functions in `validation.py` and `repair.py`.

The quotation report preserves the preparation fingerprint, matching method, initial summary, repairs with original/corrected pages and zero-based evidence indices, and remaining findings. Its final summary includes `corrected`; `findings` describes only remaining possible mismatches, unmatched quotations, and unconfirmed spans. An unmatched quotation can reflect OCR or layout differences. Flags alone do not fail a run; invalid corrected candidates and report-saving failures follow normal failure handling. Location checks do not establish factual support or evidence adequacy. No issue status is changed or resolution attributed to a model by Python.

Earlier runs remain unchanged and need no new report. V uses an older E exactly as saved, without retroactively correcting it. All three formal comparison outputs must use the same frozen processing policy; C will apply it to its own final answer and source readings. Assessment covers processed outputs, with raw responses available for review.

### Saved run

`output.json` follows [run.schema.json](schemas/run.schema.json). It records plan/run identity, stage/purpose, source path, retry/input links, UTC start/end, measured duration, frozen settings/environment, generation calls, tool-log path, status/error, and accepted `plan_data`/`plan_issues`. Only saved success retains the accepted answer; failures retain evidence with null accepted output. Unknown measurements remain null.

A `plan_id` identifies one PDF version, and a `run_id` identifies one execution. Action/issue IDs are local to linked outputs and persist through verification/curation. Each manual invocation gets a new numbered run directory, including retries. `--retry-of-run-id` links a failed attempt; it does not resume or overwrite it. Selected E/E+V pairs retain their exact run IDs when later runs become available. V records `input_run_id`; validators retain E issue IDs/origins and enforce permitted resolvers and valid action links. The prompt requires continuing action identities and explanations for splits, merges, and removals; experts assess those semantic decisions.

### Saved execution

| Evidence | Location within the run |
| --- | --- |
| Frozen input and tool catalogue | `artifacts/extractor_input.json` for E or `artifacts/verifier_input.json` for V; `artifacts/mcp_catalogue.json` |
| Application code, schemas, setup files, SHA-256 manifest | `artifacts/code/`, `artifacts/code_fingerprints.json` |
| Environment notes | `artifacts/environment/observations.json` |
| Exact request, capacity reports, headers, received chunks, result summary | `responses/attempt_NN/` |
| Decoded HTTP body and exact assistant text | `responses/response_NN.json`, `responses/response_NN.txt`, when available |
| Normalized assistant message | `responses/attempt_NN/assistant_message.json` |
| Pending/completed tool activity | `artifacts/tool_requests/`, `tool_log.json` |
| Fresh OCR request, PNG, text, report with hashes/settings/times/errors | `artifacts/ocr/request_NNNN/` |
| Full conversation and subprocess stderr | `artifacts/conversation.json`, `artifacts/mcp_stderr.log` |
| Validation and separate repaired candidate | `validation_report.json`, `responses/repaired_final.txt` when changed |
| Quotation/page repairs and remaining diagnostic findings | `artifacts/quotation_page_report.json` |

Observe local client versions and Git state. Remote weight revision, runtime version, quantization, model hardware, and loaded state remain null because the adapter cannot inspect them. Source/code snapshots establish what was used, including uncommitted code; they do not identify an undisclosed remote weight revision.

Storage validates paths, source identity, selected preparation, and linked records. Successful runs require the frozen input; loading compares its source fingerprint with the preparation and page text. V also requires its saved E record and byte fingerprint to match the linked extractor. Completed records/artifacts cannot be overwritten. Active records and ordered logs can grow atomically without changing fixed settings or earlier known observations. Use one writer at a time.

Checkpoint failure stops execution and triggers best-effort failed publication. Preserve available bytes and usage. A failed save or abrupt termination may leave `running`, partial artifacts, and null end/duration; recovery is manual after confirming process termination. Cancellation preserves available evidence and returns 130. Other CLI outcomes are 0 for saved success, 1 for operational failure, and 2 for invalid arguments.

Comparison-plan feedback remains restricted, including exploratory runs: hide claims, issues, response fragments, repair details, quotation/page correction and flag counts, and client logs until a validated independent-reference workflow exists. Report paths remain visible; files remain on disk. If troubleshooting exposes outputs, an unexposed expert must complete the comparison reference form.

### Validation and permitted repair

`validation.py` checks strict JSON, fields/values, unique IDs, action links, physical page ranges, source/collection consistency, issue roles, and run relationships. Problems use `syntax`, `structure`, `reference`, or `other`. It neither inserts defaults nor interprets factual support. `validate_and_repair_agent_response()` coordinates these four repairs through `repair.py`:

| Repair | Boundary |
| --- | --- |
| Whole-response JSON code fence | One complete answer, without surrounding commentary. |
| Trailing comma | Immediately before a closing bracket/brace, outside strings. |
| Missing closing delimiters | Unambiguous nesting after a complete value and confirmed normal completion. |
| Single page number | Positive integer converted to a one-item `page_numbers` list, then range-checked. |

The source-based page-citation repair is coordinated separately by the runner using `quotation_diagnostics.py`, as described above. Preserve the original and candidate separately and repeat acceptance checks on any changed answer. Failed/truncated requests receive no repairs. Missing fields, unsupported details, duplicates, and other substantive violations require a separately initiated attempt.

Issue checks enforce one linked issue per affected action, valid IDs/links, and resolver/status relationships. Open issues require null resolver/resolution; resolved issues require a permitted resolver and nonblank explanation. E uses extractor origin/resolver. V retains original identities/origins, may reopen issues, and uses verifier origin for additions and verifier resolver for its fixes. Expert resolutions belong only in curated copies, validated with `validate_curated_dataset()`. Removed/merged actions require updated links and an explanation of retired targets where a link becomes null.

### Planned collaboration (C)

C is stage 4 in DESIGN.md: an independent configuration with three fixed agent roles and dynamic task allocation. The planned command is `run_collaboration_mode <plan_id> --source-path <preparation.json> --profile <collaboration_profile> --purpose <purpose>`, retaining the existing purpose/study-set checks, comparison disclosure restrictions, and manual retry rules. The command, profiles, prompts, and runtime are not yet implemented.

| Role | Model | Responsibility |
| --- | --- | --- |
| Coordinator | GLM-5.3-Flash | Assign work, compare findings, request checks, maintain the working draft, and produce the complete answer. |
| Extractor | Inkling 2 Small | Identify eligible activities, group occurrences, recover associated details, and propose supported records or revisions. |
| Verifier | DeepSeek V4.1 Flash 1017 | Investigate the source independently and check proposed records, omissions, quotations, and uncertainties. |

The collaboration configuration will bind all three model profiles, shared source/tools, role prompts, and budgets. New C prompts will reuse the coding rules and field definitions while allowing targeted assignments. The baseline E/V prompts and saved outputs remain unchanged.

| Protocol choice | Required behavior |
| --- | --- |
| Starting information | All agents receive the same whole prepared plan, physical page boundaries, collection metadata, shared coding rules, and field definitions. Baseline E/V outputs, their OCR/log artifacts, and expert references are excluded. |
| Task allocation and communication | GLM chooses tasks and order, dispatches independent work in parallel, and requests follow-up as findings emerge. Structured tasks and findings pass through the coordinator. Workers can raise disagreements or request another check. The number and order of exchanges can adapt within run limits. |
| Working state | The coordinator owns a versioned working draft; workers propose evidence-supported changes. Each worker has its own conversation containing its assignment and relevant draft/peer findings. |
| Budgets | Global request, token, tool, and elapsed-time limits cover all agents and repeated delegations. Budget is reserved before parallel dispatch and does not reset for a new task. Final JSON generation has a separate reserve; every request also passes the existing capacity check. |
| Completion | Both worker roles contribute, and the coordinator reviews source coverage, evidence, and disagreements before requesting final generation. Source uncertainty remains an open issue. Investigation stops at its budget limit with final-generation capacity retained. |
| Failures | A required worker/model/API failure, missing role contribution, or invalid final answer fails C. Available evidence is preserved. Retries create linked new attempts with the original preparation/settings; model/provider fallback and automatic retries remain disabled. |

Python will own scheduling, source-bound tool routing, budget accounting, and serialized file publication. Each task will record a unique ID, assigned role, objective, source scope, and draft version. Findings will link to their task, affected records, quotations/pages, proposed changes, and remaining questions. Requests, responses, tool results, draft versions, timestamps, and per-call usage will be preserved. Document text and returned evidence remain source material rather than instructions.

One C attempt will occupy `runs/<plan_id>/run_collaboration_NNNN/`. Its record will preserve the exact preparation fingerprint, all three profiles/prompts, budgets, task/call links, and outcome. Worker calls belong to C rather than separate baseline E/V runs. C action and issue IDs are independent of E/E+V and remain stable through C revisions. The planned `coordinator` issue role will identify coordinator-origin concerns or fixes; worker origins and claimed resolvers are retained when GLM accepts their contributions. Expert resolution remains restricted to curated copies.

The coordinator's final `plan_data` and `plan_issues` will undergo the shared strict response checks, permitted formatting repairs, source checks, and quotation/page correction policy, followed by revalidation and saving. Citation checks will use the preparation and successful OCR readings from this C run. New C role/run validators must preserve the existing E/V restrictions and historical loading.

Implementation starts with GLM schema/tool/limit checks and a fictional coordination test with controlled worker replies. Offline tests will cover dispatch, parallel budget reservations, source isolation, ID continuity, failures, final validation, and immutable evidence. Live Freetown/Paris pilots and manual assessment will follow before comparison settings are frozen. Coordination quality is **Not yet tested**.

## 6. Expert review and dataset assembly

The [expert reference format](#appendix-supporting-json-files), creation command, and validation command are implemented. Experts will complete one form per plan from the original PDF for assessment of E, E+V, and C. Pilot completion and manual assessment on the development plans. Record reviewer roles, prior output exposure, and disagreement procedures in study notes. Development outputs have already been viewed, so this review pilots the process rather than providing independent comparison evidence.

### Expert reference creation — implemented

`create_expert_reference <plan_id> --prepared-by <name-or-study-ID>` creates `expert_references/<plan_id>/expert_reference.json`. Repeat `--prepared-by` for multiple experts; `--project-root` follows the same convention as other commands. Registration is required, but preparation, model runs, and an API token are not.

`expert_files.py` reuses `documents.list_documents()` to check collection integrity, then copies the selected registered title, source URL, and access date. Unknown metadata remains null or an empty list; language is `English` under the shared contract. Actions start empty. No model outputs are read and no OCR or API calls are made.

`storage.save_new_expert_reference()` applies the reference schema through `validation.validate_expert_reference_structure()`, checks the destination, and atomically publishes a new UTF-8 JSON file. It refuses existing files, directories, and symbolic-link destinations; publication also refuses a concurrent collision. The reference folder is outside `runs/`, so creation does not count as saved model work or change study-set permissions. The registry, preparations, and runs remain unchanged. Experts edit the saved form directly; creation cannot reset it. The command does not establish that the form is complete or factually correct.

### Expert reference validation — implemented

`validate_expert_reference <plan_id>` checks the canonical form at `expert_references/<plan_id>/expert_reference.json`. It uses the shared `--project-root` option and returns 0 when the checks pass, 1 for file/data failures, or 2 for invalid command syntax. Problems include their category and field location. No files or reports are written, and no OCR or API requests are made.

`expert_files.py` reuses collection integrity checks, reads the registered original into memory, verifies those exact bytes against its SHA-256 checksum, and counts physical PDF pages with the strict pypdf reader. Unreadable, encrypted, empty, missing, or modified originals stop validation. Preparation and model outputs are not required. Each two-page spread counts as one physical PDF page.

`storage.load_expert_reference()` reads only the selected form and rejects symbolic-link redirection. `validation.parse_expert_reference_json()` rejects malformed JSON, duplicate fields, and nonstandard numbers, then checks the shared schema, selected plan ID, exact registered source URL/access date, unique action IDs, and evidence page bounds. Other metadata remains expert-coded. The action-ID and page-range rules are shared with model-answer validation; no reference fields are repaired or rewritten.

Passing establishes file/link consistency. Empty action lists can pass, with an explicit terminal reminder to complete the form. Experts establish completeness, correct grouping, source support, and quotation fidelity. A validation pass does not mark the form complete or enable comparison execution.

### Manual expert assessment — planned

1. Complete the generated form from the original PDF. For comparison plans, this happens before viewing any model output.
2. Run `validate_expert_reference` and address reported problems. Preserve the completed form as `expert_reference.json`; it contains the expert's grouped activities, associated details, and source evidence, and stays the common reference throughout the comparison.
3. Experts manually assess each selected E, linked E+V, and independent C output against every reference activity with 0/0.5/1 and reasons. Combine split/duplicate output records by activity; assess each activity within a bundled record separately.
4. Experts judge source support and evidence adequacy for each distinct output activity. An activity absent from the reference is checked against the PDF before being classified as unsupported; any reference coverage gap is noted in the manual review.
5. Experts check every initially open E issue marked resolved by V before curation. Record whether all grouped concerns were addressed. C's independently generated issue handling and agent disagreements are described in review notes rather than matched to E issue IDs.

Assessment is manual; no separate assessment JSON templates or schemas are planned. The analysis uses the recorded judgments and exact selected run IDs. Pending judgments make the corresponding measures unavailable. The three quality measures and two issue measures remain as defined in DESIGN.md.

#### Worked scoring example

A fictional plan reports 100 trees planted in North Ward in 2025 and 200 planned for South Ward in 2027. The reference has one tree-planting action, type `nature-based`, retaining both phases and their associated details. Overall status is `unspecified` because no overall status is given.

| Score | Example output |
| --- | --- |
| 1 | Both phases, wards, quantities, dates, and statuses are correct; unstated fields use the defined missing values. |
| 0.5 | North Ward is correct but South Ward is omitted, or all 300 trees are described as already planted. |
| 0 | Tree planting is omitted or has no correct substantive description. |

### Measurement capture and calculation — planned

`metrics.py` will use selected saved runs, the completed expert reference, and manual judgments with [DESIGN.md appendix G](DESIGN.md#g-evaluation-measures-and-calculations). All three configurations use action score percentage, unsupported action count with total distinct activities, adequate-evidence percentage, and open issue counts. Expert-confirmed/claimed verifier resolutions apply only to E+V's initially open E issues. Expert grouping supplies distinct-activity units; later expert fixes remain outside model comparison.

E+V shares E and adds V duration/tokens. C uses its own complete elapsed duration, including coordination and parallel work; overlapping worker durations are not summed. C token totals include every coordinator/worker call once. Failed attempts are reported separately by top-level run ID, with worker errors retained within C. EasyOCR contributes duration, not LLM tokens. Missing observations or pending judgments make a measure unavailable; zero denominators are not applicable. Export per-plan counts/denominators and changes for E+V minus E and C minus E+V. Optional notebooks use the same calculations.

### Instruction dataset assembly — planned

After assessment, experts curate separate supported answers while preserving assessed outputs. Each whole-plan example pairs extraction instructions, sufficient source text/page links and reviewed recovery, and an expert-curated answer. Correct/exclude unsupported content, preserve reasons/source links, and validate targets with the curated-answer contract. Expert fixes retain issue IDs/origins and record expert authorship/resolution; confirmation of a V fix remains in the manual study review records. Pilot the export format and report plans, examples, and grouped actions separately. Fine-tuning remains future work.

## 7. Development checkpoint and next steps

### Current development checkpoint

E and V have completed live development runs on both plans. The following reviewed pairs are development evidence, not the formal comparison:

| Plan | Reviewed E → V | Observations |
| --- | --- | --- |
| Freetown (`plan_0001`) | `run_extract_0008` → `run_verify_0002` | Both contain 14 actions. V added useful corrections but retained source/citation gaps; this pair predates the current prompts and automatic citation processing. |
| Paris (`plan_0002`) | `run_extract_0002` → `run_verify_0006` | E has 36 actions and V has 38. Later prompt revisions retained coherent excerpts and courtyard uncertainty; omissions, bundling, quotation errors, and a temporal overstatement remain. |

Paris runs exercised early-draft handling, strict final generation, and quotation diagnostics. The latest reviewed run matched 100 of 130 quotations after whitespace normalization, flagged 30, and made no citation repairs. These counts do not measure evidence adequacy. Qualifying correction behavior was tested offline, including the three known Freetown page mismatches; historical runs were preserved. At that development checkpoint, the full offline suite passed 1,871 tests with 11 OCR dependency warnings.

Current E/V prompts are being held stable. GLM-5.3-Flash is selected for C, with the protocol above agreed; compatibility, implementation, and development pilots remain pending. Formal expert scores and confirmation of model-claimed issue resolutions also remain pending. [CHANGELOG.md](CHANGELOG.md) preserves earlier failures, revisions, repeated runs, and limitations.

### Next implementation steps

1. Check GLM compatibility and coordination on fictional inputs, implement C and its contracts/tests, then pilot it on Freetown and Paris.
2. Pilot expert reference completion, validation, and manual assessment of the development outputs. Implement calculations/exports from those judgments.
3. Freeze code, role prompts, profiles, preparation, processing, budgets, stopping rules, and scoring before enabling the five-plan comparison. Record the selected E, first successful linked V, and first successful independent C run using the same preparation before assessment. Experts complete one reference before viewing any comparison output; selected IDs stay fixed when newer runs appear.
4. Curate supported answers and export instruction examples after assessment. Dataset expansion and fine-tuning remain deferred.

## Appendix: supporting JSON files

Existing workflow fields are defined in the [JSON contract map](#json-contracts). The expert reference format is defined by [expert_reference.schema.json](schemas/expert_reference.schema.json), which reuses the existing plan data schema.

### Expert reference form

Use one form per plan, saved at `expert_references/<plan_id>/expert_reference.json`. It contains the expert's reading of the original PDF and is used for E, E+V, and C. For comparison plans, complete the form before viewing any model output. Development forms pilot the process, with prior exposure recorded in study notes.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer, fixed at 1 | Reference form format version. |
| `plan_id` | string | Registered document. |
| `prepared_by` | nonempty list of strings | Names or study codes identifying the experts who completed the form. |
| `plan_data` | object | Plan metadata, grouped actions, and evidence using the existing plan data fields. |

The schema checks required fields and types, nonblank plan/reviewer identifiers, and the shared metadata/action/evidence field rules. The validation command additionally checks registered plan/source links, unique action IDs, and upper page bounds against the actual PDF. Experts establish factual support and completeness; independence is maintained through the review procedure.

### Manual assessment

Experts compare the saved E, E+V, and C outputs with the same completed reference form. Manual scores, activity-support and evidence judgments, E+V resolution checks, and explanatory notes provide inputs to the agreed measures. C's collaboration and issue handling are described in review notes. Preserve selected run IDs and reviewer identities. No separate assessment JSON format is required.
