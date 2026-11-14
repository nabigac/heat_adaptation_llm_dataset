# Design Doc: Heat Adaptation LLM Dataset

**Research design · updated 2026-11-14**

## 1. Context and problem

To compare how cities address heat, we need a consistent account of the actions their plans describe. Producing that account requires interpreting text and tables, combining repeated descriptions, and preserving details such as implementation status, recipients, costs, and expected benefits. An extraction can be well structured yet omit an action, misstate a detail, or cite evidence that does not support its claims.

The substantive question is **what cities document doing or planning to do about heat, and how they describe those actions**. Plans provide evidence of stated intentions and reported implementation. They do not independently establish what happened on the ground or whether an action reduced heat risk.

Large language models (LLMs) could help organize this evidence, but their outputs need to be checked against source documents and expert judgments.

## 2. Research aim and questions

This study will evaluate a workflow in which LLMs extract documented heat adaptation actions and experts assess their quality. The main contribution is an evaluated expert–LLM workflow: what it gets right, where it fails, and what expert intervention is needed. A source-linked heat adaptation action dataset is a study output.

1. How reliably can the workflow identify and describe heat adaptation actions documented in public plans?
2. How does adding an LLM verifier change action quality, supporting evidence, unresolved issues, and computational requirements?

## 3. Methods

### Eligible plans

Experts screen final, publicly available government or public-agency plans in English, published or updated in 2010 or later. Plans must address heat directly, or have a dedicated heat section with at least one action. Prioritize recent versions and require a human-readable PDF with stable page positions, including readable scans.

The intended interpretation is city heat adaptation. Before selecting comparison plans, fix whether broader county, regional, state, or national plans are eligible when they address cities. The metadata can represent these scales; supporting a value in software does not make it part of the study sample.

### Study sample

| Study set | Planned size | Purpose |
| --- | --- | --- |
| Development | 2 plans | Inspect outputs openly, refine coding and software, and pilot expert assessment. |
| Comparison | 5 separate plans | Compare extraction with and without verification against independent expert work. |
| Expansion | Deferred | Build a larger dataset after the evaluated workflow works. |

The comparison size is based on workload, not a statistical power calculation. Select varied lengths, layouts, and plan types; avoid near copies. Keep development plans out of comparison and fix the comparison selection before model runs.

### Extraction unit and action coding

The extraction unit is one distinct action in one plan. Repeated mentions do not create new actions. Counts describe documented actions under our coding rules, not adaptation effort, investment, or effectiveness. Document length, detail, and the way actions are separated affect counts; do not rank cities by counts alone.

Each output contains plan information, action records with supporting evidence, and issues requiring review. Costs and benefits are recorded with the action they describe. The appendix specifies the complete output format.

Coding means assigning source information to defined fields and categories. Include a specific intervention or activity explicitly connected to reducing heat risks or enabling heat adaptation. A heat-specific heading can establish this connection. Do not infer heat relevance from a general climate, greening, or health measure.

| Coding decision | Rule |
| --- | --- |
| Separate actions | Split distinct activities, such as planting trees and installing drinking fountains. Keep one activity's quantities, timing, conditions, and stated implementers together. |
| Repeated mentions | Combine descriptions of the same action within a plan; retain evidence for its details. Flag conflicting statements. |
| Goals | A broad aspiration alone is not an action. Keep an action's explicit target or deadline in its description. |
| Monitoring and evaluation | Include a concrete heat-related activity, such as operating a heat-health surveillance programme, as an action. Do not create a separate monitoring catalogue or treat monitoring as evidence of effectiveness. |
| Where and who | Record the stated location and intended recipients or affected groups. Recipients are not implementing agencies; include stated implementers in `action`. Do not infer either from the plan's issuing agency. |
| Costs | Preserve amounts, currency/units, periods, and whether they describe estimates, allocations, expenditure, or needs. Do not convert currency or invent allocations. |
| Benefits | Preserve outcomes, quantities, affected groups, comparisons, timing, and qualifications. Distinguish expected, modelled, and observed outcomes, including stated adverse effects. |
| Shared statements | Attach a cost or benefit only where the source connects it to the action. Explicitly label shared budgets or outcomes; repeated shared amounts must not be added together. General plan-wide statements without an action link are outside this dataset. |
| Missing details | Use `null` for unavailable descriptive fields, `unspecified` for unstated status, and an empty type list when no category can be justified. Missing information is not zero cost, no benefit, or proof that an action does not exist. |

The four action types are study coding categories, not mutually exclusive scientific classes. Assign every category supported by the action's described mechanism; do not assign additional types merely because an action could have wider effects. An action with several types still counts as one action; totals by type can overlap.

| Action type | Working definition |
| --- | --- |
| `infrastructural` | Changes to built assets, equipment, or physical services, such as cool roofs or drinking-water infrastructure. |
| `institutional` | Policies, governance, planning, financing arrangements, coordination, or formal service and monitoring systems. |
| `behavioral/cultural` | Activities intended to change knowledge, practices, routines, or cultural and social norms, such as heat-safety outreach. |
| `nature-based` | Activities using vegetation, ecosystems, or ecological processes to address heat, such as tree canopy or wetland restoration explicitly linked to heat. |

Status describes what the document reports: `planned` means proposed or committed without evidence that work has begun; `underway` means started or operating; `completed` means explicitly finished; `unspecified` means status is not established. A past deadline does not prove completion. If a reported state falls outside these four values, such as withdrawal, preserve it in `action`, use `unspecified`, and flag the coding limitation. If different phases have different states, describe that distinction rather than implying the whole action is complete.

These operational definitions should be tried on development examples before comparison, especially overlapping types, compound actions, and shared costs.

### Evidence and issues

Every action needs source evidence: exact, continuous quotations with physical PDF page numbers, starting at 1 regardless of printed labels. Separate passages need separate evidence entries; do not join them with invented ellipses. Preserve necessary headings and footnotes. Evidence must support the action's details, not merely mention the same topic.

OCR (optical character recognition) converts image text into machine-readable text and may misread words or numbers. Experts check quoted OCR against the original PDF. Unreadable material is a source gap, not proof of absence. A model's description of a chart is not a quotation.

Issues identify problems needing review. Bundle concerns about the same action into one issue; use an unlinked issue for an omission or source gap. Ordinary unstated details do not automatically need issues. A verifier retains existing issue IDs, may add issues, and explains any claimed resolution. Expert assessment determines whether that resolution is justified. Exclude unresolved unsupported material from a curated release.

### Workflow and comparison

Use open-weight models, whose trained parameters are available for download. An agent is a model in a loop that can request tools before answering. Model Context Protocol (MCP) is the interface used here to connect that loop to document tools; it is an implementation choice, not a separate experimental treatment.

| Step | Work and saved result |
| --- | --- |
| 1. Add and prepare | Preserve the PDF, collection details, page text, and preparation problems. |
| 2. Extract (E) | Supply the whole prepared plan; save actions, evidence, issues, settings, and execution records. |
| 3. Verify (E+V) | A different model checks a copy of that exact extraction against the same source, including unflagged actions and possible omissions. Save the full revised output. |
| 4. Prepare the reference | After both outputs succeed, experts independently extract from the original PDF without seeing model outputs. Save this initial reference before revealing outputs. |
| 5. Assess | Experts match actions by meaning, review additions and reference corrections, then assess both outputs against one shared final reference. Preserve the initial reference and reasons for revisions. |
| 6. Analyze | Compare paired results by plan and report practical lessons, limitations, and computational requirements. |

Use the first successful comparison extractor run and the first successful verifier run linked to it under fixed settings. Successful means execution and format checks passed; it does not mean the content is correct. Retain failed attempts and link manual retries. Deliberate repeats of successful work are exploratory and do not replace the selected output.

Fix models, prompts, preparation, tools, coding rules, and scoring before comparison. Document any later revision and do not silently combine different study setups. Both configurations share the same extraction; the comparison evaluates the tested model pair and workflow, not the isolated effect of MCP, open weights, or model family.

The action-focused protocol remains under development. [IMPLEMENTATION.MD](IMPLEMENTATION.MD) distinguishes working software from planned stages and records the development evidence; [README.md](README.md) explains available commands.

## 4. Evaluation

### Expert reference and scoring

The expert reference is an independently coded comparison dataset, not an assumption of infallible ground truth. Preserve initial matches, review supported additions, and record corrections in one shared final reference. Assess both saved outputs before making expert corrections to them.

Match actions by meaning. Several output records may cover one reference action, or one output may cover several reference actions. Count each reference action once; duplicates earn no extra credit.

| Score | Judgment about a reference action and its matched output |
| --- | --- |
| 1 | All required substantive details are correct, with no unsupported substantive additions. |
| 0.5 | Some substantive information is correct, but a required detail is wrong, missing, or unsupported. |
| 0 | No substantive information is correct, or the action is omitted. |

Action type, status, location, recipients, costs, benefits, and relevant detail in the description are assessed under the same coding rules. Correctly recording an unstated detail does not reduce the score. Assess quotations and page citations separately; plan metadata and issues are not additional actions.

### Evaluation outcomes

| Outcome | How it is assessed |
| --- | --- |
| Action coverage and correctness | Report the fully correct reference-action percentage and partial-credit score percentage. Always accompany them with counts and support judgments for distinct additions beyond the initial reference; unsupported additions do not lower a reference-based score. |
| Evidence quality | Report actions with quotations, the percentage of supplied quotation uses that faithfully support their assigned claims, and the percentage of cited pages that are correct. Missing evidence must remain visible. |
| Computational requirements | Report successful processing time, input/output tokens, and failed attempts. E+V includes the shared extractor plus verifier. Successful-run time excludes preparation, human review, and failed-attempt time; report failures separately. |
| Issues and expert intervention | Report open issues, claimed and expert-confirmed resolutions, and concrete examples of needed corrections. Issue counts do not measure expert review time. |

### Analysis and limitations

Detailed calculations and expert-file definitions are in [IMPLEMENTATION.MD](IMPLEMENTATION.MD#expert-files-and-measurement). Pending judgments remain pending, not zero. A percentage with a zero denominator is not applicable. Report per-plan counts and paired changes; summaries are descriptive given the small, selected sample.

Before comparison, pilot the action definitions and scoring with experts, resolve ambiguous examples, and agree how reviewers will handle disagreements. Expert identities are not currently recorded in the planned file format; document the assessment procedure and reviewer roles in study reporting. Extraction accuracy, OCR accuracy, and workflow benefits remain to be established empirically.

## Appendix: full output JSON specification

A **schema** defines an object's fields, types, and permitted values. An **object** groups named fields; a **list** holds zero or more items; an **enum** limits a value to named choices. `null` means unavailable, not zero.

This appendix defines the complete intended model answer and saved run object, including nested fields. It is the **action-focused target**, not the contract currently enforced by `schemas/`. Operational files and expert assessment files are documented in [IMPLEMENTATION.MD](IMPLEMENTATION.MD#appendix-supporting-json-files). The code migration must version the changed format and preserve earlier five-category runs.

All fields are required unless marked optional. Text is nonblank unless stated otherwise. Dates use `YYYY-MM-DD`; timestamps use UTC; paths are project-relative; durations are seconds. IDs must resolve within the relevant document/run, and cited pages must be within the original PDF.

### A. Model answer and content

The model returns `content` and `review` only. Python adds execution details when saving the run.

| Field | Type | Meaning |
| --- | --- | --- |
| `content` | object | Plan information and action records, defined below. |
| `review` | object | Contains the `issues` list defined in section D. |

Within `content`:

| Field | Type | Meaning |
| --- | --- | --- |
| `plan_info` | object | One plan's metadata, defined in section B. |
| `plan_actions` | list of action objects | Distinct documented heat adaptation actions, defined in section C. Empty only after checking for actions and recording any unresolved source gap. |

### B. Plan information

| Field | Type | Meaning |
| --- | --- | --- |
| `plan_title` | string or null | Title stated in the plan. |
| `jurisdiction_name` | string or null | Named jurisdiction covered by the plan. |
| `country` | string or null | Country identified by the source. |
| `plan_scale` | enum or null | `city`, `county`, `region`, `state`, or `country`; document scale, not an automatic eligibility decision. |
| `plan_type` | enum or null | `heat_specific_plan` or `broader_climate_plan`. |
| `publication_year` | integer or null | Publication or update year of this document version. |
| `lead_agencies` | list of strings | Stated lead agencies for the plan; empty if unknown. Does not establish who implements individual actions. |
| `source_url` | string | Official source URL from the selected preparation's collection metadata. |
| `date_accessed` | date string | Collection access date from the selected preparation. |
| `language` | string | `English` for the present study. |

### C. Action and evidence

| Field | Type | Meaning |
| --- | --- | --- |
| `action_id` | string | Stable local ID, such as `action_0001`. |
| `action` | string | Description of one distinct action, including stated implementers, quantities, timing, conditions, and other relevant details. |
| `action_type` | list of unique enum values | Any supported combination of `infrastructural`, `institutional`, `behavioral/cultural`, and `nature-based`. Use `[]` if no type can be justified and flag the classification uncertainty. |
| `action_status` | enum | `planned`, `underway`, `completed`, or `unspecified`, as defined in section 3. |
| `action_location` | string or null | Stated places or geographic coverage; preserve multiple locations in the description. |
| `action_recipient` | string or null | Stated intended recipients, populations, or affected groups; preserve multiple groups in the description. |
| `action_cost` | string or null | Source-linked description of amounts, currency/units, periods, cost character, and qualifications. Explicitly identify shared amounts. |
| `action_benefit` | string or null | Source-linked description of outcomes, quantities, affected groups, comparisons, timing, and qualifications, preserving whether expected, modelled, or observed. |
| `evidence` | list of evidence objects | Quotations supporting the action and its details. An empty list requires a review issue and is not acceptable for an unqualified curated record. |

Each evidence object:

| Field | Type | Meaning |
| --- | --- | --- |
| `quote` | string | Exact continuous source passage; use separate objects for separate passages. |
| `page_numbers` | nonempty list of unique positive integers | Physical PDF positions containing the passage, starting at 1. A continuous passage may span pages. |

### D. Review and issues

| Field | Type | Meaning |
| --- | --- | --- |
| `issues` | list of issue objects | Problems and uncertainties retained for review; `[]` when none are identified. |

Each issue object:

| Field | Type | Meaning |
| --- | --- | --- |
| `issue_id` | string | Stable issue ID retained through verification. |
| `related_record_id` | string or null | Affected action ID; null for an omission, plan-level/source problem, or removed record. |
| `description` | string | Grouped concerns; identify relevant pages and any affected records not linked directly. |
| `type` | enum or null; optional | `unclear_meaning`, `conflicting_evidence`, `source_issue`, `extraction_process_issue`, or `no_records_found`. |
| `origin_stage` | enum | `extractor` or `verifier`; unchanged for a continuing issue. |
| `status` | enum | `open` or `resolved`. |
| `resolved_by` | enum or null | `extractor` or `verifier` when resolved; null while open. |
| `resolution` | string or null | Explanation addressing every concern when resolved; null while open. |

### E. Saved run

Python saves this outer object in `output.json`. The action-focused migration needs a new format version; existing version 1 runs retain their original meaning.

| Field | Type | Meaning |
| --- | --- | --- |
| `schema_version` | positive integer | Saved-format version; set during the coordinated schema migration. |
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
| `settings` | object | Complete frozen settings, defined in section F. |
| `model_calls` | list of model-call objects | Ordered generation attempts and available usage, defined in section G. |
| `tool_log_path` | string or null | Saved ordered tool log, when present. |
| `content` | object or null | Section A content on success; null without an accepted final answer. |
| `review` | object or null | Section D review on success; null without an accepted final answer. |
| `error` | string or null | Failure explanation when available. |

### F. Saved settings and nested objects

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

### G. Model-call entry

| Field | Type | Meaning |
| --- | --- | --- |
| `input_tokens` | nonnegative integer or null | Provider-reported input usage; unavailable is not zero. |
| `output_tokens` | nonnegative integer or null | Provider-reported output usage. |
| `finish_reason` | string or null | Provider-reported reason generation ended. |
| `truncated` | Boolean or null | Whether output was cut off; reported truncation fails the run. |
| `response_path` | string or null | Preserved response location, when available. |
