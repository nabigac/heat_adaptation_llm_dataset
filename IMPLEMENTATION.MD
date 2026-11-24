# Implementation: Heat Adaptation LLM Dataset

**Implementation guide · updated 2026-11-24**

This guide maps the repository, current execution settings, and remaining work. [DESIGN.md](DESIGN.md) defines the research protocol, coding rules, and evaluation; [README.md](README.md) provides setup and commands. The study develops the workflow on two plans, adds eight, and compares all ten in one complete frozen round. E, E+V, and C have completed development runs on Freetown and Paris. The latest C prompts and execution budgets have passed offline checks; live checks, final-round controls, and formal expert assessment remain pending.

## 1. File directory

```text
heat_adaptation_llm_dataset/
├── src/                         # Application modules; see the responsibility map below
├── tests/                       # Automated checks with fictional inputs and controlled HTTP
├── configs/profiles.json         # E/V and C agent routing, limits, prompts, shared tools
├── configs/collaboration.json    # C agent binding and shared limits
├── prompts/
│   ├── shared_coding.md          # Activity grouping, inclusion, evidence, and issue rules
│   ├── field_definitions.md      # Meaning of every answer field and missing value
│   ├── extractor.md              # Extractor task and investigation instructions
│   ├── verifier.md               # Approved verification task and issue continuity rules
│   ├── coordinator.md            # C delegation, reconciliation, and completion task
│   └── worker.md                 # Shared task instructions for both C workers
├── schemas/                     # JSON field contracts; see the contract map below
├── data/                        # Tracked registry and separately preserved research inputs
│   ├── registry/plans.json       # Tracked identity, collection metadata, preparation links
│   ├── raw/<plan_id>.pdf         # Preserved original PDF; excluded from Git
│   ├── processed/<plan_id>/preparation_NN/  # Excluded from Git
│   │   ├── preparation.json    # Settings, source identity, status, and page-file link
│   │   ├── pages.json          # Ordered physical pages, exact text, and review notes
│   │   └── images/             # Preserved page PNGs and candidate-region crops
│   ├── expert_references/<plan_id>/  # Excluded from Git
│   │   ├── expert_reference.json # One shared expert form
│   │   └── reference_freeze.json # Fingerprints and reviewer confirmation
│   ├── assessments/<plan_id>/assessment_NNNN/  # Excluded from Git
│   │   ├── metadata.json       # Exact input identities, reviewers, and instructions
│   │   ├── action_scores.csv   # Reference activity matches and scores
│   │   ├── output_review.csv   # Output activity grouping, support, and evidence judgments
│   │   ├── verifier_resolutions.csv # Confirmation of V's claims about initially open E issues
│   │   └── metrics_NNNN/        # Preserved calculation snapshots
│   │       ├── results.json    # Measures, paired changes, statuses, and provenance
│   │       ├── summary.csv     # One row per measure/configuration or paired change
│   │       ├── assessment_inputs/ # Exact copies of metadata and review CSVs
│   │       └── code/           # Calculation code, schemas, and locked dependencies
│   └── reports/summary_NNNN/    # Excluded from Git
│       ├── summary.json        # Exact selections, aggregates, and contributing/excluded plans
│       ├── summary.csv         # Per-plan and aggregate measures
│       ├── inputs/<plan_id>/results.json # Exact selected result copies
│       └── code/               # Summary code, schemas, and locked dependencies
├── runs/<plan_id>/
│   ├── run_extract_NNNN/         # Extractor attempts; same file layout as below
│   ├── run_collaboration_NNNN/   # Development C attempts; see saved C execution
│   └── run_verify_NNNN/          # Verifier attempts linked to an exact extractor input
│       ├── output.json          # Status, settings, measurements, accepted answer
│       ├── responses/           # Requests, responses, capacity reports, repaired candidate
│       ├── artifacts/           # Input/code snapshots, budgets, MCP diagnostics, tools, OCR
│       │   └── quotation_page_report.json # Citation repairs and remaining review flags
│       ├── tool_log.json        # Ordered tool activity, when present
│       └── validation_report.json # Final-answer checks, when attempted
├── artifacts/huggingface_checks/ # Explicit compatibility diagnostics, outside study runs
├── artifacts/collaboration_checks/ # Coordinator checks with controlled workers; not study runs
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
| [src/expert_files.py](src/expert_files.py) | Independent reference creation, record editing, validation, and freezing against checked collection metadata and the original PDF, without model-output access. |
| [src/expert_templates.py](src/expert_templates.py) | Guided blank actions/issues, field instructions, and unfinished-guidance detection. |
| [src/assessments.py](src/assessments.py) | Development run selection, frozen-reference/source checks, exact input fingerprints, and prefilled review CSV creation. |
| [src/assessment_validation.py](src/assessment_validation.py) | Read-only assessment input/CSV checks, parsed judgments, pending fields, and review status by configuration. |
| [src/metrics.py](src/metrics.py) | Per-plan measures, paired changes, explicit availability states, and preserved result/CSV/input/code snapshots. |
| [src/metric_summaries.py](src/metric_summaries.py) | Saved-package validation, archived-review recalculation, explicit cross-plan selections, aggregation, and preserved reports. |
| [src/document_tools.py](src/document_tools.py) | PDF rendering/image inspection, EasyOCR, source-bound page/quotation tools, and the local MCP server. |
| [src/agents.py](src/agents.py) | Profile/prompt loading, E input selection, complete source input, shared extractor/verifier execution, and incremental recording. |
| [src/agent_budget.py](src/agent_budget.py) | Independent E/V request ceilings, shared E+V estimated-token charges, and protected final-request capacity. |
| [src/collaboration.py](src/collaboration.py) | In-memory C controller: delegation, parallel tasks, versioned drafts, evidence, and final response. Clients are explicitly injected. |
| [src/collaboration_runner.py](src/collaboration_runner.py) | Saved C lifecycle: live HF clients, source-bound MCP, checkpoints, source/code rechecks, citation processing, and final status. |
| [src/collaboration_storage.py](src/collaboration_storage.py) | Separate C record contract, immutable evidence, active checkpoints, strict loading, and completed-run protection. |
| [src/collaboration_contracts.py](src/collaboration_contracts.py) | C binding, source-only development input, task/result checks, and separate final-answer validation. |
| [src/collaboration_budget.py](src/collaboration_budget.py) | Shared request/token reservations, agent/global tool quotas, usage, and final time reserve. |
| [src/collaboration_check.py](src/collaboration_check.py) | Capped live coordinator diagnostic with fictional source/tools and explicitly controlled workers. |
| [src/huggingface_api.py](src/huggingface_api.py) | Prepared HTTP requests, fixed provider routing, schema adaptation, size estimates, response interpretation, and usage. |
| [src/models.py](src/models.py) | Shared response/tool schemas, conversation validation, and model-result evidence types; no network operations. |
| [src/validation.py](src/validation.py) | Strict JSON parsing, schema checks, record relationships, source context, and permitted-repair coordination. |
| [src/repair.py](src/repair.py) | The four allowed formatting repairs, producing a separate candidate and audit trail. |
| [src/quotation_diagnostics.py](src/quotation_diagnostics.py) | Local quotation matching, conservative single-page citation corrections, and remaining review flags; no model calls or file access. |
| [src/storage.py](src/storage.py) | Paths, identities, atomic publication, immutable evidence, active-record updates, and loading/integrity checks. |
| [src/huggingface_check.py](src/huggingface_check.py) | Explicit fictional-input compatibility checks, saved separately from research extractions. |

The saved C runner wraps the in-memory controller without changing E/V contracts. `metrics.py` calculates/exports per-plan measures from validated manual review under `data/assessments/`. Optional notebooks can call the same calculation code.

### JSON contracts

Read the relevant schema before changing its producer, validator, or consumer. Python validators add cross-record and filesystem-context checks; a schema alone cannot establish source fidelity. C's task/result/final-answer contracts are separate from E/V. C uses a separate saved-run contract and publication workflow; existing E/V run and response rules remain unchanged.

| Schema in `schemas/` | Contract |
| --- | --- |
| [registry.schema.json](schemas/registry.schema.json) | Registered document identity, metadata, study set, preparation link. |
| [preparation.schema.json](schemas/preparation.schema.json), [pages.schema.json](schemas/pages.schema.json) | Preparation settings/status, complete ordered pages, text/image routes and region metadata. |
| [profiles.schema.json](schemas/profiles.schema.json) | Editable extractor/verifier/coordinator/worker profiles and shared document tools; loading does not start execution. |
| [collaboration_config.schema.json](schemas/collaboration_config.schema.json) | Named C bindings and shared request, estimated-token, document-tool, and elapsed-time limits. |
| [collaboration_task.schema.json](schemas/collaboration_task.schema.json) | Assignment identity, objective, page scope, expected findings, draft version, and selected prior task context. |
| [collaboration_result.schema.json](schemas/collaboration_result.schema.json) | Worker/task identity, checked pages, findings, proposed changes, evidence, and uncertainty. |
| [collaboration_response.schema.json](schemas/collaboration_response.schema.json) | Complete plan_data/plan_issues with C-only agent identities; reuses the existing plan data contract. |
| [collaboration_run.schema.json](schemas/collaboration_run.schema.json) | Development C record, three profiles, shared settings/environment, per-agent model calls, budget, status, and accepted answer. |
| [plan_data.schema.json](schemas/plan_data.schema.json) | `plan_data.metadata`, `plan_data.actions`, evidence, categories, and missing values. |
| [agent_response.schema.json](schemas/agent_response.schema.json) | Complete model answer: `plan_data` and `plan_issues`, including issue-status constraints. |
| [curated_dataset.schema.json](schemas/curated_dataset.schema.json) | Curated E/V or C answers with workflow-specific issue identities and expert resolutions; mixed workflow identities are rejected. |
| [expert_reference.schema.json](schemas/expert_reference.schema.json) | One reference with shared plan-data fields and optional instructions, ID counters, and expert-origin issues. Python checks source links, IDs, issue links, page bounds, and unfinished guidance. |
| [expert_reference_freeze.schema.json](schemas/expert_reference_freeze.schema.json) | Exact reference/PDF fingerprints, source context, reviewer confirmation, and UTC freeze time. |
| [assessment_metadata.schema.json](schemas/assessment_metadata.schema.json) | Development assessment identity, reviewers, selected E/V/C records, frozen reference/source fingerprints, and editing instructions. |
| [metrics_results.schema.json](schemas/metrics_results.schema.json) | Per-plan measures, counts/denominators, availability states, paired changes, review state, and input/code provenance. |
| [metrics_summary.schema.json](schemas/metrics_summary.schema.json) | Selected package identities/fingerprints, aggregate measures, contributing/excluded plans, and report provenance. |
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
| `run_collaboration_mode` | `collaboration_runner.run_collaboration()` | One independent development C attempt from the selected preparation. |
| `create_expert_reference` | `expert_files.create_expert_reference()` | New guided form with one blank action and expert issue; no model calls or overwrite. |
| `edit_expert_reference` | `expert_files.edit_expert_reference()` | One checked action/issue addition or removal in the selected form. |
| `validate_expert_reference` | `expert_files.validate_expert_reference()` | Read-only field/source checks against the registered original PDF. |
| `freeze_expert_reference` | `expert_files.freeze_expert_reference()` | Validate the completed form and preserve its assessment identity with named reviewer confirmation. |
| `create_assessment` | `assessments.create_assessment()` | New metadata and three prefilled CSVs with expert judgments left blank. |
| `validate_assessment` | `assessment_validation.validate_assessment()` | Read-only input/CSV checks, separating invalid data from unfinished review. |
| `calculate_metrics` | `metrics.calculate_metrics()` | New per-plan JSON results, CSV summary, and exact review/code snapshots. |
| `summarize_metrics` | `metric_summaries.summarize_metrics()` | New cross-plan JSON/CSV report from exact saved calculations. |
| `list_plans` | `documents.list_documents()` | Read-only registration/preparation listing. |
| `list_profiles` | `cli._list_profiles()` | Read-only E/V/C choices, commands, models, and limits; C roles are nested under their binding. |

Model commands follow `CLI → saved runner → controller → Hugging Face API`, with local MCP tools for source checks. E/V share an agent loop; C uses its coordinator/worker controller. CLI argument handling and terminal feedback are shared between stages. `validation.py` checks answers and relationships; `quotation_diagnostics.py` corrects qualifying citations and flags remaining concerns; `storage.py` owns publication and file integrity. The shared runner coordinates these steps. The model never writes research files directly.

Inkling 2 Small (`thinkingmachines/Inkling-2-Small`) produces E; DeepSeek V4.1 Flash 1017 (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) checks that exact saved extraction for E+V. Both use Hugging Face Inference Providers with DeepInfra pinned. Registration, preparation, E/V execution, response validation, quotation diagnostics/corrections, saving/loading, and expert-curated answer validation are implemented. Both development plans have completed E and V; Paris runs exercised live quotation diagnostics. Qualifying citation repairs have been tested offline, but none qualified in the reviewed Paris runs.

The E/V role prompts are being held stable; the C role prompts were refined after development review, and shared field guidance now distinguishes workflow roles and response formats. Guided reference tools, development assessment creation/validation, per-plan metrics, cross-plan summaries, and E/V/C curated-answer validation are implemented. Reference completion, manual review, frozen-round controls, and instruction export remain pending. Final-round execution is disabled. Structural success and quotation matches do not establish factual quality; the [development checkpoint](#current-development-checkpoint) separates observed results from remaining work.

### Final study round — planned

Freetown and Paris are the two initial development plans. Eight additional plans complete the ten-plan sample. All ten must be rerun through E, E+V, and C in one frozen final round, yielding 30 successful configuration outputs. Initial development assignments remain part of each plan's history; final-round membership must include both registry study sets. Current purpose/category restrictions do not yet support that membership.

The round must identify all ten source/preparation versions and freeze workflow code, models/hosts, prompts, generation controls, tools, coding rules, budgets, timeouts, and validation/processing/repair policies. Each configuration keeps its own fixed definition across the sample. C may adapt its task sequence within that definition. Scoring rules are fixed before assessment.

Select the first validated successful E, its first successful linked V, and the first successful independent C within the round. Retries under unchanged settings retain the round; V keeps its selected E. Any frozen-workflow change supersedes the whole round and requires all three configurations to rerun on all ten plans, including earlier successes. Even a C-only change on the eighth plan requires a full restart. Preserve superseded runs as development history.

Planned controls must bind runs, assessments, metrics, and summaries to the round; reject mixed/superseded selections; and require all 30 outputs before final assessment/reporting. Current development commands neither enforce those identities nor certify round completeness. Partial development reports remain useful for piloting review. Failure counting is outside the study outcomes; logs preserve execution problems and refinements. Reported runtime/tokens cover the selected successful runs.

## 3. Document collection and preparation

Experts screen eligibility using [DESIGN.md](DESIGN.md#eligible-plans) before registration. Registration assigns a document-version ID and SHA-256 checksum, preserves the original, and reuses an existing record for identical bytes. Revised contents receive a new ID. Duplicate registration cannot change metadata or study set.

`update_plan_data` accepts only title, source URL, access date, and study set. Validate the whole proposal before saving. Omitted fields stay unchanged. Development assignments remain fixed; other study-set changes require no saved model work. Registry corrections do not rewrite metadata snapshots in earlier preparations or runs.

Registry `development` identifies the initial two plans and `comparison` the additional eight. Both will participate in the final study round. Execution and assessment must support that membership without relabelling initial development history; current code still restricts purpose to the existing study-set rules.

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

`list_profiles` validates the model profiles, prompt files, and C bindings before displaying command-level choices. It requires no credentials and makes no writes or model calls. `--config-path` selects model profiles; `--collaboration-config-path` selects C bindings. Coordinator/worker profiles are components of C, not standalone run modes.

### Current configuration settings

These are configured limits for future runs, not claimed provider maxima. Model profiles are in [configs/profiles.json](configs/profiles.json); [configs/collaboration.json](configs/collaboration.json) binds C's three agents and shared limits. Saved runs retain their original settings.

| Setting | E | E+V | C |
| --- | --- | --- | --- |
| Selectable profile | `inkling2_small_hf_extractor` | E profile plus `deepseek_v4_1_flash_1017_hf_verifier` | `glm5_3_flash_hf_collaboration` |
| Models | Inkling 2 Small | Inkling 2 Small → DeepSeek V4.1 Flash 1017 | GLM-5.3-Flash coordinates Inkling and DeepSeek as flexible workers |
| Service / fixed host | Hugging Face / DeepInfra | Same | Same |
| Starting input | Whole prepared plan | Exact saved E answer and its whole prepared plan | Same prepared plan, independently of E/V outputs and expert references |
| Role prompts in `prompts/` | `extractor.md` | E prompt, then `verifier.md` | `coordinator.md`; both workers use `worker.md` |
| Context per request, input + output | 1,048,576 tokens | Same | Same |
| Output per request, including reasoning | 131,072 tokens | Same | Same |
| Temperature / top-p / seed | All `null`: provider defaults | Same | Same |
| Model/API requests, including final generation | 25 | 50: 25 per stage | 25 shared across all agents and phases |
| Document-tool submissions | 25 | 50: 25 per stage | 75: 25 per agent across all its tasks |
| Maximum model-request timeout | 1,800 seconds | Same | Same |
| Maximum document-tool timeout | 120 seconds | Same | Same |
| Whole-configuration elapsed ceiling | 5,400 seconds (90 minutes) | Shared by linked E and V; human waiting excluded | Shared by all agents; overlapping work counted once |
| Protected final-generation window | 1,800 seconds: Inkling's answer | 1,800 seconds: V's revised answer | 1,800 seconds: GLM's combined answer |
| Work before that final window | At most 3,600 seconds of investigation | At most 3,600 seconds for complete E plus V investigation | At most 3,600 seconds for coordinator/worker investigation, including worker results |
| Aggregate estimated-token ceiling | 31,457,280 | 31,457,280 shared by E and V | 31,457,280 shared by all agents |
| Document tools / OCR | Saved page text, exact quotation lookup, fresh EasyOCR; English, CPU, 150 DPI | Same | Same |
| Model input | Text only; direct image delivery disabled | Same | Same |
| Final answer validation | `agent_response.schema.json`, Python checks, four permitted format repairs | Same, plus E issue continuity | Strict `collaboration_response.schema.json` and Python checks; no format-repair pass |
| Quotation processing | Shared automatic location diagnostic and qualifying single-page citation corrections | Same, including local access to E's saved OCR readings | Same, using C's own source readings |
| Current execution scope | Development and permitted exploratory work | Same | Development plans only |

The endpoint is `https://router.huggingface.co/v1`; routing appends `:deepinfra` to the configured model ID. IDs are `thinkingmachines/Inkling-2-Small`, `deepseek-ai/DeepSeek-V4.1-Flash-1017`, and `zai-org/GLM-5.3-Flash`. Every profile loads `prompts/shared_coding.md` and `prompts/field_definitions.md` before its role prompt. C's component profile names and responsibilities appear in the [collaboration section](#collaboration-c).

Shared field guidance distinguishes complete E/V/C answers from C worker task results and specifies each workflow's issue origins/resolvers. Its effect on model quality is **Not yet tested**.

Null generation controls leave the selected model/host defaults unspecified; they do not establish identical sampling across models or deterministic output. All three models passed the five basic compatibility checks and completed development runs under earlier settings. The current budgets, shared guidance, and latest C prompts are **Not yet tested** in live study runs. Formal comparison remains disabled.

### Configuration time allowance

Each complete configuration has a 90-minute ceiling and a protected 30-minute final window. E/V profiles and the C binding set `max_elapsed_seconds: 5400` and `final_generation_seconds: 1800`. The first 60 minutes cover the work preceding the final answer, as specified in the configuration table. Final generation can begin as soon as investigation ends; the controller does not wait until minute 60.

V deducts its exact linked E duration from the shared clock, excluding human waiting between commands. A saved E exceeding 60 minutes, or lacking a valid duration, is refused before allocating V. An E ending exactly at 60 minutes leaves V final generation only. Manual retries get new attempt allowances; V retries retain the same E debit. Failed attempts remain separate evidence.

The clock starts before input assembly. Setup, model and document-tool waits are clipped to the current phase deadline. When investigation capacity ends, the controller hands off to the protected final request. Pending tool calls receive explicit replies when time prevents their execution. Model/tool transport failures still fail the attempt. A result finishing beyond the overall deadline cannot succeed; cleanup and evidence saving may finish afterward.

New E/V runs save the calculation in `artifacts/time_budget.json` and observed transition in `artifacts/final_handoff.json`. Historical profiles omitting these optional controls retain their original behavior; saved runs are unchanged.

### Configuration request and token allowances

The [configuration table](#current-configuration-settings) is the current numeric specification.

`max_model_requests` and `max_tool_calls` are independent E/V profile controls. One API reply can request multiple document tools. A 25-request stage reserves one final request, permitting at most 24 investigation requests; all 25 tools remain usable through batching. Missing request controls preserve the historical tool-derived bound.

`max_estimated_tokens` limits the sum of input admission estimates plus maximum output allowances. E/V reserves one full context for its final answer; C uses its coordinator/worker reservations below. V recomputes its linked E charge from the exact saved hosted request bodies; missing, malformed, or inconsistent requests block V before allocation. No prompts or saved requests are regenerated, and small actual usage does not release an admission charge. This is a conservative operational estimate, not a certified count or billing ceiling.

At 25 requests and a 1,048,576-token per-request limit, the common aggregate ceiling cannot further restrict E or C while each request fits. It can constrain E+V across 50 potential requests. Equal ceilings do not establish equal computation.

E/V saves each admission snapshot beside its request and totals in `artifacts/request_budget.json`; API-reported usage remains separate. When investigation cannot fit around protected request/token capacity, the controller requests the strict final answer. Final acceptance rules and failure preservation remain unchanged.

### Input and request preparation

`build_extractor_input()` checks the exact preparation and original PDF, snapshots prompts/settings, and assembles the whole source without model/OCR calls or file writes. Join `shared_coding.md`, `field_definitions.md`, and `extractor.md` with two newlines in one system message. A user message contains collection metadata, preparation notes, and all unchanged page text with distinct physical-page boundaries. Document text and tool results are evidence, not instructions.

`select_verifier_input_run()` chooses the highest numbered eligible, successful E run that passes saved-run validation, unless `--input-run-id` selects one explicitly. Resolve selection once and preserve it; verifier retries keep their original E input even if a newer extraction exists. The rule applies across study sets and permitted purposes. Time/token conditions are checked after selection; a failing selection stops without automatically switching to an earlier E.

`build_verifier_input()` selects one validated E run and uses that run's exact preparation. It loads the three verifier-profile prompts and adds a separate user message containing E's complete `plan_data` and `plan_issues`. E's reasoning, execution logs, and expert files are excluded from the model conversation. The input snapshot also preserves E's full run record and SHA-256 fingerprint. Require a different model and identical shared document-tool settings; stop if the baseline or source changes.

`build_huggingface_request()` creates a `PreparedHuggingFaceRequest`. Its serialized bytes, endpoint, timeout, expected model, and capacity limits are fixed. The runner saves its decoded body, the capacity check measures those bytes, and `request_huggingface_chat()` sends them without rebuilding the request. Internal tool arguments are objects; API arguments are JSON strings with unique call IDs. Return every tool result in call order, retaining the matching ID. Preserve reasoning in raw evidence while omitting it from API conversation replay.

Investigation exposes function definitions in `tools`. Final generation removes tools and requests strict `json_schema` output. `models.prepare_response_schema()` expands the authoritative schemas. DeepInfra receives a separate copy omitting `uniqueItems` and `if`/`then`/`else`; field names, required fields, types, permitted values, and other constraints remain. Adapt only schema positions, never literal property names or enum/const data. Complete Python validation retains all acceptance rules. Save the authoritative contract in the input snapshot and the adapted contract in the sent request.

The same DeepInfra preparation also merges the known issue-item `allOf` into one object by applying its resolver enum directly to the issue definition. This preserves the same permitted answers; unfamiliar compositions remain unchanged. Inkling, DeepSeek, and GLM passed all five compatibility checks with identical project schemas on 2026-11-22. Retain each exact outgoing schema and the full Python checks. Historical requests remain unchanged.

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

Requests retain the configured ID, and raw responses retain the reported ID. Other checkpoints, variants, and unlisted namespaces are rejected. Alias recognition leaves schema, usage, completion, and tool checks unchanged.

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
3. Before each investigation request, refresh the controller message with document-tool allowance, request counts, and estimated-token charges. Reserve one request and a full context for final generation. Earlier exact requests remain immutable. Prepare, record, budget, and send the request. Process tool calls first; otherwise a normally completed, nonempty reply ends investigation. The reply may be a readiness signal, prose, or a draft; its text is preserved without acceptance. Empty, failed, truncated, and unconfirmed replies cannot trigger final generation.
4. Execute calls sequentially. Every submitted MCP call consumes budget, including failures; excess requests receive logged non-execution errors. Catalogue discovery consumes no slot. Continue until a normal nonempty tool-free reply or investigation budget exhaustion. A call denied by the deadline receives an explicit result before handoff.
5. Send one final request with tools disabled and the response schema enabled, even after an early draft. Validate completion and answer, apply permitted format repairs, and recheck the source. Verification also checks the preserved E snapshot.
6. Diagnose quotation locations and apply qualifying single-page corrections. Validate any changed candidate again, then check collection metadata and verifier issue continuity. Preserve repairs and remaining flags without adding model/tool calls.
7. Stop the MCP subprocess, preserve its diagnostics, and recheck application snapshots before final publication. Return the last successfully saved status, even if the answer was valid in memory.

The handoff reply counts as a generation. Blocked preflight is retained as an attempt but contributes no generation usage. Whole-stage elapsed time includes setup, tools, validation, saving, and cleanup. Request deadlines cover connection, response reads, and in-request evidence callbacks; tool deadlines also cover SDK waiting/decoding.

E/V and C reuse `agents._bounded_mcp_request()` for complete MCP requests. A submitted tool exceeding its deadline fails the attempt, including synchronous decoding that returns late. Preserve the failure and any decoded late reply, stop further model requests, and retain evidence from already submitted concurrent work. Ordinary source/OCR error replies remain recoverable.

#### Investigation handoff

E/V and C workers use `models.is_investigation_handoff()`: confirmed normal completion, no API error, no tool calls, and nonempty text after whitespace stripping. `READY_FOR_FINAL_RESPONSE` remains the preferred signal, but ordinary prose and drafts also end investigation. JSON shape, Markdown fences, and wording are not parsed at this boundary. Tool-bearing replies execute their calls first. Empty or whitespace-only text, failed/truncated completion, and unknown completion status fail without final generation.

The original reply remains unchanged in saved evidence and conversation. It is unvalidated notes or a draft, not accepted data or source evidence. Python requests one separate complete response with tools disabled and the final schema enabled. That response alone must pass the existing completion, JSON, field, relationship, and source checks before acceptance. Invalid final answers fail without falling back to earlier text or starting a model repair/retry loop. This may spend a final request after unhelpful prose; budgets and required C contributions still apply. C coordinator completion retains its separate state and coordination-tool rules.

The shared coding prompt specifies activity-level grouping, source-specific quantity/date associations, and meaningful continuous evidence passages. Keep adjacent lines from one passage in one evidence object, preserving line breaks as \n and word-wrap hyphens. Short `find_quote` queries locate passages; saved quotations need enough context to support the recorded details. A clearly supported activity is retained with a linked issue when faithful evidence cannot be recovered.

Both stages check every quotation against source text and physical pages. The final request preserves accurate, sufficiently complete draft excerpts. V also reviews inherited evidence, checks the source section by section for omissions, and compares issue explanations with the final fields. Discrepancies stay open when reconciliation requires an unstated assumption. These are model instructions within the existing call sequence; expert assessment establishes semantic correctness. Observed development results appear in the [checkpoint](#current-development-checkpoint).

### Automatic quotation/page checks and corrections

The sequence is `JSON checks and format repairs → source checks → citation correction → JSON/context checks → saving`. Matching and correction live in `quotation_diagnostics.py`; the shared runner coordinates validation and preservation.

After structural and source checks, Python compares every evidence quotation with the prepared physical pages and successful OCR readings already saved during the run. V also uses OCR readings from its pinned E run locally; E's logs remain outside the verifier conversation. This step launches no OCR or model requests. Matching collapses whitespace only, preserving words, case, punctuation, and hyphens. Repeated wording elsewhere does not flag a valid cited location. Multi-page matches must use text from every cited page in consecutive physical order; uncertain spans remain unconfirmed.

`correct_quotation_pages()` returns a copied `plan_data` and a version 2 diagnostic report. It changes only a single-page citation with available cited text, no quotation match there, and exactly one alternative matching physical page. It never changes quotation wording, action details, metadata, or issues. Repeated matches, unavailable cited text, multi-page citations, and inexact wording remain unchanged; no general page-number offset is inferred. Invalid page ranges fail structural validation before this step.

The shared runner adds each `quotation_page_number` change to `validation_report.json`, serializes a separate `responses/repaired_final.txt`, and validates it again before contextual acceptance. Existing format repairs remain in the same audit trail; the raw model response remains unchanged. V receives the saved, processed E answer. These source-based repairs stay outside the source-independent functions in `validation.py` and `repair.py`.

The quotation report preserves the preparation fingerprint, matching method, initial summary, repairs with original/corrected pages and zero-based evidence indices, and remaining findings. Its final summary includes `corrected`; `findings` describes only remaining possible mismatches, unmatched quotations, and unconfirmed spans. An unmatched quotation can reflect OCR or layout differences. Flags alone do not fail a run; invalid corrected candidates and report-saving failures follow normal failure handling. Location checks do not establish factual support or evidence adequacy. No issue status is changed or resolution attributed to a model by Python.

Earlier development runs remain unchanged and need no new report. V uses a selected older E exactly as saved, without retroactively correcting it. In the final round, V must use that round's selected E, and all 30 outputs must use the frozen processing policy. C applies it to its own final answer and source readings. Assessment covers processed outputs, with raw responses available for review.

### Saved run

`output.json` follows [run.schema.json](schemas/run.schema.json). It records plan/run identity, stage/purpose, source path, retry/input links, UTC start/end, measured duration, frozen settings/environment, generation calls, tool-log path, status/error, and accepted `plan_data`/`plan_issues`. Only saved success retains the accepted answer; failures retain evidence with null accepted output. Unknown measurements remain null.

A `plan_id` identifies one PDF version, and a `run_id` identifies one execution. Action/issue IDs are local to linked outputs and persist through verification/curation. Each manual invocation gets a new numbered run directory, including retries. `--retry-of-run-id` links a failed attempt; it does not resume or overwrite it. Selected E/E+V pairs retain their exact run IDs when later runs become available. V records `input_run_id`; validators retain E issue IDs/origins and enforce permitted resolvers and valid action links. The prompt requires continuing action identities and explanations for splits, merges, and removals; experts assess those semantic decisions.

### Saved execution

| Evidence | Location within the run |
| --- | --- |
| Frozen input and tool catalogue | `artifacts/extractor_input.json` for E or `artifacts/verifier_input.json` for V; `artifacts/mcp_catalogue.json` |
| Application code, schemas, setup files, SHA-256 manifest | `artifacts/code/`, `artifacts/code_fingerprints.json` |
| Environment notes | `artifacts/environment/observations.json` |
| Time ceiling, protected final window, linked E duration, remaining investigation/stage time | `artifacts/time_budget.json` for timed E/V runs |
| Observed investigation-to-final transition and reason | `artifacts/final_handoff.json` for E/V with a protected window |
| E/V request counts, E token debit, and charged admission estimates | `artifacts/request_budget.json`; per-request snapshots in `responses/attempt_NN/request_budget.json` |
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

Issue checks enforce one linked issue per affected action, valid IDs/links, and resolver/status relationships. Open issues require null resolver/resolution; resolved issues require a permitted resolver and nonblank explanation. E uses extractor origin/resolver. V retains original identities/origins, may reopen issues, and uses verifier origin for additions and verifier resolver for its fixes. Model answers exclude expert resolutions; their curated copies allow them through `validate_curated_dataset()`. Removed/merged actions require updated links and an explanation of retired targets where a link becomes null.

### Collaboration (C)

C is stage 4 in DESIGN.md: GLM coordinates two flexible workers from the same prepared plan, independently of E/E+V and expert references. The source-only input builder, contracts, controller, live-client wrapper, MCP lifecycle, saved C runs, citation processing, and `run_collaboration_mode` are implemented for development and have completed live runs on both plans. The latest prompts and budgets require new live checks; formal comparison remains disabled.

| Agent | Model/profile | Responsibility |
| --- | --- | --- |
| Coordinator | GLM-5.3-Flash; `glm5_3_flash_hf_coordinator` | Assign tasks, reconcile findings, maintain the draft, and produce the complete answer. |
| `worker_1` | Inkling 2 Small; `inkling2_small_hf_worker` | Extract, investigate, or verify according to the assignment. |
| `worker_2` | DeepSeek V4.1 Flash 1017; `deepseek_v4_1_flash_1017_hf_worker` | Extract, investigate, or verify according to the assignment. |

The C binding uses the profiles above and the limits in the [configuration table](#current-configuration-settings). Workers share the [worker task](prompts/worker.md); GLM uses the [coordinator task](prompts/coordinator.md). Current guidance emphasizes a provisional draft while capacity remains, activity grouping, explicit heat eligibility, coverage beyond the main heat sections, retention of associated details, and exact continuous quotations. Interleaved OCR passages use shorter locatable excerpts with remaining gaps flagged. These instructions require live review; offline validation does not establish their quality effect.

#### Input and contracts

`build_collaboration_input()` loads one explicit, validated development preparation and its original PDF through the existing source checks. It snapshots the full source, collection URL/date, physical page count, fingerprint, configuration, and three profiles. It reads no baseline runs or expert forms and performs no model/OCR calls or writes. Other study sets are refused by this prototype.

| Contract | Content and checks |
| --- | --- |
| Task | Python-assigned `task_id` and `draft_version`; `worker_id`, `objective`, `source_pages`, `expected_findings`, `independent`, and `context_task_ids`. Empty source pages means the whole plan; page hints do not remove full-source access. Context IDs must name completed tasks. |
| Worker result | Exact task/worker/version, `checked_pages`, and nonempty `findings`. Each finding has `description`, nullable `related_action_id` and `proposed_change`, `evidence`, and `unresolved`. A task-specific generation schema fixes identity/version and restricts links to null or the accepted IDs in that task's draft snapshot; a new candidate always has a null link. Python still checks identity, links, and physical pages. Reported coverage and evidence remain claims requiring review. |
| Complete C answer | Shared `plan_data`/`plan_issues` fields, with issue origins/resolvers restricted to `worker_1`, `worker_2`, or `coordinator`. Python checks IDs, issue links/statuses, page bounds, missing-evidence/type issues, and exact collection URL/date. Expert resolutions are excluded from model answers. |

C schemas are expanded separately; changing their identities does not widen E/V acceptance. Complete source text is supplied to every agent. Each task has its own worker conversation. Independent checks omit draft answers and prior findings; other tasks receive the current draft and only selected completed results. This keeps task context explicit without importing unrelated conversations.

#### Controller and execution

`run_collaboration_prototype()` requires an explicit asynchronous model client. Its default behavior cannot start paid requests. Optional document tools require a client bound to the input fingerprint, using only `get_page_text`, `find_quote`, and permitted `run_ocr` capabilities. This core owns no MCP server or files.

1. GLM uses `assign_tasks` to choose one task per selected worker, with at most two in a batch. One delegation call may accompany document-tool calls. Python validates all call arguments, assignment context, and physical page bounds before execution, then processes calls in their returned order. Delegation waits for its worker results before later calls; independent workers within that batch run concurrently. Resource admission occurs as each call is reached, and worker dispatch prepares/reserves both workers' first and mandatory result requests before starting either. Tasks can change purpose while worker identities stay fixed.
2. Workers investigate with available document tools. Their context includes `allowed_action_ids` and the task-specific result schema. As in E/V, a normally completed, nonempty reply without tool calls ends investigation without accepting its content. Python preserves that reply and requests one schema-constrained task result, reiterating the exact identity/version and null links for new candidates. Final worker JSON is parsed strictly and validated; investigation prose or drafts cannot replace a failed result. There is no model repair/retry loop or automatic replacement of invalid links. Tool quotas persist across assignments.
3. GLM receives the validated findings and uses `submit_draft` with a complete answer and `based_on_version`. Python increments the version only after acceptance. Stale versions, reused retired action IDs, removed continuing issue IDs, and changed issue origins are rejected. Source explanations for corrections remain model claims.
4. GLM uses `finish_investigation` after both workers contribute and a valid draft exists. At most one coordination tool is allowed per turn; `submit_draft` and `finish_investigation` must each be standalone. Document-only batches remain allowed. An early complete answer still needs both contributions and a subsequent strict final request. If investigation capacity expires after both workers return validated findings, the reserved final request may assemble the first complete answer without an intermediate draft. Missing or failed required workers still block completion. Unexecuted pending calls receive explicit non-submission results, and the handoff records the available draft version and worker tasks.
5. Python disables tools, makes the reserved final request under the C answer schema, and validates the complete answer. The core returns that raw validated answer; the saved runner applies quotation checks and publishes the accepted result separately.

A required worker/model/API failure, submitted tool timeout, invalid result, or invalid final answer fails C and stops further model requests. Ordinary source/OCR error replies count as submitted calls and remain recoverable; source uncertainty may remain unresolved. Parallel worker shutdown retains the timeout as the failure cause. No automatic retries, provider fallback, or model substitution occurs. Cancellation retains available evidence in `CollaborationCancelled.result`.

`CollaborationResult` retains status/error, accepted answer, exact prepared model requests, raw response evidence, tasks, draft versions, tool/decision events, budget observations, and stopping reason in memory. Failed attempts have no accepted answer. The saved runner publishes input/profile/code snapshots and this evidence without overwriting earlier attempts under `runs/<plan_id>/run_collaboration_NNNN/`.

#### Saved C execution

`run_collaboration()` accepts a prepared development plan and a named C binding. It requires `HF_TOKEN` before allocating `runs/<plan_id>/run_collaboration_NNNN/`. `--config-path` selects C bindings; `--model-config-path` selects agent profiles. A retry links a failed C attempt using the same preparation and purpose but always creates a new folder. Comparison and exploratory C execution remain disabled.

The wrapper snapshots the complete input, preparation/pages, all profiles/prompts, observed environment, and application code/contracts. It starts the shared source-bound MCP server; all three models use the existing HF adapter. Independent worker requests can overlap. Checkpoints save each request before dispatch, raw HTTP chunks as received, response usage/errors, and numbered controller events containing tasks, draft updates, and tool activity. A saving failure stops further work. Ordinary source/OCR problems return error replies; complete-request timeouts and MCP transport/protocol exceptions, including unsaved OCR evidence, fail the run. Controller events and tool records retain timeout evidence and any decoded late reply. The MCP subprocess closes before accepted output is published.

| Saved path within the C folder | Contents |
| --- | --- |
| `output.json` | Active/final status, fixed source/settings, actor/task/phase for each model attempt, observed usage, budget, stopping reason, and accepted answer only on success. |
| `responses/attempt_NNNN/` | Exact request, capacity estimate, HTTP status, immutable received chunks, raw response, and decoded answer text when available. |
| `artifacts/collaboration_input.json`, `artifacts/code/`, `artifacts/code_fingerprints.json` | Complete startup source/settings and implementation evidence. |
| `artifacts/events/`, `artifacts/controller_result.json` | Incremental events and final controller outcome, tasks, draft versions, and budget. |
| `artifacts/tool_requests/`, `artifacts/tool_results/`, `tool_log.json` | Document activity with agent identity; each request/result is immutable, and the active aggregate log is append-only. |
| `artifacts/mcp_catalogue.json`, `artifacts/mcp_stderr.log`, OCR files | Available document tools, subprocess diagnostics, and fresh source readings when requested. |
| `validation_report.json`, `artifacts/quotation_page_report.json` | Strict C final validation, conservative citation corrections, and remaining review flags. A corrected candidate is preserved separately in `responses/page_corrected_final.json`. |

C retains strict schema acceptance without a model repair loop. After success, the shared quotation checker may correct a uniquely located single-page citation; it never changes quotation wording. The corrected candidate is validated again. Unmatched quotations remain review flags, as in E/V; structural success does not establish factual quality. Sources and startup code are rechecked, and whole-run elapsed time includes setup, concurrent work, cleanup, and checks.

C storage uses `collaboration_run.schema.json`, leaving E/V record and issue-role rules unchanged. Strict loading requires the preserved input, matching source fingerprint, saved settings, response/report links, and matching saved-code hashes. Completed records and evidence cannot be overwritten. Cancellation returns 130 with available evidence retained; a saving failure or abrupt termination can leave `running` or partial files. Recovery and retries remain manual. Both development plans completed saved C runs under earlier settings. Their outputs remain development evidence requiring expert assessment.

#### Development limits and reservations

Shared C limits live in its binding; per-agent document-tool limits live in the component profiles. Their current values are listed once in the [configuration table](#current-configuration-settings). E/V stages have independent request ceilings; C shares its request ceiling across all agents. These are complete-workflow comparisons, with actual resource use reported separately.

Reserve the coordinator's full context allowance for final generation. Before parallel dispatch, reserve each worker's initial input estimate/output allowance plus one full-context result request. Reservations are synchronous and atomic. Additional investigation requests must fit around all pending reserves. Charge each submitted request its full UTF-8 input estimate plus output allowance; small or unavailable reported usage does not release that charge. Unused worst-case reservation space is released when the actual prepared request consumes it. Oversized requests fail without shortening the plan.

Each model/tool timeout is clipped to its remaining phase time. Actual API input/output totals remain separate; an unavailable component stays null. Request, estimated-token, tool, and time limits never reset on delegation. These ceilings are development choices; formal settings will be fixed after pilots and before comparison.

Basic compatibility checks and the controlled-worker diagnostic below test interfaces. The separate real-plan runs demonstrate execution; expert assessment is needed to establish extraction and collaboration quality.

#### Coordination diagnostic

`uv run --locked python -m collaboration_check` defaults to `glm5_3_flash_hf_collaboration`; `--profile` selects another named binding. Only the coordinator makes HTTP requests. It is capped at eight attempts, 16,384 requested output tokens per call, 300 seconds per request, and 900 seconds overall, including a protected final window of at most 300 seconds. These detached diagnostic overrides preserve the active profiles and inherit the binding's shared request/token limits, currently 25 logical requests. Controlled worker steps count against that shared allowance; the separate eight-attempt limit bounds paid coordinator requests. The report records coordinator HTTP attempts and provider-reported usage separately.

The two-page fictional source contains tree planting, drinking fountains, and incompatible tree-budget statements. Controlled cards follow task order, not permanent worker specialties. The proposal card deliberately gives the wrong fountain count; the check card corrects it and flags the budget conflict. GLM is asked to delegate a batched source/proposal check, reconcile findings, save a draft, and produce the complete answer. Document callbacks read only this fixture; no PDFs, OCR, baseline runs, or expert forms are accessed.

Passing requires controller completion, contributions from both controlled workers, batched delegation, two separate activities, the corrected count, both budget values with an open issue, matching quotation pages, and unchanged code/contracts. These are fixture assertions, not study quality scores or proof of effective task allocation. The diagnostic does not assess live worker performance or whole-plan quality; those require separate real-plan execution and expert review.

Each invocation creates a new folder under `artifacts/collaboration_checks/`. It preserves the fictional source, capped/base settings and prompts, generated diagnostic instructions, application/schema/lockfile snapshots and fingerprints, every prepared request, raw/partial responses, controlled replies, controller events/tasks/drafts, and `report.json`. HTTP evidence is checkpointed before sending and during receipt; credentials and headers are excluded. Controlled steps have no HTTP status, no claimed API usage, and `generation_started: false`. Cancellation preserves available evidence and returns 130; model or saving failures stop further requests without automatic retry. A hard termination can leave a `running` report and partial files.

The first live check truncated at the former 4,096-token allowance. After increasing it to 16,384, one completed attempt altered two final quotations; an unchanged repeat passed all eight checks with four matching quotations. These outcomes demonstrate both interface completion and output variability. Workers were controlled fixtures; no diagnostic is a study C run or evidence of live worker quality.

## 6. Expert review and dataset assembly

The [expert reference format](#appendix-supporting-json-files), guided reference tools, and development assessment creation are implemented. Reference completion and manual assessment still need a development pilot. Experts use one form per plan from the original PDF for all three final-round outputs, freezing it before recording judgments. Reviewer roles, prior exposure, and disagreement procedures belong in study notes. Completed, reviewed development forms can supply the references for the initial two plans in the ten-plan comparison, with their prior exposure retained in interpretation.

### Expert reference creation — implemented

`create_expert_reference <plan_id> --prepared-by <name-or-study-ID>` creates `data/expert_references/<plan_id>/expert_reference.json`. Repeat `--prepared-by` for multiple experts; `--project-root` follows the same convention as other commands. Registration is required, but preparation, model runs, and an API token are not.

`expert_files.py` checks collection integrity and copies the registered title, source URL, and access date. Other metadata starts null or empty; language is `English`. `expert_templates.py` supplies instructions, `action_0001`, and `issue_0001`, with `TODO:` text guidance, `unspecified` action status, empty type/evidence lists, and an open expert-origin issue. New forms start `id_counters.action` and `id_counters.issue` at 1. No model outputs are read and no OCR or API calls are made.

`storage.save_new_expert_reference()` checks structure and atomically publishes the UTF-8 form, refusing occupied or redirected destinations and concurrent creation collisions. References live outside `runs/` and do not count as model work. Creation preserves the registry, preparations, and runs; rerunning it cannot reset an existing form. Experts code the fields directly and manage records with the editor.

### Expert reference editing — implemented

`edit_expert_reference --plan-id <plan_id>` requires one of `--add-action`, `--add-issue`, `--remove-action [ACTION_ID]`, or `--remove-issue [ISSUE_ID]`. Additions advance the persistent action or issue counter; removal never lowers it, so deleted IDs are not reused. Default removal selects the highest-ID record exactly matching its blank template; any changed field preserves it. Explicit IDs may select edited records. Action removal is blocked while issues link to it.

Before each edit, counters retain at least the highest currently present numbered IDs. Older forms gain counters from their current records on first edit; previously deleted IDs cannot be reconstructed. Keep these editor-managed counters when coding fields directly. Frozen references reject editor changes.

Editing verifies the original PDF, collection links, draft fields, unique IDs, issue links, and page bounds. Internal `allow_templates=True` permits unfinished guidance and empty type/evidence lists during editing. Normal reference validation rejects unfinished guidance. `storage.save_expert_reference_edit()` compares the original file bytes before atomic replacement and refuses intervening changes. Use one writer at a time; this is not a multi-writer lock. Missing or malformed forms are not recreated or repaired. Editing makes no model or OCR calls.

### Expert reference validation — implemented

`validate_expert_reference <plan_id>` checks the canonical form at `data/expert_references/<plan_id>/expert_reference.json`. It uses the shared `--project-root` option and returns 0 when the checks pass, 1 for file/data failures, or 2 for invalid command syntax. Problems include their category and field location. No files or reports are written, and no OCR or API requests are made.

`expert_files.py` reuses collection integrity checks, reads the registered original into memory, verifies those exact bytes against its SHA-256 checksum, and counts physical PDF pages with the strict pypdf reader. Unreadable, encrypted, empty, missing, or modified originals stop validation. Preparation and model outputs are not required. Each two-page spread counts as one physical PDF page.

`storage.load_expert_reference()` reads only the selected form and rejects symbolic-link redirection. `validation.parse_expert_reference_json()` checks strict JSON, fields, selected plan/source links, unique action IDs, and evidence page bounds. When present, reference issues require unique IDs, valid action links, at most one issue per action, and `expert` origins/resolvers. All references require linked issues for empty action types or evidence. An omitted `plan_issues` is checked as `{"issues": []}` without changing the file. Normal validation rejects `TODO:` guidance in editable text fields while leaving verbatim quotations untouched. No fields are repaired or rewritten.

Passing establishes file/link consistency. Empty action lists can pass; unfinished guidance cannot. Experts establish completeness, grouping, source support, and quotation fidelity. A validation pass does not mark the form complete or enable comparison execution.

### Expert reference freezing — implemented

After completing and reviewing the form, use `freeze_expert_reference <plan_id> --frozen-by <name-or-study-ID>`. Repeat `--frozen-by` for multiple reviewers. The named reviewers confirm readiness for assessment; software checks structure and source consistency, not scientific completeness or independence. Registration and the original PDF are required; preparation, model runs, and an API token are not.

The command fully validates the form and publishes `data/expert_references/<plan_id>/reference_freeze.json` once. It records SHA-256 fingerprints of the exact reference and original PDF bytes, source URL/date, physical page count, reviewer names, UTC time, and readiness confirmation. The reference stays in `expert_reference.json`; no additional reference form is created. Publication checks the reviewed bytes again and refuses intervening changes.

Freeze metadata blocks editor changes and recreation, including when the reference file is missing. `validate_expert_reference` verifies the reference fingerprint and checked source context against the freeze; changed files or damaged metadata fail. The CLI prints the reference fingerprint for manual judgments. Use one writer at a time and back up both files. Freezing does not enable comparison runs or release comparison-plan feedback.

Reference commands now use `data/expert_references/`. `storage.migrate_expert_references()` moves the old root folder without rewriting files and refuses occupied destinations or symbolic links. Existing freeze metadata may retain its original path as provenance; readers accept the same plan's old or current canonical path while verifying the bytes at the current location. New freezes record the current path. Creation refuses an existing legacy plan folder instead of resetting it at the new location.

### Assessment creation — implemented for development

`create_assessment <plan_id> --reviewer <name-or-study-ID>` requires a completed, frozen reference and three validated, successful development outputs. Repeat `--reviewer` for multiple reviewers. Optional flags are `--extractor-run-id`, `--verifier-run-id`, `--collaboration-run-id`, `--notes`, and the standard `--project-root`.

`select_assessment_runs()` selects the highest-numbered eligible E, the latest eligible V linked to that E, and the latest eligible C using the same preparation. If V alone is explicit, its recorded input determines E. Explicit mismatches fail without fallback. A latest E without an eligible V fails instead of silently choosing an older pair. Number order determines recency; file times do not. These are development defaults. Final assessment must use the first-success selections from one complete ten-plan round; its controls remain unimplemented.

Creation reuses strict saved-run loaders, checks the original PDF against the frozen reference, and fingerprints the exact selected records and reference/freeze files. Source and supporting evidence are rechecked before publication. Each invocation creates a new `data/assessments/<plan_id>/assessment_NNNN/`, including occupied or interrupted numbers in allocation. Metadata is published last; an interrupted folder without it is incomplete and is preserved. Use one writer at a time.

| File | Copied context | Manual fields |
| --- | --- | --- |
| `metadata.json` | Input IDs/paths/fingerprints, reviewers, notes, and instructions | Generated from command choices; no hand-edited judgments. |
| `action_scores.csv` | One reference activity per E/V/C output, description, and evidence | Matching output ID lists, 0/0.5/1 score, and reason. |
| `output_review.csv` | One candidate group per output record, IDs, description, and evidence | Confirm/regroup activities; enter support, evidence adequacy, and reasons. |
| `verifier_resolutions.csv` | Initially open E issues that V marks resolved by verifier, with descriptions and claimed resolution | Confirmation and reason. |

ID lists are JSON arrays inside CSV cells, preserving multiple links unambiguously. Judgment cells start blank, not zero or false. Output groups are candidates until experts combine splits/duplicates or separate bundled activities. No activity matching or scoring is inferred. Resolutions of new V issues or already resolved E issues are excluded from the resolution table. A table with no eligible claims still has its header. Creation uses no model/OCR calls and produces no metrics.

### Assessment validation — implemented for development

`validate_assessment <plan_id> --assessment-id <assessment_NNNN>` loads the recorded IDs explicitly, checks their saved fingerprints and E/V/preparation relationships, and revalidates the frozen reference, original PDF, and supporting run/source evidence. Newer runs never replace the recorded inputs. Missing files, changed inputs, symbolic assessment paths, malformed CSV/JSON, unknown links, or inconsistent judgments fail validation. Files are rechecked for changes during validation; save edits before retrying.

Each reference activity requires exactly one scoring row per configuration, preserving its copied description and evidence. Matching ID lists are local to that output; `[]` confirms an omission and requires zero. Scores accept only 0, 0.5, or 1. Output groups require unique IDs within their configuration and nonempty lists of known output records. Several groups may link one bundled record; one group may link several split records. Labels may be edited, while copied evidence must retain original quotations/pages from linked records. Every output record must be covered before review is complete. V-resolution rows must match exactly the initially open E issues that V claims to resolve, with their copied context intact. Unsupported activities cannot have adequate evidence.

Blank manual fields, missing output-group coverage, and `undetermined` judgments remain pending. A valid unfinished review returns 0; invalid data returns 1. `--require-complete` also returns 1 for pending review. The report separates reference scoring, output support/evidence, and V-resolution review status. These statuses do not establish scientific correctness, resolve zero denominators, or certify final-round membership.

The module returns parsed in-memory judgments and fingerprints of the exact four assessment files for later calculations, withholding usable data on validation errors. It writes no files, repairs no values, calculates no metrics, and makes no model/OCR calls. Ordinary UTF-8 CSV exports may reorder columns, use a byte-order mark or CRLF line endings, and retain multiline evidence.

### Manual expert assessment — planned

1. Complete the generated form from the original PDF. Where no model output has been viewed, do this before viewing it; record existing exposure from initial development or later refinement.
2. Run `validate_expert_reference`, address reported problems, and confirm scientific readiness. Run `freeze_expert_reference`, then `create_assessment` for the development pilot. Metadata records the selected run IDs, frozen reference identity, and reviewers. The frozen reference stays common to all three outputs.
3. Fill `action_scores.csv` with activity matches, 0/0.5/1 scores, and reasons. Combine split/duplicate output records by activity; assess each activity within a bundled record separately.
4. Confirm activity grouping and fill support/evidence judgments in `output_review.csv`. An activity absent from the reference is checked against the PDF before being classified as unsupported; any reference coverage gap is noted in the review.
5. Fill `verifier_resolutions.csv` to assess whether V addressed every grouped concern in initially open E issues it claims to resolve. C's independently generated issue handling and agent disagreements are described in review notes rather than matched to E issue IDs.
6. Run `validate_assessment` while editing; use `--require-complete` to check that all manual judgments and output coverage are settled. Address invalid records without treating pending judgments as zero.
7. For final study assessment, use the selected outputs from one complete ten-plan round. Preserve pilot and superseded judgments separately; current tools do not enforce this round requirement.

Assessment judgments are recorded in CSVs; metadata JSON is generated. Run `calculate_metrics` after validation to save per-plan results, retaining pending measures as unavailable. Current version 1 formats retain `included_attempts: null` and unavailable failure fields as compatibility placeholders outside the study outcomes. Generated guidance and these fields need alignment when formats record round identity, while preserving existing artifacts. The three quality measures and two issue measures remain as defined in DESIGN.md.

#### Worked scoring example

A fictional plan reports 100 trees planted in North Ward in 2025 and 200 planned for South Ward in 2027. The reference has one tree-planting action, type `nature-based`, retaining both phases and their associated details. Overall status is `unspecified` because no overall status is given.

| Score | Example output |
| --- | --- |
| 1 | Both phases, wards, quantities, dates, and statuses are correct; unstated fields use the defined missing values. |
| 0.5 | North Ward is correct but South Ward is omitted, or all 300 trees are described as already planted. |
| 0 | Tree planting is omitted or has no correct substantive description. |

### Measurement capture and calculation — implemented for development

`calculate_metrics <plan_id> --assessment-id <assessment_NNNN>` validates the recorded inputs and review files before calculating [DESIGN.md appendix G](DESIGN.md#g-evaluation-measures-and-calculations). `summarize_assessment()` contains the arithmetic; publication is separate. All three configurations use action score percentage, unsupported action count with total distinct activities, adequate-evidence percentage, and open issue counts. Confirmed/claimed V resolutions apply only to initially open E issues that V claims to resolve. Expert grouping supplies distinct-activity units; later expert fixes remain outside comparison.

E+V adds the selected successful E and V duration/tokens. C uses its complete successful-run elapsed duration and each recorded coordinator/worker call once, without adding overlapping worker times or counting budget totals again. These measures exclude failed attempts and superseded rounds. Input/output token components remain separate; any missing required component makes its total unavailable. An empty call list cannot establish zero usage. EasyOCR contributes duration, not LLM tokens.

Each measure records `value`, `status`, `reason`, `unit`, `numerator`, and `denominator`. States are `available`, `pending`, `unavailable`, or `not_applicable`. Reference scores require completed matching/scoring/reasons. Output counts and evidence percentages require reviewed group coverage/support; evidence also requires settled adequacy judgments. Candidate groups remain distinct from confirmed output totals. Missing judgments stay null. Zero-denominator percentages and a V-resolution table with no eligible claims are not applicable, with zero counts retained. Counts such as zero unsupported activities remain valid. Paired changes are E+V minus E and C minus E+V, using percentage points for percentage measures. Changes require both constituent measures to be available.

Every call creates a new `metrics_NNNN/` under the assessment with `results.json`, a long-form `summary.csv`, exact copies of all four input files under `assessment_inputs/`, and calculation code/schemas/locked dependency files under `code/`. Results follow `metrics_results.schema.json`, record input/code/summary hashes and review state, and retain full numeric precision. Inputs and code are rechecked before publication. `results.json` is published last; interrupted folders remain without that completion marker and their numbers are reserved. Use one writer at a time. Earlier results, live assessments, frozen references, and saved model outputs are preserved.

Valid partial assessments can produce partial development results. `--require-complete` rejects pending manual review before writing; it does not require all resource observations to exist. Successful publication returns 0; validation, strict-review, or publication failures return 1. No model/OCR calls are made. Current exports retain unused null failure entries. Final results must identify the complete round and its selected successful outputs.

### Cross-plan summaries — implemented for development

`summarize_metrics --result <metrics_folder>` accepts exact project-relative saved calculation folders or their `results.json` paths. Repeat `--result` once per selected plan; at least one is required. There is no latest-result default. Duplicate plans and incompatible study purposes/calculation methods fail. Single-plan reports can pilot the same workflow.

`load_metric_snapshot()` checks strict result JSON, canonical identities/paths, archived review/code/CSV fingerprints, and required code files. It reuses assessment validation on `assessment_inputs/`, checking the frozen reference and original source/run evidence while ignoring later live CSV edits. It recomputes the supported method and verifies saved measures, review state, metadata, and CSV content. Archived code is retained for audit and is not executed.

| Summary measure | Aggregation |
| --- | --- |
| Action/evidence percentages | Mean of available per-plan percentages, with equal plan weight. Activity denominators remain in per-plan rows. |
| Paired changes | Mean of available within-plan changes for each contrast and measure; percentages use percentage points. |
| Activity/issue counts, runtime, tokens | Totals by configuration over available plans, with applicable output denominators retained. E and E+V remain separate configurations. |
| Confirmed/claimed V resolutions | Sum both counts over the same eligible plans; plans with no claims contribute known zero counts. An all-zero claim denominator is not applicable. |
| Compatibility fields | Current version 1 exports retain unavailable failure entries outside the research outcomes. |

Every aggregate records its calculation, unit, status, contributing plan count/IDs, and excluded plan IDs/statuses/reasons. Measures can use different plan sets because of unavailable judgments or zero denominators. Pending or missing values are excluded explicitly and never replaced by zero; an empty contributing set retains its unavailable state. Current development summaries accept subsets of plans. Final reporting must include all ten selected calculations from one complete round, with per-measure exclusions still explicit. That sample/round check remains to be implemented.

Each call creates `data/reports/summary_NNNN/` with `summary.json`, per-plan/aggregate `summary.csv` rows, selected result copies under `inputs/<plan_id>/`, and current code/schema/dependency snapshots under `code/`. JSON follows `metrics_summary.schema.json` and records exact selected result paths and all package-file fingerprints. Keep the selected metric packages for their archived review/code evidence. Packages, source inputs, and summary code are rechecked before publication. `summary.json` is published last; interrupted folders retain their evidence and reserve their numbers. Existing reports are preserved. Use one writer at a time. Successful publication returns 0; invalid selections or publication failures return 1. No model/OCR calls are made; formal comparison remains disabled.

### Instruction dataset assembly — planned

`validate_curated_dataset()` supports E/V or C answers. C retains `worker_1`, `worker_2`, and `coordinator` origins and permits these agents or `expert` as resolvers. Each answer uses one workflow's identities; E/V role rules remain enforced. Model-answer schemas continue to exclude expert resolutions. Independent reference issues use `expert` origin in their separate form.

After assessment, experts curate separate supported answers while preserving assessed outputs. Each whole-plan example pairs extraction instructions, sufficient source text/page links and reviewed recovery, and an expert-curated answer. Correct/exclude unsupported content, preserve reasons/source links, and validate targets with the curated-answer contract. Expert fixes retain issue IDs/origins and record expert authorship/resolution; confirmation of a V fix remains in the manual study review records. Pilot the export format and report plans, examples, and grouped actions separately. Fine-tuning remains future work.

## 7. Development checkpoint and next steps

### Current development checkpoint

All three configurations have completed live development runs on both plans. These reviewed outputs used earlier settings and are not the formal comparison or a live test of the current budgets.

| Plan | Reviewed E → V | Reviewed C | Preliminary observations |
| --- | --- | --- | --- |
| Freetown (`plan_0001`) | `run_extract_0008` → `run_verify_0002` | `run_collaboration_0005` | All contain 14 action records. C completed follow-up checks using 21 requests in 28m59s. Source/citation gaps remain; the E/V pair predates later prompts and automatic citation processing. |
| Paris (`plan_0002`) | `run_extract_0002` → `run_verify_0006` | `run_collaboration_0002` | E/V contain 36/38 records; C contains 77. C completed four worker tasks using 21 requests in 38m36s. Review found useful distinctions alongside unnecessary splitting, missed activities/details, and uncertain eligibility. |

Paris V matched 100 of 130 quotations against available text and flagged 30; C matched 64 of 149 and flagged 85. Neither made a citation correction. Most C flags aligned after relaxing spacing or typographic punctuation in a read-only investigation; the saved matcher and outputs were unchanged. These are location/fidelity diagnostics, not evidence-adequacy scores or proof that one workflow is better.

The latest shared guidance, C prompts, budgets, and timeout handling passed offline checks; E/V role prompts remain stable. C curated-answer validation, guided reference tools, development assessment creation/validation, per-plan metrics, and cross-plan summaries are implemented. References, assessments, and reports live under `data/`. Freetown's reference was moved byte-for-byte and remains an unfrozen guided starter. Eight additional plans, frozen-round controls, a complete 30-output final round, expert review, and final results remain pending. [CHANGELOG.md](CHANGELOG.md) records development validation results, failures, and revisions.

### Next implementation steps

| Step | Current status | Remaining work |
| --- | --- | --- |
| 1. Pilot expert review | Reference tools and assessment CSV creation implemented; manual review pending | Complete and freeze initial references, create pilot assessments, record prior exposure, and settle grouping, reviewer roles, scoring, and disagreement procedures. Prepare shared references for all ten plans. |
| 2. Refine and complete the sample | Two initial plans registered; E/V/C runners implemented | Check the current workflow on both initial plans, add and prepare eight plans, and document further refinements. Fix the ten-plan sample and workflow settings for a final round. |
| 3. Implement frozen study rounds | Final-round execution remains disabled | Record workflow/source identities and all ten plan memberships, including the initial development plans. Bind runs and first-success E/V/C selections to the round. Any frozen-workflow change must supersede the whole round and require all three configurations to rerun on all ten plans. Require all 30 outputs before final assessment/reporting and reject mixed or superseded rounds. |
| 4. Complete assessment/reporting integration | Development metrics and summaries implemented | Extend E/V/C purpose, input, record/schema, storage, assessment, and reporting rules to final-round membership. Preserve prior-exposure records and reference freezes. Align generated instructions and retire unused failure fields with compatible format updates. Pilot complete ten-plan reports, retaining unavailable judgments as unavailable. |
| 5. Curate answers and build instruction export | E/V/C curated-answer validation implemented; curation and export pending | Prepare separate expert-curated answers and export validated instruction/source/answer examples without changing assessed outputs. |
| Later expansion | Deferred | Dataset expansion and model fine-tuning follow evaluation of the workflow. |

## Appendix: supporting JSON files

Existing workflow fields are defined in the [JSON contract map](#json-contracts). The expert reference format is defined by [expert_reference.schema.json](schemas/expert_reference.schema.json), which reuses the existing plan data schema.

### Expert reference form

Use one form per plan, saved at `data/expert_references/<plan_id>/expert_reference.json`. It contains the expert's reading of the original PDF and is used for all three final-round outputs. Complete it before viewing model outputs where no prior exposure has occurred; record exposure from initial development or subsequent refinement. Initial forms can pilot the process and, after review and freezing, supply references for those plans in the final comparison.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer, fixed at 1 | Reference form format version. |
| `plan_id` | string | Registered document. |
| `prepared_by` | nonempty list of strings | Names or study codes identifying the experts who completed the form. |
| `id_counters` | object; optional | Nonnegative integer `action` and `issue` counters retaining the highest numbered IDs allocated or observed by the editor. Removal never lowers them. |
| `plan_data` | object | Plan metadata, grouped actions, and evidence using the existing plan data fields. |
| `instructions` | list of strings; optional | Editing guidance supplied in new forms, outside coded content. |
| `plan_issues` | object; optional | Expert concerns in `issues`, using the shared issue fields with `expert` origin and `expert` or null resolver. |

New forms include instructions, issues, and counters; older version 1 forms without them remain readable under the same evidence/type checks. Reference issue IDs are independent of model-output issues. The schema checks fields and values; Python adds source, ID, link, page-bound, and unfinished-guidance checks. Experts establish factual support and completeness; the review procedure records preparers and prior output exposure.

### Expert reference freeze

`data/expert_references/<plan_id>/reference_freeze.json` follows [expert_reference_freeze.schema.json](schemas/expert_reference_freeze.schema.json). All fields are required.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer, fixed at 1 | Freeze format version. |
| `plan_id` | string | Selected registered plan. |
| `reference_path` | string | Reference path recorded at freezing; migration preserves historical paths. |
| `reference_sha256` | SHA-256 string | Fingerprint of the exact completed reference bytes. |
| `document_sha256` | SHA-256 string | Fingerprint of the registered original PDF bytes. |
| `source_url` | string | Registered source URL at freezing. |
| `date_accessed` | date string | Registered collection date at freezing. |
| `page_count` | positive integer | Physical pages counted in the original PDF. |
| `frozen_at` | UTC timestamp string | Time of freezing. |
| `frozen_by` | nonempty list of strings | Names or study IDs of reviewers confirming readiness for assessment. |
| `confirmed_complete` | boolean, fixed at true | Recorded reviewer confirmation, not a software finding of completeness. |

### Manual assessment

Experts compare saved E, E+V, and C outputs with the same frozen reference. CSV review tables hold matches, scores, support/evidence judgments, V-resolution checks, and reasons. C's collaboration and issue handling are described in review notes. Generated metadata follows [assessment_metadata.schema.json](schemas/assessment_metadata.schema.json); manual judgments are not entered in JSON.

| Metadata field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer, fixed at 1 | Assessment metadata version. |
| `assessment_id` | string | Numbered assessment folder identity. |
| `plan_id` | string | Registered development plan. |
| `purpose` | string, fixed at development | Current assessment scope. |
| `created_at` | UTC timestamp string | Creation time. |
| `reviewers` | nonempty list of strings | Reviewer names or study IDs supplied to creation. |
| `notes` | string or null | Optional review context. |
| `reference` | object | Current reference/freeze paths and exact file fingerprints. |
| `source` | object | Preparation path, source fingerprint, original PDF fingerprint, and physical page count. |
| `runs` | object | E, E+V, and C run IDs, record paths/fingerprints, and selection method. |
| `included_attempts` | null | Unused version 1 compatibility field; failure counts are outside the study outcomes. |
| `instructions` | list of strings | CSV editing guidance and pending-value rules. |
