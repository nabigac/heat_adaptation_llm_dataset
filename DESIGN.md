# Design Doc: Heat Adaptation LLM Dataset

**Research design · updated 2026-11-14**

## 1. Context and problem

There is a need for publicly available, structured datasets on how different governments address heat risk and approach heat adaptation. Cities, counties, regions, states, and countries have published plans and policies that record proposed actions and reported implementation. This information needs to be extracted and collated before it can be compared consistently across plans.

Data extraction can be difficult and time-consuming, creating a bottleneck for research and evidence assessment. Extracting information from heat adaptation plans can be especially complex because documents may be long and vary in structure and terminology. Comparing their content requires interpreting text and tables, combining repeated descriptions, and preserving the context and qualifications of each action.

Large language models (LLMs) are emerging tools that could help turn the content of heat adaptation plans into comparable, structured data. For the dataset to be useful, extracted information must be accurate and supported by the plans. Expert assessment is needed to evaluate the quality of the extraction and identify where correction or further source review is required.

Open-weight models, whose trained parameters are available for download, are useful candidates for producing public research datasets because they can be run locally and their model weights, versions, prompts, and settings can be documented. Together with preserved source documents, code, and expert assessments, these records support reproducibility.

## 2. Research aim and questions

This study will evaluate a workflow in which LLMs extract documented heat adaptation actions from government plans and experts assess their quality. The main contribution is an evaluated expert–LLM workflow: what it gets right, where it fails, and what expert intervention is needed. A source-linked heat adaptation action dataset is a study output.

1. How reliably can the workflow identify and describe heat adaptation actions documented in government plans?
2. How does adding an LLM verifier change action quality, supporting evidence, unresolved issues, and computational requirements?

## 3. Methods

### Eligible plans

Eligible documents are final, publicly available government or public-agency plans in English, published or updated in 2010 or later. They either address heat directly or contain a dedicated heat section with at least one action. Experts will screen plans against these criteria, with preference for recent versions. Eligible PDFs have stable page positions and are readable by a person, including when the document is a scan.

City, county, regional, state, and national plans are eligible under these criteria. The study has particular interest in city plans while retaining government heat adaptation plans at all these levels within scope. Broader plans can address heat adaptation across their jurisdiction without a specific urban focus.

### Study sample

| Study set | Planned size | Purpose |
| --- | --- | --- |
| Development | 2 plans | These plans support open inspection of outputs, refinement of coding and software, and a pilot of expert assessment. |
| Comparison | 5 separate plans | These plans support comparison of extraction with and without verification against independent expert work. |
| Expansion | Deferred | A later phase would extend the dataset after the workflow has been evaluated. |

The aim is to select plans that vary in length, layout, and type, with particular interest in city plans. The selection process will avoid near-duplicate documents, and the administrative levels represented in the sample will be reported. Development plans will remain separate from the comparison set, which will be selected before comparison runs begin.

### Extracted dataset and action records

Each extraction produces a dataset for one plan, stored as a single JSON object. JSON is a format for storing structured data: an **object** groups named fields, and an **array** is a list of items. The plan dataset contains one object describing the plan and an array of action objects, with one object for each distinct heat adaptation action identified in the document. The aim is to capture all of the plan's heat adaptation actions and their stated details.

The plan is therefore the document being processed, and each action is an individual record within its dataset. Inside the `content` object, `plan_info` describes the plan and `plan_actions` lists its action objects. A separate `review` object contains an `issues` array for problems or uncertainties that need review.

| Component | Meaning and information gathered | JSON representation |
| --- | --- | --- |
| Plan | A specific version of a government or public-agency plan addressing heat adaptation, either directly or within a broader plan. The complete document is the source for extraction. | One plan dataset containing `content` and `review`. |
| Plan information | The plan's title, jurisdiction, country, administrative level, plan type, publication year, lead agencies, source URL, access date, and language. | One object in `content.plan_info`. |
| Actions | The distinct heat adaptation interventions or activities described in the plan. Each action object contains the fields listed below. | An array of objects in `content.plan_actions`. |
| Action identifier | A stable identifier for an action record, allowing it to be followed through extraction and verification. | `action_id` within each action object. |
| Action description | What the plan proposes or reports doing, including stated implementers, quantities, timing, conditions, and other relevant details. | `action` within each action object. |
| Action type | The categories that describe the action: infrastructural, institutional, behavioral/cultural, or nature-based. An action may have more than one type. | `action_type` within each action object. |
| Action status | Whether the plan describes the action as planned, underway, completed, or unspecified. | `action_status` within each action object. |
| Action location | Where the action takes place or the geographic area it covers, when stated. | `action_location` within each action object. |
| Action recipients | The intended recipients, populations, or affected groups, when stated. | `action_recipient` within each action object. |
| Action cost | Stated amounts, currency or units, periods, and qualifications, including whether an amount is an estimate, allocation, expenditure, or resource need. | `action_cost` within each action object. |
| Action benefit | Stated outcomes, quantities, affected groups, comparisons, timing, and qualifications, including whether outcomes are expected, modelled, or observed. | `action_benefit` within each action object. |
| Supporting evidence | Exact quotations and original PDF page references supporting the action and its details. | An `evidence` array within each action object. |
| Review issues | Uncertainty, conflicting statements, missing evidence, source gaps, or possible omissions that need checking. An issue may relate to a particular action or to the plan more broadly. | An array of issue objects in `review.issues`. |

Costs, benefits, and supporting evidence remain attached to the action they describe. The verifier produces a revised version of the same plan dataset, and the extractor's version is preserved for comparison. The overall study dataset brings together the extracted information from multiple plans.

The appendix provides the full field definitions and the [action coding rules](#e-action-coding-rules), which describe how source information is interpreted and organized into these records.

### Evidence and issues

Source evidence consists of exact, continuous quotations with physical PDF page numbers, starting at 1 regardless of printed labels. Separate passages are represented by separate evidence entries, without inserted ellipses joining them. Relevant headings and footnotes are retained where needed to interpret a passage. Evidence is assessed for support of the action's details; a reference to the same topic alone is insufficient.

OCR (optical character recognition) converts image text into machine-readable text and may misread words or numbers. Experts will check quoted OCR against the original PDF. Unreadable material is treated as a source gap rather than evidence that information is absent. A model's description of a chart does not qualify as a source quotation.

Issues identify problems needing review. Concerns about the same action are grouped into one issue, while omissions and source gaps may be recorded without a linked action. Ordinary unstated details do not automatically require an issue. The verifier retains existing issue IDs, may add issues, and explains any claimed resolution. Experts will assess whether those resolutions are justified. Material whose source support remains unresolved will be excluded from the curated dataset.

### Workflow and comparison

The planned workflow uses open-weight models as extraction and verification agents. An agent is a model in a loop that can request tools before answering. Model Context Protocol (MCP) connects that loop to document tools. MCP is shared infrastructure for the two configurations and is not evaluated as a separate experimental treatment.

| Stage | Procedure and saved result |
| --- | --- |
| 1. Registration and preparation | The workflow preserves the PDF, collection details, page text, and preparation problems. |
| 2. Extraction (E) | The extractor receives the whole prepared plan. Its actions, evidence, issues, settings, and execution records are saved. |
| 3. Verification (E+V) | A different model checks a copy of that exact extraction against the same source, including unflagged actions and possible omissions. The full revised output is saved. |
| 4. Independent reference preparation | After both outputs succeed, experts independently extract from the original PDF without seeing model outputs. The initial reference is saved before outputs are revealed. |
| 5. Expert assessment | Experts match actions by meaning, review additions and reference corrections, and assess both outputs against one shared final reference. The initial reference and reasons for revisions are preserved. |
| 6. Analysis | Paired results are compared by plan, alongside practical lessons, limitations, and computational requirements. |

Each comparison pair will consist of the first successful extractor run and the first successful verifier run linked to it under the fixed study settings. Success indicates that execution and format checks passed; content correctness is assessed separately. Failed attempts will be retained, with manual retries linked to the earlier attempt. Deliberate repeats of successful work are exploratory and do not replace the selected output.

Models, prompts, document preparation, tools, coding rules, and scoring will be fixed before the comparison. Any later revisions will be documented, and results from different study setups will remain identifiable in the analysis. Both configurations share the same extraction, so the comparison evaluates the tested model pair and workflow. It does not isolate the effects of MCP, open weights, or model family.

The action-focused protocol remains under development. [IMPLEMENTATION.MD](IMPLEMENTATION.MD) distinguishes working software from planned stages and records the development evidence; [README.md](README.md) explains available commands.

## 4. Evaluation

### Expert reference and scoring

The expert reference provides an independently coded basis for comparison and may itself require correction. Initial matches will be preserved, supported additions reviewed, and corrections recorded in one shared final reference. Both saved model outputs will be assessed before expert corrections are made to them.

Experts will match actions by meaning. Several output records may cover one reference action, or one output may cover several reference actions. Each reference action contributes once to scoring, so duplicate output records receive no additional credit.

| Score | Judgment about a reference action and its matched output |
| --- | --- |
| 1 | All required substantive details are correct, with no unsupported substantive additions. |
| 0.5 | Some substantive information is correct, but a required detail is wrong, missing, or unsupported. |
| 0 | No substantive information is correct, or the action is omitted. |

Action type, status, location, recipients, costs, benefits, and relevant detail in the description are assessed under the same coding rules. Correctly recording an unstated detail does not reduce the score. Quotations and page citations are assessed separately. The action-scoring rubric applies to action records; plan information and review issues are not scored as additional actions.

### Evaluation outcomes

| Outcome | How it is assessed |
| --- | --- |
| Action coverage and correctness | Results will include the fully correct reference-action percentage and partial-credit score percentage, alongside counts and support judgments for distinct additions beyond the initial reference. These additional judgments are necessary because unsupported additions do not lower a reference-based score. |
| Evidence quality | Results will include the number of actions with quotations, the percentage of supplied quotation uses that faithfully support their assigned claims, and the percentage of cited pages that are correct. Missing evidence will be identified separately. |
| Computational requirements | Results will include successful processing time, input/output tokens, and failed attempts. E+V includes the shared extractor plus verifier. Successful-run time excludes preparation, human review, and failed-attempt time; failures are reported separately. |
| Issues and expert intervention | Results will include open issues, claimed and expert-confirmed resolutions, and examples of needed corrections. Issue counts do not measure expert review time. |

### Analysis and limitations

The analysis will report each plan's administrative level alongside the evaluation results and the changes between extraction alone and extraction followed by verification. Summaries will be descriptive given the small, selected sample. Pending judgments remain unscored, and percentages with zero denominators are treated as not applicable. Detailed calculations and expert-file definitions are provided in [IMPLEMENTATION.MD](IMPLEMENTATION.MD#expert-files-and-measurement).

A development pilot with experts will inform the action definitions, clarify ambiguous examples, and establish how reviewers will handle disagreements before the comparison begins. Study reporting will describe the assessment procedure and reviewer roles; the planned file format does not currently record expert identities. Extraction accuracy, OCR accuracy, and the benefits of verification remain questions for the empirical evaluation.

## Appendix: plan dataset and coding rules

A **schema** defines an object's fields, types, and permitted values. An **object** groups named fields; a **list** holds zero or more items; an **enum** limits a value to named choices. `null` means unavailable, not zero.

This appendix defines the intended plan dataset: plan information, action records with supporting evidence, and review issues, followed by the rules for coding actions. It describes the **action-focused target**; the current schemas still use the earlier five-category format. Execution records, settings, model-call measurements, and other workflow files are documented in [IMPLEMENTATION.MD](IMPLEMENTATION.MD#appendix-supporting-json-files).

All fields are required unless marked optional. Text is nonblank unless stated otherwise. Dates use `YYYY-MM-DD`. Record links refer to items within the same plan dataset, and cited page numbers fall within the original PDF's page range.

### A. Plan dataset and content

The model returns a plan dataset containing `content` and `review`. Execution metadata is described in the implementation document's [saved run specification](IMPLEMENTATION.MD#saved-run).

| Field | Type | Meaning |
| --- | --- | --- |
| `content` | object | Plan information and action records, defined below. |
| `review` | object | Contains the `issues` list defined in section D. |

Within `content`:

| Field | Type | Meaning |
| --- | --- | --- |
| `plan_info` | object | One plan's metadata, defined in section B. |
| `plan_actions` | list of action objects | Distinct documented heat adaptation actions, defined in section C. An empty list reflects a completed check for actions, with any unresolved source gap recorded as an issue. |

### B. Plan information

| Field | Type | Meaning |
| --- | --- | --- |
| `plan_title` | string or null | Title stated in the plan. |
| `jurisdiction_name` | string or null | Named jurisdiction covered by the plan. |
| `country` | string or null | Country identified by the source. |
| `plan_scale` | enum or null | Administrative level covered by the plan: `city`, `county`, `region`, `state`, or `country`. The value `country` denotes a national plan; all five levels are within the study's scope. |
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
| `action_type` | list of unique enum values | Any supported combination of `infrastructural`, `institutional`, `behavioral/cultural`, and `nature-based`. An empty list (`[]`) indicates that no type could be justified and is accompanied by an issue describing the classification uncertainty. |
| `action_status` | enum | `planned`, `underway`, `completed`, or `unspecified`, as defined in appendix E. |
| `action_location` | string or null | Stated places or geographic coverage, with multiple locations retained in the description. |
| `action_recipient` | string or null | Stated intended recipients, populations, or affected groups, with multiple groups retained in the description. |
| `action_cost` | string or null | Source-linked description of amounts, currency/units, periods, cost character, and qualifications. Shared amounts are identified as such. |
| `action_benefit` | string or null | Source-linked description of outcomes, quantities, affected groups, comparisons, timing, and qualifications, preserving whether expected, modelled, or observed. |
| `evidence` | list of evidence objects | Quotations supporting the action and its details. An empty list requires a review issue and is not acceptable for an unqualified curated record. |

Each evidence object:

| Field | Type | Meaning |
| --- | --- | --- |
| `quote` | string | Exact continuous source passage. Separate passages are represented by separate objects. |
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
| `description` | string | Grouped concerns, including relevant pages and any affected records not linked directly. |
| `type` | enum or null; optional | `unclear_meaning`, `conflicting_evidence`, `source_issue`, `extraction_process_issue`, or `no_records_found`. |
| `origin_stage` | enum | `extractor` or `verifier`; unchanged for a continuing issue. |
| `status` | enum | `open` or `resolved`. |
| `resolved_by` | enum or null | `extractor` or `verifier` when resolved; null while open. |
| `resolution` | string or null | Explanation addressing every concern when resolved; null while open. |

### E. Action coding rules

The following rules describe how agents and experts interpret the source when creating action records.

#### Action inclusion and record boundaries

Coding means assigning source information to defined fields and categories. An eligible action is a specific intervention or activity that the plan explicitly connects to reducing heat risks or enabling heat adaptation. This connection may be established by the action's description or a heat-specific heading. General climate, greening, or health measures are included only when the source establishes their relevance to heat adaptation.

| Coding decision | Approach |
| --- | --- |
| Separate actions | Distinct activities, such as planting trees and installing drinking fountains, are represented by separate records. Each record retains the activity's stated quantities, timing, conditions, and implementers. |
| Repeated mentions | Descriptions of the same action within a plan are combined, with evidence retained for its details. Conflicting statements are recorded as issues for review. |
| Goals | A broad aspiration alone does not constitute an action. An action's explicit target or deadline forms part of its description. |
| Monitoring and evaluation | Concrete heat-related activities, such as operating a heat-health surveillance programme, are recorded as actions. There is no separate monitoring catalogue, and monitoring activity alone does not establish effectiveness. |
| Where and who | Records describe the stated location and intended recipients or affected groups. Stated implementers appear in `action`, separately from recipients. The issuing agency is not assumed to implement or receive every action. |
| Costs | Records retain stated amounts, currency/units, periods, and whether they describe estimates, allocations, expenditure, or needs. Amounts remain in their original currency, and allocations are recorded only where supported by the source. |
| Benefits | Records retain stated outcomes, quantities, affected groups, comparisons, timing, and qualifications. Descriptions distinguish expected, modelled, and observed outcomes, including stated adverse effects. |
| Shared statements | A cost or benefit is attached to an action only where the source establishes the connection. Shared budgets or outcomes are identified as shared, so repeated amounts are not added together. General plan-wide statements without an action link fall outside the dataset. |
| Missing details | Unavailable descriptive fields are represented by `null` and unstated status by `unspecified`. The type list is empty when no category can be justified. Missing information does not establish zero cost, no benefit, or the absence of an action. |

#### Action types

The four action types are study coding categories that may overlap. Classification reflects every category supported by the action's described mechanism; possible wider effects alone do not justify additional types. Multiple types describe different aspects of the same action record.

| Action type | Working definition |
| --- | --- |
| `infrastructural` | Changes to built assets, equipment, or physical services, such as cool roofs or drinking-water infrastructure. |
| `institutional` | Policies, governance, planning, financing arrangements, coordination, or formal service and monitoring systems. |
| `behavioral/cultural` | Activities intended to change knowledge, practices, routines, or cultural and social norms, such as heat-safety outreach. |
| `nature-based` | Activities using vegetation, ecosystems, or ecological processes to address heat, such as tree canopy or wetland restoration explicitly linked to heat. |

#### Action status

Status describes what the document reports: `planned` means proposed or committed without evidence that work has begun; `underway` means started or operating; `completed` means explicitly finished; `unspecified` means status is not established. A past deadline does not prove completion. A reported state outside these four values, such as withdrawal, is retained in `action`, with status recorded as `unspecified` and the coding limitation identified in an issue. Where phases have different states, the description preserves those distinctions so that completion of one phase does not imply completion of the entire action.

The development phase will examine how these definitions apply to overlapping types, compound actions, and shared costs before their use in the comparison.
