# Structured change log

Dated decisions, changes, failures, and findings from development. Entries describe the setup and evidence at the time. Current study methods and commands are in [DESIGN.md](DESIGN.md), [README.md](README.md), and [IMPLEMENTATION.MD](IMPLEMENTATION.MD).

[2026-11-18](#2026-11-18) · [2026-11-19](#2026-11-19) · [2026-11-20](#2026-11-20) · [2026-11-21](#2026-11-21) · [2026-11-22](#2026-11-22) · [2026-11-23](#2026-11-23) · [2026-11-24](#2026-11-24) · [2026-11-25](#2026-11-25)

<details>
<summary>Categories and entry template</summary>

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

Add dated entries to the matching date group. Record observed results separately from expectations; use "Not yet tested" when evidence is unavailable.

### YYYY-MM-DD — Short title

- **Category:** Code / Model / Data / Research / Process / Other
- **Problem:** What needed attention?
- **Decision/change:** What was decided or changed?
- **Reason:** Why?
- **Observed result:** What was observed or learned?
- **Remaining questions:** What remains unresolved? Use "None" if complete.

</details>

## Entries

Related changes on the same date are grouped below. Historical labels, settings, counts, and pending work describe the state at that time; use the guides for the current workflow.

<a id="2026-11-18"></a>
<details>
<summary><strong>2026-11-18</strong> — extraction and hosted-model selection (5 entries)</summary>

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

### 2026-11-18 — Review extraction and diagnose hosted Qwen failures

- **Category:** Model
- **Problem:** Revised local extraction retained quotation/status errors; hosted Qwen attempts failed API, output-limit, and schema checks.
- **Decision/change:** Piloted `Qwen/Qwen3.5-397B-A17B` through Hugging Face/Novita with the same prepared plan, prompts, tools, and Python checks. After `0003` failed, used JSON-object mode with schema instructions for `0004`. Inspected its preserved response offline without another run or relaxed acceptance rules.
- **Reason:** Test a larger model and distinguish provider constraints from output quality. Relaxing the token guard alone would still leave invalid JSON fields.
- **Observed result:** Local `0002` succeeded in about 18 minutes with 13 actions and two open issues, separating competition and ambassador training. Hosted `0003` made two investigation requests and ten quotation lookups, then received HTTP 400 rejecting `json_schema` and reporting `json_object` support. Run `0004` completed normally but reported 18,052 output tokens against 16,384 and included two unexpected fields; cost across three requests was about $0.12. Neither hosted answer was accepted.
- **Remaining questions:** Accepted hosted extraction quality is **Not yet tested**. Provider limit enforcement and schema compatibility remained unresolved; the next entry records the model/host change.

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

</details>

<a id="2026-11-19"></a>
<details>
<summary><strong>2026-11-19</strong> — Paris, verification, and quotation checks (5 entries)</summary>

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

### 2026-11-19 — Build verification and refine source inspection

- **Category:** Code / Model
- **Problem:** E+V needed exact saved-E verification; its first pilot exhausted tool capacity and introduced a citation error.
- **Decision/change:** Added the DeepSeek profile/prompt, validated E selection, shared API/tools, `run_verify_mode`, issue continuity, and separate V records with E/source snapshots. Defaults select the latest eligible E; retries retain input. After the first pilot, raised E/V document tools from 10 to 20, refreshed remaining-budget instructions, and strengthened final page checks. Output allowance stayed at 131,072 tokens.
- **Reason:** Check inherited content and omissions while preserving E for comparison; allow more source inspection.
- **Observed result:** Both Freetown pilots independently used `run_extract_0008` and succeeded without repairs. V `0001`: 3m55s, 14 actions, 70 quotations, four open issues, two claimed resolutions, ten tools executed/two denied. V `0002`: 5m40s, 14 actions, 89 quotations, five open issues, two new claimed resolutions, all 20 tools executed. Review found useful evidence/detail corrections but one wrong-page campaign citation in the first and three wrong-page quotations in the second. Source gaps persisted.
- **Remaining questions:** More tools did not eliminate citation errors. Prompt/budget changes were combined, so their separate effects are unknown. Expert resolution assessment, formal quality scoring, and Paris verification remained pending.

### 2026-11-19 — Add Python quotation checks and citation correction

- **Category:** Code / Research
- **Problem:** Incorrect physical-page citations persisted despite model source-checking instructions.
- **Decision/change:** Added quotation diagnostics and conservative citation correction after E and V. A single citation changes only when its available cited text does not match and the complete quotation uniquely matches another physical page after whitespace normalization. Raw responses, corrected candidates, and repairs are preserved; corrected answers are validated again. Ambiguous cases remain flagged.
- **Reason:** Correct qualifying location errors consistently without additional model calls or changes to quotation wording and issue statuses.
- **Observed result:** The focused regression suite passed 464 tests; 12 follow-up boundary/context checks passed. Read-only replay corrected all three known Freetown V2 page mismatches in memory, leaving two unmatched quotations. Historical artifacts remained unchanged; no paid requests were made for this implementation.
- **Remaining questions:** New live runs with automatic correction are **Not yet tested**. Unmatched wording, source fidelity, and evidence adequacy still require review.

</details>

<a id="2026-11-20"></a>
<details>
<summary><strong>2026-11-20</strong> — handoff, prompts, and repeated verification (3 entries)</summary>

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

### 2026-11-20 — Preserve Paris connection failure and review repeated verification

- **Category:** Model / Code / Research
- **Problem:** Paris V `0003` lost its connection; retry `0004` fragmented quotations, and subsequent review found omissions and a premature issue resolution.
- **Decision/change:** Preserved `0003` and manually retried unchanged settings/E input as `0004`. Then clarified quotation continuity, context/search snippets, checked draft excerpts, section-by-section omission review, and source-supported discrepancy resolution. Agreed to keep the resulting prompts stable.
- **Reason:** Retain failure evidence and address observed errors before further tuning. The connection failure's upstream host/router/network cause remains unconfirmed.
- **Observed result:** Run `0003` stopped after 5m13s on its first request, below its 30-minute timeout: HTTP 200, whitespace-only incomplete body, no tools, usable answer, or token usage. Runs `0004`–`0006` independently used `run_extract_0002` with unchanged model settings and succeeded without repairs. Run `0004` expanded 137 draft excerpts to 361 fragments. After quotation guidance, `0005` retained 122 excerpts without tiny fragments; after coverage/resolution guidance, `0006` retained 130, left the courtyard discrepancy open, and added runoff-water cooling. Whitespace-normalized matches rose from 66/122 to 100/130, runtime from 8m to 14m5s, and reported cost from about $0.066 to $0.129. Offline checks passed 174 then 126 tests plus both-plan input checks. Matches are diagnostics, not evidence-adequacy scores.
- **Remaining questions:** Connection recurrence/origin, omissions, bundling, quotation errors, and unstable statuses remain unresolved; `0006` called planned bathing sites already opened. Repeats with differing tool activity do not isolate prompt effects. Expert scoring and confirmation of resolutions remain pending.

</details>

<a id="2026-11-21"></a>
<details>
<summary><strong>2026-11-21</strong> — expert references and collaboration planning (2 entries)</summary>

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

</details>

<a id="2026-11-22"></a>
<details>
<summary><strong>2026-11-22</strong> — collaboration execution and time controls (4 entries)</summary>

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

</details>

<a id="2026-11-23"></a>
<details>
<summary><strong>2026-11-23</strong> — collaboration review and reference identity (4 entries)</summary>

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

</details>

<a id="2026-11-24"></a>
<details>
<summary><strong>2026-11-24</strong> — assessments, metrics, summaries, and study execution (3 entries)</summary>

### 2026-11-24 — Create and validate assessment review files

- **Category:** Code / Data / Research
- **Problem:** Manual assessment lacked generated inputs, organized storage, and validation before calculation.
- **Decision/change:** Added `create_assessment` with compatible latest E/linked V/same-preparation C defaults, explicit overrides, fingerprints, generated JSON metadata, and three CSVs with blank judgments. Initially captured reviewer identities. Moved references to `data/expert_references/` and assessments to `data/assessments/`, preserving historical freeze bytes/paths and excluding both from Git. Added read-only `validate_assessment`: exact source/reference/run checks, strict CSV/JSON, links, copied context, activity coverage, eligible V resolutions, and consistent judgments. Blank/undetermined fields stay pending; `--require-complete` requires settled review. Return parsed judgments and file hashes for calculation. Updated guides/diagram.
- **Reason:** Prepare reproducible expert judgments against a shared independent reference and distinguish unfinished review from invalid data.
- **Observed result:** Creation passed 2,529 tests (36 creation/7 migration); validation then passed 2,639 (110 new validation cases), both with 11 OCR/PyTorch warnings. Cases covered pending/completed review, regrouping, empty outputs, damaged/changed inputs, and CLI codes. All 25 historical runs loaded; compatible defaults resolved for both initial plans. Reference migration preserved bytes and the unfrozen starter. Link/CLI/schema checks passed. No real assessments or paid requests were created.
- **Remaining questions:** Calculation, reporting/failure scope, manual review, comparison controls, and instruction export remained pending. Assessment against completed real references is **Not yet tested**.

### 2026-11-24 — Calculate per-plan metrics and summarize selected plans

- **Category:** Code / Data / Research
- **Problem:** Validated judgments lacked per-plan calculations and reproducible cross-plan reports.
- **Decision/change:** Added `calculate_metrics` for action scores, unsupported activities/evidence, issues/V resolutions, successful runtime/tokens, and E+V minus E / C minus E+V. Preserve counts, denominators, units/reasons, and pending/unavailable/not-applicable states. Each numbered package saves JSON/CSV, exact review inputs, and code/schema/dependencies; recheck inputs/code and optionally require completed review. Added `summarize_metrics` with explicit one-result-per-plan selections, method checks, archived-judgment recalculation, and fingerprints. Percentages/paired changes use equal-plan means; counts/resources use labelled totals with contributing/excluded plans. Preserve numbered reports, JSON/CSV, result copies, and code under the then-current `data/reports/`. Reuse shared assessment checks and metric rows. Updated guides/diagram.
- **Reason:** Reproduce agreed arithmetic and selections without replacing judgments, obscuring missingness, or overwriting earlier results.
- **Observed result:** Calculation passed 323 related tests (40 new); summaries passed 369 (46 summary cases). Checks covered the 70% example, grouping denominators, paired units, E+V costs, C parallel timing/tokens, missing/zero/pending values, unequal plan sizes, contributing sets, two fictional PDF packages, changed inputs, archived recalculation, duplicates, preserved versions, and interrupted saves. Link/CLI checks passed. Freetown's reference stayed unchanged/unfrozen; no real assessments/reports or paid requests were created.
- **Remaining questions:** Failure-reporting scope, real expert assessment, comparison controls, and instruction export remained pending. Scientific per-plan and cross-plan results are **Not yet tested**.

### 2026-11-24 — Use one comparison sample with manually tracked selections

- **Category:** Code / Data / Research
- **Problem:** Separate plan categories excluded the initial two plans; execution/reporting labels complicated one ten-plan study with manual final selections.
- **Decision/change:** Moved both registry entries into one comparison sample, refining on two first. Initially separated development/comparison run purposes, then simplified active commands/schemas to comparison throughout that day. Restored latest eligible assessment defaults with explicit overrides; record final first-successful selections/versions manually and rerun all three configurations across all ten after workflow changes. Preserve earlier runs and their original labels/bytes through a separate read-only compatibility view; reject unknown labels. Standardized operational feedback and updated guides.
- **Reason:** Use one workflow for refinement/final execution while preserving reproducibility through recorded settings, IDs, and fingerprints.
- **Observed result:** Initial sample support passed 2,748 tests (19 new cases); simplification passed 2,738 (23 archive-compatibility cases). Both included a ten-plan report with distinct fictional PDFs. All 25 historical runs loaded unchanged; preservation checks covered 9,697 then 9,698 research files, with only the authorized initial registry-membership changes. Documentation/installed-CLI checks passed after an offline editable-install refresh. No paid requests or real assessments were created.
- **Remaining questions:** E/V evidence checks, unused failure fields, real assessment, current live settings, the final run set, and curation/export remained pending. Scientific outcomes are **Not yet tested**.

</details>

<a id="2026-11-25"></a>
<details open>
<summary><strong>2026-11-25</strong> — data storage, dataset building, and validation (7 entries)</summary>

### 2026-11-25 — Simplify assessment interfaces and reporting formats

- **Category:** Code / Data / Research
- **Problem:** Assessment purpose duplicated its fixed role; unused failure fields and legacy-format adapters conflicted with the agreed study.
- **Decision/change:** Removed the assessment purpose flag/API parameters, then the metadata field (version 2). A temporary version-1 reader was added and then removed before any real assessments existed. Removed `included_attempts`, `failure_reporting`, failure-count CSV/aggregate rows, stale CLI messages, and assessment/result/report adapters; retained registry/model-run compatibility. Per-plan exports contain 44 measure rows. No further version bump/migration layer was needed. Model-run purpose flags remain. Updated schemas, tests, help, and guides.
- **Reason:** Simplify unused formats before first use while preserving selected-successful-output measures and historical run evidence.
- **Observed result:** Interface removal passed 60 related checks; metadata removal passed 271. Format cleanup passed 622 (344 registry/run and 278 assessment/metric/report checks), plus three updated CLI rechecks. Tests included ten-plan reporting, archived snapshots, current metadata, and strict validation. All 25 historical runs loaded and all 9,697 research files stayed unchanged. Link/CLI/schema checks passed; no real assessments/reports or live model requests were created.
- **Remaining questions:** None for this cleanup; real expert assessment remains pending.

### 2026-11-25 — Align E/V saved-evidence checks with C

- **Category:** Code / Research
- **Problem:** E/V storage lacked C's final-candidate and archived-code consistency checks.
- **Decision/change:** Shared both checks across E/V/C during successful finalization and loading. Accepted answers must match the report-selected raw/repaired candidate, and archived code must match its startup SHA-256 manifest. Reject missing/malformed successful-run evidence while preserving incomplete failed attempts. Updated README, IMPLEMENTATION, DESIGN, and tests.
- **Reason:** Ensure assessments use answers and code consistent with the preserved run evidence.
- **Observed result:** All 630 related checks passed across targeted and regression runs, including 74 new cases for answer/code changes, strict parsing, saved E/V finalization, and downstream assessment/report rejection. All 25 historical runs loaded, and all 9,697 research files remained unchanged. Documentation checks passed for 103 local links/anchors, 15 README commands, and metadata fields. No live model requests were made.
- **Remaining questions:** None for these two checks; source correctness remains expert assessment.

### 2026-11-25 — Clarify data storage and preserve historical paths

- **Category:** Code / Data
- **Problem:** Folder names obscured workflow stages; moving source files risked breaking recorded paths and fingerprints.
- **Decision/change:** Added `migrate_data_layout` with read-only preview, collision/symlink checks, byte verification, interrupted-move recovery, and registry-path updates. PDFs now use `data/source_pdfs/`, preparations `data/prepared_plans/`, and study artifacts `data/comparison/`. Reserved `data/dataset_building/` directories for drafts, reviewed plans, and combined action datasets. Historical source/reference paths resolve to moved files without rewriting saved JSON. Selection, links, and retries recognize equivalent source paths. Updated current writers, tests, ignore rules, README, IMPLEMENTATION, and DESIGN. Recorded `finalize_reviewed_plan` and `dataset_contents.json` as planned names.
- **Reason:** Separate shared inputs, comparison work, and later dataset building while preserving reproducibility.
- **Observed result:** Moved 149 files: two PDFs, 146 preparation/image files, and one reference. All 9,697 research files matched their original hashes at mapped locations; all 25 run objects loaded exactly unchanged. Only registry path fields changed; the starter reference remains unfrozen. All 2,829 current test cases were covered across the regression run and targeted rechecks, including 355 final path-identity checks and 15 migration cases. Two folder-depth fixture setups were corrected and passed rechecks. The main run retained 11 existing OCR/PyTorch warnings. Checks passed for 103 local links/anchors, 17 README commands, metadata fields, installed CLI listing, and an idempotent migration preview. All 36 earlier log entries were preserved. No live model requests were made.
- **Remaining questions:** Dataset-building execution, review commands, reviewed/combined-data contracts, and collection assembly remain planned. Instruction export is deferred.

### 2026-11-25 — Add dataset-building execution and protect study selections

- **Category:** Code / Data / Research
- **Problem:** Post-study execution needed a separate purpose without changing plan membership or mixing its outputs into comparison assessments.
- **Decision/change:** Enabled `--purpose dataset_building` for E/V/C on comparison or expansion plans; kept comparison as the default, requiring comparison membership. V selects only same-purpose E inputs. Retries retain purpose, and saved-run loading checks linked purposes. Assessments skip dataset-building defaults and reject explicit selections; the same gate protects validation, metrics, and reports. Updated README, IMPLEMENTATION, DESIGN, schemas, help, and tests.
- **Reason:** Support fresh runs of the chosen configuration for the original ten plans and later expansion while preserving study selections and historical evidence.
- **Observed result:** All 837 related tests passed, including 29 new cases, saved E/V/C execution, selection/retry boundaries, assessment rejection, and ten-plan reporting. All 25 historical run objects loaded unchanged; the registry and all 9,697 research files matched the pre-change contents. Checks passed for installed E/V/C help, 103 local links/anchors, 19 README commands, and all 10 assessment metadata fields. All 37 earlier entries were preserved. No live inference was performed.
- **Remaining questions:** Fresh live dataset-building execution and output quality are **Not yet tested**. Chosen-configuration tracking, review drafts, reviewed-plan finalization, and combined dataset assembly remain planned. Instruction export is deferred.

### 2026-11-25 — Add plan review lifecycle and remove name capture

- **Category:** Code / Data / Process
- **Problem:** Dataset-building outputs lacked editable review drafts and a completed clean-plan product. Reference, freezing, and assessment interfaces required unnecessary names or study IDs.
- **Decision/change:** Added `create_review_draft`, `validate_review_draft`, and `finalize_reviewed_plan` with separate draft, completion-record, and reviewed-plan schemas. Select only successful dataset-building E/E+V/C runs; preserve original issue identities and model-resolved decisions, require expert resolutions for open concerns, and retain newly raised expert issues. Check issues before writing clean metadata/actions without issue objects. Save exact draft/run copies and separate issue history, fingerprints, time, and review scope; check completed snapshots on loading and resume only matching interrupted writes. Removed `prepared_by`, `frozen_by`, and `reviewers` from current APIs/schemas and their CLI flags. Removed only `prepared_by` from Plan 0001's unfrozen reference. Updated review guidance, README, IMPLEMENTATION, and DESIGN.
- **Reason:** Separate editable work, completed review evidence, and clean data while preserving traceability without personal identifiers. Review covers remaining open issues, without claiming a full audit of the output or omissions.
- **Observed result:** All 673 related cases passed, including 65 new review cases, reference/curation checks, name-free assessments, metrics, ten-plan reports, migration, and CLI behavior. A final guidance update passed 34 focused rechecks, including saved metric/report loading. All 25 historical run objects and the registry remained unchanged; the only research-file change was the requested reference-field removal, with all other reference content preserved. Checks passed for installed command help, 107 local links/anchors, 22 README commands, and three metadata tables. All 38 earlier log entries were preserved. No live inference was performed.
- **Remaining questions:** Real-plan use is **Not yet tested**. Collection-wide configuration/version checks and `build_heat_action_dataset` remain planned; instruction export is deferred.

### 2026-11-25 — Build combined heat action datasets

- **Category:** Code / Data / Research
- **Problem:** Completed reviewed plans could not be assembled into a preserved dataset with configuration consistency and duplicate prevention.
- **Decision/change:** Added `build_heat_action_dataset --review <path>` for explicit completed review versions. Require one common recorded E/E+V/C workflow: model/provider settings, ordered prompts, tools, budgets, software-version information, and archived code. Include both linked E/V stages and all C profiles/limits. Reject duplicate plans or original PDFs. Write issue-free combined metadata/actions, `dataset_contents.json`, exact review copies, and assembly-code snapshots into a new `dataset_NNNN/`. Publish contents last, reserve interrupted versions, and validate stored packages independently of later live-review edits. Updated README, IMPLEMENTATION, DESIGN, schemas, help, and tests.
- **Reason:** Preserve source/review provenance and earlier versions while extending the heat adaptation action dataset under one recorded workflow. Plan-specific inputs and observations may differ; matching recorded values does not verify undisclosed hosted revisions.
- **Observed result:** All 228 related tests passed, including 59 new assembly cases covering E/E+V/C, completed reviews, mismatched settings/code, duplicate plans/PDFs, a ten-plan build, local action IDs, prior-version preservation, interrupted publication, changed inputs/copies/code, strict loading, and CLI/path behavior. Related review, saved-evidence, CLI, and two-plan reporting regressions passed. All 25 historical run objects, the registry, and 9,697 research files remained unchanged. Checks passed for installed help, 111 local links/anchors, 23 README commands, both new schemas, and three metadata tables. All 39 earlier entries were preserved. No live inference or real dataset builds were performed.
- **Remaining questions:** Real-plan assembly is **Not yet tested**. Pilot the full dataset-building/review/assembly workflow after study configuration selection. Instruction export and fine-tuning remain deferred.

### 2026-11-25 — Harden C validation and clarify completed-output checks

- **Category:** Code / Process
- **Problem:** C compared UTC timestamps as text and could crash on malformed saved input. Review/assembly/CLI logic was dense or duplicated, and completed-output checks lacked direct CLI commands.
- **Decision/change:** Compare parsed UTC times and reconstruct/type-check preserved C input. Share JSON/hash/path/version helpers, expose completed-review snapshots, separate validation/dispatch phases, and add focused comments/type hints. Added read-only `validate_reviewed_plan` and `validate_heat_action_dataset`, exposing checks already used during finalization/assembly. Updated guides for the current lifecycle and grouped related same-day history while preserving decisions/results.
- **Reason:** Make file consistency and completion checks easier to understand and rerun without editing data or creating versions.
- **Observed result:** The code pass completed with all 2,994 tests passing, including 28 new regression cases, and 11 OCR dependency warnings. All 25 historical runs loaded unchanged; all 9,697 research files and the registry were preserved. No live model requests were made. Documentation checks passed for 119 local links/anchors, 24 README commands, and three field tables; all 40 earlier events are retained in 32 grouped entries.
- **Remaining questions:** Current live settings, real-plan review/assembly, and final study outcomes are **Not yet tested**. Instruction export/fine-tuning remain deferred.

</details>
