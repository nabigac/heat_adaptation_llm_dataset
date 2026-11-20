# Implementation: Heat Adaptation LLM Dataset

**Implementation guide · updated 2026-11-19**

This guide maps the repository and specifies execution, preservation, and the remaining implementation work. [DESIGN.md](DESIGN.md) defines the research protocol, coding rules, and evaluation formulas; [README.md](README.md) provides setup and terminal commands. Existing JSON schemas are the authoritative field contracts. Proposed expert-file contracts appear at the end of this guide because their schemas are not implemented yet.

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
├── runs/<plan_id>/
│   ├── run_extract_NNNN/         # Extractor attempts; same file layout as below
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

Git tracks code, schemas, prompts, profiles, registry metadata, and project documents. Back up PDFs, prepared text, runs, diagnostics, and OCR models separately. Some directories exist only after use. Credentials stay outside saved project artifacts.

### Module responsibilities

| Module | Owns |
| --- | --- |
| [src/cli.py](src/cli.py) | Arguments, command dispatch, terminal feedback, comparison disclosure restrictions, exit codes. |
| [src/documents.py](src/documents.py) | Registration, collection-metadata updates, native text preparation, and selective OCR coordination. |
| [src/document_tools.py](src/document_tools.py) | PDF rendering/image inspection, EasyOCR, source-bound page/quotation tools, and the local MCP server. |
| [src/agents.py](src/agents.py) | Profile/prompt loading, E input selection, complete source input, shared extractor/verifier execution, and incremental recording. |
| [src/huggingface_api.py](src/huggingface_api.py) | Prepared HTTP requests, fixed provider routing, schema adaptation, size estimates, response interpretation, and usage. |
| [src/models.py](src/models.py) | Shared response/tool schemas, conversation validation, and model-result evidence types; no network operations. |
| [src/validation.py](src/validation.py) | Strict JSON parsing, early-draft recognition, schema checks, record relationships, source context, and permitted-repair coordination. |
| [src/repair.py](src/repair.py) | The four allowed formatting repairs, producing a separate candidate and audit trail. |
| [src/quotation_diagnostics.py](src/quotation_diagnostics.py) | Local quotation matching, conservative single-page citation corrections, and remaining review flags; no model calls or file access. |
| [src/storage.py](src/storage.py) | Paths, identities, atomic publication, immutable evidence, active-record updates, and loading/integrity checks. |
| [src/huggingface_check.py](src/huggingface_check.py) | Explicit fictional-input compatibility checks, saved separately from research extractions. |

Planned modules are `src/expert_files.py` for references and assessments, and `src/metrics.py` for shared calculations/exports. Planned research paths are `drafts/`, `reference_initial.json`, `reference_final.json`, `assessment_e.json`, `assessment_ev.json`, and `runs/analysis/`; optional notebooks will call the same calculation code.

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
| `run_verify_mode` | `agents.run_verifier()` | One new verification attempt linked to its selected E, with a full revised answer. |
| `list_plans` | `documents.list_documents()` | Read-only registration/preparation listing. |

Both model commands follow `CLI → saved runner → shared model/tool loop → Hugging Face API`, with local MCP tools for source checks. CLI argument handling and terminal feedback are shared between stages. `validation.py` checks answers and relationships; `quotation_diagnostics.py` corrects qualifying citations and flags remaining concerns; `storage.py` owns publication and file integrity. The shared runner coordinates these steps. The model never writes research files directly.

Inkling 2 Small (`thinkingmachines/Inkling-2-Small`) produces E. DeepSeek V4.1 Flash 1017 (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) checks and revises that exact saved extraction for E+V. Both models use Hugging Face Inference Providers with DeepInfra pinned. The verifier profile, prompts, input selection, shared runner, CLI, and preservation checks are implemented; Freetown pilots succeeded at 10 and 20 tool calls. Automatic quotation checks and qualifying citation repairs are implemented and tested offline; live use of that step and Paris verification remain pending. Registration, preparation, extraction, response validation, saving/loading, and expert-curated answer validation are implemented. Expert references/assessments, metrics, comparison execution, and instruction export remain planned. Formal comparison is currently blocked.

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

`configs/profiles.json` contains shared `document_tools` plus named model profiles. A profile defines execution settings independently of the study set; `--purpose` identifies how a run is used. Select `--profile` explicitly for extraction. Each run saves the selected values and ordered prompt texts.

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

Verifier profile `deepseek_v4_1_flash_1017_hf_verifier` uses DeepSeek through the same service and fixed host, with the same limits and shared tools. It loads the shared coding rules and field definitions, followed by the [verifier task](prompts/verifier.md). Freetown `run_verify_0002` completed with the updated 20-call allowance and source-page instructions, while citation errors remained. Twenty is the tool-call ceiling; the output token allowance remains 131,072 per request. Historical runs retain their saved limits, prompts, and exact requests.

Authentication reads `HF_TOKEN` at execution. Require it before allocating a run; never save authentication headers or credentials. `.env` files are not loaded automatically. [README.md](README.md#api-access) explains setup. Local LLM weights and serving software are unnecessary; OCR and document processing remain local.

### Input and request preparation

`build_extractor_input()` checks the exact preparation and original PDF, snapshots prompts/settings, and assembles the whole source without model/OCR calls or file writes. Join `shared_coding.md`, `field_definitions.md`, and `extractor.md` with two newlines in one system message. A user message contains collection metadata, preparation notes, and all unchanged page text with distinct physical-page boundaries. Document text and tool results are evidence, not instructions.

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

Model identity checks are case-insensitive and allow the verified `deepseek-ai/DeepSeek-V4.1-Flash-1017` → `deepseek/deepseek-v4.1-flash-1017` response alias. Requests retain the configured ID, and raw responses retain the reported ID. Other checkpoints and unlisted namespaces are rejected.

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

Limits are capped by the profile, with at most 300 seconds per request. Requested caps are not guaranteed billing ceilings. Only the 64-token probe permits truncation; missing output usage makes it inconclusive. Validate the fictional extraction against the original contract. Save the base profile name, actual model/override, selected checks, settings, exact requests, responses, estimates, usage, and results under `artifacts/huggingface_checks/`. These small checks do not establish acceptance of the full configured output allowance, whole-plan capacity, extraction/verifier quality, or future provider behavior. Study files and credentials remain outside diagnostic artifacts.

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

The shared coding prompt directs activity-level grouping before additions, source-specific quantity/date associations, and short exact excerpts when layout interrupts text. Source line breaks and word-wrap hyphens can remain in quotations. A clearly supported activity is retained with a linked issue when faithful evidence cannot be recovered. Before readiness, both E and V check every evidence quotation; V explicitly includes unchanged extractor evidence and cross-checks issue explanations against the final fields and actual revisions. The final controller request repeats the same quotation scope using physical page boundaries or returned page numbers. These are model instructions, not an automatic factual assessment or an extra model pass; their quality effect remains **Not yet tested**.

### Automatic quotation/page checks and corrections

The sequence is `JSON checks and format repairs → source checks → citation correction → JSON/context checks → saving`. Matching and correction live in `quotation_diagnostics.py`; the shared runner coordinates validation and preservation.

After structural and source checks, Python compares every evidence quotation with the prepared physical pages and successful OCR readings already saved during the run. V also uses OCR readings from its pinned E run locally; E's logs remain outside the verifier conversation. This step launches no OCR or model requests. Matching collapses whitespace only, preserving words, case, punctuation, and hyphens. Repeated wording elsewhere does not flag a valid cited location. Multi-page matches must use text from every cited page in consecutive physical order; uncertain spans remain unconfirmed.

`correct_quotation_pages()` returns a copied `plan_data` and a version 2 diagnostic report. It changes only a single-page citation with available cited text, no quotation match there, and exactly one alternative matching physical page. It never changes quotation wording, action details, metadata, or issues. Repeated matches, unavailable cited text, multi-page citations, and inexact wording remain unchanged; no general page-number offset is inferred. Invalid page ranges fail structural validation before this step.

The shared runner adds each `quotation_page_number` change to `validation_report.json`, serializes a separate `responses/repaired_final.txt`, and validates it again before contextual acceptance. Existing format repairs remain in the same audit trail; the raw model response remains unchanged. V receives the saved, processed E answer. These source-based repairs stay outside the source-independent functions in `validation.py` and `repair.py`.

The quotation report preserves the preparation fingerprint, matching method, initial summary, repairs with original/corrected pages and zero-based evidence indices, and remaining findings. Its final summary includes `corrected`; `findings` describes only remaining possible mismatches, unmatched quotations, and unconfirmed spans. An unmatched quotation can reflect OCR or layout differences. Flags alone do not fail a run; invalid corrected candidates and report-saving failures follow normal failure handling. Location checks do not establish factual support or evidence adequacy. No issue status is changed or resolution attributed to a model by Python.

Earlier runs remain unchanged and need no new report. V uses an older E exactly as saved, without retroactively correcting it. Formal comparison pairs must use the same frozen processing policy for both stages; assessment covers processed outputs, with raw responses available for review.

### Saved run

`output.json` follows [run.schema.json](schemas/run.schema.json). It records plan/run identity, stage/purpose, source path, retry/input links, UTC start/end, measured duration, frozen settings/environment, generation calls, tool-log path, status/error, and accepted `plan_data`/`plan_issues`. Only saved success retains the accepted answer; failures retain evidence with null accepted output. Unknown measurements remain null.

A `plan_id` identifies one PDF version, and a `run_id` identifies one execution. Action/issue IDs are local to linked outputs and persist through verification/curation. Each manual invocation gets a new numbered run directory, including retries. `--retry-of-run-id` links a failed attempt; it does not resume or overwrite it. Selected E/E+V pairs retain their exact run IDs when later runs become available.

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

Comparison-plan feedback remains restricted, including exploratory runs: hide claims, issues, response fragments, repair details, quotation/page correction and flag counts, and client logs until a validated independent-reference workflow exists. Report paths remain visible; files remain on disk. If troubleshooting exposes outputs, an unexposed expert must prepare the initial reference.

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

## 6. Remaining implementation

### Verifier pilot — in progress

`run_verify_mode` calls `agents.run_verifier()` with required plan ID, `--profile`, and `--purpose`; optional `--input-run-id`, `--retry-of-run-id`, `--config-path`, and `--project-root` control selection. Source preparation is inherited from E. Shared CLI handling prints the saved status, actual E input ID, and available evidence paths; cancellation returns 130, and comparison details remain restricted. Freetown verification completed with the configured 131,072-token allowance. The remaining pilot work is Paris verification and live review of the new quotation checks and citation corrections.

The implemented runner uses `agents.select_verifier_input_run()` to select the highest numbered eligible E run that passes saved-run validation, unless an explicit E ID is supplied. It resolves selection once, preserves the input, and retains that E on retries. This applies to development, comparison, and later expansion purpose rules; formal comparison execution remains disabled. It supplies the whole source, answer/issues, and matching shared tools for review of grouping, unflagged content, omissions, details, and evidence.

V is saved separately with `input_run_id`; verifying a newer E starts a new pair. Validators enforce issue ID/origin retention, permitted resolvers, and valid action links. The prompt requires continuing action identities and explanations for splits, merges, removals, and resolutions; semantic correctness remains an expert judgment. Freeze both configurations, including clean committed code, before enabling formal comparison. Record the selected comparison pair before expert assessment and retain it when later extractions become available.

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

Inkling extraction succeeded without repairs on Freetown (`run_extract_0008`: 14 actions, five open issues) and Paris (`run_extract_0002`: 36 actions, five open issues). Preliminary review found quotation, evidence, grouping, status, and omission problems. Formal quality scores remain **Not yet tested**. Earlier trials and decisions remain in [CHANGELOG.md](CHANGELOG.md).

DeepSeek passed all five compatibility checks and completed Freetown verification twice from the same `run_extract_0008`. `run_verify_0001` used a 10-call ceiling; `run_verify_0002` used 20 calls and the revised source-page instructions. Both succeeded without Python repairs and retained 14 actions. Preliminary review found useful quotation/detail corrections alongside remaining source gaps and incorrect page citations. These pilots predate automatic citation correction and do not establish formal E+V quality or isolate the effects of the prompt and budget changes.

The new Python step passed a 464-test focused regression suite and 12 follow-up boundary/context checks. Read-only replay corrected all three known page mismatches in `run_verify_0002` in memory, leaving two unmatched quotations for review. Saved runs were not changed. New live runs with automatic citation correction are **Not yet tested**.

Paris `run_verify_0001` stopped after 14 tool calls when DeepSeek returned a JSON answer instead of the readiness signal. It never reached final-generation constraints or quotation checks; offline inspection also found an unexpected `resolution_pages` field. The controller now recognizes a complete early draft and proceeds to the existing strict-schema final request. The failed run remains unchanged; a live retry with this transition is **Not yet tested**.

Next: retry Paris with the updated controller and review corrections and remaining flags; implement expert-file validation and the agreed measures; freeze settings and produce consistent E/E+V pairs for the five-plan comparison; then curate/export instruction examples. Direct model images, richer status listing, expansion, and fine-tuning are deferred.

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
