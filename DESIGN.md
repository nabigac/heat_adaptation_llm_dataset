# Design Doc: Heat Adaptation LLM Dataset

**Research design · updated 2026-11-14**

## 1. Context and problem

Government and public-agency plans describe actions to address heat risk. Extracting these actions into a consistent dataset would support comparison across jurisdictions. The work requires reading varied documents, combining descriptions spread across pages, and preserving details such as implementation status, costs, and expected benefits.

Large language models (LLMs) could assist this work, but their outputs require assessment against the source. This study examines a workflow combining open-weight models, document tools, and heat adaptation experts. Open-weight models have downloadable trained parameters and can be run locally. Preserving the source documents, model versions, prompts, settings, and expert judgments supports reproducibility.

## 2. Research aim and objectives

The study will develop and evaluate an agentic workflow for extracting heat adaptation actions from plans and producing an expert-curated pilot instruction dataset. In an agentic workflow, models can request tools while completing a task. An instruction example pairs task instructions and source input with a reviewed answer for future fine-tuning.

The study has two objectives.

1. **Document workflow development.** Explain document preparation, extraction, tool use, failures, and expert intervention through preserved records and development examples.
2. **Evaluate added verification.** Compare an extractor alone (E) with that same extraction revised by a different open-weight model (E+V). Assess corrected errors, recovered omissions, introduced errors, unresolved issues, and computational requirements.

The intended publication is a short empirical methods paper for an AI journal, accompanied by the workflow and pilot dataset. Fine-tuning is a future use of the dataset.

## 3. Methods

### Eligible plans

Eligible plans meet all of the following criteria.

- Final, publicly available English plan issued by a government or public agency, published or updated in 2010 or later.
- Address heat directly, or contain a dedicated heat section with at least one action.
- Available as a PDF with stable page positions and content readable by a person, including scanned pages.

Experts screen eligibility, preferring recent versions. City, county, regional, state, and national plans are eligible, with particular interest in city plans. Broader plans may cover heat adaptation across their jurisdiction.

### Study sample

| Study set | Planned size | Purpose |
| --- | --- | --- |
| Development | 2 plans | Refine coding, software, and expert assessment through openly inspected examples. |
| Comparison | 5 separate plans | Evaluate E and E+V against independent expert work under fixed settings. |
| Expansion | Deferred | Extend the dataset after evaluating the workflow. |

Select plans that vary in length, layout, and type, avoiding near-duplicates. Select the comparison set before comparison runs and keep development documents separate. Record the selection rationale and document characteristics.

### Extracted dataset and action records

Each plan produces one JSON dataset containing plan information, action records, and review issues. JSON stores named fields in objects and lists of objects in arrays.

Within a plan, group actions by the specific activity undertaken. For example, all tree planting belongs in one action object, including planting in different neighborhoods or phases. Preserve the details associated with each location or phase. Tree planting and drinking-fountain installation form separate actions. The broad `action_type` categories classify each activity and may overlap.

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

Evidence consists of exact, continuous quotations with physical PDF page numbers counted from 1. Keep separate passages in separate evidence entries, including relevant headings or footnotes. Together, quotations must support the activity and its stated details.

Group concerns about one action into one issue. Record omissions and source gaps without an action link when necessary. Ordinary unstated details use the defined missing values. The verifier retains existing issue IDs, may add issues, and explains claimed resolutions for expert assessment. Expert curation corrects or excludes unsupported material.

### Workflow and comparison

Both stages use the same source preparation and document-tool capabilities through Model Context Protocol (MCP), the interface connecting agents to tools.

| Stage | Procedure and saved result |
| --- | --- |
| 1. Registration and preparation | Preserve the original PDF, collection metadata, page text, and preparation problems. |
| 2. Extraction (E) | Supply the whole prepared plan. Save the answer, issues, settings, tool activity, and execution records. |
| 3. Verification (E+V) | A different model checks a copy of that exact extraction, including unflagged content and possible omissions. Save its full revised answer. |
| 4. Independent reference preparation | After both outputs succeed, experts code the original PDF without seeing model outputs. Preserve this initial reference. |
| 5. Expert assessment | Match activities by meaning, review possible reference corrections, and assess both outputs against one shared final reference. Preserve revision reasons and source evidence. |
| 6. Analysis and dataset assembly | Compare paired outputs and document development lessons. Assemble instruction examples from expert-curated answers and their supporting inputs. |

Use the first successful E run and the first successful V run linked to it under the fixed settings. Successful execution means format and execution checks passed. Retain failed attempts and link manual retries. Deliberate repeats of successful work are exploratory.

Fix models, prompts, preparation, tools, coding rules, and scoring before comparison. Document subsequent changes and identify affected runs. [IMPLEMENTATION.MD](IMPLEMENTATION.MD) describes current software and planned work, and [README.md](README.md) provides available commands.

## 4. Evaluation

### Expert reference and scoring

Experts use the same rules for grouping activities as the models. After preserving the independent initial reference, review supported additions and other reference corrections from both outputs. Record every revision with its reason and source evidence, then score both saved outputs against the shared final reference.

Match actions by activity and meaning. Assess split or duplicate records together and count each reference activity once. Preserve conflicting or unsupported details when judging the output. If a record bundles different activities, assess its relevant content against each matching reference activity.

| Score | Judgment about a reference action and its matched output |
| --- | --- |
| 1 | The activity and all required substantive details are correct, with source support for every substantive addition. |
| 0.5 | Some substantive information about the activity is correct, but a required detail is wrong, omitted, or unsupported. |
| 0 | The activity is omitted, or the matched content contains no correct substantive information about it. |

Assess the description, classification, status, locations, recipients, costs, and benefits under the coding rules. Required substantive details include stated quantities, implementers, timing, conditions, and differences between neighborhoods or phases. Defined missing values are correct when the source is silent. Experts judge content against the original PDF, with supplied quotations and citations assessed through the evidence measure. Plan information is checked during curation, and issues have their own measures.

For a fictional example, a heat adaptation section reports 100 trees planted in North Ward in 2025 and another 200 planned for South Ward in 2027. The reference contains one tree-planting action, classified as nature-based, with both wards and their associated quantities, dates, and phase statuses. Its overall status is `unspecified` because the source supplies differing phase statuses without an overall status.

| Score | Example output |
| --- | --- |
| 1 | Correctly records both planting phases, their wards, quantities, dates, and statuses, and uses the defined missing values for unstated fields. |
| 0.5 | Correctly records the North Ward planting but omits South Ward, or incorrectly describes all 300 trees as already planted. |
| 0 | Omits tree planting, or supplies a description with no correct substantive information about that activity. |

This study-specific rubric will be piloted on development plans. Checking the support for individual details draws on source-based factual evaluation in LLM research. [Min et al., 2023](https://aclanthology.org/2023.emnlp-main.741/)

### Evaluation outcomes

| Outcome | Measure and purpose |
| --- | --- |
| Action accuracy and completeness | **Action score percentage**, using the 0/0.5/1 scores for final reference activities. |
| Unsupported activities | **Unsupported action count**, reported alongside the total distinct output activities. This captures invented or ineligible activities outside the reference-based score. |
| Evidence quality | **Actions with adequate evidence**, the percentage of output activities whose supplied evidence supports all recorded substantive details and uses faithful quotations with correct pages. |
| Issues requiring review | **Open issues** in E and E+V, and **expert-confirmed verifier resolutions** reported against resolutions claimed for initially open E issues. |
| Computational requirements | Successful processing runtime, provider-reported tokens, and failed executions as supporting information. |

The [evaluation appendix](#f-evaluation-measures-and-calculations) defines calculations and denominators. Assessment notes explain errors and corrections without requiring separate scores for every quotation or page.

### Analysis and limitations

Report E, E+V, and their paired differences for each plan, with examples of corrected errors, recovered omissions, new errors, and unresolved problems. Development records explain consequential choices, failures, useful tools, and expert interventions. A short paper can present the workflow, one compact comparison table, selected error examples, and the resulting pilot dataset.

The small, selected sample supports descriptive findings about this workflow and model pair. Quality comparisons require successful paired outputs, so report any selected plan lacking a pair and why. Both configurations share E, while E+V adds another model pass and computational work. Grouping by activity gives each reference activity equal weight even when activities differ in complexity. The coarse scoring scale and combined evidence judgment require explanations of important errors. Issue counts depend on what models flag and cannot establish total error burden or expert time savings.

Before comparison, use development plans to settle coding examples, reviewer roles, and disagreement handling. Report the number and expertise of reviewers and how the reference and assessments were reconciled. Reference revision after viewing model outputs can favor their suggestions, so preserve the independent initial reference and evidence for every accepted change.

The instruction dataset will contain curated answers supported by the inputs supplied with each example. Its size is reported as both source plans and instruction examples, alongside action counts. Describe source selection, language, geographic coverage, and intended use to make the dataset's scope clear. [Bender and Friedman, 2018](https://aclanthology.org/Q18-1041/)

## Appendix: dataset, coding rules, and evaluation

A **schema** defines fields, types, and permitted values. An **object** groups named fields, a **list** holds items, and an **enum** limits a value to named choices. `null` represents unavailable information.

Sections A–D define the target plan dataset, E gives coding rules, and F defines evaluation. The current software still uses the earlier five-category format. [IMPLEMENTATION.MD](IMPLEMENTATION.MD#appendix-supporting-json-files) specifies workflow files and migration work.

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
| `action_type` | list of unique enum values | Any supported combination of `infrastructural`, `institutional`, `behavioral/cultural`, and `nature-based`. An empty list (`[]`) indicates that no type could be justified and is accompanied by an issue describing the classification uncertainty. |
| `action_status` | enum | `planned`, `underway`, `completed`, or `unspecified`, as defined in appendix E. |
| `action_location` | string or null | All stated places or geographic coverage, retaining their associations with phases or quantities where needed. |
| `action_recipient` | string or null | All stated intended populations or affected groups, retaining relevant local or phase-specific distinctions. |
| `action_cost` | string or null | Amounts, currency/units, periods, cost character, and qualifications, with each amount linked in the description to its activity, location, or phase. Shared amounts are identified. |
| `action_benefit` | string or null | Outcomes, quantities, affected groups, comparisons, timing, and qualifications, including local or phase-specific differences and whether expected, modelled, or observed. |
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

An eligible action is a specific activity explicitly connected to reducing heat risk or enabling heat adaptation through its description or a heat-specific heading. Include general climate, greening, or health measures when the source establishes their heat relevance.

| Coding decision | Approach |
| --- | --- |
| Activity grouping | Combine the same specific activity across neighborhoods, programmes, phases, and repeated mentions. One tree-planting object retains all stated locations, quantities, dates, implementers, statuses, costs, benefits, and evidence. Differences in those details alone do not create separate action objects. |
| Separate activities | Use separate objects for distinct activities, such as tree planting and drinking-fountain installation. Broad categories such as nature-based can contain several distinct activities. Pilot borderline cases and record examples before comparison. |
| Associations and conflicts | Keep each detail associated with its stated location or phase. Repeated totals are counted once. Record conflicting source statements as issues. |
| Goals | Include a concrete activity and its targets or deadlines. Broad aspirations alone fall outside the action records. |
| Monitoring and evaluation | Include concrete heat-related activities such as operating heat-health surveillance. Preserve the source's distinction between monitoring and demonstrated outcomes. |
| Where and who | Record stated locations and intended populations. Put implementers in `action`, using action-specific evidence for responsibility. |
| Costs | Records retain stated amounts, currency/units, periods, and whether they describe estimates, allocations, expenditure, or needs. Amounts remain in their original currency, and allocations are recorded only where supported by the source. |
| Benefits | Records retain stated outcomes, quantities, affected groups, comparisons, timing, and qualifications. Descriptions distinguish expected, modelled, and observed outcomes, including stated adverse effects. |
| Shared statements | Attach costs or benefits where the source establishes an activity link. Identify shared budgets or outcomes and retain their scope. General plan-wide statements without an activity link fall outside the action dataset. |
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

Use the source's overall status for the grouped activity when stated. `planned` means proposed or committed, `underway` means started or operating, `completed` means explicitly finished, and `unspecified` means an overall status cannot be established. A past deadline alone cannot establish completion.

When the source gives differing neighborhood or phase statuses without an overall status, use `unspecified` and preserve each status in `action`. This mixed reporting alone requires no issue. For states outside the four values, such as withdrawal, preserve the source wording in `action`, use `unspecified`, and flag the coding limitation.

### F. Evaluation measures and calculations

Use the selected E and linked E+V outputs. Quality is assessed on each saved output before curation. Runtime and token totals for E+V include the shared extractor and the verifier.

#### Before expert assessment

| Measure | Calculation | Comparison |
| --- | --- | --- |
| Open issues | Count issues marked `open` in each output. | E is the initial baseline. E+V includes retained and newly raised open issues. |
| Successful processing runtime | Sum measured durations of selected successful stages, in seconds. | E uses extractor duration. E+V adds verifier duration. |
| Tokens used | Sum provider-reported input and output tokens across generation calls, retaining the two components. | E uses extractor calls. E+V adds verifier calls. |
| Failed executions | Count distinct failed comparison run IDs, including retries. | Report by stage, counting shared extractor failures once. |

Runtime covers stage setup/loading, model and tool requests, saving, validation, permitted repairs, and cleanup. Report failed-attempt measurements separately from successful processing. Preparation, human review, and gaps between attempts fall outside stage runtime.

#### After expert assessment

First reconcile supported additions and corrections into the shared final reference. Group output content by specific activity, combining split or duplicate records while retaining their IDs and all substantive claims. Assess bundled activities separately. Each final reference activity receives one score under section 4.

| Measure | Calculation | Interpretation |
| --- | --- | --- |
| Action score percentage | Sum of final reference action scores ÷ number of final reference actions × 100. | Main quality measure, combining correctness and completeness with partial credit. |
| Unsupported action count | Count distinct output activities without source support as eligible heat adaptation actions, alongside total distinct output activities. | Captures invented or ineligible activities outside the reference denominator. Wrong details within a supported activity affect its action score. |
| Actions with adequate evidence | Number of output activities with adequate evidence ÷ total distinct output activities × 100. | Evidence must collectively support all recorded substantive details. Every supplied quotation must faithfully reproduce the PDF and cite its correct physical pages. Missing evidence and unsupported activities fail this judgment. |
| Expert-confirmed verifier resolutions | Count initially open E issues marked resolved by V and judged justifiably resolved. Report as confirmed / claimed resolutions. | Shows whether the verifier's explanations address all grouped concerns. The open-issue count in E supplies the initial issue total. |

For example, six scores of 1, two of 0.5, and two omissions among ten reference activities yield an action score of 70%. If an output also invents two activities, report those in the unsupported action count. Keep the score distribution available in the assessments.

An activity can receive full content credit while its supplied evidence is inadequate, for example when its description is correct but its page citation is wrong. Experts check all supplied evidence, recording one adequacy judgment and explanation per output activity. Record important quotation, citation, or coverage failures in that explanation.

For issue assessment, only initially open E issues that V marks resolved require a resolution judgment. A claimed resolution is confirmed when source review shows that every grouped concern was addressed. Retain unresolved or unjustified cases for discussion. More open issues can reflect improved detection, so interpret counts alongside quality scores and examples.

#### Paired comparisons and reporting conventions

Calculate paired changes as E+V minus E, expressing percentage differences in percentage points. Report every plan with counts and denominators. A descriptive overall summary uses the mean of valid per-plan percentages and identifies contributing plans. Retain per-plan results so larger documents do not hide variation.

Use `null` for pending judgments or unavailable measurements. Missing required usage or duration makes the corresponding total unavailable. Zero denominators are not applicable. Supported output activities absent from the initial reference enter the shared final reference before scoring. Any activity whose support is still undetermined keeps the relevant quality measures pending.

The study reports three quality measures and two issue measures. Use review notes for detailed quotation, citation, addition, and issue examples. Formal assessment files contain the judgments required above.
