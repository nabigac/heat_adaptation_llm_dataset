# Implementation Doc: Heat Adaptation LLM Dataset

**Technical implementation · updated 2026-11-14**

This document explains how the software supports the study in [DESIGN.md](DESIGN.md), from preparing source documents to preserving model outputs and calculating expert-assessed results. It describes working components, planned stages, and the evidence available for each. [README.md](README.md) explains available commands.

## 1. Purpose and research requirements

The implementation must make the extraction process inspectable and support a consistent comparison between extraction alone (E) and extraction followed by verification (E+V). Software checks test whether the workflow follows specified rules; experts assess the meaning, source support, and correctness of the extracted information.

| Research need | Implementation requirement |
| --- | --- |
| Trace claims to their source | Preserve the original PDF, selected preparation, page references, quotations, and any additional OCR readings. |
| Compare E and E+V consistently | Use the same saved extraction and source for each pair; record model settings, prompts, tools, and failed attempts. |
| Protect independent expert judgment | Keep model outputs hidden during initial reference preparation and preserve references separately from model runs. |
| Reproduce the analysis | Save measurements and completed assessments, select analysis inputs explicitly, and calculate measures through shared code. |

**Implementation status:** the working extractor still uses five content lists: goals, actions, monitoring/evaluation, benefits, and costs. The action-focused format specified in the design document has not yet been implemented. Existing prompts, schemas, code, and saved runs have not been migrated. Verification, expert files, and analysis below describe planned behavior.

## 2. System architecture and responsibilities

Python owns file identity, orchestration, validation, measurements, and saving. Models interpret source material and request tools; experts establish source support and correctness. A module is a Python file grouping related functions.

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

The extractor acts as the MCP client, starting `document_tools.py` as a local subprocess (a separate running program). It exchanges messages through standard input/output; no MCP network port is opened. `models.py` calls the separate Ollama HTTP service. Python carries tool requests and results between them; Ollama does not directly access the document server.

The MCP SDK builds the tool catalogue from function descriptions and argument/result types. Python converts it into Ollama's tool format and validates requests before execution. Tools accept page numbers or quotations, not arbitrary paths, URLs, or executable instructions. Source text is evidence, never agent instructions. Expert files stay outside agent access, including on reruns.

## 3. Document collection and preparation

The workflow accepts prescreened government or public-agency plans at city, county, regional, state, and national levels. The particular research interest in city plans informs sample selection; the same registration and preparation workflow applies at every level. Record the document's administrative level in `plan_info.plan_scale`, using `country` for national plans.

Registration preserves `data/raw/<plan_id>.pdf` and records its SHA-256 checksum, a fingerprint of the file's bytes. Identical bytes reuse the document; revised bytes receive a new ID. Never replace a registered PDF with different content.

`update` changes only explicitly supplied title, source URL, access date, or study set after validating the complete proposed entry. Omitted values remain unchanged; an unchanged update writes nothing. Development assignments stay fixed. Other study-set changes are permitted only before model work is saved. Each preparation snapshots the then-current source URL and access date; later corrections do not rewrite completed work.

### Prepare text automatically, investigate gaps with tools

Preparation tries native PDF text first, using pypdf; a separate PDFium renderer can recover image access if native reading fails. Known blank pages do not require OCR. Missing or unreliable native text uses full-page OCR when enabled.

Even on pages with native text, an individual image is a candidate when it occupies at least 10% of the visible page and has no native text within its bounds. Save the page PNG and candidate crops. Append labeled regional OCR to unchanged native text and mark its source `mixed`. The threshold applies to each image, not their combined area.

This screening rule can include photographs and miss small charts or images with partial text layers. It does not fix table reading order. Successful OCR retains review notes because text recognition is not accuracy validation. The present backend is cached English EasyOCR on the CPU, with 150 DPI rendering; DPI means dots per inch. Download models explicitly during setup. Normal operation is offline and loads a reader only when needed. `--no-ocr` retains image screening and preservation.

| Preparation status | Meaning |
| --- | --- |
| `ready` | Automatic checks found no problems or review flags; not a guarantee of completeness. |
| `ready_with_gaps` | Every page has a usable reading route, but content needs review, including successfully recovered OCR. |
| `failed` | Page counting or a required reading route failed. Resolve this before model processing. |

Each attempt gets a new folder. Publish images and page data before its preparation record; validate linked PNGs and crop dimensions when loading. Include every known PDF page once. If neither reader can identify pages, save null page count and an empty page list where possible. Identity, validation, or storage failures may prevent a complete preparation record.

Preserve version 2 readability; new preparations use version 3 with image paths, image regions, and mixed text. Missing old fields are not invented. Preparation status is derived from the explicitly linked record, not duplicated in the registry.

### Document tools

| Tool | Current behavior |
| --- | --- |
| `get_page_text(page_number)` | Return exact selected preparation text and notes, preserving blank/unavailable and native/OCR/mixed distinctions. |
| `find_quote(quote)` | Exact, case-sensitive substring search within each initial page. Report matches and unavailable pages separately. No normalization or cross-page joining. |
| `run_ocr(page_number)` | Render the original page and return fresh OCR using the active run's frozen settings, with preserved artifacts and source identity. |

The server checks PDF identity and preparation/page fingerprints at startup. A fingerprint detects changes; it does not establish that the underlying text is correct. OCR runs sequentially with a lazily loaded, reused reader. Models cannot override OCR settings. Each request saves separate evidence and never changes preparation text or extends `find_quote` to fresh OCR.

A failed reading can return a recoverable error to the model. Timeout, protocol failure, or inability to preserve evidence stops the run. Full-page tool OCR exists; direct model image delivery and tool-requested regional OCR remain unimplemented. Preparation already supports regional OCR. A literal quotation match does not establish support for a claim.

## 4. Model configuration and execution

### Models and profiles

The current local development profile is `qwen35_27b_extractor_development`, using `qwen3.5:27b` at `http://localhost:11434`. The recorded development machine is an Apple M5 Pro with 64 GB memory. Actual run metadata records observed hardware rather than assuming these specifications.

The installed weights use the safetensors/MLX serving path (weight storage and model execution software). The previously proposed `gemma4:31b` verifier remains an untested candidate with no profile or prompt. Test suitability and load models sequentially. Different model families can share errors; their difference alone does not establish independent verification.

| Setting | Current development value |
| --- | --- |
| Context limit | 73,728 tokens. |
| Output reservation | 16,384 tokens, including model thinking where applicable. |
| Capacity for all input | 57,344 tokens, before accounting for instructions, source, tools, and history. |
| Complete model-request timeout | 1,800 seconds. |
| Submitted document-tool calls | At most 10, including failed submitted calls. |
| Shared OCR and rendering | EasyOCR, English, CPU, cached models; 150 DPI. |
| Complete tool-request timeout | 120 seconds. |
| Direct image input | Disabled. |
| Temperature, top-p, seed | Null, using model defaults; not a claim of deterministic generation. |

`configs/profiles.json` contains shared `document_tools` and named `profiles`. Select name and stage explicitly. At startup, freeze the selected profile, shared tools, and ordered prompt texts: save their values so later edits do not change the attempt. Both comparison stages must share document-tool settings.

Future hosted APIs would change the model connection while tools and saved files stay local. Hosting is a development option, not an additional experimental configuration. Capability and token-counting support require validation before use.

### Prompts, response schema, and token budgeting

Prompts explain meaning and coding rules. The ordered extractor files are `shared_coding.md`, `field_definitions.md`, and `extractor.md`. The current files retain the earlier five-category instructions. The loader preserves each exact text; input assembly joins them with two newlines into one system message. Collection metadata, physical page numbers, preparation notes, and every prepared page go in a user message. The runner adds tool/final-phase instructions separately.

`build_extractor_input()` requires a registered plan, named profile, and exact preparation path. Shared source loading checks identity, PDF checksum, readiness, page records, and images. It never substitutes a newer preparation. Building the input itself makes no model calls, counts no tokens, performs no OCR, and creates no run.

A JSON Schema specifies machine-readable structure. Final Ollama requests send messages in `messages` and the compatible schema in `format`; plain `format: "json"` would not impose the full contract. Tool-phase requests instead send the available `tools` without the final schema. Structure constraints do not replace interpretation instructions. See the [Ollama chat API](https://docs.ollama.com/api/chat).

`prepare_ollama_response_schema()` derives a fresh provider copy from authoritative content and response schemas. It expands known local references and rewrites the nonblank-string pattern into an equivalent whole-string form tested with Ollama. Unsupported conversions fail rather than dropping constraints. Preserve the exact sent schema; do not maintain an independently edited provider contract.

#### Before every model request

1. Render the complete request with the validated Ollama render-only facility, which returns the prompt without generating an answer.
2. Count it with the matching installed tokenizer, the software that converts text into token IDs. Verify runtime version, model identity, and tokenizer fingerprints.
3. Require `input_tokens + max_output_tokens <= context_limit`.
4. Save preflight evidence, then generate within the same complete-request timeout.
5. Compare counted input with provider-reported input when available; a known disagreement fails the run.

Counting includes instructions, source, metadata, chat markers, tools, assistant prefix, and accumulated history. Disable tokenizer truncation and padding and do not add special tokens already supplied by rendering. Later requests resend full history; the application does not rely on Ollama remembering earlier requests.

The supported path is local Qwen3.5 safetensors/MLX with Ollama 0.40.14 or 0.40.16 and validated tokenizer assets. The private render-only interface is version-specific; validate changes before enabling them. The checker downloads no new assets. Request and renderer details are documented in the versioned [API definitions](https://github.com/ollama/ollama/blob/v0.40.14/api/types.go), [Qwen renderer](https://github.com/ollama/ollama/blob/v0.40.14/model/renderers/qwen35.go), and [chat implementation](https://github.com/ollama/ollama/blob/v0.40.14/server/routes.go).

Use the same body for rendering and generation. On the tested path, the final schema constrains generation separately from prompt rendering; do not add a second schema token charge. Schema text explicitly placed in messages is counted. Direct image counting remains unsupported.

If capacity is exceeded or reliable counting is unavailable, stop before generation. Do not silently truncate, reduce the output reservation, or switch to document chunks. No-truncation options and usage checks are additional safeguards. Preflight evidence includes counts, remaining capacity, request/rendered-prompt checksums, runtime/model/tokenizer identities, errors, and HTTP bodies. These counts are not provider usage and do not fill missing `model_calls` token values. Metadata and render-only operations are not extra research generation calls.

### Extractor control

1. Assemble the complete source and prompts and discover the source-bound MCP tools.
2. Count and send a tool-phase request. Accept validated tool calls or `READY_FOR_FINAL_RESPONSE` with optional outer whitespace. Other control text or premature final JSON fails rather than triggering an automatic correction.
3. Execute tools sequentially and preserve the full assistant message and ordered results, including thinking and call identifiers where supplied.
4. Continue until readiness or the tool-call limit. Each submitted call consumes a slot, including failures. Startup/catalogue discovery does not. Excess calls receive logged non-execution errors.
5. Clear tools and request one complete schema-constrained `content`/`review` answer. This scheduled final turn is not a retry.
6. Check completion and output, apply only permitted repairs, recheck source/collection details and application snapshots, and stop the MCP subprocess before accepting success.

The loop returns execution evidence; the saved wrapper adds checkpoints and final publication. A readiness signal is a measured model call. The tested Qwen renderer omits tool-result names/identifiers from rendered text, so preserve call/result ordering even when IDs exist.

This two-phase approach follows a development observation: imposing the final schema during tool selection suppressed a needed tool request in one synthetic example. Later fixtures worked with separate phases. This does not establish universal behavior for other models or runtimes.

## 5. Run records and reproducibility

The appendix defines the fields in the [saved run](#saved-run), [saved settings](#saved-settings-and-nested-objects), and [model-call entries](#model-call-entry).

### Saved extractor execution

Before execution, the saved wrapper freezes the selected input/settings and observes local hardware, software versions, and Git state. It then allocates a new run folder and creates `output.json` with status `running`. Ollama's loaded-model list is checked before render-only operations can load the model; model details supply quantization when disclosed. Missing optional observations remain null rather than being inferred from user-reported specifications. Original metadata response bodies and observation errors are retained.

The runner saves evidence at execution checkpoints:

| Evidence | Saved location within the run |
| --- | --- |
| Frozen input, source fingerprint, and discovered tools | `artifacts/extractor_input.json`, `artifacts/mcp_catalogue.json`. |
| Application code, schemas, and dependency files with SHA-256 manifest | `artifacts/code/`, `artifacts/code_fingerprints.json`. |
| Startup model observations | `artifacts/environment/`. |
| Exact request before dispatch, token reports, and preflight bodies | `responses/attempt_NN/request.json`, `token_budget.json`, `token_budget_final.json`, and `preflight/` in that attempt folder. |
| Received response chunks, raw HTTP body, and assistant text/message | `responses/attempt_NN/chunks/`, `responses/response_NN.json`, `responses/response_NN.txt`, and `responses/attempt_NN/assistant_message.json`, when available. |
| Pending tool requests and completed ordered tool activity | `artifacts/tool_requests/`, `tool_log.json`. |
| Fresh page OCR | `artifacts/ocr/request_NNNN/`: `request.json`, `page.png`, `ocr.txt`, and `result.json`, as available. |
| MCP subprocess stderr and complete message history | `artifacts/mcp_stderr.log`, `artifacts/conversation.json`. |
| Final checks and any repaired candidate | `validation_report.json`, `responses/repaired_final.txt` when a repair is applied. |

Raw HTTP bodies preserve received bytes after HTTP content decoding; assistant text is saved separately without JSON rewriting. The OCR report records original page/source identity, actual settings/package versions, timestamps, duration, file hashes, and errors. It does not certify recognition accuracy. The MCP diagnostic stream is published after subprocess shutdown; abrupt termination may prevent that log from being saved.

Only a valid accepted final answer supplies `content` and `review` in a succeeded run. Failed execution retains available evidence and null accepted output. The final record uses observed UTC times and monotonic elapsed duration, including setup/loading, model/tool requests, evidence checkpoints, validation, repairs, and MCP cleanup. Generation attempts are distinguished from blocked preflight; undisclosed usage remains null.

Supporting files are saved without overwriting earlier evidence. A checkpoint write failure stops execution and triggers best-effort failed finalization without retrying model/tool work. If final publication also fails, the caller receives the last successfully saved record and a persistence error; it must not report saved success based only on the in-memory answer. Existing completed runs stay unchanged.

### Selecting runs, failures, and feedback

Process one document at a time. `extract` requires plan ID, exact `--source-path`, `--profile`, and `--purpose`; optional `--config-path` selects another profile file. Development/comparison purposes must match the registry. Formal comparison requires observed, clean committed code; unavailable optional environment facts remain null.

Every invocation gets a new run ID. Manual retries link a failed run through `--retry-of-run-id`; successful deliberate repeats are exploratory. There are no automatic retries, equivalent-run searches, or automatic preparation substitutions. Future verification selects the exact successful E run and uses its preparation. If verification fails, retain E and retry verification only.

`list` reports registration and linked preparation status, not aggregate model-stage status. Missing links show `not_prepared`; damaged linked files raise errors. `extract` reports its actual saved status and report paths.

A complete model/tool timeout or reported output truncation fails the run even if JSON parses. Preserve available evidence. Ctrl+C requests cancellation and returns 130; saved success returns 0, failure 1, invalid CLI syntax 2. Failed final publication or abrupt termination can leave `running`, partial files, and null end time/duration. Confirm the process stopped before recovery; do not invent duration from a later recovery timestamp. Automatic recovery/resumption is not implemented.

Until an initial expert reference is validated, comparison feedback must hide claims, issues, response snippets, and repair details. The current CLI applies this restriction to every comparison-plan extraction, including exploratory repeats; creating a file named `reference_initial.json` does not unlock it. MCP stderr is retained in the run and client logging is suppressed. These are display restrictions, not filesystem access controls. If troubleshooting exposes outputs, an unexposed expert must prepare the independent reference.

### Validation and permitted repair

Check completion before repairing JSON. Reported truncation fails immediately. Classify errors as `syntax` (unreadable JSON), `structure` (wrong fields/types/values), `reference` (invalid IDs/paths/pages), or `other`; preserve location and explanation.

| Case | Permitted behavior |
| --- | --- |
| Whole-response code fence | Remove only when it encloses one complete JSON answer without surrounding commentary. |
| Trailing comma | Remove immediately before a closing bracket/brace, outside quoted text. |
| Missing closing delimiters | Append only after a complete value, with unambiguous nesting and confirmed normal completion. Never complete missing values, unfinished strings, unknown-completion answers, or truncated output. |
| Single page number | Convert a positive integer to a one-item `page_numbers` list, then validate range. |
| Missing field or other error | Leave unchanged and report it. Do not insert nulls, infer facts, alter quotes, drop records/unknown fields, or guess references. |

Keep the raw answer, save any repaired candidate separately, and repeat all checks. Repairs do not add a model call or a new run. Any remaining error fails the run. Successful repair does not count as a separate failed execution. A structurally valid answer still needs expert assessment.

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

`plan_id` identifies a document version; `run_id` identifies one execution. Action and issue IDs are local to linked outputs. Keep continuing IDs through verification and allocate new ones for additions. When removing/splitting an action, update issue links; use null for a removed target and identify it in the description. An issue affecting several resulting actions links one and names the others. Do not invent relationships to repair invalid references.

The saved run combines metadata, content, and review. Expert files use the same content format without simulated model runs. Supporting files are preserved individually; saving a run folder is not a single all-or-nothing transaction.

Track code, tests, dependency settings, schemas, prompts, profiles, registry metadata, and project documents in Git. `AGENTS.md` stays local. Credentials, PDFs, prepared text, runs, model assets, and local diagnostic artifacts are ignored; back up research files separately. Ollama manages its model assets outside this repository. No extra source, batch, review, or artifact IDs are needed.

## 6. Expert assessment and analysis

### Expert files and measurement

These stages remain planned. Require saved successful E and E+V outputs, linked to each other and the same preparation, before generating or accepting a comparison reference. Generate a blank content template with collection metadata; do not prefill model actions or issues. Experts work from the original PDF without seeing outputs.

After saving the initial reference, create E and E+V assessment templates containing known run links, quotations, pages, and relevant issues. Experts supply semantic matches and judgments. Review additions relative to the initial reference, group duplicate/split descriptions once, and save one shared final reference with evidence and reasons for revisions. Score both outputs against it.

Preserve initial references and completed assessments. Later revisions need new named files and explicit analysis selection; both assessments must use the same final reference. Validate coverage before marking complete: every final reference action, supplied quotation/page, distinct addition, and claimed initial issue resolution must be reviewed. Null judgments and undetermined support are pending.

#### Calculations

All content denominators in the action-focused design count **actions only**. Plan metadata, evidence entries, and issues are not extra actions.

| Measure | Calculation and interpretation |
| --- | --- |
| Fully correct action percentage | Final reference actions scored 1 ÷ all final reference actions × 100. |
| Partial-credit action percentage | Sum of final reference action scores ÷ final reference action count × 100. This is a rubric score, not a probability of correctness. |
| Additional actions and support | Count distinct additions relative to the initial reference and report supported ÷ all additions × 100. Always accompany reference-based scores with these results because unsupported additions do not lower those scores. |
| Actions with quotations | Count output actions with at least one nonempty quotation, once per action; also show total actions. Presence does not establish support. |
| Valid quotation percentage | Quotation uses faithful to the PDF and supporting all assigned claims ÷ all supplied quotation uses × 100. Check OCR visually. Reuse across actions counts as separate uses. |
| Page-reference correctness | Correct cited pages ÷ all cited pages across quotation uses × 100. Check each cited page separately. |
| Successful processing runtime | E duration; E+V equals that same duration plus successful V duration. Includes setup/loading, models, tools, saving checkpoints, validation, repair, and cleanup. |
| Tokens | Sum provider-reported input and output tokens across generation calls in selected successful stages; report input/output separately. Missing required usage makes the relevant total null. |
| Failures | Count distinct failed comparison attempts by stage, including retries. Count shared extraction failures once and retain their measurements separately. |
| Issue diagnostics | Count initially open E issues, those V marks resolved, those experts confirm resolved, all open issues in each output, and new V issue IDs, including newly resolved ones. |

For ten reference actions with six full, two partial, and two omitted, scores are 60% fully correct and 70% partial credit. A correct action with incorrect status receives partial credit. Matching by meaning allows many-to-many matches; duplicates earn no extra credit.

If E takes 100 seconds, V fails after 30 seconds, and its successful retry takes 60 seconds, successful runtimes are E = 100 and E+V = 160 seconds. Report the failure and its measurements separately; these runtimes do not describe total effort. Preparation and human review are excluded. Current EasyOCR adds runtime but no model tokens; any future LLM-based OCR must count its generation usage.

Keep pairs together by plan and report underlying counts and the plan's administrative level. Missing required observations make a total unavailable; zero denominators are not applicable. The proposed aggregate is the mean of valid per-plan percentages with the number of contributing plans; confirm during the development assessment. Do not infer expert review time from issue counts.

An expert marks a quotation supported only when its wording/numbers faithfully match the original PDF and all assigned claims are supported. Missing evidence remains a separate extraction problem: percentages over supplied quotes cannot detect absent quotations by themselves. Issue resolutions are model claims until confirmed by experts.

## 7. Development evidence and remaining work

The results below describe engineering checks and development observations. They do not constitute the study's expert evaluation or establish extraction accuracy.

### Current development checkpoint

| Area | Observed status |
| --- | --- |
| Registration and preparation | Implemented. Freetown `plan_0001/preparation_02` contains 46 pages: 34 native and 12 mixed, with 19 candidate image regions on 14 pages. It remains `ready_with_gaps`. |
| Saved local extraction | Implemented: complete input assembly, model/tool loop, request limits, response validation, incremental evidence saving, and CLI. |
| Automated checks | The latest recorded full suite passed 1,804 tests with 11 dependency warnings. Most model replies are controlled fixtures; tests do not establish extraction accuracy. |
| Live integration examples | Fictional prepared-text and image-only runs completed through real Ollama and MCP. The image example recovered “OPEN 3 COOLING CENTRES BY 2028” through OCR, but also raised a goal/action coding question under the earlier format. |
| Runtime compatibility | Local token accounting has been checked for Ollama 0.40.14 and 0.40.16 with the supported Qwen setup. A 0.40.16 fictional run succeeded in 193.92 seconds with matching counted/reported inputs; an oversized request was blocked. |
| First full Freetown attempt | `run_extract_0001` ended as failed after 1,156.61 seconds. Five model requests completed normally, ten page-text tools were called, and final generation used 12,575 output tokens. Two scope/link contradictions in the earlier content format failed validation. Accepted content and review remain null. |
| Diagnostic source review | Of 51 candidate quotation uses, 27 matched prepared text on other pages, consistently one page earlier than cited; 24 need further source review, and ten contain ellipses. These are diagnostic text checks, not expert quality scores. |
| Subsequent prompt clarification | Existing five-category prompts were clarified for source-supported links, physical PDF page citations, and continuous quotations. 436 targeted tests passed; effects on model behavior are **Not yet tested**. |
| Later stages | No accepted full real-plan extraction, verifier run, expert reference, assessment, or comparison result exists yet. The second development plan remains outstanding. |

The [change log](CHANGELOG.md) preserves dated results and limitations. Local evidence includes the Part 1 and Part 2 handoffs and `artifacts/freetown_run_extract_0001_review_2026-11-14/`; these ignored files are absent from a fresh clone. Historical diagnostic scripts may generate new answers and are not automatically portable replays.

Earlier capacity checks demonstrated a 54,013-token input with 1,525 output tokens at a 65,536-token context setting. Generation at the current full 73,728-context and 16,384-output limits is **Not yet tested**. Small-fixture success and token fit are not complete capacity or accuracy benchmarks.

### Next implementation steps

1. **Migrate the extraction contract together.** Update content/run schemas, shared field definitions, prompts, validation, fixtures, and tests for plan information, actions, and issues. Use exactly the nine agreed action fields; `action_type` is a list of unique categories. Remove goal links and separate goal/monitoring/benefit/cost lists from new outputs. Version the changed format and preserve the interpretation and readability of earlier saved runs.
2. **Check a small action-focused example.** Exercise overlapping types, repeated actions, unstated fields, shared costs, expected versus reported benefits, quotations, and physical page citations. Check source meaning as well as JSON validity.
3. **Complete development extraction.** Start separately identified real-plan runs, retain earlier failures, and inspect results against the PDF. Continue with the second development plan and focused OCR checks.
4. **Implement verification.** Test a verifier model, profile, prompt, and runner against the exact saved extraction and source. Preserve continuing action/issue IDs and review unflagged content and omissions.
5. **Pilot expert files and calculations.** Work through coding and assessment examples before freezing comparison settings. Implement only the agreed measures.
6. **Run the fixed comparison.** Select the five plans and preserve independent references, paired outputs, assessments, failures, and analysis inputs.

A related reproducibility gap needs attention before comparison: completed-run loading validates the linked preparation, PDF, and images, but does not compare the loaded page text against the startup fingerprint saved in `artifacts/extractor_input.json`. During-run fingerprint checks exist. File preservation by the normal workflow does not protect against later manual edits to prepared text. Address this explicitly when implementing source-integrity checks.

Direct image delivery, hosted providers, richer status listing, broader datasets, publication packaging, and fine-tuning are deferred. They are not prerequisites for establishing a useful action-extraction baseline.

## Appendix: supporting JSON files

These tables describe the workflow's saved files alongside the [plan dataset specification](DESIGN.md#appendix-plan-dataset-and-coding-rules). Operational file formats are implemented; the action-focused run format and expert-file formats remain **planned**. Existing version 1 runs retain their earlier five-category content.

All fields are required unless stated otherwise. Dates use `YYYY-MM-DD`, timestamps use UTC, durations use seconds, and paths are project-relative. Types and null conventions follow DESIGN.md. “Evidence object” and “content” refer to its appendix; saved runs and expert files will use the action-focused content after migration.

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

Preparation settings:

| Field | Type | Meaning |
| --- | --- | --- |
| `ocr_enabled` | Boolean | Whether preparation OCR was enabled. |
| `ocr_engine` | string or null | OCR package; null when disabled. |
| `ocr_version` | string or null | Detected package version; null when disabled. |
| `ocr_language` | string or null | Language setting; null when disabled. |
| `image_render_dpi` | positive integer | Rendering resolution, currently 150 DPI. |
| `candidate_image_min_area` | number greater than 0 and at most 1 | Version 3 only: per-image area threshold, currently 0.10. |

`pages.json` is an ordered list of these objects:

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

Each region:

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
| `max_tool_calls` | positive integer | Maximum submitted document-tool calls within this run. |
| `model_timeout_seconds` | positive number | Time limit for one complete model request. |
| `image_input_enabled` | Boolean | Whether direct model image input is enabled; currently unsupported. |
| `document_tools` | object | Shared document-tool settings described below. |
| `prompt_texts` | nonempty list of strings | Exact instruction-file contents in the same order as `prompt_paths`. |
| `environment` | object | Observed execution environment described below. |

Within `model`:

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | string | Model identifier used by the serving service. |
| `execution_mode` | enum | `local` or `hosted_api`; only local execution is implemented. |
| `endpoint` | string | Model service address. |
| `api_service` | string or null | Hosted API service, if applicable; an API is a software interface for requests. |
| `provider` | string or null | Hosting provider, if applicable. |

Within `generation`:

| Field | Type | Meaning |
| --- | --- | --- |
| `temperature` | nonnegative number or null | Sampling control affecting randomness; null uses the model default. |
| `top_p` | number greater than 0 and at most 1, or null | Sampling control limiting the candidate-token probability mass; null uses the default. |
| `seed` | integer or null | Random seed when supported; does not alone establish reproducibility. |
| `max_output_tokens` | positive integer | Reserved answer capacity, including model thinking where applicable. |

Within `document_tools`:

| Field | Type | Meaning |
| --- | --- | --- |
| `ocr_enabled` | Boolean | Whether tool-requested OCR is available. |
| `ocr_engine` | string or null | OCR software; null when disabled. |
| `ocr_language` | string or null | OCR language setting; null when disabled. |
| `image_render_dpi` | positive integer | Render resolution in dots per inch (DPI). |
| `tool_timeout_seconds` | positive number | Time limit for one complete tool request. |

Within `environment`; unavailable nullable observations remain null:

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

`tool_log.json` is an ordered list:

| Field | Type | Meaning |
| --- | --- | --- |
| `tool` | string | Requested tool name. |
| `arguments` | object | Submitted arguments. |
| `result` | object or null | Result, including original pages/artifact paths where applicable. |
| `elapsed_seconds` | nonnegative number or null | Measured tool duration. |
| `error` | string or null | Failure explanation. |

`validation_report.json`:

| Field | Type | Meaning |
| --- | --- | --- |
| `raw_response_path` | string | Original final answer. |
| `repaired_response_path` | string or null | Separate repaired candidate, if changed. |
| `initial_errors` | list of error objects | Problems before permitted repair. |
| `remaining_errors` | list of error objects | Problems after all checks. |
| `repairs` | list of repair objects | Ordered formatting changes. |
| `valid` | Boolean | Whether the final candidate passed validation. |

Nested report entries:

| Field | Type | Meaning |
| --- | --- | --- |
| Error: `category` | enum | `syntax`, `structure`, `reference`, or `other`. |
| Error: `location` | string or null | Field path or syntax position where known. |
| Error: `message` | string | Plain-language explanation. |
| Repair: `rule` | string | Permitted repair applied. |
| Repair: `location` | string | Location of change. |
| Repair: `before` | string | Original text at the changed location. |
| Repair: `after` | string | Replacement text. |

### Expert references — planned

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | positive integer | Expert reference format version. |
| `plan_id` | string | Registered document. |
| `content` | object | Same plan information and actions as DESIGN.md. |
| `revisions` | list of revision objects | Final reference only; initial reference stays unchanged. |
| `revisions[].record_ids` | list of strings | Reference actions affected by the revision. |
| `revisions[].reason` | string | Why the change/addition is justified. |
| `revisions[].evidence` | list of evidence objects | Supporting source passages and pages. |

### Expert assessments — planned

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
| `initial_matches` | list of match objects | Matches against the initial reference. |
| `record_scores` | list of score objects | One per final reference action. |
| `additional_records` | list of addition objects | Distinct additions relative to the initial reference. |
| `quotation_checks` | list of quotation-check objects | Every supplied quotation use and cited page. |
| `resolution_checks` | list of resolution-check objects | Initially open E issues marked resolved by V; empty for E. |

Each initial match:

| Field | Type | Meaning |
| --- | --- | --- |
| `reference_record_id` | string | Initial reference action. |
| `output_record_ids` | list of strings | Semantically matching output actions; empty for omission. |

Each record score:

| Field | Type | Meaning |
| --- | --- | --- |
| `reference_record_id` | string | Final reference action. |
| `output_record_ids` | list of strings | Matching output actions. |
| `score` | 0, 0.5, 1, or null | Rubric judgment; null while pending. Omission scores 0 once assessed. |
| `reason` | string | Expert explanation. |

Each distinct addition:

| Field | Type | Meaning |
| --- | --- | --- |
| `description` | string | Additional information proposed by the output. |
| `output_record_ids` | list of strings | Output actions describing this addition. |
| `support_status` | enum | `supported`, `unsupported`, or `undetermined` while pending. |
| `final_reference_record_ids` | list of strings | Final reference actions containing supported information. |
| `reason` | string | Expert explanation. |
| `evidence` | list of evidence objects | Source support for the judgment. |

Each quotation check:

| Field | Type | Meaning |
| --- | --- | --- |
| `record_id` | string | Output action using the quote. |
| `evidence_index` | nonnegative integer | Position in that action's evidence list, starting at 0. |
| `claim_fields` | nonempty list of strings | Fields this quotation is being used to support, assigned by experts. |
| `supports_claim` | Boolean or null | True only if faithful to the PDF and supportive of all assigned claims; null while pending. |
| `page_checks` | list of page-check objects | One per cited page. |
| `reason` | string | Expert explanation, including OCR concerns. |
| `page_checks[].page_number` | positive integer | Cited physical PDF page. |
| `page_checks[].correct` | Boolean or null | Whether the citation is correct; null while pending. |

Each resolution check:

| Field | Type | Meaning |
| --- | --- | --- |
| `issue_id` | string | Initially open issue V marked resolved. |
| `justified` | Boolean or null | Expert judgment of the claimed resolution; null while pending. |
| `reason` | string | Explanation addressing the issue's grouped concerns. |
