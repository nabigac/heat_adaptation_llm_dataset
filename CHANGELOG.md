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
