# Design Doc: Heat Adaptation LLM Dataset

**Research design · updated 2026-11-23**

## 1. Context and problem

Plans issued by governments and public agencies describe actions to address heat risk. Extracting these actions into a consistent dataset would support comparison across jurisdictions. The work requires reading varied documents, combining descriptions spread across pages, and preserving details such as implementation status, costs, and expected benefits.

Large language models (LLMs) could assist this work, but their outputs require assessment against the source. This study will examine a workflow combining open-weight models, document tools, and heat adaptation experts. Open-weight models publish their trained parameters; the study accesses these models through hosted APIs using Hugging Face Inference Providers. Preserving the source documents, model identities, available version information, prompts, settings, and expert judgments supports reproducibility.

## 2. Research aim and objectives

The study will develop and evaluate a workflow pairing heat adaptation experts with open-weight LLMs to extract actions from plans and produce a curated pilot instruction dataset. The workflow is agentic, meaning models can request tools while completing a task. An instruction example pairs task instructions and source input with a reviewed answer for future fine-tuning.

The study has two objectives.

1. **To show how experts and LLMs can be paired to build an extraction workflow.** The study will examine how expert knowledge, model outputs, and successive revisions shape the workflow and identify practical lessons for researchers developing similar workflows.
2. **To evaluate verification and collaboration.** The study will compare an extractor alone (E), that extraction revised by a different model (E+V), and a collaborative multi-agent configuration (C). The comparison will examine accuracy, completeness, supporting evidence, unresolved issues, and computational requirements.

## 3. Methods

### Eligible plans

Eligible plans meet all of the following criteria.

- They are final, publicly available English plans issued by governments or public agencies, published or updated in 2010 or later.
- They address heat directly, or contain a dedicated heat section with at least one action.
- They are available as PDFs with stable page positions and content readable by a person, including scanned pages.

Experts will screen eligibility, with preference for recent versions. City, county, regional, state, and national plans are eligible, with particular interest in city plans. Broader plans may cover heat adaptation across their jurisdiction.

### Study sample

| Study set | Planned size | Purpose |
| --- | --- | --- |
| Development | 2 plans | Refinement of how experts and LLMs work together, with observed problems and revisions informing practical lessons. |
| Comparison | 5 separate plans | Comparison of E, E+V, and C against independent expert work under fixed settings. |
| Expansion | Deferred | Possible dataset expansion after evaluation of the workflow. |

Plans will be selected to provide variation in length, layout, and type, with near-duplicates excluded. The comparison set will be selected before comparison runs and will be separate from the development documents. The selection rationale and document characteristics will be recorded.

### Extracted dataset and action records

Each configuration will produce one JSON dataset for a plan, containing plan information, action records, and review issues. JSON stores named fields in objects and lists of objects in arrays.

Within a plan, actions are grouped by the specific activity undertaken. For example, all tree planting belongs in one action object, including planting in different neighborhoods or phases. Details associated with each location or phase are preserved. Tree planting and drinking fountain installation form separate actions. The broad `action_type` categories classify each activity and may overlap.

One source heading, pathway, or programme may contain several distinct activities. Activities with different primary tasks or outputs receive separate records, even when they share a goal, recipient group, or implementer. Routine implementation choices remain part of their activity: heat-resistant species specified for tree planting belong in that planting record, while a separately commissioned species experiment has a different primary task.

#### Plan dataset components

| Component | Meaning and information gathered | JSON representation |
| --- | --- | --- |
| Plan | One document version, processed in full. | One dataset containing `plan_data` and `plan_issues`. |
| Plan information | Document and jurisdiction metadata. | `plan_data.metadata`. |
| Actions | One record per specific heat adaptation activity, combining its occurrences throughout the plan. | `plan_data.actions`. |
| Plan issues | Uncertainty, conflicts, source gaps, or possible omissions requiring review. | `plan_issues.issues`. |

#### Fields within each action object

| Action field | Meaning and information gathered | JSON representation |
| --- | --- | --- |
| Action identifier | Stable local ID followed through revisions within a workflow. | `action_id` |
| Action description | Activity, implementers, quantities, timing, conditions, and phase-specific details. | `action` |
| Action type | Infrastructural, institutional, behavioral/cultural, and/or nature-based. | `action_type` |
| Action status | Unspecified unless the source clearly establishes that the grouped activity is planned, underway, or completed. | `action_status` |
| Action location | All stated locations or geographic coverage. | `action_location` |
| Action recipients | Stated intended populations or affected groups. | `action_recipient` |
| Action cost | Stated amounts, units, periods, and whether estimated, allocated, spent, or needed. | `action_cost` |
| Action benefit | Stated outcomes and qualifications, preserving whether expected, modelled, or observed. | `action_benefit` |
| Supporting evidence | Exact quotations and physical PDF page numbers supporting the recorded details. | `evidence` |

Costs, benefits, and evidence are attached to the activity they describe. The [appendix](#appendix-dataset-coding-rules-and-evaluation) defines the fields and coding rules used by models and experts.

### Evidence and issues

Evidence consists of exact, continuous quotations with physical PDF page numbers counted from 1. Quotations preserve wording, punctuation, and line breaks without rewriting or silent omissions; hyphens at line breaks are retained. Unreliable OCR passages are represented by locatable continuous excerpts and unresolved evidence gaps. Every page containing quoted words is cited. Separate passages are represented by separate evidence entries, including relevant headings or footnotes. Adequate evidence collectively supports the activity and its stated details.

Concerns about one action are grouped into one issue. Omissions and source gaps are recorded without an action link when necessary. Ordinary unstated details are represented by the defined missing values. The verifier retains E issue IDs, may add issues, and explains claimed resolutions. C maintains its own action and issue IDs, with the role that raised or resolved each issue recorded. Curated copies of E, E+V, and C retain their workflow's issue identities and allow expert resolutions. Expert curation corrects or excludes unsupported material.

### Example data output

This fictional example groups tree planting across two wards. A linked issue records costs that could not be recovered from a table.

```json
{
  "plan_data": {
    "metadata": {
      "plan_title": "Example City Heat Action Plan",
      "jurisdiction_name": "Example City",
      "country": "Example Country",
      "plan_scale": "city",
      "plan_type": "heat_specific_plan",
      "publication_year": 2026,
      "lead_agencies": ["Example City Council"],
      "source_url": "https://example.org/heat-plan.pdf",
      "date_accessed": "2026-11-18",
      "language": "English"
    },
    "actions": [{
      "action_id": "action_0001",
      "action": "Example City Council plans to plant 100 street trees in North Ward and 200 in South Ward.",
      "action_type": ["nature-based"],
      "action_status": "planned",
      "action_location": "North Ward; South Ward",
      "action_recipient": null,
      "action_cost": null,
      "action_benefit": "Expected reduction in heat.",
      "evidence": [{
        "quote": "Example City Council plans to plant 100 street trees in North Ward and 200 in South Ward to reduce heat.",
        "page_numbers": [4]
      }]
    }]
  },
  "plan_issues": {
    "issues": [{
      "issue_id": "issue_0001",
      "related_action_id": "action_0001",
      "issue_description": "Planting costs in the table on PDF page 5 could not be recovered from prepared text or OCR.",
      "issue_type": "source_issue",
      "issue_origin": "extractor",
      "issue_status": "open",
      "resolved_by": null,
      "resolution": null
    }]
  }
}
```

### Workflow and comparison

During development, models will draft action records and flag uncertainties. Experts will examine the outputs against the plans and identify changes needed in coding rules, prompts, tools, and review procedures. Examples showing what prompted a revision, how it was addressed, and what was observed afterwards will be preserved. These examples will support the study's account of building the workflow and the lessons drawn from that process.

For E and E+V, Inkling 2 Small (`thinkingmachines/Inkling-2-Small`) is the extractor and DeepSeek V4.1 Flash 1017 (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) is the verifier. GLM-5.3-Flash (`zai-org/GLM-5.3-Flash`) is the coordinator for C. All three models will be accessed through Hugging Face Inference Providers with DeepInfra as the fixed host. E consists of the Inkling extraction with shared Python processing. E+V begins with that exact saved extraction, which DeepSeek checks and revises.

C will start independently from the same prepared plan, without access to the selected E/E+V outputs or expert reference. Inkling and DeepSeek will serve as two flexible workers with the same task instructions and document tools; either can extract or check information. The coordinator will give each task a clear objective, source scope, and expected findings, arrange parallel work where tasks are independent, and request follow-up or cross-checks. Both workers will contribute source-supported findings. Worker identities will remain fixed as assignments change. The coordinator will maintain a provisional draft while capacity remains and direct checks of grouping, heat eligibility, coverage beyond the main heat sections, associated details, and quotation fidelity. It will assemble one complete JSON answer, retaining unresolved concerns as issues. Task order and the number of exchanges may vary within fixed execution budgets.

DeepSeek was selected for its low listed cost and strong author-reported reasoning and agent benchmark results. GLM was selected for its low listed cost, long context, and listed tool and structured-output support. All three models have passed basic compatibility checks. E, E+V, and C have completed development runs on both plans. Live checks under the latest shared guidance, C prompts, and budgets, and formal expert quality assessment, remain pending. The shared guidance's effect on model quality is **Not yet tested**. PDF preparation, optical character recognition (OCR) with EasyOCR, and document tools run locally; LLM inference is hosted.

Model and hosting details, prompts, response controls, execution budgets, tool use, runtime, and provider-reported tokens will be recorded. Generation will use a provider-compatible schema, with compatibility checked separately using fictional inputs. Python will enforce the complete field and relationship rules for every final output. Structural compliance does not establish substantive accuracy. Earlier trials remain development evidence and are outside the formal comparison.

Each complete configuration will have a 90-minute execution ceiling, with 30 minutes protected for its final answer. For E+V, the complete extraction and verifier investigation will share the preceding 60 minutes; an extraction exceeding that allowance cannot enter the timed E+V workflow. Human waiting between commands will be excluded. C will share its time across all agents. Request, tool, and estimated-token ceilings will be fixed before comparison; actual resource use and failed attempts will be reported separately. Final generation may begin earlier when investigation finishes. Common ceilings do not establish equal computational effort; the current settings are specified in the implementation document's [configuration table](IMPLEMENTATION.MD#current-configuration-settings).

A submitted document-tool request exceeding its deadline will fail the configuration, including when a reply arrives late. Failure evidence and available late replies will be preserved, and no further model requests will start. Ordinary source problems, such as unreadable OCR, may remain recoverable and be retained as unresolved issues.

All agents will use the same preparation and document tool capabilities through Model Context Protocol (MCP), the interface connecting agents to tools. C agents will receive the shared coding rules and field definitions; assignments and relevant findings will be exchanged through the coordinator. Shared field guidance will distinguish complete answers from worker task results and identify each workflow's issue roles.

The final E, E+V, and C answers will receive the same automatic quotation-location checks. A single-page citation is corrected only when its cited page has available text, the quotation does not match there, and the complete quotation matches exactly one other physical page in the prepared text or successful OCR readings available within that workflow. Matching allows whitespace differences while preserving wording and punctuation. Ambiguous locations and unmatched quotations remain flagged. Raw responses, corrected candidates, and repair records will be preserved. V receives the processed E answer; expert assessment covers each configuration's processed output. Citation corrections do not establish evidence adequacy or change model-reported issue statuses.

| Stage | Procedure and saved result |
| --- | --- |
| 1. Registration and preparation | The original PDF, collection metadata, page text, and preparation problems will be preserved. |
| 2. Extraction (E) | Inkling 2 Small will receive the whole prepared plan through the Hugging Face API. Its answer, issues, settings, tool activity, and execution records will be saved. |
| 3. Verification (E+V) | DeepSeek V4.1 Flash 1017 will check a copy of that exact Inkling extraction, including unflagged content and possible omissions. Its full revised answer will be saved. |
| 4. Collaboration (C) | GLM-5.3-Flash will coordinate Inkling and DeepSeek as flexible workers with clear assignments for extraction and checking. C will start independently from the prepared plan, preserving task exchanges, execution evidence, and one complete JSON answer. |
| 5. Expert reference preparation | Experts will complete one reference form per plan from the original PDF before viewing any comparison output. The completed form will be validated and frozen before assessment. |
| 6. Manual expert assessment | Experts will match activities by meaning and assess E, E+V, and C against the same frozen reference form, using the agreed rubric, evidence judgments, and issue checks. |
| 7. Analysis and dataset assembly | Lessons about pairing experts and LLMs will be synthesized, the three configurations compared, and instruction examples assembled from expert-curated answers and supporting inputs. |

Verification will default to the most recent validated, successful E run for the plan unless a specific E run is selected. The same selection rule applies to development, comparison, and later expansion. The selected E run ID will be saved with V, and verifier retries will retain that input.

Each comparison will use the selected E output, the first successful V run linked to it, and the first successful independent C run under fixed settings and the same preparation. The selected run IDs will be recorded before assessment and retained when newer runs appear. Manual judgments will also identify the frozen reference fingerprint and reviewers. Successful execution means that format and execution checks have passed. Failures and repeated runs will be preserved, with manual retries linked to earlier attempts.

Models, prompts, preparation, tools, coding rules, budgets, stopping rules, and scoring will be fixed before comparison. C's task sequence may adapt within that fixed protocol. Subsequent changes and affected runs will be documented. [IMPLEMENTATION.MD](IMPLEMENTATION.MD) describes current software and planned work, and [README.md](README.md) provides available commands.

## 4. Evaluation

### Expert reference and scoring

Experts will complete one reference form per plan using the same grouping and coding rules as the models. The form will contain expert-coded activities, details, and source evidence from the original PDF. For comparison plans, the expert will complete it before viewing any E, E+V, or C output. All three saved outputs will be assessed manually against that same frozen form.

Reference forms begin with guided action and issue placeholders. Experts will replace the guidance or remove unused records while coding the PDF. Reference issues use `expert` origin and, when resolved, `expert` resolver. These concerns remain separate from model-output issues used in evaluation. Structural validation does not establish reference completeness or factual accuracy.

Reference action and issue IDs will remain stable, with deleted IDs unavailable for reuse. The same evidence/type-to-issue rules apply to reference actions; an omitted optional issues container means no issues. Before assessment, a named reviewer will confirm readiness and freeze the completed form. The freeze will identify the exact reference and original PDF by SHA-256 fingerprints, with reviewer and time recorded. Subsequent file changes will fail validation. This records the reviewer's decision; it does not establish scientific completeness or enable formal comparison.

Development forms will pilot coding and assessment procedures. Prior exposure to development outputs will be recorded, and those forms will not provide independent comparison evidence.

Actions will be matched by activity and meaning. Split or duplicate records will be assessed together, with each reference activity counted once. All substantive claims in matched records, including conflicting or unsupported details, will be considered in scoring. If a record bundles different activities, its relevant content will be assessed against each matching reference activity.

| Score | Judgment about a reference action and its matched output |
| --- | --- |
| 1 | The activity and all required substantive details are correct, with source support for every substantive addition. |
| 0.5 | Some substantive information about the activity is correct, but a required detail is wrong, omitted, or unsupported. |
| 0 | The activity is omitted, or the matched content contains no correct substantive information about it. |

Assessment will cover the description, classification, status, locations, recipients, costs, and benefits under the coding rules. Required substantive details include stated quantities, implementers, timing, conditions, and differences between neighborhoods or phases. Defined missing values are correct when the source is silent. Experts will judge content against the original PDF, with supplied quotations and citations assessed through the evidence measure. Plan information will be checked during curation, and issues will be assessed through their own measures.

This study-specific rubric will be piloted on development plans. A worked scoring example appears in [IMPLEMENTATION.MD](IMPLEMENTATION.MD#worked-scoring-example).

### Evaluation outcomes

| Outcome | Measure and purpose |
| --- | --- |
| Action accuracy and completeness | **Action score percentage**, using the 0/0.5/1 scores for activities in the expert reference form. |
| Unsupported activities | **Unsupported action count**, reported alongside the total distinct output activities. This captures invented or ineligible activities outside the reference-based score. |
| Evidence quality | **Actions with adequate evidence**, the percentage of output activities whose supplied evidence supports all recorded substantive details and uses faithful quotations with correct pages. |
| Issues requiring review | **Open issues** in all three outputs, and **expert-confirmed verifier resolutions** reported against resolutions claimed for initially open E issues in E+V. C's issue handling will be described in review notes. |
| Computational requirements | Successful processing runtime, provider-reported tokens, and failed executions as supporting information. |

The [evaluation appendix](#g-evaluation-measures-and-calculations) defines calculations and denominators. Assessment notes explain errors and corrections without requiring separate scores for every quotation or page.

### Analysis and limitations

The analysis will examine how heat adaptation experts and LLMs work together to develop the extraction workflow. Examples of decisions, revisions, and failures will help identify practical lessons about combining expert knowledge with model outputs to build and refine the workflow.

Comparisons within each plan will examine how sequential verification and coordinated collaboration affect action accuracy and completeness, supporting evidence, and unresolved concerns. Review notes will describe corrected errors, recovered omissions, introduced errors, and how C's agents investigate disagreements. Runtime, token use, and failures will describe computational requirements.

With five selected comparison plans and one fixed set of models, findings will be descriptive and specific to this setting. Differences involving C will reflect its complete workflow, including its third model, resource allowances, and coordination, rather than isolating coordination alone. Document layout and PDF/OCR errors may affect quality. Hosted services may disclose limited model revision and serving details; unavailable information will remain unknown. Expert judgments about grouping and scoring may vary, and omissions or misinterpretations in the reference form may influence results.

The coarse action scores and combined evidence judgment may hide differences in the nature or severity of errors. Grouping an activity across locations or phases also gives records with different amounts of detail equal weight. Issue counts depend on what the models flag and provide only a partial view of review needs.

## Appendix: dataset, coding rules, and evaluation

A **schema** defines fields, types, and permitted values. An **object** groups named fields, a **list** holds items, and an **enum** limits a value to named choices. `null` represents unavailable information.

Sections A–D define the target plan dataset, E defines category options, F gives coding rules, and G defines evaluation. [IMPLEMENTATION.MD](IMPLEMENTATION.MD#appendix-supporting-json-files) specifies the supporting workflow files.

All fields are required unless marked optional. Text is nonblank unless stated otherwise. Dates use `YYYY-MM-DD`. Record links refer to items within the same plan dataset, and cited page numbers fall within the original PDF's page range.

### A. Plan dataset and plan data

The model returns a plan dataset containing `plan_data` and `plan_issues`. Execution metadata is described in the implementation document's [saved run specification](IMPLEMENTATION.MD#saved-run).

| Field | Type | Meaning |
| --- | --- | --- |
| `plan_data` | object | Plan information and action records, defined below. |
| `plan_issues` | object | Contains the `issues` list defined in section D. |

Within `plan_data`:

| Field | Type | Meaning |
| --- | --- | --- |
| `metadata` | object | One plan's metadata, defined in section B. |
| `actions` | list of action objects | One object per specific heat adaptation activity throughout the plan. An empty list follows a completed search, with unresolved source gaps recorded as issues. |

### B. Plan information

| Field | Type | Meaning |
| --- | --- | --- |
| `plan_title` | string or null | Title stated in the plan. |
| `jurisdiction_name` | string or null | Named jurisdiction covered by the plan. |
| `country` | string or null | Country identified by the source. |
| `plan_scale` | enum or null | Administrative level covered by the plan: `city`, `county`, `region`, `state`, or `country`. The value `country` denotes a national plan. |
| `plan_type` | enum or null | `heat_specific_plan` or `broader_climate_plan`. |
| `publication_year` | integer or null | Publication or update year of this document version. |
| `lead_agencies` | list of strings | Stated plan-level lead agencies, empty if unknown. Individual implementers require action-specific evidence. |
| `source_url` | string | Official source URL from the selected preparation's collection metadata. |
| `date_accessed` | date string | Collection access date from the selected preparation. |
| `language` | string | `English` for the present study. |

### C. Action and evidence

| Field | Type | Meaning |
| --- | --- | --- |
| `action_id` | string | Stable local ID, such as `action_0001`. |
| `action` | string | Description of one specific activity across the plan, retaining implementers, quantities, dates, conditions, and statuses associated with each phase or location. |
| `action_type` | list of unique enum values | Categories defined in [appendix E](#action-types). An empty list (`[]`) indicates that no type could be justified and is accompanied by an issue describing the classification uncertainty. |
| `action_status` | enum | Overall status of the grouped activity, using the values in [appendix E](#action-status). Coding across phases and locations follows appendix F. |
| `action_location` | string or null | All stated places or geographic coverage, retaining their associations with phases or quantities where needed. |
| `action_recipient` | string or null | All stated intended populations or affected groups, retaining relevant local or phase-specific distinctions. |
| `action_cost` | string or null | Amounts, currency/units, periods, cost character, and qualifications, with each amount linked in the description to its activity, location, or phase. Shared amounts are identified. |
| `action_benefit` | string or null | Outcomes, quantities, affected groups, comparisons, timing, and qualifications, including local or phase-specific differences and whether expected, modelled, or observed. |
| `evidence` | list of evidence objects | Quotations supporting the action and its details. An empty list is accompanied by a review issue. Acceptance as an unqualified curated record requires supporting evidence. |

Each evidence object:

| Field | Type | Meaning |
| --- | --- | --- |
| `quote` | string | Exact continuous source passage, preserving wording and punctuation without rewriting or silent omissions. Separate passages are represented by separate objects. |
| `page_numbers` | nonempty list of unique positive integers | Every physical PDF position containing quoted words, starting at 1. A continuous passage may span pages. |

### D. Plan issues

Within `plan_issues`:

| Field | Type | Meaning |
| --- | --- | --- |
| `issues` | list of issue objects | Problems and uncertainties retained for review; `[]` when none are identified. |

Each issue object:

| Field | Type | Meaning |
| --- | --- | --- |
| `issue_id` | string | Stable issue ID retained through revisions and curation within its workflow. C IDs are independent of E/E+V. |
| `related_action_id` | string or null | Affected action ID. Null for an omission, a problem affecting the plan or its source, or a removed action. |
| `issue_description` | string | Grouped concerns, including relevant pages and any affected actions not linked directly. |
| `issue_type` | enum or null; optional | Classification of the concern, using the values in [appendix E](#issue-types). |
| `issue_origin` | enum | Agent that first raised the issue: `extractor` or `verifier` in E/E+V; `worker_1` (Inkling), `worker_2` (DeepSeek), or `coordinator` (GLM) in C. Retained through later review and curation. |
| `issue_status` | enum | `open` when concerns still require attention, or `resolved` when a resolution has been recorded. Model resolutions remain claims for expert assessment. |
| `resolved_by` | enum or null | Agent that resolved the issue, using the same workflow-specific identities as `issue_origin`, or `expert` in a curated copy after assessment. Null while open. |
| `resolution` | string or null | Explanation addressing every concern when resolved; null while open. |

An open issue has null `resolved_by` and `resolution`. A resolved issue identifies who resolved it and explains how all grouped concerns were addressed. Reopening retains its ID and origin. Expert assessment of V's claimed resolutions is recorded in manual review notes. A subsequent expert fix is recorded in a curated copy of the dataset. Independent expert-reference issues are defined in the [reference form](IMPLEMENTATION.MD#expert-reference-form).

### E. Category definitions

The following tables define the options for `action_type`, `action_status`, and `issue_type` in the JSON fields above.

#### Action types

The four categories describe the mechanisms used by an activity. One activity may have more than one type.

| Action type | Working definition |
| --- | --- |
| `infrastructural` | Changes to built assets, equipment, or physical services, such as cool roofs or drinking water infrastructure. |
| `institutional` | Policies, governance, planning, financing arrangements, coordination, or formal service and monitoring systems. |
| `behavioral/cultural` | Activities intended to change knowledge, practices, routines, or cultural and social norms, such as outreach on heat safety. |
| `nature-based` | Activities using vegetation, ecosystems, or ecological processes to address heat, such as tree canopy or wetland restoration explicitly linked to heat. |

#### Action status

Status describes what the selected document reports about the grouped activity. The default is `unspecified`; another value requires an explicit statement or unambiguous source evidence of the overall status. The current date does not advance an activity's reported status.

| Action status | Working definition |
| --- | --- |
| `planned` | Clearly proposed or committed, with no source evidence that work has begun. |
| `underway` | Clearly reported as in progress or operating. |
| `completed` | The grouped activity is explicitly reported as finished. |
| `unspecified` | Default when the overall status is not clearly established, including when only differing phase or location statuses are available. |

#### Issue types

An issue type describes the concern requiring review. Several concerns about the same action are explained together in `issue_description`, with the most relevant type selected when a classification is useful.

| Issue type | Working definition |
| --- | --- |
| `unclear_meaning` | Source wording or context supports more than one interpretation, affecting how an action or detail should be coded. |
| `conflicting_evidence` | Source passages give incompatible accounts of the same activity or detail that require reconciliation. |
| `source_issue` | Missing, unreadable, or unreliable source text limits extraction or evidence checking. This includes errors in optical character recognition (OCR) or problems reading tables. |
| `extraction_process_issue` | A problem during extraction, tool use, or application of the coding rules raises concern about the output's accuracy or completeness. |
| `no_records_found` | No eligible heat adaptation actions were identified, and review is needed to confirm that finding or investigate possible omissions. |

### F. Action coding rules

These rules describe how models and experts interpret the source and organize action records.

| Coding question | Coding rule |
| --- | --- |
| Which activities qualify as heat adaptation actions? | Eligible activities are explicitly connected to reducing heat risk or enabling adaptation through their description or a heat-specific heading. General climate, greening, or health measures require this source connection. |
| How should activities be grouped? | Specific activities are identified before repeated mentions are combined. The same activity is grouped across neighborhoods, programmes, and phases. One object for tree planting retains all stated locations, quantities, dates, implementers, statuses, costs, benefits, and evidence. Differences in those details alone do not create separate objects. |
| When should activities have separate records? | Activities with different primary tasks or outputs have separate objects, even within one heading, pathway, or programme. A cooling innovation competition and an ambassador training programme are distinct, as are heat mapping and an awareness campaign. Shared goals, recipients, implementers, or broad action types do not establish one activity. Routine implementation steps remain within their activity. Borderline cases will be piloted before comparison. |
| How should details and conflicting statements be handled? | Each detail retains its association with the stated location or phase. Repeated totals are counted once. Conflicting source statements are recorded as issues. |
| When should goals be included? | A concrete activity retains its stated targets or deadlines. A broad aspiration alone falls outside the action records. |
| How should monitoring and evaluation be recorded? | Concrete heat-related activities, such as operating heat-health surveillance, are actions. The description preserves the source's distinction between monitoring and demonstrated outcomes. |
| How should locations, recipients, and implementers be recorded? | Locations and intended populations use their dedicated fields. Implementers appear in `action`, supported by evidence identifying their responsibility for the activity. |
| How should action types be assigned? | Every category supported by the activity's described mechanism is recorded. Possible wider effects alone do not justify a type. Multiple types describe aspects of the same activity. |
| How should action status be coded? | The default is `unspecified`. Another value requires an explicit statement or unambiguous source evidence of the grouped activity's overall status, using appendix E. Presence in a plan or a deadline alone does not establish status. Coding reflects the selected document's account, without inference from the current date. |
| How should differing phase or location statuses be handled? | When the source provides no overall status, `action_status` is `unspecified` and each phase or location status is retained in `action`. A completed pilot or past event alone does not establish the status of a broader grouped activity. Mixed reporting alone requires no issue. |
| How should other reported states be handled? | States outside the four values, such as withdrawal, are retained in `action`, with `action_status` set to `unspecified` and the coding limitation identified in an issue. |
| How should costs be recorded? | Amounts retain their original currency or units, periods, qualifications, and whether estimated, allocated, spent, or needed. Each amount retains its association with the relevant phase or location. |
| How should benefits be recorded? | Outcomes retain quantities, affected groups, comparisons, timing, and qualifications, including stated adverse effects and whether expected, modelled, or observed. |
| When should shared budgets or outcomes be attached to an action? | Shared budgets or outcomes are attached when the source establishes an activity link. Their scope is retained, and repeated amounts are counted once. General plan-wide statements without an activity link fall outside the action dataset. |
| How should missing details be recorded? | Unavailable descriptive fields are represented by `null`, and unstated overall status by `unspecified`. When no action type can be justified, the type list is empty (`[]`) and an issue explains the uncertainty. Missing details alone cannot establish zero cost, no benefit, or absence of an action. |
| How should supporting evidence be recorded? | Exact continuous quotations preserve wording, punctuation, and parenthetical text without rewriting or silent omissions. Every physical PDF page containing quoted words is cited, counted from 1. Separate passages, including nonadjacent headings or footnotes, have separate evidence entries. When continuity across pages is unclear, separate excerpts are used. Together, the evidence supports the activity and its recorded details. |

### G. Evaluation measures and calculations

The selected E, linked E+V, and independent C outputs form the basis of comparison. Quality is assessed on saved processed outputs before curation. E+V includes the shared extractor and verifier; C includes its own coordinator and all worker activity.

#### Before expert assessment

| Measure | Calculation | Comparison |
| --- | --- | --- |
| Open issues | Number of issues whose `issue_status` is `open` in each output. | Reported for E, E+V, and C; independently generated C issues are not matched to E IDs. |
| Successful processing runtime | Measured processing duration, in seconds. | E uses extractor duration; E+V adds verifier duration. C uses its complete elapsed duration, without summing overlapping worker durations. |
| Tokens used | Sum of provider-reported input and output tokens across generation calls, with the two components retained. | E uses extractor calls; E+V adds verifier calls. C includes every coordinator and worker call once. |
| Failed executions | Number of distinct failed comparison run IDs, including retries. | Reported for E, V, and C, with shared E failures counted once. Worker errors belong to their C run rather than separate executions. |

Runtime covers setup/loading, model and tool requests, saving, validation, permitted repairs, and cleanup. C duration runs from its own start to completion, including coordination and parallel work. Failed-attempt measurements are reported separately. Preparation, human review, and gaps between attempts fall outside processing runtime.

#### After expert assessment

Experts manually compare each selected output with the frozen reference form identified in their judgments. Output content is grouped by specific activity, with split or duplicate records combined and their IDs and all substantive claims retained. Bundled activities are assessed separately. Each reference activity receives one score under section 4.

| Measure | Calculation | Interpretation |
| --- | --- | --- |
| Action score percentage | Sum of reference action scores ÷ number of reference actions × 100. | Main quality measure, combining correctness and completeness with partial credit. |
| Unsupported action count | Number of distinct output activities judged unsupported or ineligible under the coding rules, alongside the total number of distinct output activities. | Captures invented or ineligible activities outside the reference denominator. Wrong details within a supported activity affect its action score. |
| Actions with adequate evidence | Number of output activities with adequate evidence ÷ total distinct output activities × 100. | Evidence is adequate when it collectively supports all recorded substantive details and every supplied quotation faithfully reproduces the PDF and cites its correct physical pages. Missing evidence and unsupported activities fail this judgment. |
| Expert-confirmed verifier resolutions | Number of initially open E issues with `issue_status` set to `resolved` and `resolved_by` set to `verifier` in E+V that experts judge justifiably resolved, reported as confirmed / claimed resolutions. | Applies only to E+V, which revises E. The count of open issues in E supplies the initial issue total. C's independent issue handling is described in review notes. |

For example, six scores of 1, two of 0.5, and two omissions among ten reference activities yield an action score of 70%. Two additional invented activities would contribute to the unsupported action count. The score distribution is recorded in the manual review.

An activity can receive full content credit while its supplied evidence is inadequate, for example when its description is correct but its page citation is wrong. Experts check all supplied evidence, recording one adequacy judgment and explanation per output activity. The explanation identifies important quotation, citation, or coverage failures.

For issue assessment, only initially open E issues that V marks resolved require a resolution judgment. A claimed resolution is confirmed when source review shows that every grouped concern was addressed. Comparisons use the saved processed outputs before expert curation, while expert fixes are recorded in curated copies. Python citation repairs are logged separately and do not create a model-claimed issue resolution. More open issues can reflect improved detection, so counts are interpreted alongside quality scores and examples.

#### Paired comparisons and reporting conventions

Paired changes are calculated within plans as E+V minus E and C minus E+V, with percentage differences expressed in percentage points. Results are reported for each plan with counts and denominators. A descriptive overall summary uses the mean of valid per-plan percentages and identifies contributing plans. Missing configuration outputs and failures are identified; each contrast uses plans with the required outputs and judgments.

The value `null` indicates pending judgments or unavailable measurements. Missing required usage or duration makes the corresponding total unavailable. Zero denominators are not applicable. An output activity absent from the reference is checked against the PDF for source support; absence alone does not make it unsupported. Reference coverage gaps are recorded in manual review notes. Any activity whose support is still undetermined keeps the relevant quality measures pending.

The study reports three quality measures across all configurations, open issue counts across all configurations, and expert-confirmed verifier resolutions for E+V only. Review notes describe quotation, citation, addition, and issue examples, including C's collaboration process. Manually recorded judgments provide the inputs to the agreed measures.
