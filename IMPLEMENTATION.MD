# Implementation Doc: Heat Adaptation LLM Dataset

**Technical implementation · updated 2026-11-14**

This document specifies how to implement the study in [DESIGN.md](DESIGN.md). It covers document preparation, extraction, verification, expert assessment, analysis, and instruction examples. DESIGN.md defines the research protocol, coding rules, and evaluation formulas. This document defines software responsibilities, files, execution rules, and remaining work. [README.md](README.md) describes available commands.

## 1. Purpose and research requirements

The pipeline supports iterative work between heat adaptation experts and LLMs. Preserved examples of model outputs, expert judgments, revisions, and observed outcomes will support practical lessons about building the workflow. It also supports a paired comparison of extraction alone (E) with that same extraction revised by a different model (E+V). Software validates structure and execution, while experts assess source meaning, correctness, and evidence.

| Research need | Implementation requirement |
| --- | --- |
| Explain how the workflow was built | Preserve examples linking expert judgments and model outputs to decisions, revisions, failures, and lessons learned. |
| Trace claims | Preserve PDFs, selected page text, quotations, page references, and additional OCR readings. |
| Compare paired outputs | Link V to the exact successful E run and source, with frozen settings and retained failures. |
| Protect expert reference preparation | Hide model outputs until the independent initial reference has been completed and validated. |
| Reproduce analysis | Validate completed assessments and calculate the agreed measures from explicitly selected files. |
| Build instruction examples | Pair task instructions and sufficient source input with expert-curated answers. |

| Component | Status |
| --- | --- |
| Registration, preparation, and saved local extraction | Implemented. |
| Action and issue formats | Planned migration. Current prompts, schemas, validation, and saved runs use five content lists and the earlier issue field names. |
| Verifier | Planned, including compatibility work for a different model. |
| Expert files, measures, and instruction export | Planned using the streamlined evaluation in DESIGN.md. |

The target answer contains `content.plan_info`, `content.plan_actions`, and `review.issues`. Each action groups one specific activity across the plan, including its different neighborhoods and phases. New work follows the nine action fields, [category definitions](DESIGN.md#e-category-definitions), and [coding rules](DESIGN.md#f-action-coding-rules).

Each issue uses `issue_id`, `related_action_id`, `issue_description`, `issue_type`, `issue_origin`, `issue_status`, `resolved_by`, and `resolution`, as defined in [DESIGN.md appendix D](DESIGN.md#d-review-and-issues). The shared target format permits `resolved_by` values of `extractor`, `verifier`, or `expert`, with role checks for model outputs and expert-curated copies.

## 2. System architecture and responsibilities

Python controls file identity, execution, validation, measurements, and saving. Models interpret source material and request document tools. Experts prepare references, assess outputs, and curate answers.

| Module | Responsibility and status |
| --- | --- |
| `src/cli.py` | Implemented `add`, `update`, `prepare`, `extract`, and `list`; explicit input selection, allowed diagnostics, and cancellation. Later commands are planned. |
| `src/documents.py` | Registration, metadata updates, duplicate checks, page preparation, and preparation status. |
| `src/agents.py` | Profiles/prompts, complete input, extractor loop, MCP client, source checks, environment observations, and saved execution. Verifier integration is planned. |
| `src/models.py` | Local Ollama text/tool requests, compatible response schemas, token counting, completion metadata, and raw response evidence. |
| `src/document_tools.py` | Rendering, image inspection, cropping, OCR, and the selected-source MCP server. |
| `src/validation.py` | JSON syntax, types, values, references, page ranges, source consistency, and run contracts. Expert coverage checks are planned. |
| `src/repair.py` | Only the permitted formatting repairs described below. |
| `src/storage.py` | IDs, preserved inputs, run records, supporting files, and saved status. |
| `src/expert_files.py` — planned | Reference and assessment templates, completed-file validation/import, and stage prerequisites. |
| `src/metrics.py` — planned | Shared calculations and exports for the CLI and analysis notebooks. |

The agent runner starts `document_tools.py` as a local MCP subprocess, communicating through standard input/output. Separately, `models.py` sends HTTP requests to Ollama. Python passes model-requested tool calls to MCP and returns the results to the model.

The MCP SDK derives tool definitions from function descriptions and types. Python converts them to Ollama's format and validates arguments. Tools operate on the selected source through page numbers and quotations. Treat document text and tool results as source evidence. Keep expert files outside agent inputs and tool access.

## 3. Document collection and preparation

The workflow accepts plans from governments or public agencies screened against the [study's eligibility criteria](DESIGN.md#eligible-plans).

Registration saves `data/raw/<plan_id>.pdf` and its SHA-256 checksum, a fingerprint of the bytes. Identical PDFs reuse a document ID, while revised PDFs receive a new ID.

`update` validates and changes explicitly supplied collection metadata. Development assignments are fixed, and other study-set changes are allowed only before saved model work. Each preparation copies the current source URL and access date so completed work retains its collection context.

### Prepare text automatically, investigate gaps with tools

Preparation first extracts native text with pypdf. A PDFium renderer supplies page images, including when native reading fails. Missing or unreliable text receives full-page OCR when enabled. Known blank pages retain that status.

Also screen images on pages with native text. An individual image is a candidate if it occupies at least 10% of the visible page and contains no native text within its bounds. Save full-page PNGs and candidate crops. Append labeled regional OCR while preserving native text, and mark the combined source `mixed`.

The current backend uses cached English EasyOCR models on the CPU and renders at 150 dots per inch (DPI). Setup downloads models explicitly, while normal operation loads them offline when needed. `--no-ocr` retains image screening and preservation. The screening rule can include photographs and miss small charts or partial text layers. Table reading order and OCR accuracy require source review.

| Preparation status | Meaning |
| --- | --- |
| `ready` | Automatic checks found no problems or review flags. Source accuracy still requires assessment. |
| `ready_with_gaps` | Every page has a usable reading route, with review notes for gaps or recovered OCR. |
| `failed` | Page counting or a required reading route failed and requires attention before extraction. |

Each preparation receives a new folder. Save images and page data before publishing `preparation.json`. Include every known PDF page once, in order, and validate linked PNGs and crop dimensions when loading. If page counting fails, save a null count and empty page list where possible.

New preparations use version 3 with image paths, regions, and mixed text. Loading also supports version 2 using its original fields. Derive status from the preparation explicitly linked by the registry.

### OCR evidence and source gaps

OCR converts image text into machine-readable text and can misread words or numbers. Experts check quotations against the original PDF, including table or chart context. Record unreadable material as a source gap. Evidence quotations must reproduce source wording.

### Document tools

| Tool | Current behavior |
| --- | --- |
| `get_page_text(page_number)` | Return exact selected preparation text and notes, preserving blank/unavailable and native/OCR/mixed distinctions. |
| `find_quote(quote)` | Exact, case-sensitive substring search within each initial page. Report matches and unavailable pages separately. No normalization or cross-page joining. |
| `run_ocr(page_number)` | Render the original page and return fresh OCR using the active run's frozen settings, with preserved artifacts and source identity. |

The server checks PDF identity and preparation/page fingerprints at startup. OCR runs sequentially using the frozen settings and a reused reader. Each request saves separate artifacts, while `find_quote` searches the original preparation text only. Literal matching locates wording and requires subsequent assessment of claim support.

Reading errors can be returned to the model for further investigation. Timeouts, protocol failures, or failures to save evidence stop the run. Full-page tool OCR and preparation-time regional OCR are implemented. Direct model image delivery and tool-requested regional OCR are planned extensions.

## 4. Model configuration and execution

### Models and profiles

The current development profile is `qwen35_27b_extractor_development`, using local `qwen3.5:27b` at `http://localhost:11434` through the safetensors/MLX serving setup. The recorded development machine is an Apple M5 Pro with 64 GB memory. Runs record observed hardware and software.

`gemma4:31b` is an untested verifier candidate. The current token checker explicitly supports only the validated Qwen model, runtime versions, and tokenizer assets. A second model therefore needs request, structured-output, tool-use, and token-accounting checks as well as its profile and prompt. Test and load the models sequentially before fixing the comparison pair.

| Setting | Current development value |
| --- | --- |
| Context limit | 73,728 tokens. |
| Output reservation | 16,384 tokens, including model thinking where applicable. |
| Capacity for all input | 57,344 tokens shared by instructions, source, tools, and history. |
| Complete model-request timeout | 1,800 seconds. |
| Submitted document tool calls | At most 10, including failed submitted calls. |
| Shared OCR and rendering | EasyOCR, English, CPU, cached models; 150 DPI. |
| Complete tool-request timeout | 120 seconds. |
| Direct image input | Disabled. |
| Temperature, top-p, seed | Null, using model defaults. Record this choice when reporting variability. |

`configs/profiles.json` contains shared `document_tools` and named `profiles`. Select a profile and stage explicitly, then save the selected values and ordered prompt texts at startup. Both stages use the same document tool settings. Hosted-provider support is deferred.

### Prompts, response schema, and token budgeting

The ordered extractor prompt files are `shared_coding.md`, `field_definitions.md`, and `extractor.md`. They currently contain five-category instructions and the earlier issue field names. Migration must update the prompts, schemas, validation, and fixtures together.

The target prompts require reading the complete plan, grouping by specific activity, retaining all neighborhood and phase details, applying the nine fields, and flagging unresolved problems. For mixed phase statuses without an overall source status, use `unspecified` and retain each phase's status in `action`. Keep costs and benefits attached to their stated locations or phases.

`build_extractor_input()` reads the exact selected preparation and checks PDF identity, readiness, pages, and images. It assembles input without running a model or OCR. Join exact prompt texts with two newlines in one system message. Place collection metadata, physical page boundaries, preparation notes, and all page text in a user message. The controller adds investigation and final-answer instructions.

For final generation, send messages in `messages` and the compatible JSON Schema in `format`. During investigation, expose `tools` and apply the tool-selection protocol. `prepare_ollama_response_schema()` derives the provider schema from authoritative local schemas, expands references, and converts the nonblank-string pattern to its tested equivalent. Save the exact sent schema and reject unsupported conversions. The request interface is described in the [Ollama chat API](https://docs.ollama.com/api/chat).

#### Before every model request

1. Render the complete request with the validated Ollama render-only facility, which returns the prompt without generating an answer.
2. Count it with the matching installed tokenizer, the software that converts text into token IDs. Verify runtime version, model identity, and tokenizer fingerprints.
3. Require `input_tokens + max_output_tokens <= context_limit`.
4. Save preflight evidence, then generate within the same complete-request timeout.
5. Compare counted input with provider-reported input when available; a known disagreement fails the run.

Count instructions, source, metadata, chat markers, tools, assistant prefix, and accumulated history. Disable tokenizer truncation and padding and avoid adding tokens already supplied by rendering. Resend the complete history on each request.

The implemented counting path supports local Qwen3.5 safetensors/MLX with Ollama 0.40.14 or 0.40.16 and validated tokenizer assets. Validate changes to this private render-only interface before enabling them. Counting reads installed assets. The versioned [API definitions](https://github.com/ollama/ollama/blob/v0.40.14/api/types.go), [Qwen renderer](https://github.com/ollama/ollama/blob/v0.40.14/model/renderers/qwen35.go), and [chat implementation](https://github.com/ollama/ollama/blob/v0.40.14/server/routes.go) document the tested behavior.

Use the same request body for rendering and generation. On the tested path, schema constraints apply separately from prompt rendering. Count schema text when explicitly included in messages. Direct image counting is unsupported.

Stop before generation if capacity is exceeded or reliable counting is unavailable. Preserve the whole-document input and selected output reservation. Save counts, remaining capacity, request/prompt checksums, runtime/model/tokenizer identities, errors, and preflight HTTP bodies. Research token totals use provider-reported generation usage. Metadata and render-only operations are setup activity.

### Extractor control

1. Assemble the complete source and prompts and discover the source-bound MCP tools.
2. Count and send a tool-phase request. Accept validated tool calls or `READY_FOR_FINAL_RESPONSE` with optional outer whitespace. Other control text or premature final JSON fails the attempt.
3. Execute tools sequentially and preserve the full assistant message and ordered results, including thinking and call identifiers where supplied.
4. Continue until readiness or the tool-call limit. Each submitted call consumes a slot, including failures. Startup/catalogue discovery does not. Excess calls receive logged non-execution errors.
5. Clear tools and request one complete schema-constrained `content`/`review` answer.
6. Check completion and output, apply only permitted repairs, recheck source/collection details and application snapshots, and stop the MCP subprocess before accepting success.

The loop returns execution evidence, and the saved wrapper publishes checkpoints and final status. Count the readiness signal as a generation call. Preserve call/result ordering because the tested renderer omits tool-result names and identifiers from rendered text.

The two-phase approach followed a synthetic development example in which imposing the final schema suppressed a needed tool request. Later fixtures worked with separate phases. Test this behavior for the chosen verifier.

### Verifier control — planned

1. Select the exact successful action-focused E run and load its saved preparation, answer, and issues. Check its preserved source fingerprint against the loaded text.
2. Load a different model with validated request, token-counting, schema, and tool support. Copy the shared document tool settings from the selected E run.
3. Supply the whole source, shared coding rules, saved E answer, and a verifier-specific task. Check all action fields, unflagged content, possible omissions, grouping, and source evidence.
4. Use a bounded investigation phase and return a complete revised `content`/`review` dataset. Preserve continuing action IDs and allocate new IDs for new activities.
5. Retain every existing `issue_id` and `issue_origin`. Add new issues as needed. An initially open issue resolved by V has `issue_status` set to `resolved`, `resolved_by` set to `verifier`, and a `resolution` addressing all grouped concerns. When removing or merging actions, update `related_action_id` and explain retired targets in `issue_description` where a link becomes null.
6. Save a separate verifier run with `input_run_id` pointing to E. Validate source identity, tool settings, issue continuity, output structure, and successful publication. A failed V attempt links a V retry to the same E run.

Finalize the verifier prompt and compatibility checks during development, then freeze them with the comparison settings.

## 5. Run records and reproducibility

The appendix defines the fields in the [saved run](#saved-run), [saved settings](#saved-settings-and-nested-objects), and [model-call entries](#model-call-entry).

### Saved extractor execution

The saved wrapper freezes inputs and settings, observes hardware/software and Git state, allocates a run folder, and publishes `output.json` as `running`. Check whether the model is loaded before preflight can load it. Preserve reported quantization, raw metadata responses, and observation errors. Use null for unavailable optional observations.

Save evidence at execution checkpoints.

| Evidence | Saved location within the run |
| --- | --- |
| Frozen input, source fingerprint, and discovered tools | `artifacts/extractor_input.json`, `artifacts/mcp_catalogue.json`. |
| Application code, schemas, and dependency files with SHA-256 manifest | `artifacts/code/`, `artifacts/code_fingerprints.json`. |
| Startup model observations | `artifacts/environment/`. |
| Exact request before dispatch, token reports, and preflight bodies | `responses/attempt_NN/request.json`, `token_budget.json`, `token_budget_final.json`, and `preflight/` in that attempt folder. |
| Received response chunks, raw HTTP body, and assistant text/message | `responses/attempt_NN/chunks/`, `responses/response_NN.json`, `responses/response_NN.txt`, and `responses/attempt_NN/assistant_message.json`, when available. |
| Pending tool requests and completed ordered tool activity | `artifacts/tool_requests/`, `tool_log.json`. |
| Fresh page OCR | `artifacts/ocr/request_NNNN/` containing `request.json`, `page.png`, `ocr.txt`, and `result.json`, as available. |
| MCP subprocess stderr and complete message history | `artifacts/mcp_stderr.log`, `artifacts/conversation.json`. |
| Final checks and any repaired candidate | `validation_report.json`, `responses/repaired_final.txt` when a repair is applied. |

Save received HTTP bodies after content decoding and assistant text separately. OCR reports include source/page identity, actual settings and versions, timestamps, duration, hashes, and errors. Publish MCP stderr after subprocess shutdown when available.

Accepted `content` and `review` require a valid final answer and successful saving. Failures retain available evidence with null accepted output. Record observed UTC times and measured elapsed duration through setup, execution, saving, checks, and cleanup. Distinguish blocked preflight from generation attempts, and retain null for undisclosed usage.

Preserve supporting files individually. A checkpoint failure stops execution and triggers best-effort failed finalization. If final publication fails, return the last successfully saved record and persistence error. Report success from the saved record.

### Selecting runs, failures, and feedback

Process one plan at a time. `extract` requires a plan ID, exact `--source-path`, `--profile`, and `--purpose`. Optional `--config-path` selects another profile file. Development/comparison purposes must match the registry, and formal comparison requires observed, clean committed code.

Each invocation receives a new run ID. Link manual retries with `--retry-of-run-id`. Select the first successful run under fixed settings, retain failures, and label deliberate successful repeats exploratory. The implemented workflow uses explicit preparation selection and manual retries.

`list` displays registration and linked preparation status, while `extract` reports saved run status and report paths. Model/tool timeouts and reported truncation fail the attempt. Extraction returns 0 for saved success, 1 for failure, 2 for invalid syntax, and 130 for cancellation.

Abrupt termination or failed publication can leave `running` and partial files. Confirm process termination before recovery and retain unavailable end times/durations as null. Recovery and resumption are manual.

The current CLI hides claims, issues, snippets, and repair details for all comparison-plan extractions, including exploratory repeats. Validated expert-reference handling must be implemented before enabling output disclosure. The restriction controls display, and research files remain accessible on disk. If troubleshooting exposes model outputs, assign initial reference preparation to an unexposed expert.

### Validation and permitted repair

Check completion before repairing JSON. Classify errors as `syntax`, `structure`, `reference`, or `other`, retaining location and explanation. Truncation fails the attempt.

| Case | Permitted behavior |
| --- | --- |
| Whole-response code fence | Remove only when it encloses one complete JSON answer without surrounding commentary. |
| Trailing comma | Remove immediately before a closing bracket/brace, outside quoted text. |
| Missing closing delimiters | Append after a complete value only when nesting is unambiguous and normal completion is confirmed. |
| Single page number | Convert a positive integer to a one-item `page_numbers` list, then validate range. |
| Missing field or other error | Preserve the answer and report the problem for a separately initiated attempt. |

Save the raw answer and repaired candidate separately, then repeat all checks. Limit repairs to the four formatting cases above. Any remaining error fails the run. Repairs belong to the same run and require no additional generation. Source interpretation and correctness are expert judgments.

Planned issue validation will check the renamed fields, unique IDs, valid `related_action_id` links, and one linked issue per affected action. An open `issue_status` requires null `resolved_by` and `resolution`. A resolved issue requires a permitted resolver and a nonblank explanation. Extractor answers use `extractor` as `issue_origin` and as the resolver of any issue they resolve. Verification retains existing origins and can retain or reopen earlier issues. New verifier issues use `issue_origin` set to `verifier`, and a resolution made during verification uses `resolved_by` set to `verifier`. The value `expert` is permitted for resolutions in expert-curated copies. Model output validation will reject claims that an expert resolved an issue.

### Files and identifiers

| Path | Purpose |
| --- | --- |
| `src/`, `tests/` | Shared implementation and automated checks. |
| `configs/profiles.json`, `prompts/`, `schemas/` | Runtime choices, interpretation instructions, and machine-readable contracts. |
| `pyproject.toml`, `uv.lock`, `.python-version` | Project setup, locked dependencies, and Python selection. |
| `data/registry/plans.json` | Registered document versions and collection metadata. |
| `data/raw/<plan_id>.pdf` | Preserved original document. |
| `data/processed/<plan_id>/preparation_NN/` | `preparation.json`, `pages.json`, and saved `images/`. |
| `runs/<plan_id>/run_extract_NNNN/` | `output.json`, responses, artifacts, tool log, and validation report. |
| `runs/<plan_id>/run_verify_NNNN/` — planned | Corresponding complete verifier run and evidence. |
| `runs/<plan_id>/drafts/` — planned | Editable expert templates. |
| `runs/<plan_id>/reference_initial.json`, `reference_final.json` — planned | Independent initial and shared revised references. |
| `runs/<plan_id>/assessment_e.json`, `assessment_ev.json` — planned | Expert judgments for the explicitly selected pair. |
| `runs/analysis/`, `notebooks/` — planned | Calculated results and analysis notebooks using shared calculation code. |
| `artifacts/` | Local diagnostic evidence and historical handoffs. |
| `.cache/easyocr/`, `.venv/` | Local OCR models and Python environment. |

`plan_id` identifies a document version and `run_id` identifies an execution. Action and issue IDs are local to linked outputs. Preserve continuing IDs through verification and expert curation, and use new IDs for additions. For removed actions, set `related_action_id` to null and identify the target in `issue_description`. An issue concerning several actions links one and names the others in that description.

Expert references use the shared content schema in separate files. Track code, tests, dependencies, schemas, prompts, profiles, registry metadata, and project documents in Git. Back up ignored PDFs, prepared text, runs, model assets, and diagnostic artifacts separately. `AGENTS.md` and credentials stay local, and Ollama manages weights outside the repository.

## 6. Expert assessment, analysis, and dataset assembly

These stages are planned. Implement the three quality measures, two issue measures, and supporting execution information in [DESIGN.md appendix G](DESIGN.md#g-evaluation-measures-and-calculations). The appendix below defines the required expert-file fields.

### Expert files and measurement

1. **Prepare the independent reference.** Require successful E and E+V runs linked to the same extraction and preparation. Generate a template with collection metadata and empty content fields. Experts complete it from the original PDF using the rules for grouping activities, then validate and preserve it before revealing model outputs.
2. **Reconcile the reference.** Experts inspect both outputs for supported activities or details missing from the initial reference. Record accepted corrections in one shared final reference with source evidence and reasons. Retain the independent initial file.
3. **Score reference activities.** For each output, match its content to every final reference activity and assign 0, 0.5, or 1 with an explanation. Combine split or duplicate records during assessment and retain conflicting claims when scoring.
4. **Assess output activities.** Group each output's content by specific activity. For every group, record its raw record IDs, source support, final-reference link when supported, and one evidence judgment. Check all supplied quotations, physical pages, and coverage of the recorded details against the original PDF. Explain failures in the group judgment.
5. **Check claimed issue resolutions.** Select issues with `issue_status` set to `open` in E and set to `resolved` with `resolved_by` set to `verifier` in the saved E+V output. Record whether source review confirms that all grouped concerns were addressed. E assessments have an empty resolution-check list. A later expert fix is recorded during curation.
6. **Complete and preserve assessments.** Record assessors and relevant review notes. Require coverage of every reference activity, every output activity, and every claimed initial resolution. Save revisions as new named files, and use explicitly selected completed files for analysis.

An output record can contribute to several activity groups if it bundles distinct activities. An invented activity or one outside the heat adaptation inclusion rules is unsupported and has no final-reference link. Wrong details within a supported activity affect its action score and evidence judgment. Source-support judgments of `undetermined` and null scores remain pending.

During the development pilot, record reviewer numbers, expertise, and roles, and settle how disagreements are resolved. The combined evidence judgment reduces form-filling while still requiring source inspection. Review notes capture useful examples of quotation errors, citation errors, omissions, false flags, and justified or unjustified resolutions.

#### Worked scoring example

For a fictional example, a heat adaptation section reports 100 trees planted in North Ward in 2025 and another 200 planned for South Ward in 2027. The reference contains one action for tree planting, classified as nature-based, with both wards and their associated quantities, dates, and phase statuses. Its overall status is `unspecified` because the source supplies differing phase statuses without an overall status.

| Score | Example output |
| --- | --- |
| 1 | Both planting phases, their wards, quantities, dates, and statuses are recorded correctly, with the defined missing values for unstated fields. |
| 0.5 | The North Ward planting is recorded correctly but South Ward is omitted, or all 300 trees are incorrectly described as already planted. |
| 0 | Tree planting is omitted, or the description contains no correct substantive information about that activity. |

### Measurement capture and calculation

`metrics.py` will calculate all measures from validated selected files. Before expert assessment, it can calculate open issues, runtime, provider-reported tokens, and failed-run counts. After assessment, it adds action scores, unsupported activity counts, adequate-evidence percentages, and confirmed/claimed verifier resolutions.

Count each reference activity once for the action score and each distinct output activity once for evidence and unsupported-action counts. The expert's grouping supplies these units. Validate links and coverage before calculation, including supported activities added to the shared final reference. Count open issues using `issue_status` in the saved model outputs. Use `issue_id` to match claimed verifier resolutions to the E+V assessment. Expert fixes in curated copies are recorded separately from these comparison measures.

Each pair shares E. Add V duration and tokens for E+V. For example, E taking 100 seconds, a failed V attempt taking 30 seconds, and a successful V retry taking 60 seconds produce successful-processing times of 100 and 160 seconds, with one V failure and its measurements reported separately.

Use provider-reported generation usage for token totals. Current EasyOCR contributes duration. Missing required observations or pending judgments make the corresponding measure unavailable, and zero denominators are not applicable. Export per-plan results, numerators, denominators, and paired changes using the design's formulas. Optional notebooks call the same calculation code.

### Instruction dataset assembly — planned

After assessing the saved outputs, experts curate supported answers in separate files. Each example uses the shared plan dataset format.

When an expert fixes an issue, retain its `issue_id` and `issue_origin`, set `issue_status` to `resolved` and `resolved_by` to `expert`, and explain the fix and supporting evidence in `resolution`. Update `related_action_id` if the action was removed or regrouped. Confirming an adequate verifier resolution belongs in `resolution_checks`; authorship of a subsequent expert fix belongs in the curated issue object. Preserve the assessed model outputs as the comparison evidence.

| Part of an instruction example | Source |
| --- | --- |
| Task instructions | Extraction instructions and field definitions. |
| Source input | Corresponding plan text, page links, and reviewed text recovery needed to support the answer. |
| Target answer | Expert-curated plan information, grouped actions, evidence, and reviewed issues. |

Require expert review and schema validation for each target. Correct or exclude unsupported content, include any necessary recovered text in the input, and retain source links and correction reasons. Pilot and document the export format before assembly. Report the numbers of source plans, instruction examples, and grouped actions separately. Whole-plan input with one curated answer forms one instruction example. Fine-tuning is future work.

## 7. Development evidence and remaining work

Use preparation notes, preserved run evidence, expert assessments, and concise development records to show how expert knowledge and model outputs shaped the workflow. Link practical lessons to the problems encountered, revisions made, and outcomes observed. The checkpoint below records development observations. Research quality results require completed expert assessment.

### Current development checkpoint

| Area | Observed status |
| --- | --- |
| Registration and preparation | Freetown `plan_0001/preparation_02` has 46 pages, comprising 34 native and 12 mixed pages, with 19 candidate image regions on 14 pages. Status is `ready_with_gaps`. |
| Saved extraction and engineering checks | Local execution, tools, limits, validation, saving, and CLI are implemented. The full suite was rerun on 2026-11-14 with 1,804 passes and 11 dependency warnings. Most model replies are controlled fixtures. |
| Live integration | Fictional prepared-text and image-only runs completed through Ollama and MCP, including OCR recovery. Qwen token accounting was checked with Ollama 0.40.14 and 0.40.16. A 0.40.16 fixture completed in 193.92 seconds with matching counted/reported inputs, and an oversized request was blocked. |
| First Freetown attempt | `run_extract_0001` failed after 1,156.61 seconds. Five model requests and ten page-text calls completed. Final generation used 12,575 output tokens, but two five-category scope/link contradictions failed validation. Accepted output is null. |
| Diagnostic source review | Of 51 candidate quotation uses, 27 matched prepared text one physical page earlier than cited, 24 required further source review, and ten contained ellipses. These findings require expert interpretation. |
| Prompt clarification | Five-category prompts were clarified for source links, physical pages, and continuous quotations. 436 targeted tests passed. Effects on model behavior are **Not yet tested**. |
| Revised study protocol | Activity grouping, renamed issue fields, expert resolutions, category definitions, rubric examples, and streamlined evaluation are documented. Their implementation and development-pilot results are **Not yet tested**. |
| Remaining research stages | Accepted full real-plan extraction, the second development plan, verification, expert assessment, comparison, and instruction assembly are pending. |

The [change log](CHANGELOG.md) preserves dated evidence. Local handoffs and `artifacts/freetown_run_extract_0001_review_2026-11-14/` provide additional diagnostics and require separate backup. Historical diagnostic scripts can generate new answers.

An earlier capacity check used 54,013 input tokens and 1,525 output tokens at a 65,536-token context setting. Generation at the full configured 73,728-context and 16,384-output limits is **Not yet tested**.

### Next implementation steps

1. **Migrate the extraction format.** Update content/run schemas, prompts, validation, response-schema conversion checks, fixtures, and relevant tests together. Apply the nine action fields, eight issue fields, category options in DESIGN.md appendix E, and coding rules in appendix F. Validate expert resolutions in curated copies and model-stage resolutions in saved runs. Assign a new run-format version and support loading earlier version 1 files with their original field names and interpretation.
2. **Check a small example.** Include tree planting across neighborhoods and phases, differing statuses, overlapping categories, shared costs, unstated fields, expected benefits, quotations, and physical pages. Inspect source meaning and format acceptance.
3. **Complete development extraction.** Obtain and inspect accepted action-focused outputs for both development plans. Retain earlier failures and investigate source-recovery problems that affect extraction.
4. **Implement verification.** Validate the different model's request and token-accounting path, then implement its profile, prompt, loop, input links, and continuity checks. Test corrections, omissions, unflagged errors, and failed V retries.
5. **Pilot assessment and measures.** Implement templates and validation for the streamlined files below. Work through coding, grouping, rubric, evidence, and resolution examples, including expert fixes after assessment. Check the appendix G calculations against hand-worked cases and settle reviewer procedures before freezing comparison settings.
6. **Run the comparison.** Select the five plans and preserve independent references, the first successful paired outputs, assessments, failed attempts, and analysis inputs. Report the agreed measures and explanatory examples.
7. **Assemble instruction examples.** Pilot the export format, curate supported answers and issue resolutions, include sufficient source inputs, and check example counts and source links.

Issue field migration applies within each issue object.

| Current field | Target field |
| --- | --- |
| `related_record_id` | `related_action_id` |
| `description` | `issue_description` |
| `type` | `issue_type` |
| `origin_stage` | `issue_origin` |
| `status` | `issue_status` |

The fields `issue_id`, `resolved_by`, and `resolution` keep their names. The target `resolved_by` options add `expert` for fixes in curated datasets. Existing saved runs retain their original field values and model settings.

Before comparison, also close the saved-source loading gap. Current loading validates the linked preparation, PDF, and images, but does not compare page text with the startup fingerprint in `artifacts/extractor_input.json`. Add that comparison when loading runs for verification or assessment, so later text edits are detected. During-run fingerprint checks already exist.

Direct image delivery, hosted providers, richer status listing, broader datasets, publication packaging, and fine-tuning are deferred.

## Appendix: supporting JSON files

These tables define workflow files alongside the [plan dataset](DESIGN.md#appendix-dataset-coding-rules-and-evaluation). Registry, preparation, profile, and execution formats are implemented. The migrated action content and expert-file formats are planned. Existing version 1 runs use five-category content.

Fields are required unless stated otherwise. Dates use `YYYY-MM-DD`, timestamps use UTC, durations use seconds, and paths are project-relative. Content, evidence objects, and missing-value conventions follow DESIGN.md. Apply the migrated content schema to new runs and planned expert files.

### Registry

The root object has `schema_version` and `plans`; each plan is defined below.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Registry version, currently 1. |
| `plans` | list of plan entries | Registered document versions. |
| `plans[].plan_id` | string | Unique document ID. |
| `plans[].plan_title` | string | Collection title. |
| `plans[].pdf_path` | string | Preserved original PDF path. |
| `plans[].document_sha256` | string | 64-character hexadecimal PDF checksum. |
| `plans[].source_url` | string | Official source location. |
| `plans[].date_accessed` | date string | Actual collection access date. |
| `plans[].study_set` | enum | `development`, `comparison`, or `expansion`. |
| `plans[].prepared_source_path` | string or null | Explicitly linked preparation, or null before preparation. |

### Preparation and page text

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Preparation version 3; version 2 remains readable. |
| `plan_id` | string | Registered document ID. |
| `pdf_path` | string | Preserved original. |
| `document_sha256` | string | PDF checksum. |
| `source_url` | string | Source URL copied at preparation time. |
| `date_accessed` | date string | Access date copied at preparation time. |
| `prepared_at` | timestamp string | Preparation timestamp. |
| `pages_path` | string | Linked ordered page list. |
| `page_count` | positive integer or null | Known PDF page count; null when counting failed. |
| `settings` | object | Preparation settings below. |
| `status` | enum | `ready`, `ready_with_gaps`, or `failed`. |
| `problem` | string or null | Preparation problem/review notes. |

The preparation `settings` object contains the following fields.

| Field | Type | Meaning |
| --- | --- | --- |
| `ocr_enabled` | Boolean | Whether preparation OCR was enabled. |
| `ocr_engine` | string or null | OCR package; null when disabled. |
| `ocr_version` | string or null | Detected package version; null when disabled. |
| `ocr_language` | string or null | Language setting; null when disabled. |
| `image_render_dpi` | positive integer | Rendering resolution, currently 150 DPI. |
| `candidate_image_min_area` | number greater than 0 and at most 1 | Version 3 only: per-image area threshold, currently 0.10. |

`pages.json` is an ordered list of page objects.

| Field | Type | Meaning |
| --- | --- | --- |
| `page_number` | positive integer | Physical PDF position; every known page appears once. |
| `text` | string or null | Selected text. Empty native text can represent a known blank page; null means unavailable. |
| `text_source` | enum or null | `native`, `ocr`, or `mixed`; null exactly when text is null. Version 2 cannot use mixed. |
| `readable` | Boolean | Whether a usable reading route exists. |
| `image_available` | Boolean | Image availability; in version 3 agrees with a saved full-page image path. |
| `problem` | string or null | Page problems/review notes; retained after OCR where appropriate. |
| `image_path` | string or null | Version 3: preserved full-page PNG. |
| `image_regions` | list of region objects | Version 3: candidate regions; empty when none. |

Each image region has the following fields.

| Field | Type | Meaning |
| --- | --- | --- |
| `bounds` | list of four nonnegative integers | Left, top, right, bottom pixels from the saved image's top-left. |
| `area_fraction` | positive number at most 1 | Visible image polygon area divided by visible page area. |
| `image_path` | string or null | Preserved crop path; null if it could not be saved. |

OCR/mixed text requires enabled preparation OCR. Empty OCR output does not establish blankness. Python supplies defaults before saving; validation does not insert missing values.

### Profile configuration

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | integer | Profile-file version, currently 1. |
| `document_tools` | object | Shared tool fields defined under [Saved settings and nested objects](#saved-settings-and-nested-objects). |
| `profiles` | list of profile objects | Unique named profiles. Each uses the `name`, `stage`, `model`, `generation`, `context_limit`, `prompt_paths`, `max_tool_calls`, `model_timeout_seconds`, and `image_input_enabled` fields defined under [Saved settings and nested objects](#saved-settings-and-nested-objects). |

Run-only `prompt_texts` and `environment` are observed/snapshotted at execution, not editable profile fields. Runs add the shared tool configuration to their saved settings.

### Saved run

Python saves this outer object in `output.json`. The action-focused migration needs a new format version; existing version 1 runs retain their original meaning.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | positive integer | Saved-format version assigned during the coordinated schema migration. |
| `plan_id` | string | Registered document version. |
| `run_id` | string | One execution, such as `run_extract_0001`. |
| `stage` | enum | `extractor` or `verifier`. |
| `purpose` | enum | `development`, `comparison`, or `exploratory`. |
| `input_run_id` | string or null | Successful extractor run used by verification; null for extraction. |
| `retry_of_run_id` | string or null | Failed run retried by this attempt. |
| `source_path` | string | Exact preserved `preparation.json` used. |
| `status` | enum | `running`, `succeeded`, or `failed`. |
| `started_at` | timestamp string | Observed execution start. |
| `ended_at` | timestamp string or null | Observed end; null if not recorded. |
| `elapsed_seconds` | nonnegative number or null | Measured stage duration; null if unavailable. |
| `settings` | object | Complete frozen settings, defined under [Saved settings and nested objects](#saved-settings-and-nested-objects). |
| `model_calls` | list of model-call objects | Ordered generation attempts and available usage, defined under [Model-call entry](#model-call-entry). |
| `tool_log_path` | string or null | Saved ordered tool log, when present. |
| `content` | object or null | The [plan dataset's content](DESIGN.md#a-plan-dataset-and-content) on success; null without an accepted final answer. |
| `review` | object or null | The [review object](DESIGN.md#d-review-and-issues) on success; null without an accepted final answer. |
| `error` | string or null | Failure explanation when available. |

### Saved settings and nested objects

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | Selected profile name; a profile is a named group of settings. |
| `stage` | enum | `extractor` or `verifier`, matching the run. |
| `model` | object | Model connection described below. |
| `generation` | object | Answer-generation controls described below. |
| `context_limit` | positive integer | Maximum tokens available to input and generated output together. A token is a unit of text processed by the model. |
| `prompt_paths` | nonempty list of strings | Ordered instruction-file paths. |
| `max_tool_calls` | positive integer | Maximum submitted document tool calls within this run. |
| `model_timeout_seconds` | positive number | Time limit for one complete model request. |
| `image_input_enabled` | Boolean | Whether direct model image input is enabled; currently unsupported. |
| `document_tools` | object | Shared document tool settings described below. |
| `prompt_texts` | nonempty list of strings | Exact instruction-file contents in the same order as `prompt_paths`. |
| `environment` | object | Observed execution environment described below. |

The `model` object defines the connection.

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | Model identifier used by the serving service. |
| `execution_mode` | enum | `local` or `hosted_api`; only local execution is implemented. |
| `endpoint` | string | Model service address. |
| `api_service` | string or null | Hosted API service, if applicable; an API is a software interface for requests. |
| `provider` | string or null | Hosting provider, if applicable. |

The `generation` object defines sampling and output capacity.

| Field | Type | Meaning |
| --- | --- | --- |
| `temperature` | nonnegative number or null | Sampling control affecting randomness; null uses the model default. |
| `top_p` | number greater than 0 and at most 1, or null | Sampling control limiting the candidate-token probability mass; null uses the default. |
| `seed` | integer or null | Random seed when supported; does not alone establish reproducibility. |
| `max_output_tokens` | positive integer | Reserved answer capacity, including model thinking where applicable. |

The `document_tools` object defines shared tool settings.

| Field | Type | Meaning |
| --- | --- | --- |
| `ocr_enabled` | Boolean | Whether tool-requested OCR is available. |
| `ocr_engine` | string or null | OCR software; null when disabled. |
| `ocr_language` | string or null | OCR language setting; null when disabled. |
| `image_render_dpi` | positive integer | Render resolution in dots per inch (DPI). |
| `tool_timeout_seconds` | positive number | Time limit for one complete tool request. |

The `environment` object records observations, using null where a nullable observation is unavailable.

| Field | Type | Meaning |
| --- | --- | --- |
| `model_revision` | string or null | Observed model version or content identifier. |
| `runtime` | string or null | Software serving the model. |
| `runtime_version` | string or null | Serving-software version. |
| `quantization` | string or null | Reported reduced-precision weight format. |
| `hardware` | string or null | Observed hardware description. |
| `code_commit` | string or null | Git revision identifying application code. |
| `code_dirty` | Boolean | Whether the application working tree has uncommitted changes. Formal comparison requires clean code. |
| `python_version` | string or null | Python interpreter version. |
| `model_client_version` | string or null | Version of the model-request client. |
| `preparation_version` | string or null | Preparation format/version observed. |
| `tools_version` | string or null | Document-tool implementation version. |
| `ocr_version` | string or null | Installed OCR package version. |
| `model_loaded_at_start` | Boolean or null | Whether the model was already loaded before the run's preflight requests. |

### Model-call entry

| Field | Type | Meaning |
| --- | --- | --- |
| `input_tokens` | nonnegative integer or null | Provider-reported input usage; unavailable is not zero. |
| `output_tokens` | nonnegative integer or null | Provider-reported output usage. |
| `finish_reason` | string or null | Provider-reported reason generation ended. |
| `truncated` | Boolean or null | Whether output was cut off; reported truncation fails the run. |
| `response_path` | string or null | Preserved response location, when available. |

### Tool log and validation report

`tool_log.json` is an ordered list of tool calls.

| Field | Type | Meaning |
| --- | --- | --- |
| `tool` | string | Requested tool name. |
| `arguments` | object | Submitted arguments. |
| `result` | object or null | Result, including original pages/artifact paths where applicable. |
| `elapsed_seconds` | nonnegative number or null | Measured tool duration. |
| `error` | string or null | Failure explanation. |

`validation_report.json` records final-response checks.

| Field | Type | Meaning |
| --- | --- | --- |
| `raw_response_path` | string | Original final answer. |
| `repaired_response_path` | string or null | Separate repaired candidate, if changed. |
| `initial_errors` | list of error objects | Problems before permitted repair. |
| `remaining_errors` | list of error objects | Problems after all checks. |
| `repairs` | list of repair objects | Ordered formatting changes. |
| `valid` | Boolean | Whether the final candidate passed validation. |

Error and repair entries contain the following fields.

| Field | Type | Meaning |
| --- | --- | --- |
| Error `category` | enum | `syntax`, `structure`, `reference`, or `other`. |
| Error `location` | string or null | Field path or syntax position where known. |
| Error `message` | string | Plain-language explanation. |
| Repair `rule` | string | Permitted repair applied. |
| Repair `location` | string | Location of change. |
| Repair `before` | string | Original text at the changed location. |
| Repair `after` | string | Replacement text. |

### Expert references — planned

Use this format for the independent initial reference and shared final reference. Validate both against the action content schema. Record reviewer roles and disagreement procedures during the pilot.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | positive integer | Expert reference format version. |
| `plan_id` | string | Registered document. |
| `prepared_by` | nonempty list of strings | Names or study codes identifying the experts who prepared this version. |
| `content` | object | Same plan information and actions as DESIGN.md. |
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
