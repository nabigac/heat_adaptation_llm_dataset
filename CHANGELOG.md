# Structured change log

Decisions, changes, failures, and findings that explain how the workflow developed. Entries describe the setup and evidence at the time; later entries record changed decisions. Current usage is in [README.md](README.md) and [IMPLEMENTATION.MD](IMPLEMENTATION.MD).

## Categories

| Category | Covers |
| --- | --- |
| Code | Software, tools, setup. |
| Model | Models, settings, prompts. |
| Data | Sources, preparation, data format. |
| Research | Design, evaluation, interpretation. |
| Process | Review and working practices. |
| Other | Other meaningful changes. |

## Entry template

Add dated entries at the bottom. Record observed results separately from expectations; use "Not yet tested" when evidence is unavailable.

### YYYY-MM-DD — Short title

- **Category:** Code / Model / Data / Research / Process / Other
- **Problem:** What needed attention?
- **Decision/change:** What was decided or changed?
- **Reason:** Why?
- **Observed result:** What was observed or learned?
- **Remaining questions:** What remains unresolved? Use "None" if complete.

## Entries

### 2026-11-18 — Build the workflow through the first extraction

- **Category:** Code
- **Problem:** The old workflow did not match the action-focused study.
- **Decision/change:** Retrospective through 2026-11-16: implemented `add_plan`, `update_plan_data`, `prepare_plan`, `run_extract_mode`, and `list_plans`. Adopted `plan_data.metadata`, `plan_data.actions`, and `plan_issues.issues`; reset earlier study artifacts before fresh extraction. Initial inference used Qwen3.5 27B through local Ollama with MCP tools and preserved execution evidence.
- **Reason:** Python manages execution and validation; LLMs interpret sources; experts assess accuracy.
- **Observed result:** 1,733 tests passed, with 11 dependency warnings. Freetown preparation had 46 pages and status `ready_with_gaps`. Run `0001` (commit `3488cdd`) succeeded without repairs in about 17 minutes: 12 action records, 76 evidence passages, no reported issues. Review found grouping, status, and quotation errors.
- **Remaining questions:** Formal expert assessment and later workflow stages remained pending.

### 2026-11-18 — Clarify activity grouping, status, and quotation prompts

- **Category:** Model
- **Problem:** Run `0001` bundled distinct activities, overstated completion, and altered quotations. One omission occurred despite correct prepared native text, identifying a generation error.
- **Decision/change:** Refined the three extractor prompt files: separate distinct activities, combine repeated occurrences, default status to `unspecified`, and require continuous verbatim quotations with every relevant physical page. `find_quote` checks uncertain wording within the existing budget. Schemas and execution code were unchanged.
- **Reason:** Clarify coding decisions in response to observed errors.
- **Observed result:** 90 affected tests passed; revised prompts loaded with unchanged source text, and all 78 original-run files were preserved. No extraction was launched at this step; the quality effect was **Not yet tested**.
- **Remaining questions:** Assess grouping, status, and quotation fidelity on subsequent development outputs.

### 2026-11-18 — Review revised extraction and pilot Hugging Face

- **Category:** Model
- **Problem:** Local Qwen3.5 27B run `0002` separated the competition and ambassador training, but quotation and status problems remained after prompt refinement.
- **Decision/change:** Added a Hugging Face adapter to pilot the larger open-weight `Qwen/Qwen3.5-397B-A17B`, pinned to Novita, using the same prepared plan, prompts, local tools, and Python validation. After run `0003` failed, selected JSON-object mode with the target schema in the instructions for the next attempt.
- **Reason:** Test whether a larger model could improve extraction without local hardware constraints.
- **Observed result:** Run `0002` succeeded in about 18 minutes with 13 action records and two open issues. Run `0003` completed two investigation requests and ten quotation lookups, then failed with HTTP 400: Novita rejected `json_schema` and reported support for `json_object`. No final dataset was accepted.
- **Remaining questions:** Hosted extraction quality was **Not yet tested**; JSON-object mode still needed checks for output validity and token-limit behavior.

### 2026-11-18 — Hosted JSON output fails budget and schema checks

- **Category:** Model
- **Problem:** Hosted Qwen3.5-397B-A17B/Novita run `0004` exceeded its requested output limit.
- **Decision/change:** Inspected the preserved response offline, without changing settings or launching another extraction.
- **Reason:** Check whether token usage was the only obstacle.
- **Observed result:** Normal completion reported 18,052 output tokens against a 16,384 limit. The JSON also contained two unexpected fields; relaxing the token guard would still leave an invalid answer. Reported cost across three requests was about $0.12.
- **Remaining questions:** Provider limit enforcement and strict-schema compatibility; the following entry records the hosting/model change.

### 2026-11-18 — Select Inkling 2 Small through Hugging Face

- **Category:** Model
- **Problem:** Hosted Qwen attempts failed acceptance; local outputs had content and quotation problems.
- **Decision/change:** Selected Inkling 2 Small (`thinkingmachines/Inkling-2-Small`) through Hugging Face, pinned to DeepInfra, for E and the shared E+V starting output. A different hosted verifier remains unselected. Set 32,768 output tokens per request and added fictional-input compatibility checks. The DeepInfra generation copy omits `uniqueItems` and conditional issue rules; Python retains all acceptance checks. Removed active local inference, local token counting, obsolete Qwen/Novita profiles, and unused dependencies. Kept local PDF processing, EasyOCR, and MCP tools; preserved earlier artifacts and historical loading.
- **Reason:** DeepInfra rejected `uniqueItems`. Schema adaptation enabled compatibility, and the Inkling pilot supported further development. Provider and generation differences prevent attributing gains solely to the model.
- **Observed result:** All three Inkling checks passed, including the 64-token probe. Freetown `0005` succeeded without repairs in 193 seconds: 14 action records, one claimed resolved issue, about $0.082 reported cost. A whitespace-normalized quotation screen matched 61/62 passages to cited prepared text, versus 21/76 and 27/49 in local runs; this is not evidence-adequacy scoring. Review found better mapping coverage, campaign status, and Kroobay detail associations. Run `0002` shared the initial source/prompts. The cleanup passed 1,643 tests with 11 OCR dependency warnings; 723 preserved files were unchanged and all five records loaded.
- **Remaining questions:** An altered quotation, incomplete evidence, and a false claim that denied OCR requests executed still need review. Resident-advice eligibility, the second development plan, formal assessment, and verifier implementation remain pending.

### 2026-11-18 — Clarify hosted execution and implementation guide

- **Category:** Code
- **Problem:** Duplicate request preparation, dense API handling, and repeated documentation obscured the workflow.
- **Decision/change:** Reuse one prepared request for recording, budgeting, and sending; add named helpers and boundary comments; reject malformed response metadata while preserving raw evidence and valid failed records. Reorganize IMPLEMENTATION.MD around the file directory and linked contracts. Shorten this log and align model, hosting, OCR, tool-budget, and stage descriptions across project documents.
- **Reason:** Improve traceability and readability while retaining the selected extraction setup.
- **Observed result:** 1,660 tests passed, with 11 OCR dependency warnings. Four offline request comparisons retained identical bytes, routing, timeouts, and estimates. All 734 preservation-baseline files were unchanged; all five historical runs loaded. The implementation guide was roughly halved. No paid calls were made.
- **Remaining questions:** Formal extraction-quality assessment and the different hosted verifier remain pending.

### 2026-11-19 — Add Paris and increase the extraction output allowance

- **Category:** Data / Model
- **Problem:** The workflow needed testing on a second development plan; Paris extraction stopped at its output limit.
- **Decision/change:** Registered and prepared Paris (`plan_0002`), reran Freetown, and attempted Paris extraction with Inkling 2 Small through Hugging Face/DeepInfra. Increased the output allowance from 32,768 to 131,072 tokens per request and aligned the implementation guide and tests.
- **Reason:** Allow more space for reasoning, actions, and supporting quotations.
- **Observed result:** Paris preparation preserved 92 physical PDF pages with status `ready_with_gaps`; spread spot checks confirmed numbering, with OCR limitations remaining. Freetown `0006` succeeded with 14 actions and five issues. Paris `0001` reached 32,768 output tokens, including 21,487 reasoning tokens, and its incomplete JSON was rejected. The allowance update passed 271 focused tests and offline capacity checks for both plans; existing runs were preserved.
- **Remaining questions:** Higher-allowance rerun results are pending; formal extraction quality is **Not yet tested**.

### 2026-11-19 — Complete and review both development extractions

- **Category:** Model / Research
- **Problem:** Both development plans needed complete extractions and preliminary review after increasing the output allowance.
- **Decision/change:** Reran Freetown (`plan_0001`, `0008`) and Paris (`plan_0002`, `0002`) with the updated hosted workflow and 131,072-token output allowance. Reviewed outputs against prepared text, tool results, and selected PDF pages.
- **Reason:** Confirm execution and identify errors to inform verifier development.
- **Observed result:** Both succeeded without repairs. Freetown returned 14 actions and five open issues in 4m 40s (about $0.073); Paris returned 36 actions and five open issues in 14m 16s (about $0.230). Costs are API-reported. Freetown covered the main pathways but retained citation, quotation, and evidence gaps. Paris omitted a heat-monitoring programme and showed bundled activities, incorrect detail associations, status problems, and incomplete evidence. These are preliminary findings, not formal quality scores.
- **Remaining questions:** Independent references, formal quality assessment, and verifier performance are **Not yet tested**.

### 2026-11-19 — Select DeepSeek V4.1 Flash 1017 as verifier

- **Category:** Model / Code
- **Problem:** E+V needed a different, affordable reasoning model to check and revise Inkling extractions.
- **Decision/change:** Selected `deepseek-ai/DeepSeek-V4.1-Flash-1017` through Hugging Face, pinned to DeepInfra. Added a diagnostic model override and fictional tool round trip, plus a narrow fix accepting the documented response alias for this exact checkpoint. Inkling remains the extractor; the verifier profile and runner remain planned.
- **Reason:** Low listed token prices and strong author-reported reasoning and agent benchmark results motivated the selection; they do not establish verification quality. See the [model card](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017) and [provider listing](https://deepinfra.com/deepseek-ai/DeepSeek-V4.1-Flash-1017/api).
- **Observed result:** All five live compatibility checks passed: strict JSON, project schema, short output-limit probe, tool call, and result replay. API-reported cost was about $0.00083, with about 11 seconds across model requests. The focused adapter/diagnostic suite passed 123 tests. The initial alias-mismatch failure was preserved.
- **Remaining questions:** Whole-plan capacity, acceptance of a 131,072-token output allowance, and verifier quality are **Not yet tested**. Implement the verifier and pilot it on both development plans.

### 2026-11-19 — Build verification and pilot Freetown

- **Category:** Code / Model
- **Problem:** E+V needed an implemented verifier operating on an exact saved extraction.
- **Decision/change:** Added the DeepSeek profile and prompt, validated E selection, shared API/tool execution, `run_verify_mode`, issue-continuity checks, and separate V records with preserved E/source snapshots. Selection defaults to the latest eligible successful E; retries retain their original input.
- **Reason:** Check the whole answer, including unflagged content and possible omissions, while preserving the baseline for comparison.
- **Observed result:** Freetown `run_verify_0001`, using `run_extract_0008`, succeeded without Python repairs in 3m 55s: 14 actions, 70 quotations, four open issues, and two claimed resolutions. Ten tool calls executed; two excess requests were denied. Preliminary review found quotation/page improvements and a new wrong-page campaign citation.
- **Remaining questions:** Resolution claims need expert assessment; formal verifier quality and Paris verification remain pending.

### 2026-11-19 — Increase tool calls and repeat Freetown verification

- **Category:** Model / Code
- **Problem:** The first verifier exhausted its tool allowance and still introduced a citation error.
- **Decision/change:** Increased both E and V ceilings from 10 to 20 document-tool calls, refreshed remaining-budget instructions each turn, and strengthened final source-page checks. The output allowance stayed at 131,072 tokens per request.
- **Reason:** Allow more source inspection and make remaining calls and citation requirements clear.
- **Observed result:** `run_verify_0002` independently checked the same `run_extract_0008` and succeeded without Python repairs in 5m 40s: 14 actions, 89 quotations, five open issues, and two new claimed resolutions. All 20 calls executed with none denied. Review found useful detail/evidence corrections but three wrong-page quotations; source gaps remained.
- **Remaining questions:** More tool calls did not eliminate citation errors. Prompt and budget changes were tested together, so their separate effects are unknown; formal quality assessment remains pending.

### 2026-11-19 — Add Python quotation checks and citation correction

- **Category:** Code / Research
- **Problem:** Incorrect physical-page citations persisted despite model source-checking instructions.
- **Decision/change:** Added quotation diagnostics and conservative citation correction after E and V. A single citation changes only when its available cited text does not match and the complete quotation uniquely matches another physical page after whitespace normalization. Raw responses, corrected candidates, and repairs are preserved; corrected answers are validated again. Ambiguous cases remain flagged.
- **Reason:** Correct qualifying location errors consistently without additional model calls or changes to quotation wording and issue statuses.
- **Observed result:** The focused regression suite passed 464 tests; 12 follow-up boundary/context checks passed. Read-only replay corrected all three known Freetown V2 page mismatches in memory, leaving two unmatched quotations. Historical artifacts remained unchanged; no paid requests were made for this implementation.
- **Remaining questions:** New live runs with automatic correction are **Not yet tested**. Unmatched wording, source fidelity, and evidence adequacy still require review.

### 2026-11-20 — Handle early JSON drafts before final generation

- **Category:** Code
- **Problem:** Paris `run_verify_0001` returned a JSON answer during investigation instead of the readiness signal, so execution stopped before the schema-constrained final request.
- **Decision/change:** Added early JSON draft handling to the shared E/V controller. A normally completed, recognizable JSON draft can now end investigation; it is preserved but not accepted. The same model then receives the existing final request with tools disabled and the required schema. The two stages already existed; their transition changed while final acceptance checks stayed strict.
- **Reason:** Handle premature answers without bypassing validation or repeatedly regenerating failed final answers.
- **Observed result:** 328 regression tests passed. Paris `run_verify_0002`, retrying from the same `run_extract_0002`, submitted a draft on request 3 and completed final generation on request 4. It succeeded in 7m 1s with 41 actions. Quotation checks matched 63 of 121 passages, flagged 58 as unmatched, and made no page corrections. Earlier runs were preserved.
- **Remaining questions:** Review revised actions and unmatched quotations against the PDF; successful execution does not establish quality. Early drafts can consume more tokens than a short readiness signal.

### 2026-11-20 — Refine shared coding and verifier review prompts

- **Category:** Model
- **Problem:** Paris review found possible duplicate activities, incorrect date associations, quotation gaps, and an eligible activity left uncoded because quotation recovery was difficult.
- **Decision/change:** Clarified activity-based grouping, source links for quantities and dates, faithful quotation handling, inclusion despite unresolved evidence gaps, and agreement between issues and final fields. The verifier now explicitly checks inherited evidence as well as additions and revisions.
- **Reason:** Better represent the study's coding rules and address observed errors without adding plan-specific instructions.
- **Observed result:** 174 focused tests and offline input checks passed; model settings and saved runs were preserved. Quality effects are **Not yet tested**.
- **Remaining questions:** Whether subsequent outputs improve grouping, completeness, and source fidelity.

### 2026-11-20 — Retry Paris verification after a connection failure

- **Category:** Process / Code
- **Problem:** Paris `run_verify_0003` failed with `peer closed connection without sending complete message body (incomplete chunked read)`.
- **Decision/change:** Preserved the failure and started manual retry `run_verify_0004` using the same `run_extract_0002` and settings.
- **Reason:** An upstream hosting/router timeout, service interruption, or network interruption could explain the closure; the cause is unconfirmed.
- **Observed result:** Run `0003` stopped after 5m 13s on its first request, below the configured 30-minute timeout. HTTP 200 was received, but the body contained only whitespace; no tools ran or usable answer or token usage arrived.
- **Remaining questions:** Retry `0004` was still running at this entry. Whether the connection failure recurs and where it originates remain unresolved.

### 2026-11-20 — Refine quotation guidance and review repeated Paris verification

- **Category:** Model / Research
- **Problem:** Paris retry `0004` succeeded but split 137 draft excerpts into 361 fragments. Later review found persistent omissions and a premature issue resolution.
- **Decision/change:** Clarified quotation continuity, context, search snippets, and preservation of checked draft excerpts in shared guidance and final instructions. Added section-by-section verifier omission review and source-supported discrepancy resolution. Agreed to keep the current prompts stable.
- **Reason:** Address observed errors and consolidate findings before further prompt tuning.
- **Observed result:** Paris `0004`–`0006` independently used `run_extract_0002` and unchanged model settings; all succeeded without Python repairs. After the quotation revision, `0005` kept 122 excerpts without tiny fragments. After the coverage/resolution revision, `0006` kept 130, left the courtyard discrepancy open, and added runoff-water cooling. Whitespace-normalized matches rose from 66/122 to 100/130; these are diagnostics, not evidence-adequacy scores. Runtime rose from 8m to 14m 5s and API-reported cost from about $0.066 to $0.129. Offline checks passed 174 then 126 tests, plus both-plan input checks.
- **Remaining questions:** Omissions, bundling, quotation errors, and unstable statuses persist; `0006` described planned bathing sites as already opened. Individual repeats and differing tool activity do not isolate prompt effects. Expert reference scoring and confirmation of claimed resolutions remain pending.

### 2026-11-21 — Add expert reference forms and validation

- **Category:** Code / Research
- **Problem:** The study needed a clear expert reference format and practical checks before manual assessment.
- **Decision/change:** Defined one `expert_reference.json` per plan and added `create_expert_reference` and `validate_expert_reference`. Forms live in `expert_references/<plan_id>/`, excluded from Git, with expert identity and shared metadata/action/evidence fields. Creation supplies collection metadata and empty actions and refuses overwrites. Read-only validation checks JSON, fields, registration links, unique action IDs, and physical PDF page bounds. Removed the unused `examples/` folder and aligned documentation.
- **Reason:** Support manual comparison against one independent expert form completed from the PDF before viewing comparison outputs. Separate initial/final reference versions and assessment JSON files were removed from the planned workflow.
- **Observed result:** 836 focused/regression tests passed; existing PDFs, preparations, and runs were preserved. No API requests were made. Validation establishes technical consistency; empty actions are flagged, and experts establish accuracy and completeness.
- **Remaining questions:** Real-plan reference completion and the manual assessment pilot are **Not yet tested**.

### 2026-11-21 — Plan collaboration with a GLM coordinator

- **Category:** Research / Model
- **Problem:** E/E+V examines sequential verification but does not test dynamic coordination among agents.
- **Decision/change:** Added C as study stage 4, with `zai-org/GLM-5.3-Flash` selected through Hugging Face/DeepInfra to coordinate Inkling and DeepSeek. Planned `run_collaboration_mode` starts independently from the same prepared plan. The coordinator assigns parallel or dependent tasks, requests follow-up, reconciles findings, and produces complete JSON. The protocol defines shared guidance, messages, draft ownership, global budgets, stopping/failure rules, and saved evidence. All three outputs use the same expert reference and quality measures; E-issue resolution confirmation remains specific to E+V.
- **Reason:** Explore whether coordinated collaboration improves extraction and evidence quality, with its computational tradeoffs. GLM's low listed cost, long context, and listed tool/structured-output support motivated selection. Comparisons assess the complete workflow, including model and computation differences.
- **Observed result:** DESIGN.md and IMPLEMENTATION.MD were updated and 47 local links checked. C's command, profiles, and runtime remain unimplemented; GLM compatibility and coordination quality are **Not yet tested**.
- **Remaining questions:** Check GLM compatibility, establish numerical budgets, implement/test C, and pilot it on Freetown and Paris before freezing comparison settings.

### 2026-11-22 — Unify hosted compatibility and test the collaboration controller

- **Category:** Code / Model
- **Problem:** GLM returned a different model identifier and rejected the project schema; C also needed executable coordination and budget controls.
- **Decision/change:** Added the exact GLM response alias and a shared DeepInfra schema representation for Inkling, DeepSeek, and GLM, flattening the known issue-resolver constraint while retaining full Python validation. Added coordinator and flexible-worker profiles/prompts, C contracts, source-only input, parallel delegation, versioned drafts, and shared limits: 12 model requests including final generation, 20 document-tool calls per agent/60 overall, and 90 minutes. Added a separate controlled-worker diagnostic; raised only its output allowance from 4,096 to 16,384 tokens, retaining the main profiles' 131,072 allowance.
- **Reason:** Use consistent hosted interfaces and test coordination before connecting live workers and real plans.
- **Observed result:** All three models passed five compatibility checks. Offline controller/contract checks passed; the latest diagnostic/adapter regression suite passed 136 tests. The first coordination check truncated; the second completed but altered two final quotations. An unchanged repeat passed all eight checks, with four matching quotations, five GLM requests, and a runtime of 175 seconds. Earlier artifacts were preserved.
- **Remaining questions:** The quotation failure shows variability despite the successful repeat. Saved C runs, MCP integration, and the CLI remain pending; live worker coordination and full-plan quality are **Not yet tested**.

### 2026-11-22 — Add saved collaboration execution and refine its controls

- **Category:** Code / Model
- **Problem:** C needed saved real-plan execution; its first attempts exposed coordination and worker-response problems.
- **Decision/change:** Added `run_collaboration_mode` with preserved source, requests, worker findings, drafts, tools, and validation records. Allowed delegation alongside document tools, restricted worker action links to accepted IDs, and enabled reserved final assembly from both validated worker results without an intermediate draft. Later increased the shared API-request ceiling from 12 to 21, including final generation; document-tool limits remain 20 per agent/60 overall.
- **Reason:** Support traceable collaboration while retaining strict validation and allowing more investigation.
- **Observed result:** Freetown C `0001` failed on mixed tool calls; `0002` failed on an unknown worker action link. Targeted fixes passed offline checks, and earlier runs were preserved.
- **Remaining questions:** Live execution with the 21-request allowance and collaboration on Paris are **Not yet tested**.

### 2026-11-22 — Refine collaboration prompts and handle combined readiness replies

- **Category:** Model / Code
- **Problem:** Freetown C review found quotation typography differences and a questionable completion status. Run `0004` later failed when DeepSeek combined the readiness signal with a fenced JSON draft.
- **Decision/change:** Refined C prompts to preserve exact quotation characters, check the whole grouped activity's status, keep initial investigations focused, and prioritize targeted cross-checks when budget remains. Added shared recognition of readiness followed by one JSON draft, optionally fenced, for E/V and C workers. Original replies remain preserved, and a separate schema-constrained final response is still required. Updated the implementation guide; budgets and acceptance rules were unchanged.
- **Reason:** Improve source fidelity and handle investigation-to-final transitions consistently.
- **Observed result:** Run `0004` reached cross-checking but failed after 18 of 21 model requests. Its enclosed draft passed structural checks in a read-only review. The fix passed 156 offline tests and saved-response replay with a controlled final reply. All 6,371 existing research files were unchanged.
- **Remaining questions:** Successful live execution after the fix and the prompt refinements' effects on output quality are **Not yet tested**. Expert assessment remains pending.

### 2026-11-22 — Standardize configuration execution time

- **Category:** Code / Research
- **Problem:** C had an overall deadline while E/V only had individual request timeouts.
- **Decision/change:** Applied a 90-minute ceiling per complete configuration. V deducts its linked E duration, excluding the human wait between commands. New E/V runs save the calculation and clip requests to remaining time. Updated documentation; historical settings remain unchanged.
- **Reason:** Apply a consistent operational stopping rule.
- **Observed result:** Freetown C `0005` succeeded with 14 activity groups and two independent follow-up checks, using 21 requests in 28m59s at about $0.196. The deadline update passed 2,217 tests with 11 existing OCR warnings. Both plans passed offline input checks, and historical records remained readable.
- **Remaining questions:** Live E/V enforcement is **Not yet tested**. Total API/tool allowances remain different, so the common deadline does not establish equal computation. Expert quality assessment remains pending.

### 2026-11-23 — Generalize the investigation handoff after the Paris failure

- **Category:** Code / Model
- **Problem:** Paris C `0001` failed after five requests when Inkling returned ordinary readiness prose that Python attempted to parse as JSON.
- **Decision/change:** A normally completed, nonempty reply without tool calls now ends investigation in E/V and C workers. Original replies remain unvalidated; a separate strict final response is required. Budgets and final acceptance checks were unchanged, and the implementation guide was updated.
- **Reason:** Handle intermediate wording consistently without depending on a particular signal or JSON format.
- **Observed result:** 271 focused tests and offline saved-response replay with a controlled final reply passed. Existing research files were preserved. Retry `0002` was recorded as running at the time of this entry.
- **Remaining questions:** The retry's outcome and output quality are pending; successful live Paris completion after this fix is **Not yet tested**.

### 2026-11-23 — Review Paris collaboration and standardize execution controls

- **Category:** Code / Model / Research
- **Problem:** Paris collaboration review exposed grouping, coverage, and quotation gaps; profile discovery and execution controls needed alignment.
- **Decision/change:** Renamed C to `glm5_3_flash_hf_collaboration`, added `list_profiles`, and refined C prompts for grouping, heat eligibility, whole-plan coverage, provisional drafts, and faithful quotations. Set 25 API requests per E/V stage and 25 shared for C, with 25 document tools per stage/agent. Retained 90 minutes overall, protected 30 minutes for the final answer, and added a common 31,457,280 estimated-token ceiling. V debits its linked E's duration/estimates and requires E to finish within 60 minutes. Consolidated documentation and remaining work.
- **Reason:** Respond to observed errors and make limits reproducible while comparing complete workflows with different resource allowances.
- **Observed result:** Paris C `0002` succeeded under the earlier 21-request ceiling in 38m36s. Review of its 77 records and 85 unmatched quotation flags identified grouping and omission concerns. The budget update passed 2,283 tests with 11 existing OCR warnings; both plans passed offline budget checks, historical records remained readable, and research files were preserved. No paid requests were launched for these updates.
- **Remaining questions:** The latest C prompts and current budgets are **Not yet tested** in live runs. Expert assessment, metrics, formal comparison controls, C curation validation, and instruction export remain pending.

### 2026-11-23 — Support C curation and guided expert references

- **Category:** Code / Data
- **Problem:** Curated-answer validation rejected C identities, and empty reference forms offered little guidance for manual coding.
- **Decision/change:** Extended curation validation to C worker/coordinator identities and expert resolutions while retaining workflow-specific rules. Added guided action/issue starters, unfinished-guidance checks, and `edit_expert_reference` with default removal of untouched blanks or removal by ID. Reference issues use expert identities. Updated README, IMPLEMENTATION, and DESIGN.
- **Reason:** Support expert coding and curation before instruction export while preserving assessed model outputs.
- **Observed result:** The C curation update passed 2,378 tests with 11 existing OCR/PyTorch warnings; all 25 saved records loaded. The reference update then passed 770 focused tests. Freetown's empty form was recreated with one guided action and issue; an installed-CLI add/remove round trip preserved that starter and 32 registry, source, preparation, and output files. No paid requests were made.
- **Remaining questions:** The latest C prompts and budgets are **Not yet tested** in live study runs. Reference completion, manual assessment, metrics, formal comparison controls, and instruction export remain pending.

### 2026-11-23 — Enforce C deadlines and stabilize expert references

- **Category:** Code / Model / Data / Research
- **Problem:** C could recover from submitted tool timeouts, omitted reference issues bypassed checks, shared role guidance was ambiguous, and deleted reference IDs could be reused.
- **Decision/change:** Reused E/V's complete-request timeout handling in C, preserving failure and late-reply evidence and stopping further model requests. Ordinary source/OCR errors remain recoverable. Unified reference evidence/type-to-issue checks for omitted and empty issue containers, clarified shared answer/worker formats and issue roles, and added persistent ID counters plus `freeze_expert_reference` with named reviewer confirmation and reference/PDF fingerprints. Updated README, IMPLEMENTATION, and DESIGN.
- **Reason:** Preserve execution stopping rules and stable reference identities before assessment.
- **Observed result:** Full regression passed 2,485 tests with 11 existing OCR/PyTorch warnings; 97 reference checks passed after the final counter refinement. All 25 historical runs loaded, and read-only checks preserved 9,422 research files. Both development C inputs included the updated guidance for all three roles. Documentation checks passed for 91 local links/anchors, 12 CLI examples, and the reference/freeze format tables against their schemas. Freetown remains an unfrozen guided draft. No paid requests were made.
- **Remaining questions:** The shared guidance's effect on model quality and live execution under the latest settings are **Not yet tested**. Reference completion, assessment, metrics, formal comparison controls, and instruction export remain pending.

### 2026-11-24 — Create assessment review files and move references under data

- **Category:** Code / Data / Research
- **Problem:** Manual assessment lacked generated review inputs, and expert references lived outside the data directory.
- **Decision/change:** Agreed CSV judgments with generated JSON metadata and future JSON results/CSV summaries. Added `create_assessment` with latest validated successful E, linked V, and same-preparation C defaults, explicit run overrides, reviewer identities, input fingerprints, and three prefilled CSVs with blank judgments. Moved reference commands and existing files to `data/expert_references/`; assessments use `data/assessments/`. Preserved historical freeze bytes/path provenance and excluded both directories from Git. Updated README, IMPLEMENTATION, and DESIGN.
- **Reason:** Prepare reproducible manual review inputs while keeping research files together and preserving independent references and assessed outputs.
- **Observed result:** Full regression passed 2,529 tests with 11 existing OCR/PyTorch warnings, including 36 assessment-creation and 7 migration tests. Freetown's guided reference moved byte-for-byte and remains unfrozen. All 25 historical records loaded, and read-only defaults resolved compatible runs for both development plans. Documentation checks passed for 94 local links/anchors, 13 CLI examples, and format tables against their schemas. No paid requests were made.
- **Remaining questions:** CSV validation, metric calculation, failure-reporting scope, manual review, formal comparison controls, and instruction export remain pending. Assessment with a completed real expert reference is **Not yet tested**.

### 2026-11-24 — Validate assessment records and review completion

- **Category:** Code / Data / Research
- **Problem:** Saved manual review CSVs lacked checks before metric calculation.
- **Decision/change:** Added read-only `validate_assessment` with exact input/source checks, strict CSV/JSON parsing, configuration-specific links, reference-row and output-group coverage, eligible V-resolution checks, and consistent judgments. Blank or undetermined judgments remain pending; `--require-complete` requires settled review. Parsed judgments and assessment-file fingerprints are available in memory for later calculations. Updated README, IMPLEMENTATION, DESIGN, and the workflow diagram.
- **Reason:** Preserve selected evidence and scoring denominators while distinguishing unfinished review from invalid records.
- **Observed result:** Full regression passed 2,639 tests with 11 existing OCR/PyTorch warnings, including 110 new assessment-validation tests covering pending/completed reviews, regrouping, empty outputs, damaged files, changed inputs, and CLI exit codes. Checks passed for 95 local links/anchors and 16 README CLI examples; all 25 historical run records loaded. Freetown's reference remains unchanged and unfrozen, and no real assessments or paid requests were created.
- **Remaining questions:** Metric calculation, failure-reporting scope, real-plan manual review, formal comparison controls, and instruction export remain pending. Scientific assessment with completed real references is **Not yet tested**.

### 2026-11-24 — Calculate and preserve per-plan assessment metrics

- **Category:** Code / Data / Research
- **Problem:** Validated judgments had no calculation or export workflow.
- **Decision/change:** Added development `calculate_metrics` with reference scores, reviewed activity counts/evidence percentages, open issues, confirmed/claimed V resolutions, runtime/tokens, and E+V minus E / C minus E+V changes. Results preserve pending, unavailable, and not-applicable states with counts, denominators, units, and reasons. Each numbered export retains JSON results, a CSV summary, exact review-file copies, and calculation code/schema/dependency snapshots. Added optional strict manual-completion checks, result-schema validation, and input/code rechecks before publication. Updated README, IMPLEMENTATION, DESIGN, and the workflow diagram.
- **Reason:** Make agreed per-plan calculations reproducible without replacing expert judgments or overwriting earlier results.
- **Observed result:** All 323 related assessment, CLI, reference-freeze, and migration regression tests passed, including 40 new metric tests. Checks covered the design's 70% example, grouping denominators, paired directions/units, shared E+V costs, C parallel timing and token totals, missing observations, pending judgments, zero denominators, preserved recalculations, and interrupted publication. Documentation checks passed for 97 local links/anchors and 17 CLI examples. Freetown's reference remains unchanged and unfrozen; no real assessments or paid model requests were created.
- **Remaining questions:** Failure-reporting scope/counts, cross-plan aggregation, the real-plan manual assessment pilot, formal comparison controls, and instruction export remain pending. Scientific results from completed real references are **Not yet tested**.

### 2026-11-24 — Summarize selected plan metrics

- **Category:** Code / Data / Research
- **Problem:** Saved per-plan results lacked a combined study report.
- **Decision/change:** Added `summarize_metrics` with explicit saved-result selections, one calculation per plan, compatible-method checks, package fingerprints, and recalculation from archived judgments. Percentages and paired changes use equal-plan means; counts/resources use labelled totals. Each measure records contributing/excluded plans and preserves pending/unavailable values. Reports retain JSON/CSV, selected result copies, and calculation code under numbered `data/reports/` folders, excluded from Git. Shared assessment validation now supports archived inputs, and metric rows are reused across exports. Updated README, IMPLEMENTATION, DESIGN, and the workflow diagram.
- **Reason:** Make study summaries reproducible while keeping plan weighting, paired eligibility, and missing observations explicit.
- **Observed result:** All 369 related summary, metric, assessment, CLI, reference-freeze, and migration regression tests passed, including 46 summary tests. Checks covered unequal plan sizes, different contributing sets, paired changes, zero/missing values, archived recalculation, changed files, duplicate selections, two distinct fictional source packages, and preserved/interrupted reports. Documentation checks passed for 99 local links/anchors and 18 CLI examples. Freetown's reference remains unchanged and unfrozen; no real assessments/reports or paid model requests were created.
- **Remaining questions:** Failure-reporting scope/counts, the real-plan assessment pilot, formal comparison controls, and instruction export remain pending. Scientific cross-plan results from completed real assessments are **Not yet tested**.
