# Design Doc: Heat Adaptation LLM Dataset

**Research design · updated 2026-11-25**

[Sample](#study-sample) · [Workflow](#workflow-and-comparison) · [Evaluation](#4-evaluation) · [Dataset building](#5-post-study-dataset-building) · [Coding rules](#f-action-coding-rules) · [Calculations](#g-evaluation-measures-and-calculations)

## 1. Context and problem

Heat adaptation actions are spread across government plans, with varied terminology, layouts, and evidence. Extracting them into consistent records could support comparison across jurisdictions, but requires careful grouping, source interpretation, and review.

This study pairs heat adaptation experts with open-weight large language models (LLMs) accessed through hosted APIs. It preserves source documents, prompts, settings, available model-version information, outputs, and expert judgments so the workflow can be examined and reproduced.

The study compares three configurations:

| Configuration | How it works |
| --- | --- |
| **Extractor (E)** | One model extracts actions and supporting evidence from the prepared plan. |
| **Extractor + Verifier (E+V)** | A second model, the verifier (V), checks that exact saved extractor output against the same plan and revises it. |
| **Collaboration (C)** | A coordinator directs two model workers to investigate the plan and assemble one answer, independently of E/E+V. |

## 2. Research aim and objectives

Develop and evaluate an expert–LLM extraction workflow, then build a heat adaptation action dataset using the selected configuration.

1. **Understand how experts and LLMs build the workflow.** Document problems, revisions, and practical lessons from refinement.
2. **Evaluate verification and collaboration.** Compare E, E+V, and C for action accuracy/completeness, evidence, unresolved issues, and successful-run resource use.

The workflow is agentic: models can request document tools while completing their tasks. Dataset building follows the comparison study; instruction export and fine-tuning are deferred.

## 3. Methods

### Eligible plans

Plans must be:

- Final, publicly available English documents issued by governments or public agencies, published or updated in 2010 or later.
- Explicitly about heat, or contain a dedicated heat section with at least one action.
- Available as PDFs with stable physical pages and content readable by a person, including scanned documents.

Experts screen eligibility and select varied lengths, layouts, and plan types, excluding near-duplicates. Recent versions and city plans are preferred; other jurisdictional scales are eligible.

### Study sample

All ten plans belong to one comparison sample. Use two first to build and test the workflow, then extend execution to the other eight. Study runs use `purpose: comparison`; manually recorded versions and run IDs identify the final study results.

| Stage | Plans | Use |
| --- | --- | --- |
| Initial refinement | 2 | Build the workflow, refine prompts/tools, and check execution. |
| Additional sample | 8 | Extend execution after initial refinement; document further revisions. |
| Final comparison | All 10 | Run and assess E, E+V, and C under the final settings. |

Record selection reasons, document characteristics, and which plans informed refinements. Preserve earlier outputs; rerun all ten under the [final selection rules](#final-versions-and-output-selection).

### Extracted dataset and action records

Each model output contains three components:

| Component | Contents |
| --- | --- |
| `plan_data.metadata` | Plan and jurisdiction information. |
| `plan_data.actions` | One record per specific heat adaptation activity across the plan. |
| `plan_issues.issues` | Grouped concerns, source gaps, conflicts, and possible omissions. |

Group repeated occurrences of the same activity while retaining quantities, implementers, locations, phases, timing, costs, benefits, and evidence. Separate different primary tasks or outputs, even under one programme. Tree planting and drinking fountains are separate activities; differing planting locations alone do not create separate records.

The [appendix](#appendix-dataset-coding-rules-and-evaluation) defines all fields, categories, missing values, and coding rules.

### Evidence and issues

Evidence uses exact continuous quotations and every physical PDF page containing the quoted words, counted from 1. Separate passages have separate evidence entries. Quotations preserve wording, punctuation, and line breaks. When optical character recognition (OCR) is unreliable, use locatable excerpts and record unresolved gaps.

In model outputs, group concerns about one action into one issue. Source problems and possible omissions may have no action link. V retains E issue IDs/origins and records its claimed fixes. C maintains independent action/issue identities. Expert corrections follow the comparison in separate dataset-building review drafts.

### Workflow and comparison

| Configuration | Models and task | Input |
| --- | --- | --- |
| **Extractor (E)** | Inkling 2 Small (`thinkingmachines/Inkling-2-Small`) extracts actions. | Whole prepared plan. |
| **Extractor + Verifier (E+V)** | DeepSeek V4.1 Flash 1017 (`deepseek-ai/DeepSeek-V4.1-Flash-1017`) checks and revises E. | That exact saved E and its prepared plan. |
| **Collaboration (C)** | GLM-5.3-Flash (`zai-org/GLM-5.3-Flash`) coordinates Inkling and DeepSeek as flexible workers. | Same prepared plan, independently of E/E+V and expert references. |

All inference uses Hugging Face with DeepInfra as the fixed host. PDF preparation, EasyOCR, and source tools run locally through MCP, the interface connecting models to document tools. C may run independent assignments in parallel, exchange relevant findings, revise a shared draft, and assemble one answer. Both workers contribute; roles remain fixed while tasks vary.

During refinement, experts review outputs against the PDFs and revise prompts, coding guidance, tools, and review procedures. Preserve examples showing the problem, revision, and observed outcome. Current results and implementation limits are described in [IMPLEMENTATION.MD](IMPLEMENTATION.MD#current-checkpoint).

#### Final versions and output selection

Version and run selection are tracked manually:

1. Record the final code version, model/host identities, prompts, generation controls, tools, budgets, timeouts, validation/repair policies, and each plan's source/preparation version. Fix coding and scoring rules.
2. Run all ten plans under the final settings with `purpose: comparison`. For each, record the first validated successful E, its first successful linked V, and the first successful independent C. V retries retain that E. The purpose label alone does not identify final selections.
3. Retry execution failures with unchanged settings. **Any workflow change requires rerunning all three configurations across all ten plans**, including earlier successes.
4. Check the manual log and saved evidence before assessment/reporting: all **30 selected outputs** must use the final versions. Keep earlier outputs as history.

Each configuration uses its own fixed definition across plans. C's task sequence may adapt within that definition. No software command to create or freeze a study round is required.

#### Budgets, processing, and preservation

Each configuration has a 90-minute ceiling, including a protected 30-minute final-answer window. E+V shares the first 60 minutes between complete E execution and V investigation; an E exceeding that allowance cannot enter timed E+V. C shares its budget across all agents. Human waiting is excluded. Common ceilings do not establish equal computation; [implementation settings](IMPLEMENTATION.MD#current-configuration-settings) define the other limits.

A submitted tool timeout fails the execution, preserves available evidence/late replies, and stops further model requests. Ordinary unreadable-source/OCR replies may remain recoverable. Execution success means format and execution checks pass; experts still judge substantive quality.

All outputs receive the same quotation-location checks. A single-page citation is corrected only when its readable cited page does not match and the full quotation matches exactly one other available physical page. Matching tolerates whitespace differences while preserving wording/punctuation. Ambiguous and unmatched quotations remain flagged. Raw replies, candidates, repairs, settings, tool activity, and available usage are preserved. V receives processed E; assessment uses processed outputs before curation.

Successful-run finalization and loading check accepted answers against preserved final candidates and archived code against startup checksums. Saved C inputs must match their source/settings; chronology uses parsed UTC times. These checks establish record consistency, while experts judge accuracy.

## 4. Evaluation

### Expert reference and scoring

Experts code one reference per plan from the original PDF using the same activity rules. Complete it before viewing outputs where no prior exposure has occurred; record exposure from initial testing or later refinement. Review, validate, and freeze the completed form before scoring all three outputs against it.

Reference freezing records exact reference/PDF fingerprints, time, and readiness confirmation. Reference, assessment, and review records do not capture names or study IDs. Software checks structure and links; experts establish completeness and source meaning. Reference IDs remain stable and deleted IDs are not reused. Guided placeholders must be completed or removed. Reference issues use the expert role and remain separate from model issues.

Match activities by meaning. Combine split/duplicate output records, retain all substantive claims, and assess each activity in a bundled record separately. Each reference activity receives one score:

| Score | Judgment |
| --- | --- |
| 1 | Activity and all required substantive details are correct; every substantive addition has source support. |
| 0.5 | Some substantive information is correct, but a required detail is wrong, missing, or unsupported. |
| 0 | Activity is omitted, or matched content contains no correct substantive information about it. |

Required details include description, type, status, places, recipients, costs/benefits, quantities, implementers, timing, and conditions. Defined missing values are correct when the source is silent. Evidence is judged separately, so correct content can receive full credit with inadequate citations.

### Evaluation outcomes

| Outcome | Measure |
| --- | --- |
| Accuracy and completeness | Reference action-score percentage using 0/0.5/1 scores. |
| Unsupported activities | Unsupported/ineligible activity count alongside total distinct output activities. |
| Evidence quality | Percentage of output activities with faithful, correctly cited evidence supporting all substantive details. |
| Review issues | Open issues in E, E+V, and C; expert-confirmed/claimed V resolutions for initially open E issues. |
| Resources | Runtime and provider-reported input/output tokens for selected successful runs. |

Check activities absent from the reference against the PDF before judging them unsupported. Confirm a V resolution only when every grouped concern is addressed. Describe C issue handling and agent disagreements in notes, without matching its issue IDs to E's.

Experts fill prepopulated assessment CSVs; generated metadata identifies inputs and fingerprints. Use explicit run IDs from the manual log for final assessments; latest-run defaults support earlier review. Assessments accept only comparison-purpose outputs, including when selecting defaults. Software validates records and calculates measures without supplying judgments or certifying the final settings/sample. See [calculation rules](#g-evaluation-measures-and-calculations) and the [worked scoring example](IMPLEMENTATION.MD#worked-scoring-example).

### Analysis and limitations

Compare E+V minus E and C minus E+V within each plan. Report all ten plans, counts/denominators, and equal-weight means of valid per-plan percentages. Each paired summary uses plans with both measures available. Identify contributing/excluded plans for every measure.

Pending judgments and missing observations remain `null`; zero denominators are not applicable. Runtime/token totals cover selected successful runs, excluding retries, superseded work, preparation, and human review. Failures remain execution history, outside quantitative outcomes.

Interpretation will account for:

- The small, selected sample and any plans used for refinement. Results describe the final workflows on these documents.
- C's extra model, allowances, and complete coordination workflow; differences do not isolate coordination alone.
- PDF layout/OCR errors and undisclosed hosted model/serving details.
- Expert grouping/scoring variability and possible omissions or errors in the reference.
- Coarse scores, unequal detail within grouped activities, and issue counts that depend on what models notice.

## 5. Post-study dataset building

Choose one configuration and rerun it with `purpose: dataset_building`, including the original ten plans. Those plans retain `study_set: comparison`; additional plans use `study_set: expansion`. V requires an E with the same purpose, and retries retain their purpose. Purpose controls eligibility and bookkeeping without changing extraction rules. Comparison assessments accept only comparison-purpose runs.

Experts review **remaining open issues only**. Retain every original issue; open concerns and newly raised expert concerns require expert resolutions before finalization. Preserve model-resolved statuses/resolutions. After action merges/removals, update links while retaining the original concerns. Record `review_scope: open_issues_only`; completeness, omissions, and model-resolved concerns remain outside this review scope.

| Stage | Saved product |
| --- | --- |
| Review draft | Editable plan data/issues and an exact selected successful dataset-building run. |
| Completed reviewed plan | Clean `metadata`/`actions`, a separate `review_record.json`, and exact draft/run copies. |
| Combined dataset | `heat_action_dataset.json` with one entry per plan; `dataset_contents.json` and preserved review copies identify its inputs and workflow. |

`finalize_reviewed_plan` checks issues before removing them from the data product. `build_heat_action_dataset` requires explicit completed review versions, rejects duplicate plan IDs/original PDFs, and enforces one recorded workflow. Compare model/provider settings, prompts, tools, budgets, software-version information, and archived code; E+V includes both linked stages and C includes its workers. Matching recorded information cannot verify undisclosed hosted revisions.

Completed and combined data contain **no issue objects**; separate review evidence retains the decisions and source limitations. Further edits start a new draft, and each combined build preserves a new version. Read-only `validate_reviewed_plan` and `validate_heat_action_dataset` recheck saved outputs and evidence without changing them or supplying expert judgments.

Comparison work uses `data/comparison/`; drafts, reviewed plans, and combined versions use `data/dataset_building/`. PDFs, preparations, and model runs are shared across stages. The core software path is implemented; real-plan pilots and study execution remain. Instruction export and fine-tuning are deferred. See the [command workflow](README.md#7-run-the-chosen-configuration-for-dataset-building).

## Appendix: dataset, coding rules, and evaluation

A **schema** defines fields, types, and permitted values. An **object** groups named fields, a **list** holds items, and an **enum** limits a value to named choices. `null` represents unavailable information.

Sections A–D define the target plan dataset, E defines category options, F gives coding rules, and G defines evaluation. [IMPLEMENTATION.MD](IMPLEMENTATION.MD#appendix-supporting-json-files) specifies the supporting workflow files.

All fields are required unless marked optional. Text is nonblank unless stated otherwise. Dates use `YYYY-MM-DD`. Record links refer to items within the same plan dataset, and cited page numbers fall within the original PDF's page range.

<details>
<summary>Dataset fields and category definitions (A–E)</summary>

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
| `evidence` | list of evidence objects | Quotations supporting the action and its details. An empty list requires a linked issue; any remaining source limitation is retained in the completed review record. |

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
| `issue_id` | string | Stable issue ID retained through revisions and review within its workflow. C IDs are independent of E/E+V. |
| `related_action_id` | string or null | Affected action ID. Null for an omission, a problem affecting the plan or its source, or a removed action. |
| `issue_description` | string | Grouped concerns, including relevant pages and any affected actions not linked directly. |
| `issue_type` | enum or null; optional | Classification of the concern, using the values in [appendix E](#issue-types). |
| `issue_origin` | enum | Agent that first raised the issue: `extractor` or `verifier` in E/E+V; `worker_1` (Inkling), `worker_2` (DeepSeek), or `coordinator` (GLM) in C. New expert-added review issues use `expert`; original origins remain unchanged. |
| `issue_status` | enum | `open` when concerns still require attention, or `resolved` when a resolution has been recorded. Model resolutions remain claims for expert assessment. |
| `resolved_by` | enum or null | Agent that resolved the issue, using the same workflow-specific identities as `issue_origin`, or `expert` for a resolution in a dataset-building review draft. Null while open. |
| `resolution` | string or null | Explanation addressing every concern when resolved; null while open. |

An open issue has null `resolved_by` and `resolution`. A resolved issue records the resolving role and explains how all grouped concerns were addressed. Model verification may reopen an issue while retaining its ID/origin; plan review preserves model-resolved statuses and resolutions. Expert assessment of V's claimed resolutions is recorded in the assessment. Later expert fixes belong in review drafts from separate dataset-building runs. Independent expert-reference issues are defined in the [reference form](IMPLEMENTATION.MD#expert-reference-form).

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

</details>

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

The final comparison uses the manually recorded E, linked E+V, and independent C outputs for all ten plans. Quality is assessed on saved processed outputs before curation. E+V includes the shared extractor and verifier; C includes its own coordinator and all worker activity.

#### Before expert assessment

| Measure | Calculation | Comparison |
| --- | --- | --- |
| Open issues | Number of issues whose `issue_status` is `open` in each output. | Reported for E, E+V, and C; independently generated C issues are not matched to E IDs. |
| Successful processing runtime | Measured processing duration, in seconds. | E uses extractor duration; E+V adds verifier duration. C uses its complete elapsed duration, without summing overlapping worker durations. |
| Tokens used | Sum of provider-reported input and output tokens across generation calls, with the two components retained. | E uses extractor calls; E+V adds verifier calls. C includes every coordinator and worker call once. |

Runtime covers setup/loading, requests, tools, saving, validation, permitted repairs, and cleanup. C uses its own elapsed duration, counting overlapping work once. Totals cover selected successful runs; failed/superseded attempts remain history. Failure counts, preparation, human review, and gaps between attempts are outside the reported measures.

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

For issue assessment, only initially open E issues that V marks resolved require a resolution judgment. A claimed resolution is confirmed when source review shows that every grouped concern was addressed. Comparisons use the saved processed outputs before expert curation, while later expert fixes are recorded in dataset-building review drafts. Python citation repairs are logged separately and do not create a model-claimed issue resolution. More open issues can reflect improved detection, so counts are interpreted alongside quality scores and examples.

#### Paired comparisons and reporting conventions

| Report | Rule |
| --- | --- |
| Per-plan results | Retain counts/denominators and one exact saved calculation per plan. Manually check all 30 selected outputs against final settings. |
| Percentages | Equal-weight mean of valid per-plan percentages across the ten-plan sample. |
| Paired changes | E+V minus E and C minus E+V within plans, then mean over eligible pairs; percentage changes use percentage points. |
| Counts/resources | Labelled configuration totals; confirmed/claimed V resolutions use the same contributing plans. |
| Missing values | `null` for pending/unavailable observations; missing required usage/duration makes its total unavailable. Zero-denominator percentages are not applicable. |

Identify contributing/excluded plans for every measure. Undetermined support keeps affected quality measures pending. Check activities absent from the reference against the PDF and record reference gaps; absence alone does not establish unsupported content. Review notes retain quotation, citation, addition, issue, and C collaboration examples.

<details>
<summary>Fictional JSON example</summary>

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

</details>
