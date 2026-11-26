# Implementation: Heat Adaptation LLM Dataset

**Implementation guide · updated 2026-11-25**

Technical reference for code, saved files, contracts, and remaining work. [README.md](README.md) gives commands; [DESIGN.md](DESIGN.md) defines the study; [CHANGELOG.md](CHANGELOG.md) preserves project history.

[Files and modules](#1-file-directory) · [Settings](#current-configuration-settings) · [Execution](#5-model-execution-and-preservation) · [Expert review](#6-expert-review-and-dataset-assembly) · [Next steps](#next-steps)

| Area | Current status |
| --- | --- |
| Preparation and E/V/C execution | Implemented; early runs completed on the two initial plans under earlier settings. |
| References, assessments, metrics, summaries | Implemented for the comparison sample; real expert assessment pending. |
| Latest guidance, C prompts, budgets | Checked offline; fresh live checks and quality assessment pending. |
| Ten-plan study execution | One comparison workflow throughout. Final versions, first-successful selections, and all 30 outputs are checked manually. |
| Dataset building | Execution, review drafts, finalization, assembly, and read-only completed-output validation implemented; real-plan pilot pending. |

## 1. File directory

<details>
<summary>Repository and generated-data layout</summary>

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
│   ├── source_pdfs/<plan_id>.pdf # Preserved original PDF; excluded from Git
│   ├── prepared_plans/<plan_id>/preparation_NN/  # Excluded from Git
│   │   ├── preparation.json    # Settings, source identity, status, and page-file link
│   │   ├── pages.json          # Ordered physical pages, exact text, and review notes
│   │   └── images/             # Preserved page PNGs and candidate-region crops
│   ├── comparison/             # Excluded from Git
│   │   ├── expert_references/<plan_id>/
│   │   │   ├── expert_reference.json # Independent PDF-coded benchmark
│   │   │   └── reference_freeze.json # Fingerprints, time, and readiness confirmation
│   │   ├── assessments/<plan_id>/assessment_NNNN/
│   │   │   ├── metadata.json   # Selected inputs, notes, and instructions
│   │   │   ├── action_scores.csv
│   │   │   ├── output_review.csv
│   │   │   ├── verifier_resolutions.csv
│   │   │   └── metrics_NNNN/   # Results/CSV, exact assessment inputs, and code
│   │   └── reports/summary_NNNN/ # JSON/CSV, selected results, and code
│   └── dataset_building/
│       ├── review_drafts/<plan_id>/review_NNNN/
│       │   ├── review_draft.json # Editable plan data/issues; fixed source context
│       │   └── source_run.json # Exact selected dataset-building run
│       ├── reviewed_plans/<plan_id>/review_NNNN/
│       │   ├── reviewed_plan.json # Clean metadata/actions, without issues
│       │   ├── review_record.json # Completion, provenance, and issue history
│       │   ├── review_draft.json # Exact reviewed draft
│       │   └── source_run.json # Exact original selected run
│       └── heat_action_datasets/dataset_NNNN/
│           ├── heat_action_dataset.json # Clean combined plan data
│           ├── dataset_contents.json # Completion, selections, workflow, and hashes
│           ├── inputs/<plan_id>/<review_id>/ # Four exact completed-review files
│           └── artifacts/code/  # Assembly source, schemas, and dependency files
├── runs/<plan_id>/
│   ├── run_extract_NNNN/         # Extractor attempts; same file layout as below
│   ├── run_collaboration_NNNN/   # C attempts; see saved C execution
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
└── AGENTS.md                     # Local working agreements; excluded from Git
```

</details>

Git tracks code, schemas, prompts, profiles, registry metadata, tests, and documents. Back up PDFs, prepared text/images, references, assessments, reports, runs, diagnostics, and OCR models separately. Credentials stay outside saved artifacts.

### Module responsibilities

<details>
<summary>Module responsibility map</summary>

| Module | Owns |
| --- | --- |
| [src/cli.py](src/cli.py) | Arguments, command dispatch, operational feedback, and exit codes. |
| [src/artifact_io.py](src/artifact_io.py) | Shared JSON encoding, exact-byte hashes, bounded artifact paths, next-version IDs, and assembly-code snapshots. Workflow modules own content checks. |
| [src/documents.py](src/documents.py) | Registration, collection-metadata updates, native text preparation, and selective OCR coordination. |
| [src/expert_files.py](src/expert_files.py) | Independent reference creation, record editing, validation, and freezing against checked collection metadata and the original PDF, without model-output access. |
| [src/dataset_assembly.py](src/dataset_assembly.py) | Explicit completed-review selections, common workflow checks, preserved combined datasets, and package validation. |
| [src/plan_reviews.py](src/plan_reviews.py) | Dataset-building run selection, editable draft checks, issue continuity, reviewed-plan finalization, and completed snapshot loading. |
| [src/expert_templates.py](src/expert_templates.py) | Guided blank actions/issues, field instructions, and unfinished-guidance detection. |
| [src/assessments.py](src/assessments.py) | Compatible run selection, frozen-reference/source checks, exact input fingerprints, and prefilled review CSV creation. |
| [src/assessment_validation.py](src/assessment_validation.py) | Read-only assessment input/CSV checks, parsed judgments, pending fields, and review status by configuration. |
| [src/metrics.py](src/metrics.py) | Per-plan measures, paired changes, explicit availability states, and preserved result/CSV/input/code snapshots. |
| [src/metric_summaries.py](src/metric_summaries.py) | Saved-package validation, archived-review recalculation, explicit cross-plan selections, aggregation, and preserved reports. |
| [src/document_tools.py](src/document_tools.py) | PDF rendering/image inspection, EasyOCR, source-bound page/quotation tools, and the local MCP server. |
| [src/agents.py](src/agents.py) | Profile/prompt loading, E input selection, complete source input, shared extractor/verifier execution, and incremental recording. |
| [src/agent_budget.py](src/agent_budget.py) | Independent E/V request ceilings, shared E+V estimated-token charges, and protected final-request capacity. |
| [src/collaboration.py](src/collaboration.py) | In-memory C controller: delegation, parallel tasks, versioned drafts, evidence, and final response. Clients are explicitly injected. |
| [src/collaboration_runner.py](src/collaboration_runner.py) | Saved C lifecycle: live HF clients, source-bound MCP, checkpoints, source/code rechecks, citation processing, and final status. |
| [src/collaboration_storage.py](src/collaboration_storage.py) | Separate C record contract, immutable evidence, active checkpoints, strict loading, and completed-run protection. |
| [src/collaboration_contracts.py](src/collaboration_contracts.py) | C binding, source-only study input, task/result checks, and separate final-answer validation. |
| [src/collaboration_budget.py](src/collaboration_budget.py) | Shared request/token reservations, agent/global tool quotas, usage, and final time reserve. |
| [src/collaboration_check.py](src/collaboration_check.py) | Capped live coordinator diagnostic with fictional source/tools and explicitly controlled workers. |
| [src/huggingface_api.py](src/huggingface_api.py) | Prepared HTTP requests, fixed provider routing, schema adaptation, size estimates, response interpretation, and usage. |
| [src/models.py](src/models.py) | Shared response/tool schemas, conversation validation, and model-result evidence types; no network operations. |
| [src/validation.py](src/validation.py) | Strict JSON parsing, schema checks, record relationships, source context, and permitted-repair coordination. |
| [src/legacy_records.py](src/legacy_records.py) | Read-only old-label/path compatibility. Validation views and directory aliases preserve original records and fingerprints. |
| [src/repair.py](src/repair.py) | The four allowed formatting repairs, producing a separate candidate and audit trail. |
| [src/quotation_diagnostics.py](src/quotation_diagnostics.py) | Local quotation matching, conservative single-page citation corrections, and remaining review flags; no model calls or file access. |
| [src/storage.py](src/storage.py) | Paths, identities, atomic publication, immutable evidence, active-record updates, and loading/integrity checks. |
| [src/huggingface_check.py](src/huggingface_check.py) | Explicit fictional-input compatibility checks, saved separately from research extractions. |

</details>

### JSON contracts

Schemas define fields; Python adds relationship, source, and filesystem checks. Read the producer, validator, and consumer before changing a contract. C's contracts remain separate from E/V.

<details>
<summary>Schema responsibility map</summary>

| Schema in `schemas/` | Contract |
| --- | --- |
| [registry.schema.json](schemas/registry.schema.json) | Registered document identity, metadata, study set, preparation link. |
| [preparation.schema.json](schemas/preparation.schema.json), [pages.schema.json](schemas/pages.schema.json) | Preparation settings/status, complete ordered pages, text/image routes and region metadata. |
| [profiles.schema.json](schemas/profiles.schema.json) | Editable extractor/verifier/coordinator/worker profiles and shared document tools; loading does not start execution. |
| [collaboration_config.schema.json](schemas/collaboration_config.schema.json) | Named C bindings and shared request, estimated-token, document-tool, and elapsed-time limits. |
| [collaboration_task.schema.json](schemas/collaboration_task.schema.json) | Assignment identity, objective, page scope, expected findings, draft version, and selected prior task context. |
| [collaboration_result.schema.json](schemas/collaboration_result.schema.json) | Worker/task identity, checked pages, findings, proposed changes, evidence, and uncertainty. |
| [collaboration_response.schema.json](schemas/collaboration_response.schema.json) | Complete plan_data/plan_issues with C-only agent identities; reuses the existing plan data contract. |
| [collaboration_run.schema.json](schemas/collaboration_run.schema.json) | C record and purpose, three profiles, shared settings/environment, per-agent model calls, budget, status, and accepted answer. |
| [plan_data.schema.json](schemas/plan_data.schema.json) | `plan_data.metadata`, `plan_data.actions`, evidence, categories, and missing values. |
| [agent_response.schema.json](schemas/agent_response.schema.json) | Complete model answer: `plan_data` and `plan_issues`, including issue-status constraints. |
| [curated_dataset.schema.json](schemas/curated_dataset.schema.json) | Curated E/V or C answers with workflow-specific issue identities and expert resolutions; mixed workflow identities are rejected. |
| [review_draft.schema.json](schemas/review_draft.schema.json) | Editable answer/issues, review identity/scope, exact source selection, and instructions. Python adds continuity and completion checks. |
| [review_record.schema.json](schemas/review_record.schema.json) | Completed review, issue decisions, source/draft/product fingerprints, and expert/model resolution groups. |
| [heat_action_dataset.schema.json](schemas/heat_action_dataset.schema.json) | Combined plan identities, metadata, and actions; no issue objects. |
| [dataset_contents.schema.json](schemas/dataset_contents.schema.json) | Dataset identity, review selections/hashes, common workflow definition, counts, and assembly-code fingerprints. |
| [reviewed_plan.schema.json](schemas/reviewed_plan.schema.json) | Clean metadata/actions using the shared plan-data contract; issue objects are excluded. |
| [expert_reference.schema.json](schemas/expert_reference.schema.json) | One reference with shared plan-data fields and optional instructions, ID counters, and expert-origin issues. Python checks source links, IDs, issue links, page bounds, and unfinished guidance. |
| [expert_reference_freeze.schema.json](schemas/expert_reference_freeze.schema.json) | Exact reference/PDF fingerprints, source context, readiness confirmation, and UTC freeze time. |
| [assessment_metadata.schema.json](schemas/assessment_metadata.schema.json) | Assessment identity, selected E/V/C records, frozen reference/source fingerprints, and editing instructions. |
| [metrics_results.schema.json](schemas/metrics_results.schema.json) | Per-plan measures, counts/denominators, availability states, paired changes, review state, and input/code provenance. |
| [metrics_summary.schema.json](schemas/metrics_summary.schema.json) | Selected package identities/fingerprints, aggregate measures, contributing/excluded plans, and report provenance. |
| [run.schema.json](schemas/run.schema.json) | Saved wrapper, settings/environment, generation measurements, status, and accepted answer. |
| [tool_log.schema.json](schemas/tool_log.schema.json), [validation_report.schema.json](schemas/validation_report.schema.json) | Tool activity and final-response errors/repairs. |

</details>

Dates use `YYYY-MM-DD`, timestamps UTC, durations seconds, and paths project-relative. Registry/profile/extraction formats use version 1. Preparation uses version 3 and still reads version 2; assessment metadata uses version 2. Historical local-model records remain readable but cannot select active local profiles. Plan study sets are `comparison` or `expansion`; run purposes are `comparison` or `dataset_building`. `legacy_records.validation_view()` adapts known archived registry/run labels without changing returned objects or saved bytes. Assessment/result/report validation uses current schemas directly. Unknown labels remain invalid.

## 2. Execution path and current scope

`cli.main()` parses arguments and delegates through named handlers. Parser helpers group commands by workflow; application modules own validation and saving.

| Commands | Application entry points |
| --- | --- |
| `add_plan`, `update_plan_data`, `prepare_plan` | `documents.register_document()`, `update_document_metadata()`, `prepare_document()` |
| `run_extract_mode`, `run_verify_mode` | `agents.run_extractor()`, `run_verifier()` |
| `run_collaboration_mode` | `collaboration_runner.run_collaboration()` |
| Reference create/edit/validate/freeze commands | Matching functions in `expert_files.py` |
| `create_assessment`, `validate_assessment` | `assessments.create_assessment()`, `assessment_validation.validate_assessment()` |
| `create_review_draft`, `validate_review_draft`, `finalize_reviewed_plan` | Matching functions in `plan_reviews.py` |
| `validate_reviewed_plan` | `plan_reviews.load_reviewed_plan()` |
| `build_heat_action_dataset` | `dataset_assembly.build_heat_action_dataset()` |
| `validate_heat_action_dataset` | `dataset_assembly.load_heat_action_dataset()` |
| `calculate_metrics`, `summarize_metrics` | `metrics.calculate_metrics()`, `metric_summaries.summarize_metrics()` |
| `list_plans`, `list_profiles` | Registry/preparation listing and validated E/V/C profile display |

Model execution follows `CLI → saved runner → controller → Hugging Face API`, with local source tools through MCP. Runners own saving and final status; models never write research files directly.

### Manual tracking for the final comparison

All ten plans belong to one comparison sample. Refine on two first, extend execution to the other eight, and compare all ten under the final settings. Study runs use `purpose: comparison`; assessments, calculations, and summaries select only those outputs. Keep a manual log of the code/settings version, each preparation, selected E/V/C IDs, and prior exposure. V uses that log's E input.

Select the first successful E, linked V, and independent C. Retry execution failures without changing settings. Any workflow change requires rerunning all three configurations on all ten plans. Check all 30 selected outputs against the intended versions before final assessment/reporting; preserve earlier selections as history.

No study-round creation/freezing commands are planned. Existing records preserve source, code, prompts, settings, and links for manual checks. The implemented expert-reference freeze is separate.

E/V/C runners default to comparison; explicit `--purpose dataset_building` permits either plan set. Comparison execution requires sample membership. V input and retry links must retain the run's effective purpose. `require_run_purpose()` restricts new writes; `effective_run_purpose()` recognizes retired labels only when reading. Eligible archived comparison outputs remain usable for comparison verification/assessment. Dataset-building runs stay outside comparison assessments. Latest defaults support review; final assessment uses the manual log's three IDs. Assessments have no purpose argument/metadata field; labels do not certify final settings or inclusion.

## 3. Document collection and preparation

`migrate_data_layout [--dry-run]` preflights old directories and saved runs, moves bytes without editing preparations/reference freezes/run evidence, and updates mutable registry paths. Reads accept recorded old source prefixes through `legacy_records.canonical_data_path()` and bounded filesystem lookup. Compare canonical paths for PDF/preparation identity while fingerprinting original saved JSON values. Old and new occupied locations are ambiguous and rejected; new writes use current paths. Migration refuses symlinks/merging, verifies moved hashes and exact run records, and can resume after an interrupted rename. Old assessment/report locations must be empty; no compatibility layer is needed for their uncreated artifacts.

Registration assigns a PDF-version ID and SHA-256 checksum, preserves its bytes, and reuses the record for identical content. Experts screen [eligibility](DESIGN.md#eligible-plans) first. Revised content receives a new ID.

`add_plan` defaults to `--study-set comparison`; `expansion` is for dataset building outside the ten-plan sample. `update_plan_data` accepts title, source URL, access date, and study set. Archived sample entries may explicitly join comparison after model work; only the registry changes. Other membership changes require no saved model work. Omitted fields and snapshots remain unchanged. Record which plans informed refinement in the manual log.

### Prepare text automatically, investigate gaps with tools

1. Extract native text with pypdf in physical-page order.
2. Detect individual images covering at least 10% of a page with no native text inside their bounds; preserve full-page PNGs and candidate crops.
3. Use full-page OCR for unavailable/unreliable text. Append labelled regional OCR to usable native text as `mixed`.
4. Save a new `preparation_NN/` and update the registry link, retaining earlier/failed preparations.

EasyOCR uses cached English CPU models at 150 DPI; preparation downloads no models. `--no-ocr` skips recognition while retaining image checks. Known blank text is `""`; unavailable text is null. Preserve every page, gap, and warning. Pixel bounds are left/top/right/bottom from the image's top-left.

| Status | Meaning |
| --- | --- |
| `ready` | No automatic problems or flags. |
| `ready_with_gaps` | A reading route exists for every page, with review notes. |
| `failed` | Counting or a required reading route failed. |

Readiness does not establish accuracy. Screening can miss small charts/partial text layers; OCR can misread tables.

### Source-bound document tools

The runner starts MCP over stdin/stdout in the same environment. A source fingerprint binds it to the selected preparation; models choose pages/quotations, never other files.

| Tool | Behavior |
| --- | --- |
| `get_page_text(page_number)` | Exact selected page entry and source notes; no new recognition. |
| `find_quote(quote)` | Exact, case-sensitive, per-page substring search in initial prepared text, preserving spaces and line breaks. No normalization or cross-page joining. |
| `run_ocr(page_number)` | Fresh full-page EasyOCR from checked original bytes, using the active run's frozen settings and saving artifacts to that run. |

Fresh OCR neither replaces prepared text nor expands `find_quote`'s corpus. Rendering/recognition is sequential with a reused reader. Ordinary source/OCR error replies are recoverable; submitted timeouts, protocol/transport errors, and evidence-saving failures stop execution. Direct image delivery and tool-requested regional OCR are deferred.

## 4. Hugging Face configuration and requests

`configs/profiles.json` holds model profiles and shared tool settings; `configs/collaboration.json` binds C's profiles/limits. Profiles define execution settings. Model-run commands accept `--purpose comparison` (default) or `--purpose dataset_building`; refinement and final comparison use the same purpose. Purpose changes eligibility and bookkeeping, not prompts, budgets, or answer rules. Runs save selected values and ordered prompts.

`list_profiles` validates profiles/prompts/bindings without credentials, writes, or requests. Its `--config-path` selects model profiles; `--collaboration-config-path` selects bindings. Coordinator/worker profiles are components of C.

### Current configuration settings

Configured limits for future runs are shown below; saved runs retain their original values. These are not provider maxima.

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
| Execution eligibility | Comparison purpose on comparison plans; dataset-building purpose on either set | Same; exact saved E with matching purpose | Same as E |

The endpoint is `https://router.huggingface.co/v1`; routing appends `:deepinfra`. Model IDs are `thinkingmachines/Inkling-2-Small`, `deepseek-ai/DeepSeek-V4.1-Flash-1017`, and `zai-org/GLM-5.3-Flash`. Profiles load `shared_coding.md` and `field_definitions.md` before their role prompt.

Null sampling controls leave provider defaults unspecified, without establishing determinism or identical sampling across models. Current settings need fresh live checks; experts establish output quality.

### Configuration time allowance

The 90-minute ceiling includes a protected 30-minute final window: `max_elapsed_seconds: 5400`, `final_generation_seconds: 1800`. Generation can begin earlier when investigation finishes.

V subtracts its linked E duration, excluding human waiting. Missing duration or E exceeding 60 minutes blocks V before allocation; exactly 60 minutes permits final generation only. Retries receive new attempt allowances and retain the same E debit.

Timing starts before input assembly. Clip setup/requests to phase deadlines. Investigation exhaustion triggers final handoff; unsubmitted tools receive explicit results. A late overall result cannot succeed, though cleanup/saving may finish afterward. New runs preserve `artifacts/time_budget.json` and `artifacts/final_handoff.json`; older profiles retain original behavior.

### Configuration request and token allowances

Use the settings table as the numeric specification:

- E/V request and tool ceilings are independent. One reply can batch tools. A 25-request stage reserves one final request, leaving at most 24 for investigation.
- `max_estimated_tokens` sums input estimates and maximum output allowances. E/V reserves one full context for final generation.
- V recomputes E's charge from exact saved hosted requests. Missing/inconsistent evidence blocks V before allocation; requests are never regenerated.
- Small actual usage does not refund admission charges. This is an operational estimate, not a certified token count or billing ceiling.

The common 31,457,280 ceiling cannot further restrict 25 full-context E or C requests, but may constrain E+V across 50. Equal ceilings do not establish equal computation. Admission snapshots and `artifacts/request_budget.json` remain separate from provider usage.

### Input and request preparation

| Step | Behavior |
| --- | --- |
| E input | `build_extractor_input()` validates preparation/PDF and snapshots settings/prompts. Supply whole unchanged source with physical-page boundaries. System prompts are shared coding, field definitions, then extractor, separated by two newlines. |
| V input | `build_verifier_input()` uses validated E's preparation and complete `plan_data`/`plan_issues`. Preserve its full record/byte fingerprint locally; omit reasoning/logs and expert files from the conversation. |
| V selection | `select_verifier_input_run()` chooses highest-numbered eligible E with the same purpose, or explicit `--input-run-id`. A wrong-purpose explicit ID fails without fallback. Resolve once; retries retain input/purpose. Check time/tokens afterward without fallback. Require a different model and identical shared tools. |
| Request | `PreparedHuggingFaceRequest` fixes bytes, endpoint, timeout, model, and limits. Save, measure, and send those same bytes. |
| Tool replay | Internal arguments are objects; API arguments are JSON strings with unique call IDs. Return results in order. Preserve raw reasoning while omitting it from replay. |

Document/tool text is evidence, not instructions. Input builders make no model/OCR calls or writes.

Investigation exposes tools. Final generation removes tools and requests strict `json_schema`. `models.prepare_response_schema()` expands authoritative schemas. The DeepInfra copy omits `uniqueItems` and `if`/`then`/`else` while retaining fields, types, and other constraints; adapt schema positions only.

Merge the known issue-item `allOf` by applying its resolver enum directly; leave unfamiliar compositions unchanged. Full Python checks still enforce the original contract. Preserve authoritative and outgoing schemas. All three models passed five compatibility checks with identical project schemas on 2026-11-22; historical requests remain unchanged.

### Capacity and response checks

Before dispatch:

```text
estimated_input_tokens = len(prepared_request.body_bytes) + 8192
estimated_input_tokens + max_output_tokens <= context_limit
```

Save byte size, margin, limits, and fit decision. Reports use `counting_mode: conservative_estimate`, `input_tokens: null`, and `verified_provider_count: false`. Oversized requests stop without source shortening or reduced output reservation.

Only API `prompt_tokens`/`completion_tokens` supply actual usage. Missing stays null; reported zero stays zero. Reject malformed usage/tools/arguments, changed model identity, unknown finish reasons, truncation, and above-limit usage. Preserve bytes and valid observations on failure. HTTP has no automatic retries, redirects, model switches, or provider fallbacks.

Identity is case-insensitive and permits only these aliases in addition to configured IDs:

| Requested ID | Accepted response name |
| --- | --- |
| `deepseek-ai/DeepSeek-V4.1-Flash-1017` | `deepseek/deepseek-v4.1-flash-1017` |
| `zai-org/GLM-5.3-Flash` | `z-ai/glm-5.3-flash` |

Requests and raw replies retain their respective IDs.

### Compatibility diagnostics

Use fictional-input checks when changing the serving setup/schema. These paid diagnostics are separate from study runs.

<details>
<summary>Compatibility commands, limits, and saved evidence</summary>

```bash
uv run --locked python -m huggingface_check --check-tools
uv run --locked python -m huggingface_check --model deepseek-ai/DeepSeek-V4.1-Flash-1017 --check-tools
uv run --locked python -m huggingface_check --model zai-org/GLM-5.3-Flash --check-tools
```

Without `--check-tools`, the default Inkling check makes at most three requests; with it, at most five:

| Check | Requested output cap |
| --- | --- |
| Conflicting-field small strict schema | 2,048 tokens |
| Adapted project schema on a fictional one-page plan | 4,096 tokens |
| Short output-limit probe | 64 tokens |
| Optional forced `get_page_text` call | 2,048 tokens |
| Optional replay and JSON answer | 2,048 tokens |

The tool round trip uses a fresh fictional confirmation code without real MCP/PDF/OCR. `--model` changes only identity, retaining host/prompts/limits/task. Invalid overrides fail before requests. Standard checks stop at the first failure.

`--isolate-project-schema` replaces standard checks with two variants and cannot combine with `--check-tools`:

| Variant | Change |
| --- | --- |
| `small_schema_full_instructions` | Small schema, full instructions/source. |
| `project_schema_short_instructions` | Full project schema, short instructions/source, shared JSON instruction. |

Both use the profile-capped 4,096-token allowance. Attempt both after response/validation failures; saving failure/cancellation stops execution. Full Python project validation remains required. Reports mark `mode: project_schema_isolation`; success requires both variants and does not establish acceptance of the original request.

All requests are profile-capped and limited to 300 seconds. Only the 64-token probe permits truncation; missing output usage makes it inconclusive. Preserve settings, exact requests/replies, HTTP errors/status, estimates, usage, and results under `artifacts/huggingface_checks/`, excluding credentials/study files. These checks establish interfaces, not full-plan quality, full output capacity, billing ceilings, or future provider behavior.

</details>

## 5. Model execution and preservation

### Shared execution control

`run_extractor()` and `run_verifier()` share `_run_agent_loop()` and `_run_saved_agent()`:

1. Validate plan/preparation/profile/purpose/authentication, observe environment/Git state, snapshot code/contracts, and allocate a `running` record.
2. Assemble complete input and discover the source-bound MCP catalogue.
3. Reserve final capacity; refresh investigation budget messages; prepare/save/send requests.
4. Execute tools in order. Every submission consumes allowance, including errors; catalogue discovery does not. Denied calls receive explicit non-execution results.
5. After handoff, make one tools-disabled final request, validate it, apply permitted repairs, check source/collection and V issue continuity, and process citations.
6. Close MCP, preserve diagnostics, recheck evidence, and publish final status.

Duration includes setup, requests, tools, saving, validation, and cleanup. Blocked preflight retains an attempt without generation usage. Request deadlines include response reads/evidence callbacks; tool deadlines include SDK waiting/decoding.

E/V and C share `agents._bounded_mcp_request()`. Submitted timeouts—including synchronous decoding returning late—fail the attempt, preserve available late replies, and stop new requests. Retain evidence from already submitted parallel work. Ordinary source/OCR replies remain recoverable.

#### Investigation handoff

`models.is_investigation_handoff()` requires normal completion, no API error/tool calls, and nonempty trimmed text. `READY_FOR_FINAL_RESPONSE` is preferred; prose/drafts also qualify. Tool-bearing replies execute first. Empty, truncated, failed, or unconfirmed replies cannot trigger final generation.

Handoff content stays unvalidated in evidence. Python requests a separate strict final answer even after a complete-looking draft. Only that answer can be accepted. No model repair loop, draft fallback, or reuse of earlier text follows final failure. Worker handoff follows the same rule; C coordinator completion has separate controls below.

### Automatic quotation/page checks and corrections

Processing order: `JSON/format repair → source checks → citation correction → revalidation → saving`.

- Compare against prepared pages and successful saved OCR. V may read linked E OCR locally; E's logs stay outside its conversation.
- Match whitespace differences while preserving wording, case, punctuation, and hyphens. Multi-page matches cover all cited consecutive pages; uncertain spans remain unconfirmed.
- Correct only a single-page citation whose readable cited page does not match and whose full quotation matches exactly one other page. Do not rewrite quotations or change ambiguous/unreadable/multi-page citations; no offset is inferred.
- Revalidate a separate candidate. Keep `quotation_page_number` repairs in `validation_report.json` and version 2 `artifacts/quotation_page_report.json` with source fingerprint, summaries, repairs, and remaining findings.

No new OCR/model requests are made and no issue statuses change. Location matches establish neither support nor adequacy. Flags alone do not fail execution; invalid candidates or evidence-saving failures do. Earlier records remain unchanged; use selected E exactly as saved. Final comparison outputs must share the processing policy.

### Saved run

`output.json` follows [run.schema.json](schemas/run.schema.json): identity, stage/purpose, source, retry/input links, UTC timing, duration, settings/environment, generation measurements, logs, status/error, and answer. Only success retains accepted output; unknown measurements stay null.

Each invocation/retry receives a new ID. `--retry-of-run-id` links without resuming/overwriting and requires the same purpose; V's `input_run_id` fixes E, whose purpose must match. Saved-run loading rechecks linked purposes. Local answer IDs persist through verification/curation. Experts assess the semantic justification for splits, merges, and explanations.

E/V/C chronology checks use `validation.parse_utc_timestamp()` after schema validation. Compare actual UTC times across optional fractional seconds and equivalent `Z`/`+00:00` forms.

### Saved execution

<details>
<summary>E/V evidence paths</summary>

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

</details>

Strict loading checks paths, PDF/preparation, frozen input/source fingerprint, and links. V's preserved E object/byte fingerprint must match. Completed records/artifacts cannot be overwritten; active records/logs grow atomically without changing settings or known observations. Use one writer at a time.

Successful E/V/C finalization and loading share `storage._check_accepted_candidate()` and `_check_archived_code()`. Accepted `plan_data`/`plan_issues` must equal the validation report's repaired candidate, or raw final answer when no repair exists. Check the files listed in the startup SHA-256 manifest against their archived bytes, independently of today's code. Missing, malformed, or inconsistent evidence blocks success/loading; failed attempts retain incomplete evidence. These checks neither rewrite historical files nor establish source support.

Client versions and Git state are observed, including dirty code snapshots. Undisclosed remote revisions, runtime, quantization, hardware, and loaded state stay null.

Checkpoint failure stops work and attempts failed publication. Abrupt termination/saving failure can leave `running`, partial evidence, and null end/duration. Confirm process termination before manual recovery. CLI codes: 0 saved success, 1 failure, 2 invalid arguments, 130 cancellation.

All attempts expose operational feedback, including counts, repairs, diagnostics, and errors, while preserving full disk evidence. No plan label or terminal display certifies independence; record prior exposure and complete references before viewing outputs where possible.

### Validation and permitted repair

`validation.py` checks strict JSON, fields, unique IDs, links, physical pages, source/collection values, issue identities, and run relationships. Problems use `syntax`, `structure`, `reference`, or `other`. E/V permits only:

| Repair | Boundary |
| --- | --- |
| Whole-response JSON code fence | One complete answer, without surrounding commentary. |
| Trailing comma | Immediately before a closing bracket/brace, outside strings. |
| Missing closing delimiters | Unambiguous nesting after a complete value and confirmed normal completion. |
| Single page number | Positive integer converted to a one-item `page_numbers` list, then range-checked. |

Preserve raw/candidate bytes separately and revalidate changes. Failed/truncated requests receive no repairs. Citation correction is a separate runner step. Missing fields, duplicates, unsupported claims, and substantive violations require separate review/attempts.

Open issues require null resolver/resolution. Resolved issues require an allowed resolver/explanation. E uses extractor identities; V preserves E IDs/origins, may reopen issues, and uses verifier identities for additions/fixes. Allow one linked issue per affected action. Removed/merged links need explanations. Curated copies permit expert resolutions; model answers exclude them.

### Collaboration (C)

The controller starts from the prepared plan without E/V or expert answers. Its runner/CLI accept comparison or dataset-building purpose under the same membership rules as E/V. Retries retain source and purpose. The purpose does not change the controller's source packet or model messages.

| Agent | Model/profile | Responsibility |
| --- | --- | --- |
| Coordinator | GLM-5.3-Flash; `glm5_3_flash_hf_coordinator` | Assign tasks, reconcile findings, maintain the draft, and produce the complete answer. |
| `worker_1` | Inkling 2 Small; `inkling2_small_hf_worker` | Extract, investigate, or verify according to the assignment. |
| `worker_2` | DeepSeek V4.1 Flash 1017; `deepseek_v4_1_flash_1017_hf_worker` | Extract, investigate, or verify according to the assignment. |

Both workers share [worker.md](prompts/worker.md); GLM uses [coordinator.md](prompts/coordinator.md). Tasks/findings may vary within the binding's fixed limits.

#### Input and contracts

`build_collaboration_input()` validates an explicit study preparation/PDF and snapshots source, collection, pages, fingerprint, binding, and profiles. It reads no baseline/expert files and makes no model/OCR calls or writes.

| Contract | Content and checks |
| --- | --- |
| Task | Python-assigned `task_id` and `draft_version`; `worker_id`, `objective`, `source_pages`, `expected_findings`, `independent`, and `context_task_ids`. Empty source pages means the whole plan; page hints do not remove full-source access. Context IDs must name completed tasks. |
| Worker result | Exact task/worker/version, `checked_pages`, and nonempty `findings`. Each finding has `description`, nullable `related_action_id` and `proposed_change`, `evidence`, and `unresolved`. A task-specific generation schema fixes identity/version and restricts links to null or the accepted IDs in that task's draft snapshot; a new candidate always has a null link. Python still checks identity, links, and physical pages. Reported coverage and evidence remain claims requiring review. |
| Complete C answer | Shared `plan_data`/`plan_issues` fields, with issue origins/resolvers restricted to `worker_1`, `worker_2`, or `coordinator`. Python checks IDs, issue links/statuses, page bounds, missing-evidence/type issues, and exact collection URL/date. Expert resolutions are excluded from model answers. |

Every agent receives full source text; each task has its own conversation. Independent tasks omit draft answers/prior findings; others get the current draft and selected completed results. C schema expansion never widens E/V identities.

#### Controller and execution

`run_collaboration_prototype()` requires an injected async model client and optional fingerprint-bound tools. It owns no files/MCP lifecycle and cannot start paid requests by default.

1. `assign_tasks` admits one task per worker, at most two per batch. Validate arguments/context/pages first. Delegation may accompany document tools; calls run in order. Workers can overlap, with both first/result requests reserved before dispatch.
2. Workers investigate, then return one strict task result with exact task/worker/version and allowed IDs. New candidates use null links. Validate JSON, links, and pages; prose/drafts cannot replace a failed result. Tool quotas persist across tasks.
3. `submit_draft` supplies a complete answer and `based_on_version`. Increment after acceptance. Reject stale versions, retired action-ID reuse, removed continuing issue IDs, and changed origins.
4. `finish_investigation` requires both contributions and a valid draft. One coordination tool is allowed per turn; submit/finish stand alone. Document-only batches remain valid.
5. Python disables tools for the reserved final answer. Both workers must have validated findings. Budget handoff may assemble the first complete answer without an intermediate draft; missing/failed required workers block completion. Record unsubmitted calls, draft version, and tasks.

Required worker/model/API failure, submitted timeout, or invalid result/final answer fails C. Stop new requests, preserving parallel evidence and original cause. Ordinary source/OCR problems may remain unresolved. No automatic retry, fallback, model substitution, or link repair occurs. `CollaborationResult` preserves requests, replies, tasks, drafts, events, budgets, and outcome/error; `CollaborationCancelled.result` retains cancellation evidence.

#### Saved C execution

`run_collaboration()` defaults to comparison and requires a prepared study plan, C binding, and `HF_TOKEN` before allocation. `--config-path` selects bindings; `--model-config-path` selects agents. Retries link a failed attempt using the same preparation and a new folder.

The wrapper snapshots inputs/code/environment, owns MCP, and checkpoints requests before dispatch, received chunks, usage/errors, and events. Close MCP before accepted publication. Time includes setup, overlapping work, cleanup, and checks.

<details>
<summary>C evidence paths</summary>

| Saved path within the C folder | Contents |
| --- | --- |
| `output.json` | Active/final status, fixed source/settings, actor/task/phase for each model attempt, observed usage, budget, stopping reason, and accepted answer only on success. |
| `responses/attempt_NNNN/` | Exact request, capacity estimate, HTTP status, immutable received chunks, raw response, and decoded answer text when available. |
| `artifacts/collaboration_input.json`, `artifacts/code/`, `artifacts/code_fingerprints.json` | Complete startup source/settings and implementation evidence. |
| `artifacts/events/`, `artifacts/controller_result.json` | Incremental events and final controller outcome, tasks, draft versions, and budget. |
| `artifacts/tool_requests/`, `artifacts/tool_results/`, `tool_log.json` | Document activity with agent identity; each request/result is immutable, and the active aggregate log is append-only. |
| `artifacts/mcp_catalogue.json`, `artifacts/mcp_stderr.log`, OCR files | Available document tools, subprocess diagnostics, and fresh source readings when requested. |
| `validation_report.json`, `artifacts/quotation_page_report.json` | Strict C final validation, conservative citation corrections, and remaining review flags. A corrected candidate is preserved separately in `responses/page_corrected_final.json`. |

</details>

C uses strict `collaboration_run.schema.json` and final-answer validation without E/V format repairs. Citation correction may create `responses/page_corrected_final.json`, then revalidate. Successful loading reconstructs the expected packet, preparation, and pages and compares JSON identities, preserving list order and value types. Missing/malformed saved input produces a validation error. Response/report links use the shared candidate/code checks above; completed-record protection and partial-save rules also apply.

#### Shared limits and reservations

Reserve GLM's full context for final generation. Before parallel dispatch, atomically reserve each worker's initial input/output estimate plus a full-context result request. Further investigation fits around all reserves.

Charge submitted requests their prepared UTF-8 estimate plus output allowance. Small/missing actual usage never refunds admission charges; unused worst-case reservation space releases when the prepared request consumes it. Request/token/tool/time limits never reset on delegation. Clip timeouts to phase time and retain actual provider usage separately.

#### Coordination diagnostic

<details>
<summary>Controlled-worker command, limits, and saved evidence</summary>

`uv run --locked python -m collaboration_check` uses GLM with controlled workers on a fictional two-page source. Check batched delegation, a wrong fountain count corrected by a worker, an unresolved budget conflict, both contributions, complete output, faithful quotations/pages, and unchanged code.

| Allowance | Diagnostic limit |
| --- | --- |
| Profile | `glm5_3_flash_hf_collaboration`; override with `--profile`. |
| Paid attempts | 8 coordinator requests; workers make none. |
| Output / request timeout | 16,384 tokens / 300 seconds. |
| Overall / protected final time | 900 / up to 300 seconds. |
| Logical request budget | Inherits the binding's current 25, including controlled-worker steps. |

Overrides preserve base agent settings. Controlled cards follow task order, not fixed specialties, and read no PDFs/OCR, baselines, or expert forms.

`artifacts/collaboration_checks/` preserves inputs, overrides/base settings, prompts, code/lockfiles/hashes, requests/replies, events/tasks/drafts, usage, and `report.json`. Controlled replies have no HTTP usage/status and mark `generation_started: false`. Saving/cancellation failure stops requests; abrupt termination can leave a partial report.

This tests interfaces, not live worker or full-plan quality. Historical outcomes remain in [CHANGELOG.md](CHANGELOG.md).

</details>

## 6. Expert review and dataset assembly

One PDF-coded reference serves all three configurations. Reference, assessment, and review records capture no names or study IDs.

### Expert reference creation — implemented

`create_expert_reference <plan_id>` requires a registered PDF; no preparation, model runs, or API access.

Copy checked title/URL/access date; other metadata starts null/empty except `English`. New forms contain instructions, `action_0001`, `issue_0001`, `TODO:` guidance, `unspecified` status, empty type/evidence, an open expert issue, and counters at 1. No model output is read.

`storage.save_new_expert_reference()` publishes canonical UTF-8 bytes, refusing occupied/redirected destinations and preserving existing files.

### Expert reference editing — implemented

`edit_expert_reference --plan-id <plan_id>` requires one operation:

| Flag | Operation |
| --- | --- |
| `--add-action`, `--add-issue` | Append a guided object with the next persistent ID. |
| `--remove-action [ID]`, `--remove-issue [ID]` | Remove the highest-ID untouched blank or an explicit record, including edited content. |

Action removal is blocked by issue links. Counters never decrease; retain them when coding manually. Older forms gain counters from current highest IDs, but previously deleted IDs cannot be recovered.

Editing checks PDF/collection, draft structure, IDs/links, and pages. `allow_templates=True` permits unfinished guidance only during editing. Compare original bytes before atomic replacement and reject intervening edits. Missing/malformed forms are not recreated; frozen forms reject edits. Use one writer; this is not a multi-writer lock.

### Expert reference validation — implemented

`validate_expert_reference <plan_id>` needs only the reference, registration, and original PDF. Verify bytes/checksum and count physical pages with strict pypdf. Reject unreadable, encrypted, empty, missing, or changed originals. A two-page spread is one physical page.

Strict JSON/source/field checks reject symlinks, duplicate IDs, invalid links/pages, and editable `TODO:` guidance. Issues use expert identities and at most one link per action. Empty types/evidence require a linked issue even if the issues container is absent; omitted `plan_issues` means an empty list without rewriting.

Validation performs no repairs and establishes no scientific completeness. Empty action lists can pass; experts assess grouping, support, quotations, and completeness.

### Expert reference freezing — implemented

`freeze_expert_reference <plan_id>` validates and publishes `reference_freeze.json` once. Record exact reference/PDF hashes, source/pages, UTC time, and readiness confirmation; recheck bytes before publication.

The freeze blocks edits/recreation, including when the reference disappears. Later validation verifies exact reference/source identities. Confirmation establishes assessment readiness, not accuracy, independence, or consistent final-run settings.

References use `data/comparison/expert_references/`. `migrate_data_layout` moves earlier source/reference directories; the older `storage.migrate_expert_references()` helper still handles top-level reference folders. Both preserve bytes and reject symlinks/occupied targets. Readers accept older same-plan freeze paths while checking current bytes; new freezes record the current path. Creation refuses unmigrated reference folders. Back up both reference and freeze.

### Assessment creation — implemented

`create_assessment <plan_id>` requires a frozen reference and compatible successful comparison E/V/C. Flags select `--extractor-run-id`, `--verifier-run-id`, `--collaboration-run-id`, `--notes`, and `--project-root`.

Defaults select highest-numbered eligible comparison E, latest linked V, and latest same-preparation C, skipping dataset-building runs. Explicit V alone supplies E. Known archived comparison labels remain eligible. Mismatches fail without fallback; latest E without V also fails. Number order defines recency. For final assessment, supply all three IDs from the manual log. Final settings, first-successful selection, and sample completeness remain manual checks.

Strict loaders check source/reference identities and exact record hashes. Create `assessment_NNNN/`, reserving occupied/interrupted numbers. Recheck before publication and publish metadata last; preserve incomplete folders without that marker.

| File | Copied context | Manual fields |
| --- | --- | --- |
| `metadata.json` | Input IDs/paths/fingerprints, notes, and instructions | Generated from command choices; no hand-edited judgments. |
| `action_scores.csv` | One reference activity per E/V/C output, description, and evidence | Matching output ID lists, 0/0.5/1 score, and reason. |
| `output_review.csv` | One candidate group per output record, IDs, description, and evidence | Confirm/regroup activities; enter support, evidence adequacy, and reasons. |
| `verifier_resolutions.csv` | Initially open E issues that V marks resolved by verifier, with descriptions and claimed resolution | Confirmation and reason. |

ID lists are JSON arrays in CSV cells. Confirm groups by combining splits/duplicates or separating bundles. Judgments begin blank; matching/scoring is never inferred. No eligible V claims yields a header-only table. Creation makes no model/OCR calls.

### Assessment validation — implemented

`validate_assessment <plan_id> --assessment-id <ID>` loads recorded IDs, never today's latest. Check sample membership, comparison-purpose inputs, reference, PDF/preparation, saved evidence, CSV structure/links, and hashes. The same input gate protects calculation and archived metric/report loading. Detect intervening changes and require a retry. Both default and explicit selections are pinned in metadata.

| Table | Checks |
| --- | --- |
| Reference scores | Exactly one row per reference activity/configuration; copied context intact; known output IDs; 0/0.5/1 only; omission `[]` requires zero. |
| Output review | Unique group IDs per configuration; nonempty known record lists; original linked evidence; full coverage before completion. One group may combine records, and several groups may link a bundle. |
| V resolutions | Exactly eligible claims, with copied context intact. |
| Consistency | Unsupported activities cannot have adequate evidence; explanations are required for completion. |

Blank fields, uncovered records, and `undetermined` stay pending. Valid partial review returns 0; invalid data returns 1. `--require-complete` also rejects pending review. Readiness is per table/configuration, without establishing scientific correctness or full-sample completeness.

The API returns parsed judgments and four file hashes, withholding usable data on errors. It writes/repairs nothing. CSVs accept reordered columns, UTF-8 byte-order marks, CRLF, and multiline cells.

### Manual expert assessment — pending

1. Code the PDF reference before viewing outputs where possible; record exposure, validate, and freeze.
2. Select compatible E/V/C, create the assessment, and match reference activities by meaning.
3. Enter scores/reasons and support/evidence judgments. Check the PDF before calling an activity outside the reference unsupported.
4. Confirm every concern in eligible V fixes; note independent C issues/disagreements.
5. Validate, settle review, and calculate. Check all ten final run selections; retain earlier judgments.

#### Worked scoring example

A fictional plan reports 100 trees planted in North Ward in 2025 and 200 planned for South Ward in 2027. The reference has one tree-planting action, type `nature-based`, retaining both phases and their associated details. Overall status is `unspecified` because no overall status is given.

| Score | Example output |
| --- | --- |
| 1 | Both phases, wards, quantities, dates, and statuses are correct; unstated fields use the defined missing values. |
| 0.5 | North Ward is correct but South Ward is omitted, or all 300 trees are described as already planted. |
| 0 | Tree planting is omitted or has no correct substantive description. |

### Measurement capture and calculation — implemented

`calculate_metrics <plan_id> --assessment-id <ID>` validates before [appendix G](DESIGN.md#g-evaluation-measures-and-calculations) arithmetic. Pure `summarize_assessment()` calculation is separate from publication.

| Measure | Calculation |
| --- | --- |
| Action score | Reference scores / reference activities × 100; retain distribution. |
| Unsupported activities | Count with total reviewed output activities. |
| Adequate evidence | Adequate output activities / reviewed activities × 100. |
| Issues | Open counts for all; confirmed/claimed eligible V fixes for E+V only. |
| Runtime/tokens | Selected successful E; E plus V; C wall time and each coordinator/worker call once. |
| Paired changes | E+V minus E and C minus E+V; percentages use percentage points. |

Preserve provider input/output components. Missing required observations invalidate their totals; an empty call list cannot establish zero usage. C duration is counted once without parallel-duration or budget-usage duplication. OCR adds time, not LLM tokens.

Each measure records value/status/reason/unit/numerator/denominator. States: `available`, `pending`, `unavailable`, `not_applicable`. Scores require settled matches/scores/reasons; group totals require coverage/support, and evidence requires adequacy. Zero-denominator percentages/no eligible V claims are not applicable with zero counts retained. Zero unsupported activities remains a valid count.

Each call writes a new `metrics_NNNN/` with JSON results, long-form CSV, four exact input copies, and code/schema/dependency snapshots. Retain hashes and full numeric precision; recheck inputs/code; publish `results.json` last. Reserve interrupted numbers and preserve partial evidence.

Metrics use comparison and preserve exact assessment metadata/review files. Per-plan CSVs contain 44 measure rows. Partial reviews can yield partial metrics; use `--require-complete` for settled final review, while permitting unavailable resource observations. No model/OCR calls run. Failure counts are omitted; resource totals cover selected successful runs, excluding earlier attempts.

### Cross-plan summaries — implemented

`summarize_metrics --result <metrics_folder>` accepts project-relative folders or `results.json`; repeat once per plan, with at least one. Reject duplicates, unsupported records, and incompatible calculation methods. New summaries use comparison and preserve exact selected result copies. No latest-result default.

`load_metric_snapshot()` checks strict JSON, canonical paths/identities, archive/code/CSV hashes, and required files. Revalidate archived judgments against reference/source/run evidence, ignoring later live CSV edits. Recompute the supported method and compare measures, review state, metadata, and CSV. Never execute archived code.

| Aggregate | Rule |
| --- | --- |
| Percentages | Equal-weight mean of available per-plan percentages; activity denominators stay in per-plan rows. |
| Paired changes | Mean of eligible within-plan changes for each contrast/measure. |
| Counts/resources | Labelled totals by configuration over available plans, with applicable denominators. |
| V confirmations | Sum confirmed/claimed counts over the same eligible plans; no-claim plans contribute known zeros. |

Each aggregate records method, unit/status, contributing plan count/IDs, and excluded IDs/statuses/reasons. Measures may use different plans. Never replace pending/missing values with zero. Pilots may use subsets; manually select all ten consistent final calculations for study reporting.

Write a new `data/comparison/reports/summary_NNNN/` with JSON, per-plan/aggregate CSV, selected result copies, and current code. Record package hashes; preserve source packages for full archive evidence. Recheck packages/source/code, publish `summary.json` last, and retain interrupted folders/reserved IDs. Preserve existing reports. No model/OCR calls run.

### Post-study plan review — implemented

Review uses separate draft, completion-record, and clean-plan contracts. `validate_curated_dataset()` remains a lower-level answer check supporting expert resolutions. Model answers retain their E/V or C identities and exclude expert fixes.

After choosing a configuration, rerun original comparison plans and later expansion plans with `--purpose dataset_building`. Saved runs stay under `runs/<plan_id>/`; drafts/completed reviews use `data/dataset_building/`.

`create_review_draft <plan_id> --configuration {E,E+V,C} [--run-id <ID>]` copies one validated successful dataset-building answer. Omitted IDs select the highest-numbered eligible run; invalid explicit IDs fail without fallback. E+V checks its linked E. Record the collection configuration/version manually; draft creation does not impose a collection-wide choice.

Each new `review_NNNN/` contains `review_draft.json` and the exact `source_run.json`. IDs are reserved across draft/completed roots, including interrupted folders. Source metadata/fingerprints and original issues are checked against the saved run; no model/OCR calls or factual judgments run.

`validate_review_draft <plan_id> --review-id <ID>` checks schema/JSON, fixed source, action fields/pages, issue history, missing type/evidence explanations, and unfinished guidance. `_check_draft()` separates those phases; `_validate_issue_history()` retains every original issue's ID/origin/description/type. Open issues require expert resolutions; model-resolved decisions stay unchanged. Additional issues use expert origin. Links may change after merges/removals, and several original concerns may link to one surviving action. Validation is read-only; valid drafts can remain pending, while `--require-complete` requires no open issues.

`finalize_reviewed_plan <plan_id> --review-id <ID>` requires every issue addressed and records `review_scope: open_issues_only`. It validates the complete draft before stripping issues, then saves clean `reviewed_plan.json`, exact draft/run copies, and a separate `review_record.json`. The record identifies expert-addressed and model-resolved issues, source/draft/product fingerprints, and completion time; it captures no names. Empty type/evidence may retain a documented source limitation in that sidecar. This does not establish a full audit of source support or omissions.

Use one writer during creation/finalization. Publish the completion record last after rechecking inputs and saved files. Preserve completed outputs; further work starts a new draft. Interrupted finalization resumes only when existing files match the same reviewed bytes. A folder without its completion record is ineligible for assembly.

`load_completed_review()` checks the four-file snapshot and rereads bytes to detect intervening edits. It returns parsed data/history/source and exact checked bytes for live reviews or archived dataset inputs. `load_reviewed_plan()` exposes data/history through that shared loader. Both are independent of later original-draft edits; original source runs/evidence remain required.

`validate_reviewed_plan <plan_id> --review-id <ID>` exposes the completed-plan loader through the CLI. It reports pass/failure, configuration, action count, and scope without modifying files or creating a version. These checks already run during finalization and assembly.

### Combined action datasets — implemented

`build_heat_action_dataset --review <completed_review_folder>` accepts project-relative folders or their `reviewed_plan.json`; repeat once per plan. Require explicit completed review versions, with no latest default. Accept comparison and expansion plans through their dataset-building runs. Reject duplicate plan IDs or original PDF fingerprints before publication.

Load each four-file completed review through `load_completed_review()`. Require one common configuration and workflow definition. Version 1 compares saved settings (model/provider, ordered prompt text/paths, generation, tools, budgets, and timeouts), recorded software-version fields, and archived execution-code hashes. E+V includes its exact E and V; C includes all profiles/shared limits. Source text, run IDs, timings, usage, Git commit/dirty, hardware, and loaded-state observations remain preserved but do not define compatibility. Unknown hosted revisions remain unverified.

Write a new `dataset_NNNN/`, preserving occupied/interrupted numbers. `heat_action_dataset.json` contains `schema_version: 1` and `plans`, each with `plan_id`, `metadata`, and `actions`; action IDs remain local. `dataset_contents.json` records exact review paths/IDs, run IDs, four-file fingerprints, common workflow/definition fingerprint, counts, UTC build time, and assembly-code fingerprints. Review evidence stays in `inputs/<plan_id>/<review_id>/`; assembly source/contracts/dependency files use `artifacts/code/`.

Use one writer. Recheck selected inputs, execution workflow, and current assembly code before/after copying. Validate copied reviews, data, counts, and archived code; publish `dataset_contents.json` last. Failed folders are incomplete and preserved; another build allocates a new version. New selections never overwrite earlier datasets.

`load_heat_action_dataset()` checks package identity, archived reviews, compatibility/order, clean data/counts, and code hashes in separate phases. It regenerates expected data from archived reviews without executing archived code. Later live-review edits do not affect the saved package; original model runs/source evidence remain required.

`validate_heat_action_dataset <dataset_id>` exposes that loader through the CLI. It rechecks an existing numbered version without editing or rebuilding it. Both completed-output validators return 0 on success or 1 on invalid/missing evidence and make no model/OCR calls. Scope stays `open_issues_only`; assembly adds no scientific judgments. Instruction export and fine-tuning remain deferred.

## 7. Study checkpoint and next steps

### Current checkpoint

All three configurations have completed early live runs on both plans. These reviewed outputs used earlier settings and are not the final study set or a live test of the current budgets.

<details>
<summary>Earlier live outputs and preliminary observations</summary>

| Plan | Reviewed E → V | Reviewed C | Preliminary observations |
| --- | --- | --- | --- |
| Freetown (`plan_0001`) | `run_extract_0008` → `run_verify_0002` | `run_collaboration_0005` | All contain 14 action records. C completed follow-up checks using 21 requests in 28m59s. Source/citation gaps remain; the E/V pair predates later prompts and automatic citation processing. |
| Paris (`plan_0002`) | `run_extract_0002` → `run_verify_0006` | `run_collaboration_0002` | E/V contain 36/38 records; C contains 77. C completed four worker tasks using 21 requests in 38m36s. Review found useful distinctions alongside unnecessary splitting, missed activities/details, and uncertain eligibility. |

Paris V matched 100 of 130 quotations against available text and flagged 30; C matched 64 of 149 and flagged 85. Neither made a citation correction. Most C flags aligned after relaxing spacing or typographic punctuation in a read-only investigation; the saved matcher and outputs were unchanged. These are location/fidelity diagnostics, not evidence-adequacy scores or proof that one workflow is better.

</details>

The core software path, including completed-output validation, is implemented. Current guidance, budgets, timeout handling, and saved-evidence checks passed offline tests; fresh live checks remain pending. Both registered plans belong to the comparison sample, and the existing reference is an unfrozen guided starter. Eight additional plans, complete final run selections, expert assessment, and real dataset building remain. [CHANGELOG.md](CHANGELOG.md) records test results, failures, and revisions.

### Next steps

Remaining work is real-plan execution and expert judgment. Pilots may identify further software or prompt fixes.

| Step | Remaining work |
| --- | --- |
| Pilot review | Complete/validate/freeze initial references; test activity grouping, scoring, evidence judgments, V resolutions, and disagreements. |
| Complete study | Add/prepare eight plans, check current E/V/C, fix final versions, and run all ten under the full-rerun rule. Maintain the manual run log. |
| Assess and report | Complete judgments, validate, calculate, and summarize all ten plans. Check sample/versions manually and choose one configuration. |
| Build dataset | Rerun that configuration with dataset-building purpose; pilot open-issue review, finalization, both completed-output validators, and combined assembly on real plans. |
| Later training | Instruction export and fine-tuning follow dataset assembly. |

## Appendix: supporting JSON files

Existing workflow fields are defined in the [JSON contract map](#json-contracts). The expert reference format is defined by [expert_reference.schema.json](schemas/expert_reference.schema.json), which reuses the existing plan data schema.

<details>
<summary>Reference, freeze, and assessment field tables</summary>

### Expert reference form

Use `data/comparison/expert_references/<plan_id>/expert_reference.json` for the expert's PDF-coded reference shared by all three outputs. Complete it before viewing outputs where possible and record prior exposure. Initial forms can serve the final comparison after review and freezing.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer, fixed at 1 | Reference form format version. |
| `plan_id` | string | Registered document. |
| `id_counters` | object; optional | Nonnegative integer `action` and `issue` counters retaining the highest numbered IDs allocated or observed by the editor. Removal never lowers them. |
| `plan_data` | object | Plan metadata, grouped actions, and evidence using the existing plan data fields. |
| `instructions` | list of strings; optional | Editing guidance supplied in new forms, outside coded content. |
| `plan_issues` | object; optional | Expert concerns in `issues`, using the shared issue fields with `expert` origin and `expert` or null resolver. |

New forms include instructions, issues, and counters. Older version 1 forms remain readable under the same evidence/type checks. Reference issue IDs are independent of model issues. Validation checks are defined [above](#expert-reference-validation--implemented); experts establish source support and completeness.

### Expert reference freeze

`data/comparison/expert_references/<plan_id>/reference_freeze.json` follows [expert_reference_freeze.schema.json](schemas/expert_reference_freeze.schema.json). All fields are required.

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
| `confirmed_complete` | boolean, fixed at true | Recorded readiness confirmation, not a software finding of completeness. |

### Manual assessment

Experts compare saved E, E+V, and C outputs with the same frozen reference. CSV review tables hold matches, scores, support/evidence judgments, V-resolution checks, and reasons. C's collaboration and issue handling are described in review notes. Generated metadata follows [assessment_metadata.schema.json](schemas/assessment_metadata.schema.json); manual judgments are not entered in JSON.

| Metadata field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer, fixed at 2 | Current assessment metadata version. |
| `assessment_id` | string | Numbered assessment folder identity. |
| `plan_id` | string | Registered study plan. |
| `created_at` | UTC timestamp string | Creation time. |
| `notes` | string or null | Optional review context. |
| `reference` | object | Current reference/freeze paths and exact file fingerprints. |
| `source` | object | Preparation path, source fingerprint, original PDF fingerprint, and physical page count. |
| `runs` | object | E, E+V, and C run IDs, record paths/fingerprints, and selection method. |
| `instructions` | list of strings | CSV editing guidance and pending-value rules. |

</details>
