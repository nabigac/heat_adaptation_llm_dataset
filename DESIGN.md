# Design Doc: Heat Adaptation LLM Dataset

**Research design · updated 2026-11-14**

## 1. Context and problem

Plans issued by governments and public agencies describe actions to address heat risk. Extracting these actions into a consistent dataset would support comparison across jurisdictions. The work requires reading varied documents, combining descriptions spread across pages, and preserving details such as implementation status, costs, and expected benefits.

Large language models (LLMs) could assist this work, but their outputs require assessment against the source. This study will examine a workflow combining open-weight models, document tools, and heat adaptation experts. Open-weight models have downloadable trained parameters and can be run locally. Preserving the source documents, model versions, prompts, settings, and expert judgments supports reproducibility.

## 2. Research aim and objectives

The study will develop and evaluate a workflow pairing heat adaptation experts with open-weight LLMs to extract actions from plans and produce a curated pilot instruction dataset. The workflow is agentic, meaning models can request tools while completing a task. An instruction example pairs task instructions and source input with a reviewed answer for future fine-tuning.

The study has two objectives.

1. **To show how experts and LLMs can be paired to build an extraction workflow.** The study will examine how expert knowledge, model outputs, and successive revisions shape the workflow and identify practical lessons for researchers developing similar workflows.
2. **To evaluate added verification.** The study will compare an extractor alone (E) with that same extraction revised by a different open-weight model (E+V). The comparison will assess corrected errors, recovered omissions, introduced errors, unresolved issues, and computational requirements.

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
| Comparison | 5 separate plans | Comparison of E and E+V against independent expert work under fixed settings. |
| Expansion | Deferred | Possible dataset expansion after evaluation of the workflow. |

Plans will be selected to provide variation in length, layout, and type, with near-duplicates excluded. The comparison set will be selected before comparison runs and will be separate from the development documents. The selection rationale and document characteristics will be recorded.

### Extracted dataset and action records

Each extraction will produce one JSON dataset for a plan, containing plan information, action records, and review issues. JSON stores named fields in objects and lists of objects in arrays.

Within a plan, actions are grouped by the specific activity undertaken. For example, all tree planting belongs in one action object, including planting in different neighborhoods or phases. Details associated with each location or phase are preserved. Tree planting and drinking fountain installation form separate actions. The broad `action_type` categories classify each activity and may overlap.

#### Plan dataset components

| Component | Meaning and information gathered | JSON representation |
| --- | --- | --- |
| Plan | One document version, processed in full. | One dataset containing `content` and `review`. |
| Plan information | Document and jurisdiction metadata. | `content.plan_info`. |
| Actions | One record per specific heat adaptation activity, combining its occurrences throughout the plan. | `content.plan_actions`. |
| Review issues | Uncertainty, conflicts, source gaps, or possible omissions requiring review. | `review.issues`. |

#### Fields within each action object

| Action field | Meaning and information gathered | JSON representation |
| --- | --- | --- |
| Action identifier | Stable ID followed through verification. | `action_id` |
| Action description | Activity, implementers, quantities, timing, conditions, and phase-specific details. | `action` |
| Action type | Infrastructural, institutional, behavioral/cultural, and/or nature-based. | `action_type` |
| Action status | Planned, underway, completed, or unspecified at the grouped activity level. | `action_status` |
| Action location | All stated locations or geographic coverage. | `action_location` |
| Action recipients | Stated intended populations or affected groups. | `action_recipient` |
| Action cost | Stated amounts, units, periods, and whether estimated, allocated, spent, or needed. | `action_cost` |
| Action benefit | Stated outcomes and qualifications, preserving whether expected, modelled, or observed. | `action_benefit` |
| Supporting evidence | Exact quotations and physical PDF page numbers supporting the recorded details. | `evidence` |

Costs, benefits, and evidence are attached to the activity they describe. The [appendix](#appendix-dataset-coding-rules-and-evaluation) defines the fields and coding rules used by models and experts.

### Evidence and issues

Evidence consists of exact, continuous quotations with physical PDF page numbers counted from 1. Separate passages are represented by separate evidence entries, including relevant headings or footnotes. Adequate evidence collectively supports the activity and its stated details.

Concerns about one action are grouped into one issue. Omissions and source gaps are recorded without an action link when necessary. Ordinary unstated details are represented by the defined missing values. The verifier retains existing issue IDs, may add issues, and explains claimed resolutions for expert assessment. Experts may subsequently resolve issues in curated copies. Expert curation corrects or excludes unsupported material.

### Workflow and comparison

During development, models will draft action records and flag uncertainties. Experts will examine the outputs against the plans and identify changes needed in coding rules, prompts, tools, and review procedures. Examples showing what prompted a revision, how it was addressed, and what was observed afterwards will be preserved. These examples will support the study's account of building the workflow and the lessons drawn from that process.

The extractor and verifier will use the same source preparation and document tool capabilities through Model Context Protocol (MCP), the interface connecting agents to tools.

| Stage | Procedure and saved result |
| --- | --- |
| 1. Registration and preparation | The original PDF, collection metadata, page text, and preparation problems will be preserved. |
| 2. Extraction (E) | The extractor will receive the whole prepared plan. Its answer, issues, settings, tool activity, and execution records will be saved. |
| 3. Verification (E+V) | A different model will check a copy of that exact extraction, including unflagged content and possible omissions. Its full revised answer will be saved. |
| 4. Independent reference preparation | After successful E and V runs, experts will code the original PDF before viewing model outputs. This initial reference will be preserved. |
| 5. Expert assessment | Experts will match activities by meaning, review possible reference corrections, and assess both outputs against one shared final reference. Revisions will be recorded with reasons and source evidence. |
| 6. Analysis and dataset assembly | Lessons about pairing experts and LLMs to build the workflow will be synthesized. Paired outputs will be compared, and instruction examples will be assembled from expert-curated answers and their supporting inputs. |

Each comparison will use the first successful E run and the first successful V run linked to it under the fixed settings. Successful execution means that format and execution checks have passed. Failed attempts will be retained, with manual retries linked to the earlier attempt. Deliberate repeats of successful work will be treated as exploratory.

Models, prompts, preparation, tools, coding rules, and scoring will be fixed before comparison. Any subsequent changes and the affected runs will be documented. [IMPLEMENTATION.MD](IMPLEMENTATION.MD) describes current software and planned work, and [README.md](README.md) provides available commands.

## 4. Evaluation

### Expert reference and scoring

Experts will use the same rules for grouping activities as the models. Once the independent initial reference has been preserved, supported additions and other reference corrections identified from both outputs will be reviewed. Every revision will be recorded with its reason and source evidence. Both saved outputs will then be scored against the shared final reference.

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
| Action accuracy and completeness | **Action score percentage**, using the 0/0.5/1 scores for final reference activities. |
| Unsupported activities | **Unsupported action count**, reported alongside the total distinct output activities. This captures invented or ineligible activities outside the reference-based score. |
| Evidence quality | **Actions with adequate evidence**, the percentage of output activities whose supplied evidence supports all recorded substantive details and uses faithful quotations with correct pages. |
| Issues requiring review | **Open issues** in E and E+V, and **expert-confirmed verifier resolutions** reported against resolutions claimed for initially open E issues. |
| Computational requirements | Successful processing runtime, provider-reported tokens, and failed executions as supporting information. |

The [evaluation appendix](#g-evaluation-measures-and-calculations) defines calculations and denominators. Assessment notes explain errors and corrections without requiring separate scores for every quotation or page.

### Analysis and limitations

The analysis will examine how heat adaptation experts and LLMs work together to develop the extraction workflow. Examples of decisions, revisions, and failures will help identify practical lessons about combining expert knowledge with model outputs to build and refine the workflow.

The paired comparison will examine whether verification improves the accuracy and completeness of action records, the adequacy of supporting evidence, and the handling of issues requiring review. Changes between E and E+V will be examined for each plan, including corrected errors, recovered omissions, new errors, and unresolved issues. Runtime, token use, and failed attempts will describe the computational requirements of each approach.

With five selected comparison plans and one model pair, the findings will be descriptive and specific to this study setting. Document layout and errors when extracting text from PDFs or scans may affect extraction quality. Expert judgments about action grouping and scoring may vary, and revisions to the reference after viewing model outputs may favor information included in those outputs.

The coarse action scores and combined evidence judgment may hide differences in the nature or severity of errors. Grouping an activity across locations or phases also gives records with different amounts of detail equal weight. Issue counts depend on what the models flag and provide only a partial view of review needs.

## Appendix: dataset, coding rules, and evaluation

A **schema** defines fields, types, and permitted values. An **object** groups named fields, a **list** holds items, and an **enum** limits a value to named choices. `null` represents unavailable information.

Sections A–D define the target plan dataset, E defines category options, F gives coding rules, and G defines evaluation. [IMPLEMENTATION.MD](IMPLEMENTATION.MD#appendix-supporting-json-files) specifies the supporting workflow files.

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
| `plan_actions` | list of action objects | One object per specific heat adaptation activity throughout the plan. An empty list follows a completed search, with unresolved source gaps recorded as issues. |

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
| `quote` | string | Exact continuous source passage. Separate passages are represented by separate objects. |
| `page_numbers` | nonempty list of unique positive integers | Physical PDF positions containing the passage, starting at 1. A continuous passage may span pages. |

### D. Review and issues

| Field | Type | Meaning |
| --- | --- | --- |
| `issues` | list of issue objects | Problems and uncertainties retained for review; `[]` when none are identified. |

Each issue object:

| Field | Type | Meaning |
| --- | --- | --- |
| `issue_id` | string | Stable issue ID retained through verification and expert curation. |
| `related_action_id` | string or null | Affected action ID. Null for an omission, a problem affecting the plan or its source, or a removed action. |
| `issue_description` | string | Grouped concerns, including relevant pages and any affected actions not linked directly. |
| `issue_type` | enum or null; optional | Classification of the concern, using the values in [appendix E](#issue-types). |
| `issue_origin` | enum | `extractor` or `verifier`, identifying the stage that first raised the issue. Retained through later review and curation. |
| `issue_status` | enum | `open` when concerns still require attention, or `resolved` when a resolution has been recorded. Model resolutions remain claims for expert assessment. |
| `resolved_by` | enum or null | `extractor`, `verifier`, or `expert` when resolved. Null while open. Expert resolutions are recorded in curated copies after assessment. |
| `resolution` | string or null | Explanation addressing every concern when resolved; null while open. |

An open issue has null `resolved_by` and `resolution`. A resolved issue identifies who resolved it and explains how all grouped concerns were addressed. Reopening an issue retains its `issue_id` and `issue_origin`. Expert assessment of a verifier's claimed resolution is recorded in the assessment file. A subsequent fix by an expert is recorded in a curated copy of the dataset.

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

Status describes what the plan reports about the grouped activity.

| Action status | Working definition |
| --- | --- |
| `planned` | Proposed or committed, with no source evidence that work has begun. |
| `underway` | Work has started or the activity is operating. |
| `completed` | The grouped activity is explicitly reported as finished. |
| `unspecified` | An overall status cannot be established, including when only differing phase or location statuses are available. |

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
| How should activities be grouped? | The same specific activity is combined across neighborhoods, programmes, phases, and repeated mentions. One object for tree planting retains all stated locations, quantities, dates, implementers, statuses, costs, benefits, and evidence. Differences in those details alone do not create separate objects. |
| When should activities have separate records? | Distinct activities, such as tree planting and drinking fountain installation, have separate objects. Broad categories such as nature-based may contain several distinct activities. Borderline cases will be piloted before comparison. |
| How should details and conflicting statements be handled? | Each detail retains its association with the stated location or phase. Repeated totals are counted once. Conflicting source statements are recorded as issues. |
| When should goals be included? | A concrete activity retains its stated targets or deadlines. A broad aspiration alone falls outside the action records. |
| How should monitoring and evaluation be recorded? | Concrete heat-related activities, such as operating heat-health surveillance, are actions. The description preserves the source's distinction between monitoring and demonstrated outcomes. |
| How should locations, recipients, and implementers be recorded? | Locations and intended populations use their dedicated fields. Implementers appear in `action`, supported by evidence identifying their responsibility for the activity. |
| How should action types be assigned? | Every category supported by the activity's described mechanism is recorded. Possible wider effects alone do not justify a type. Multiple types describe aspects of the same activity. |
| How should action status be coded? | The source's overall status is recorded using the values in appendix E. A past deadline alone cannot establish completion. |
| How should differing phase or location statuses be handled? | When the source provides no overall status, `action_status` is `unspecified` and each phase or location status is retained in `action`. Mixed reporting alone requires no issue. |
| How should other reported states be handled? | States outside the four values, such as withdrawal, are retained in `action`, with `action_status` set to `unspecified` and the coding limitation identified in an issue. |
| How should costs be recorded? | Amounts retain their original currency or units, periods, qualifications, and whether estimated, allocated, spent, or needed. Each amount retains its association with the relevant phase or location. |
| How should benefits be recorded? | Outcomes retain quantities, affected groups, comparisons, timing, and qualifications, including stated adverse effects and whether expected, modelled, or observed. |
| When should shared budgets or outcomes be attached to an action? | Shared budgets or outcomes are attached when the source establishes an activity link. Their scope is retained, and repeated amounts are counted once. General plan-wide statements without an activity link fall outside the action dataset. |
| How should missing details be recorded? | Unavailable descriptive fields are represented by `null`, and unstated overall status by `unspecified`. When no action type can be justified, the type list is empty (`[]`) and an issue explains the uncertainty. Missing details alone cannot establish zero cost, no benefit, or absence of an action. |
| How should supporting evidence be recorded? | Exact continuous quotations use physical PDF page numbers counted from 1. Separate passages have separate evidence entries, including necessary headings or footnotes. Together, the evidence supports the activity and its recorded details. |

### G. Evaluation measures and calculations

The selected E and linked E+V outputs form the basis of comparison. Quality is assessed on each saved output before curation. Runtime and token totals for E+V include the shared extractor and the verifier.

#### Before expert assessment

| Measure | Calculation | Comparison |
| --- | --- | --- |
| Open issues | Number of issues whose `issue_status` is `open` in each output. | E is the initial baseline. E+V includes retained and newly raised open issues. |
| Successful processing runtime | Sum of measured durations of selected successful stages, in seconds. | E uses extractor duration. E+V adds verifier duration. |
| Tokens used | Sum of provider-reported input and output tokens across generation calls, with the two components retained. | E uses extractor calls. E+V adds verifier calls. |
| Failed executions | Number of distinct failed comparison run IDs, including retries. | Counts are reported by stage, with shared extractor failures counted once. |

Runtime covers stage setup/loading, model and tool requests, saving, validation, permitted repairs, and cleanup. Measurements for failed attempts are reported separately from successful processing. Preparation, human review, and gaps between attempts fall outside stage runtime.

#### After expert assessment

Supported additions and corrections are first reconciled into the shared final reference. Output content is grouped by specific activity, with split or duplicate records combined and their IDs and all substantive claims retained. Bundled activities are assessed separately. Each final reference activity receives one score under section 4.

| Measure | Calculation | Interpretation |
| --- | --- | --- |
| Action score percentage | Sum of final reference action scores ÷ number of final reference actions × 100. | Main quality measure, combining correctness and completeness with partial credit. |
| Unsupported action count | Number of distinct output activities judged unsupported or ineligible under the coding rules, alongside the total number of distinct output activities. | Captures invented or ineligible activities outside the reference denominator. Wrong details within a supported activity affect its action score. |
| Actions with adequate evidence | Number of output activities with adequate evidence ÷ total distinct output activities × 100. | Evidence is adequate when it collectively supports all recorded substantive details and every supplied quotation faithfully reproduces the PDF and cites its correct physical pages. Missing evidence and unsupported activities fail this judgment. |
| Expert-confirmed verifier resolutions | Number of initially open E issues with `issue_status` set to `resolved` and `resolved_by` set to `verifier` in E+V that experts judge justifiably resolved, reported as confirmed / claimed resolutions. | Shows whether the verifier's explanations address all grouped concerns. The count of open issues in E supplies the initial issue total. |

For example, six scores of 1, two of 0.5, and two omissions among ten reference activities yield an action score of 70%. Two additional invented activities would contribute to the unsupported action count. The score distribution is retained in the assessments.

An activity can receive full content credit while its supplied evidence is inadequate, for example when its description is correct but its page citation is wrong. Experts check all supplied evidence, recording one adequacy judgment and explanation per output activity. The explanation identifies important quotation, citation, or coverage failures.

For issue assessment, only initially open E issues that V marks resolved require a resolution judgment. A claimed resolution is confirmed when source review shows that every grouped concern was addressed. Comparisons use the saved model outputs before expert curation, while expert fixes are recorded in curated copies. More open issues can reflect improved detection, so counts are interpreted alongside quality scores and examples.

#### Paired comparisons and reporting conventions

Paired changes are calculated as E+V minus E, with percentage differences expressed in percentage points. Results are reported for each plan with counts and denominators. A descriptive overall summary uses the mean of valid per-plan percentages and identifies contributing plans. Results for individual plans allow variation between documents to be examined.

The value `null` indicates pending judgments or unavailable measurements. Missing required usage or duration makes the corresponding total unavailable. Zero denominators are not applicable. Supported output activities absent from the initial reference enter the shared final reference before scoring. Any activity whose support is still undetermined keeps the relevant quality measures pending.

The study reports three quality measures and two issue measures. Review notes describe detailed quotation, citation, addition, and issue examples. Formal assessment files contain the judgments required above.
