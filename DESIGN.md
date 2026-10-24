# Heat Adaptation LLM dataset

**Study design and technical implementation — draft**

**Last updated:** 2026-10-24

This document describes the study workflow, proposed system components, data records, and evaluation measures. The JSON records and metric calculations below define the proposed data contract. Models, software packages, and the remaining study procedures will be selected during development.

## 1. Purpose

This research study will develop and evaluate a workflow that pairs open-weight large language models (LLMs) with heat adaptation experts to extract structured, source-linked data from government plans.

The study has two main questions:

1. How can open-weight LLM agents and experts build an extraction dataset using Model Context Protocol (MCP) tools, and what practical lessons emerge?
2. How does adding a verifier using a different open-weight model change extraction quality, issue handling, expert review requirements, and computational resources?

The dataset will describe what plans state about heat adaptation. It may support future fine-tuning, but model fine-tuning is outside this study.

## 2. Study design

| Study set | Size | Purpose |
| --- | --- | --- |
| Development | 2 plans | Develop prompts, tools, coding rules, and review procedures with experts. |
| Comparison | 10 separate plans | Compare extraction with and without verification against an expert-coded reference. |
| Expansion | To be determined | Apply the selected workflow to additional plans and curate the dataset. The original target is 50–100 unique plans in total. |

The comparison will use two configurations:

- **Extractor (E):** An agent reads a plan, produces structured records with supporting passages, and flags issues.
- **Extractor + verifier (E+V):** A second agent, using a different model, reviews the same extraction against the source. It checks flagged issues, examines all extracted records, and looks for omissions.

Both configurations will start with the same saved extractor output. Models, prompts, tools, processing rules, and evaluation procedures will be fixed before the comparison.

Experts will prepare the initial reference without seeing model outputs. The comparison will assess model outputs before expert correction. Findings will describe the tested workflow and model pairing; the study will not separately establish the effects of MCP or open-weight models relative to alternative technologies.

## 3. Plans and extraction content

Eligible documents are final government or public-agency plans that:

- Are publicly available in English and were published or updated in 2010 or later, with recent versions prioritized.
- Focus on heat adaptation or contain a dedicated heat section with at least one heat-specific action.
- Have a readable full document and stable PDF page numbers.

Each document version will have a unique plan ID. The extraction will contain plan metadata and five lists:

| List | Content |
| --- | --- |
| Goals | Stated heat adaptation goals, targets, and deadlines. |
| Actions | Proposed or reported actions and their implementation status. |
| Monitoring and evaluation | What is tracked or evaluated, how, and by whom. |
| Benefits and impacts | Expected or reported outcomes, including adverse impacts. |
| Costs and resources | Financial costs and other resource requirements. |

Section 6 defines the extraction fields and coding rules, based on the project proposal. Each record will include exact supporting passages and PDF page numbers. The first PDF page is page 1, regardless of printed labels. Links between records require source support.

Unavailable details will use `null`, empty lists, or the specified missing-information category. Routine missing details will not automatically create issues. An empty answer category will be flagged for checking before absence is confirmed.

## 4. Processing workflow

| Stage | Main tasks | Saved outputs |
| --- | --- | --- |
| Collect and prepare | Register the document, extract text by page, and check readability. | Source metadata, original PDF, page-marked text, and preparation status. |
| Extract | Read the plan, populate records, provide evidence, and flag issues. Check output structure and apply the agreed retry policy. | Extractor output, issue state, tool activity, and run measurements. |
| Verify | Give a copy of the extractor output and the source to the verifier. Review records and issues, correct supported errors, and identify omissions. | Verifier output, record changes, issue history, and run measurements. |
| Summarize before expert review | Preserve both outputs and summarize execution, flags, resolutions, and referrals. | Pre-review measures for E and E+V. |
| Assess with experts | Match records to the reference, check correctness and evidence, and assess additional records and issue handling. | Expert assessments, reference revisions, and post-review measures. |
| Curate and expand | Correct supported errors, exclude unresolved material, and apply the selected workflow to additional plans. | Curated dataset, review coverage, and processing history. |

The extractor output will be saved once and reused for both configurations. Later corrections will create new versions rather than overwrite the outputs being evaluated. Record IDs will remain stable through correction; added records will receive new IDs. Removed or merged records will remain traceable.

If text preparation fails, the source will be reprocessed where possible. A reading failure must not be recorded as evidence that information is absent. Changes to prepared text must be versioned and applied consistently to both configurations.

During expansion, experts will review referred issues and check an agreed sample of unflagged outputs. The dataset will retain which records were reviewed and how.

## 5. Proposed system

A Python application is proposed to coordinate document processing, model calls, tools, saved outputs, and analysis.

| Component | Role |
| --- | --- |
| Document preparation | Produce readable text while retaining PDF page boundaries. |
| Pipeline controller | Run stages in order, enforce limits, validate outputs, and save results and measurements. |
| Model adapter | Translate requests and responses between the controller and the selected model runtime. |
| MCP client and server | Connect the controller to document-reading and checking tools. |
| Extractor and verifier | Use source text and tools to produce or check structured records. |
| Expert assessment and analysis | Store expert judgments and calculate measures from saved outputs. |

An agent will operate in a bounded loop: receive instructions and source text, request tools, inspect their results, and submit a structured answer. The controller will execute permitted tool requests and return results to the model.

MCP provides the interface to tools. The application remains responsible for model calls, document context, stage order, and output storage. See the [MCP architecture documentation](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture).

A local MCP server connected through standard input/output, called **stdio**, is proposed for the first implementation. This allows the controller to start the server as a local process. See the [Python SDK transport documentation](https://py.sdk.modelcontextprotocol.io/client/transports/).

### Models and source context

The extractor and verifier will be selected on the available hardware during development. Selection will consider memory requirements, document capacity, tool use, structured-output reliability, and runtime.

The model runtime is not yet selected. Ollama is a candidate with a documented [tool-calling interface](https://docs.ollama.com/capabilities/tool-calling); compatibility must be checked with the actual models.

Record the model version, runtime version, generation settings, context limit, hardware, and weight precision. If quantization is used, record its format; quantization reduces the numerical precision of model weights to lower memory requirements.

Plans will be supplied directly, without a separate document-collection search system. Each agent will receive instructions, the data specification, and page-marked plan text when it fits within the model's context capacity.

Longer plans will require a documented page-batching procedure: processing groups of pages, tracking coverage, and combining repeated records. The procedure must retain information across page boundaries and must not silently truncate the document. The approach will be selected before the comparison.

### Initial MCP tools

| Tool | Function | Limit |
| --- | --- | --- |
| List pages | Return page count and information about readable pages. | Does not establish extraction completeness. |
| Read pages | Return text for a specified PDF page range. | Interpretation remains the model's task. |
| Check quotation | Locate a quotation on the claimed pages and return surrounding text. | A text match does not establish that the passage supports the claim. |
| Validate extraction | Check required fields, allowed values, IDs, links, and page bounds. | Valid structure does not establish factual accuracy. |

Within-plan text search may be added for navigation. Search results alone will not establish complete coverage.

Tools will access the registered source and candidate records, not expert reference files. The controller will save outputs. Source text will be treated as evidence, not as instructions for the agent.

## 6. JSON specification

The proposed implementation will use separate JSON files for source information, extracted content, review history, execution, and expert assessment. The examples below are documentation, not implemented schemas.

### 6.1 Common rules and file links

- Every field listed in a table is required. A nullable field remains present with `null` when unavailable. Nested-object fields described in prose are also required.
- Lists use `[]` when empty. Enumerated missing-information values take precedence over `null`.
- Content records describe distinct items; do not create empty placeholder records to populate a category.
- IDs, versions, dates supplied by collection, and workflow fields must have valid values.
- Dates use `YYYY-MM-DD`; timestamps use UTC in `YYYY-MM-DDTHH:MM:SSZ` form. Durations use seconds.
- `schema_version` is initially `1` for the proposed implementation. Change it when the field structure or coding rules change.
- A document version has one `plan_id`. A saved extraction version has one `snapshot_id`; a stage execution has one `run_id`.
- Goal, action, and other content IDs are unique within a snapshot and remain stable through corrections to that extraction. Independent expert and model extractions may reuse local IDs; correspondence must be established by expert matching, not ID equality.
- Record references outside an extraction include its `snapshot_id`. Links within an extraction refer to IDs in that same snapshot. Page lists contain unique page numbers within source bounds.
- The controller supplies file links and execution identifiers. Agents populate content and propose issues; they do not set their own runtime measurements or expert judgments.
- Reject unexpected fields and invalid enum values. Invalid output enters the recorded repair/failure procedure.

Proposed files for each plan are a source record, immutable extraction snapshots, review snapshots, stage-run files, configuration-result files, references, and assessments. Each review snapshot describes exactly one extraction snapshot. New stages create new files.

### 6.2 Source record

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `source_id` | String | Identifier for the PDF and prepared-text version. Reprocessing creates a new source record. |
| `plan_id` | String | Document-version identifier, such as `plan_0001`. |
| `study_set` | Enum | `development`, `comparison`, or `expansion`. |
| `source_url` | String | Official document or download-page URL. |
| `date_accessed` | Date | Date supplied by collection. |
| `pdf_path` | String | Project-relative path to the original PDF. |
| `document_sha256` | String | The document's 64-character hexadecimal checksum. |
| `preparation_version` | String | Version of the text preparation procedure. |
| `page_count` | Positive integer | Number of PDF pages. |
| `preparation_status` | Enum | `ready` or `failed`. Only ready sources enter extraction. |
| `pages` | List of page objects | One item per PDF page. |
| `problem` | String or null | Preparation problem, if any. |

Each page object contains `page_number` (positive integer), `text_path` (string or null), `readable` (Boolean), and `problem` (string or null). The page list must cover pages 1 through `page_count` exactly once. Prepared text retains page boundaries and substantive wording.

### 6.3 Extraction snapshot

This object preserves the proposal's content fields and adds links to the source, run, and separate review file.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format and coding-rule version. |
| `snapshot_id` | String | Unique identifier for this saved extraction. |
| `parent_snapshot_id` | String or null | Previous version, including the extractor version used by the verifier. |
| `source_id` | String | Source record used. |
| `run_id` | String or null | Stage run that produced the extraction; null for manual expert coding or correction. |
| `review_id` | String | Review snapshot created with this extraction. A configuration result can point to a later review of the same extraction. |
| `plan_id` | String | Document-version identifier. |
| `study_set` | Enum | `development`, `comparison`, or `expansion`. |
| `extraction_method` | Enum | `expert`, `extractor_only`, or `extractor_verifier`. Later expert correction does not change its original method. |
| `stage` | Enum | `expert_reference`, `extractor`, `verifier`, `expert_corrected`, or `curated`. |
| `plan_info` | Object | Metadata defined below. |
| `plan_goals` | List | Goal records. |
| `plan_actions` | List | Action records. |
| `plan_mon_eval` | List | Monitoring and evaluation records. |
| `plan_benefits` | List | Benefit and impact records. |
| `plan_costs` | List | Cost and resource records. |

**Plan information**

| Field | Type | Description |
| --- | --- | --- |
| `plan_title` | String or null | Full document title. |
| `jurisdiction_name` | String or null | Jurisdiction covered. |
| `country` | String or null | Country covered. |
| `plan_scale` | Enum or null | `city`, `region`, `state`, or `country`. |
| `plan_type` | Enum or null | `heat_specific_plan` or `broader_climate_plan`. |
| `publication_year` | Integer or null | Publication year of this document version. |
| `lead_agencies` | List of strings | Organizations that prepared or issued the plan. |
| `source_url` | String | Copied from the source record. |
| `date_accessed` | Date | Copied from the source record. |
| `language` | String | Document language; English under the inclusion criteria. |

Metadata may come from the document or verified collection record. Issuing agencies are not automatically responsible for every action.

**Evidence objects**

Every content record has an `evidence` list. Each evidence object contains:

| Field | Type | Description |
| --- | --- | --- |
| `quote` | String | An exact, continuous source passage. |
| `page_numbers` | Nonempty list of positive integers | PDF pages containing that passage. |

Separate passages have separate objects. A continuous passage crossing a page boundary may list several pages. Quotes preserve substantive wording, numbers, units, and qualifications. A record with no usable evidence is flagged for checking and cannot enter the accepted dataset without support.

**Goal records: `plan_goals`**

| Field | Type | Description |
| --- | --- | --- |
| `goal_id` | String | Local ID, such as `goal_0001`. |
| `goal` | String | Explicitly stated goal, retaining relevant population and geographic scope. |
| `targets` | List of target objects | Each has `target` (string) and `deadline` (string or null). |
| `evidence` | List of evidence objects | Support for the goal and targets. |

Each target stays paired with its own deadline. Preserve quantities, units, baselines, and the source's timing precision, such as `2030` or `within five years of adoption`. Qualitative commitments may be targets. Do not infer a goal solely from an action or benefit.

**Action records: `plan_actions`**

| Field | Type | Description |
| --- | --- | --- |
| `action_id` | String | Local ID, such as `action_0001`. |
| `action` | String | Explicit action, beginning with an action verb. Include implementers, populations, locations, quantities, and timing where stated and relevant. |
| `action_status` | Enum | `planned`, `in_progress`, `completed`, `discontinued`, or `not_specified`. |
| `related_goal_ids` | List of strings | Goals explicitly associated with the action. |
| `evidence` | List of evidence objects | Support for the action, status, and links. |

`planned` means proposed or committed without evidence implementation has begun; `in_progress` means underway or functioning; `completed` means finished; `discontinued` means stopped or withdrawn. Use `not_specified` when status cannot be assigned clearly.

Repeated mentions of an item are combined. Independently implementable actions normally receive separate records; components of one integrated measure may remain together.

**Monitoring, benefit, and cost records**

These three record types share the following fields:

| Field | Type | Description |
| --- | --- | --- |
| `scope` | Enum | `linked`, `plan_wide`, or `unspecified`. |
| `related_goal_ids` | List of strings | Explicitly associated goals. |
| `related_action_ids` | List of strings | Explicitly associated actions. |
| `evidence` | List of evidence objects | Support for the content, scope, and links. |

They also contain the ID and description fields below.

| List | ID field | Description field | Content |
| --- | --- | --- | --- |
| `plan_mon_eval` | `mon_eval_id` | `mon_eval` | What is tracked or evaluated, indicators, methods, frequency, responsible bodies, and reporting where stated. |
| `plan_benefits` | `benefit_id` | `benefit` | Expected or reported outcomes, preserving values, affected groups, comparisons, timing, and qualifications. |
| `plan_costs` | `cost_id` | `cost` | Financial costs or non-financial resource requirements, preserving amounts, currency/units, periods, and recurring or one-off character. |

ID and description fields are strings. Use IDs such as `mon_eval_0001`, `benefit_0001`, and `cost_0001`.

`linked` requires at least one supported goal or action link. `plan_wide` requires explicit application to the overall heat plan or programme. `unspecified` means the source does not establish the scope. Both link lists must be empty for `plan_wide` and `unspecified`. Unspecified scope alone does not create an issue.

Monitoring an activity does not establish reduced heat risk. Benefits distinguish expected, modelled, and observed outcomes; reported outcomes remain claims made by the plan. Costs distinguish estimates, allocations, expenditure, and stated needs. Shared budgets are recorded once and linked to the relevant actions; currencies and amounts are not converted or divided without source support.

### 6.4 Extraction example

This fictional example illustrates all five lists. It is a candidate extraction requiring review: the action's status is wrong and its description omits a stated quantity and deadline. The quotations are illustrative, not taken from a real plan.

```json
{
  "schema_version": 1,
  "snapshot_id": "snapshot_extract_0001",
  "parent_snapshot_id": null,
  "source_id": "source_0001",
  "run_id": "run_extract_0001",
  "review_id": "review_extract_0001",
  "plan_id": "plan_0001",
  "study_set": "development",
  "extraction_method": "extractor_only",
  "stage": "extractor",
  "plan_info": {
    "plan_title": "Example City Heat Action Plan",
    "jurisdiction_name": "Example City",
    "country": "Example Country",
    "plan_scale": "city",
    "plan_type": "heat_specific_plan",
    "publication_year": 2026,
    "lead_agencies": ["Example City Council"],
    "source_url": "https://example.org/heat-plan.pdf",
    "date_accessed": "2026-10-24",
    "language": "English"
  },
  "plan_goals": [{
    "goal_id": "goal_0001",
    "goal": "Reduce heat exposure around schools.",
    "targets": [{
      "target": "Plant 5,000 trees around schools",
      "deadline": "2030"
    }],
    "evidence": [{
      "quote": "Our goal is to reduce heat exposure around schools.",
      "page_numbers": [12]
    }, {
      "quote": "To meet this goal, the city will plant 5,000 trees around schools by 2030.",
      "page_numbers": [12]
    }]
  }],
  "plan_actions": [{
    "action_id": "action_0001",
    "action": "Plant trees around schools.",
    "action_status": "completed",
    "related_goal_ids": ["goal_0001"],
    "evidence": [{
      "quote": "To meet this goal, the city will plant 5,000 trees around schools by 2030.",
      "page_numbers": [12]
    }]
  }],
  "plan_mon_eval": [{
    "mon_eval_id": "mon_eval_0001",
    "mon_eval": "The parks department will count new school trees annually.",
    "scope": "linked",
    "related_goal_ids": [],
    "related_action_ids": ["action_0001"],
    "evidence": [{
      "quote": "The parks department will count the new school trees each year.",
      "page_numbers": [12]
    }]
  }],
  "plan_benefits": [{
    "benefit_id": "benefit_0001",
    "benefit": "The school trees are expected to provide more shade for pupils.",
    "scope": "linked",
    "related_goal_ids": [],
    "related_action_ids": ["action_0001"],
    "evidence": [{
      "quote": "The school trees are expected to provide more shade for pupils.",
      "page_numbers": [12]
    }]
  }],
  "plan_costs": [{
    "cost_id": "cost_0001",
    "cost": "A budget allocation of USD 2 million for school tree planting over 2027–2030.",
    "scope": "linked",
    "related_goal_ids": [],
    "related_action_ids": ["action_0001"],
    "evidence": [{
      "quote": "The school tree-planting programme has a budget of USD 2 million for 2027–2030.",
      "page_numbers": [12]
    }]
  }]
}
```

### 6.5 Review snapshot and issue history

Review information is stored separately so verification and expert corrections do not replace earlier states.

| Review field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `review_id` | String | Unique review snapshot ID. |
| `snapshot_id` | String | Extraction snapshot being reviewed. |
| `plan_id` | String | Document identifier. |
| `review_required` | Boolean | True if at least one issue remains open. |
| `status` | Enum | `not_reviewed`, `partially_reviewed`, or `reviewed`; describes expert review only. |
| `reviewed_record_ids` | List of strings | Output records assessed by an expert. |
| `reviewed_categories` | List of strings | Fully checked category names, including checks for omissions. |
| `issues` | List of issue objects | Open and resolved issues. |

Category names are the five list names in the extraction object. An expert may finish review while leaving an unresolved issue, so review coverage and issue resolution are separate.

| Issue field | Type | Description |
| --- | --- | --- |
| `issue_id` | String | Stable issue ID across stages. |
| `target_key` | String | Stable grouping key for the affected item, category, or source. |
| `related_id` | String | Affected record ID, or `plan_id` for a category, omitted item, or source problem. |
| `issue_category` | Enum | Primary type used for issue-type counts. |
| `issue` | String | Summary of the problem. |
| `origin_stage` | Enum | `extractor`, `verifier`, or `reprocessing`. |
| `origin_run_id` | String | Run in which the issue first appeared. |
| `status` | Enum | `pending_verification`, `pending_reprocessing`, `pending_expert_review`, or `resolved`. |
| `resolved_by` | Enum or null | `verifier`, `expert`, or `pipeline`; null while open. |
| `resolution` | String or null | Overall resolution explanation; null while open. |
| `concerns` | Nonempty list | Specific problems grouped within the issue. |
| `history` | Nonempty list | Ordered creation and change events. |

A concern contains `concern_id` (stable string), `field` (field path relative to the affected record, or a full plan path), `description` (string), `status` (`open` or `resolved`), and `resolution` (string or null). Concern counts are not issue counts.

An event contains `event_id`, `occurred_at`, `actor`, `run_id`, `from_status`, `to_status`, `change_type`, `note`, and `evidence`. IDs and notes are strings; `run_id` is null for manual expert actions; `from_status` is null on creation. Actors are `extractor`, `verifier`, `pipeline`, or `expert`. Status values follow the issue enum. Change types are `created`, `routed`, `corrected`, `confirmed_absent`, `reprocessed`, or `reopened`. Evidence uses the quotation-page structure and may be empty for routing events.

**Draft grouping rules:** one issue per existing record; one per empty category; one per source problem. A suspected omitted item receives a provisional target key, retained if a new record is added. Distinct omitted items receive distinct keys. The draft assigns one primary issue category so type percentages do not overlap. These extensions to the agreed record-level rule require review before comparison.

Issue categories retain the proposal's values:

| Value | Use |
| --- | --- |
| `no_records_found` | A category is empty after processing a readable source; absence has not yet been established. |
| `unclear_meaning` | Meaning, classification, or relationship is uncertain. |
| `conflicting_evidence` | Passages make incompatible claims that context does not resolve. |
| `source_issue` | The document or prepared text prevents reliable checking. |
| `extraction_process_issue` | Extraction or validation failed, or an incorrect or omitted extraction was identified. |

This review example corresponds to the fictional action above. Its two concerns count as one issue.

```json
{
  "schema_version": 1,
  "review_id": "review_extract_0001",
  "snapshot_id": "snapshot_extract_0001",
  "plan_id": "plan_0001",
  "review_required": true,
  "status": "not_reviewed",
  "reviewed_record_ids": [],
  "reviewed_categories": [],
  "issues": [{
    "issue_id": "issue_0001",
    "target_key": "record:action_0001",
    "related_id": "action_0001",
    "issue_category": "extraction_process_issue",
    "issue": "The action status and description require source checking.",
    "origin_stage": "extractor",
    "origin_run_id": "run_extract_0001",
    "status": "pending_verification",
    "resolved_by": null,
    "resolution": null,
    "concerns": [{
      "concern_id": "concern_0001",
      "field": "action_status",
      "description": "The source describes a commitment, but the record says completed.",
      "status": "open",
      "resolution": null
    }, {
      "concern_id": "concern_0002",
      "field": "action",
      "description": "The description omits the quantity and deadline.",
      "status": "open",
      "resolution": null
    }],
    "history": [{
      "event_id": "event_0001",
      "occurred_at": "2026-10-24T12:00:00Z",
      "actor": "extractor",
      "run_id": "run_extract_0001",
      "from_status": null,
      "to_status": "pending_verification",
      "change_type": "created",
      "note": "Flagged the action for verification.",
      "evidence": [{
        "quote": "To meet this goal, the city will plant 5,000 trees around schools by 2030.",
        "page_numbers": [12]
      }]
    }]
  }]
}
```

The extraction's `review_id` points to its initial review; a configuration result identifies the final pre-expert review used for that branch. Both reviews must name the same extraction snapshot. The common extractor snapshot is the comparison baseline. Its issues enter `pending_verification` for E+V; E receives a separate review snapshot routing content issues to `pending_expert_review`. The extracted content is identical. Retryable source/process issues enter `pending_reprocessing` in either branch. A partial correction keeps the issue open. `resolved` requires all concerns addressed or source-supported confirmation that no correction is needed. Verification never changes expert-review coverage.

### 6.6 Stage-run record

A run represents one extractor, verifier, or reprocessing stage. Its attempts and model calls are recorded even if the stage fails.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `run_id`, `plan_id`, `source_id` | Strings | Execution and source identifiers. |
| `stage` | Enum | `extractor`, `verifier`, or `reprocessing`. |
| `parent_run_id` | String or null | Extractor run for a verifier; retried stage for reprocessing. |
| `input_snapshot_id` | String or null | Input extraction; null for the first extraction. |
| `output_snapshot_id` | String or null | Output extraction; null if none was produced. |
| `status` | Enum | `running`, `succeeded`, or `failed`. |
| `started_at`, `ended_at` | Timestamp; end nullable | Stage boundaries. |
| `elapsed_seconds` | Nonnegative number or null | Measured stage duration; null until finished. |
| `model` | Object or null | Model and runtime settings; null for model-free reprocessing. |
| `versions` | Object | Software, prompt, tool, and preparation versions. |
| `execution_policy` | Object | Frozen limits: `max_attempts` and `max_tool_calls` as positive integers. |
| `attempts` | List of attempt objects | All attempts, including failed ones. |
| `error` | String or null | Final failure explanation. |

The model object contains `name`, `revision`, `runtime`, `runtime_version`, `quantization` (string or null), `context_limit` (positive integer), `generation_settings` (object), `runtime_options` (object), and `hardware` (string). Name, revision, runtime, and runtime version are strings. Generation settings contain `temperature` (nonnegative number), `top_p` (number greater than 0 and at most 1), `seed` (integer or null), and `max_output_tokens` (positive integer); runtime-specific settings are recorded under `runtime_options`. The versions object contains `code_commit`, `code_dirty` (Boolean), `prompt_version`, `tools_version`, and `preparation_version`; unavailable non-applicable versions are null.

Each attempt contains `attempt_id`, `started_at`, `ended_at`, `status` (`succeeded` or `failed`), `error` (string or null), `model_calls` (list), and `tool_trace_path` (string or null). Each model-call object contains `call_id`, `input_tokens`, `output_tokens`, and `response_path`. Token counts are nonnegative integers or null when unavailable; the response path is a string or null for a request that returned no response.

Run duration includes model loading, model calls, tools, validation, automatic repairs, and retry waits within that stage. Source preparation and human review are excluded from extraction/verification runtime and recorded separately when performed. Token totals sum every model call in every attempt; if any required count is unavailable, the corresponding total is null rather than treating the missing count as zero.

### 6.7 Configuration result

This record links the shared extractor run to E or E+V. It prevents extraction cost from being omitted or counted twice.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `result_id`, `plan_id`, `source_id` | Strings | Result and source identifiers. |
| `configuration` | Enum | `extractor_only` or `extractor_verifier`. |
| `extractor_run_id` | String | The same extractor run in both configurations. |
| `verifier_run_id` | String or null | Verifier run for E+V; null for E. |
| `reprocessing_run_ids` | List of strings | Additional stage runs charged to this result, with no repeated IDs. |
| `snapshot_id`, `review_id` | String or null | Output and review used for evaluation; null if unavailable. |
| `status` | Enum | `running`, `succeeded`, or `failed`. |
| `error` | String or null | Configuration failure explanation. |

Runtime and tokens use the distinct linked stage-run IDs. Work performed within a stage's attempts is not also charged as a separate stage. Shared source preparation is outside these configuration totals. E+V fails if its required verifier stage fails; it must not silently fall back to E and be reported as verified.

### 6.8 Expert reference and assessment

The expert reference uses the same extraction-content structure, with `extraction_method: expert` and `run_id: null`. A reference-set record contains `reference_set_id`, `plan_id`, `initial_snapshot_id`, `final_snapshot_id` (string or null until adjudication is complete), `expert_ids` (list of strings), and `revisions` (list of objects with `record_ids`, `reason`, and `evidence`). It also has `schema_version`.

The initial reference is saved before experts see model outputs. A shared final reference incorporates supported additions and corrections found during assessment. Both configurations use the same final reference.

| Assessment field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `assessment_id`, `result_id`, `plan_id` | Strings | Assessment and configuration-result identifiers. |
| `snapshot_id`, `review_id` | Strings | Preserved pre-correction output and review assessed. |
| `initial_reference_id`, `final_reference_id` | String; final nullable while draft | Reference snapshot IDs used. |
| `expert_id` | String | Assessor identifier. |
| `completed_at` | Timestamp or null | Null until assessment is complete. |
| `status` | Enum | `draft` or `complete`. |
| `initial_matches` | List | Initial-reference matches used to identify additions. |
| `record_scores` | List | One score per final-reference content record, including omitted records. |
| `additional_records` | List | Distinct additional items assessed against the initial reference. |
| `quotation_checks` | List | One assessment per quotation use in the output. |
| `issue_assessments` | List | One assessment per issue recorded before expert review. |
| `unflagged_problems` | List | Expert-discovered problem groups missing from the recorded concerns. |

Nested assessment objects are defined below. Their IDs refer to the snapshots named in the parent object.

| Object | Required fields |
| --- | --- |
| Initial match | `reference_record_id` (string), `output_record_ids` (list of strings; empty if omitted). |
| Record score | `reference_record_id`, `output_record_ids`, `score` (0, 0.5, or 1), and `reason` (string). Omitted items have no output IDs and score 0. |
| Additional record | `additional_id`, `output_record_ids`, `support_status` (`supported`, `unsupported`, or `undetermined`), `final_reference_record_ids` (list), `reason`, and `evidence`. |
| Quotation check | `record_id`, `evidence_index` (zero-based integer), `claim_fields` (nonempty list of field-path strings), `supports_claim` (Boolean or null), `page_checks` (list), and `reason`. Each page check contains `page_number` and `correct` (Boolean or null). |
| Issue assessment | `issue_id`, `genuine` (Boolean or null), `verifier_resolution_supported` (Boolean or null), and `reason`. |
| Unflagged problem | `finding_id`, `target_key`, `output_record_ids`, `reference_record_ids`, `concerns` (list of strings), and `evidence`. |

Unless specified otherwise, identifiers and reasons in this table are strings; ID fields named in the plural are lists of strings. Evidence uses the common quotation-page structure. Null judgments are pending, not false.

Expert matching allows a reference item to match several split output records, or one combined output record to cover several reference items. Each reference item receives credit once. Duplicate output records do not earn extra credit.

For counting additions, experts group split or duplicate outputs describing the same new item into one additional-record assessment. An output already matched to the initial reference is not an addition merely because its wording differs. A supported additional item must represent distinct source-backed information absent from that reference. If its details are imperfect, it is scored separately against the revised reference; support of the item does not imply full record correctness.

Quotation support is assessed for all substantive claim fields assigned to that passage in `claim_fields`. Mark support true only if the passage supports those claims without contradicting their qualifications. Page checks assess each quotation–page pair. Identical quotes reused in different records are separate uses. Missing evidence is recorded as an extraction/review problem; it is not inserted into the denominator of a measure of supplied quotations.

A genuine issue identifies at least one real error, uncertainty, source problem, or processing problem requiring attention. Expert-discovered concerns not described by any pre-review flag are grouped once per affected target under `unflagged_problems`. A record may have a valid flagged concern and a different missed concern, contributing once to each measure.

Only complete assessments enter final quality calculations. An `undetermined` additional record or pending quotation/issue judgment must be resolved or reported as unassessed, not assigned zero. A rate with required judgments still pending is null; any assessed subtotal is labeled with its coverage rather than presented as the complete rate. There must be one final-reference score for every reference record and one check for every supplied quotation and page reference. Failed runs without an output remain in operational results; quality is reported as not assessed, with the number of assessed and failed plans stated.

### 6.9 Calculated metric record

Analysis writes one object per metric and grouping. These are derived outputs, not agent-generated scores.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `metric_id` | String | Stable measure name from Section 8. |
| `phase` | Enum | `pre_expert` or `post_expert`. |
| `stage` | Enum | `extractor`, `verifier`, `configuration_total`, or `expert_assessment`; identifies the stage summarized. |
| `category` | Enum | `operational_performance`, `issue_handling`, `verifier_contribution`, `expert_review_workload`, `extraction_quality`, or `evidence_support`. |
| `plan_id` | String or null | Null only for an aggregate across plans. |
| `configuration` | Enum | `extractor_only` or `extractor_verifier`. |
| `content_category` | String or null | One of the five extraction-list names for category-level scores; otherwise null. |
| `issue_category` | String or null | Issue type for a type-specific count/rate; otherwise null. |
| `aggregation` | Enum | `per_plan`, `mean_across_plans`, or `pooled`. |
| `value` | Number or null | Calculated result; null if unavailable or not applicable. |
| `unit` | Enum | `seconds`, `tokens`, `count`, or `percent`. |
| `numerator`, `denominator` | Number or null | Raw values for a ratio; null for a simple count or total. |
| `contributing_plans` | Integer | Number of plans represented. |
| `status` | Enum | `complete`, `not_applicable`, or `incomplete`. |
| `reason` | String or null | Explanation for an unavailable result. |
| `input_ids` | List of strings | Result, run, review, or assessment IDs used. |

For percentages, `value = numerator / denominator × 100`. A mean across plans uses the sum of valid per-plan percentages as numerator and the number of those plans as denominator; it does not multiply by 100 again. Retain the per-plan records supplying that mean. A failed run produces a complete failure-count observation, but unavailable quality measures have incomplete status rather than being silently scored zero.

## 7. Issue handling

### Unit and history

Multiple problems within one extracted record will count as one issue. For example, an action with an incorrect status and deadline has one issue describing both problems. Further concerns about that record will be added to the same issue.

Each issue will identify:

- Its stable ID and affected record, plan, or answer category.
- The problem type and affected fields.
- The stage at which it was first detected.
- Its status and changes in status.
- The actor responsible for each change and the supporting explanation.

Partial fixes will be recorded while the issue remains open. A closed issue may be reopened, with its earlier resolution retained. Section 6.5 proposes grouping rules for source problems, empty categories, and omitted records.

### Categories and status

The proposal's issue categories will be retained initially: no records found, unclear meaning, conflicting evidence, source issue, and extraction-process issue. A bundled issue may concern several problem types. The draft uses one primary type per issue for non-overlapping type percentages, while preserving every concern.

Statuses will distinguish pending verification, pending reprocessing, pending expert review, and resolved. Resolutions will identify whether they came from the verifier, pipeline, or expert. Verification does not count as expert review.

The verifier may resolve an issue through a supported correction or by confirming that a category is not reported after checking the relevant readable source. Confirmation of absence is not necessarily an error correction.

Initial extractor issues and newly raised verifier issues will remain distinguishable. A verifier-reported resolution and the expert's judgment of that resolution will be stored separately.

## 8. Evaluation measures

The table defines the measures per plan and configuration. Proportions are multiplied by 100 for reporting as percentages. Every measure retains its numerator and denominator; zero denominators produce `null`, displayed as not applicable. Counts may be zero.

### 8.1 Before expert review

| Category | Metric | Calculation | Data used |
| --- | --- | --- | --- |
| Operational performance | Total runtime (`runtime_seconds`) | Sum `elapsed_seconds` over the distinct stage-run IDs linked to the configuration result. | Configuration result and stage runs. |
| Operational performance | Tokens used (`input_tokens`, `output_tokens`, `total_tokens`) | Sum input and output token counts across every model call and attempt in those runs. Report input, output, and total. | Stage-run attempts. |
| Operational performance | Failed runs (`failed_runs`) | Per plan: 1 if the configuration result failed, otherwise 0 once finished. Across plans: sum these indicators. Attempt failures remain separately recorded. | Configuration-result status. |
| Issue handling | Issues recorded (`issues_recorded`) | Count distinct `issue_id` values in the stage's review snapshot, including resolved issues. | Review snapshot. |
| Issue handling | Open issues (`open_issues`) | Count issues with `status != resolved`. | Review snapshot. |
| Issue handling | Issue count and proportion by type (`issues_by_type`, `issue_type_percent`) | Count issues of primary type k; percentage = that count ÷ all recorded issues × 100. Label any separate open-only summary explicitly. | `issue_category` in the same review snapshot. |
| Verifier contribution | Initial issues marked resolved (`initial_issues_resolved_percent`) | Initial extractor issues whose final pre-review status is resolved by the verifier ÷ all initial extractor issues × 100. | Baseline issue IDs, final verifier review, and history. |
| Verifier contribution | Initial issues referred to experts (`initial_issues_referred_percent`) | Initial extractor issues whose final status is `pending_expert_review` ÷ all initial extractor issues × 100. | Same baseline and final review. |
| Verifier contribution | Newly raised issues (`new_issues`) | Count issue IDs in the verifier review that were absent from the baseline extractor review. | Baseline and verifier reviews. |
| Expert review workload | Issues referred for expert review (`expert_referrals`) | Count final issues with `status = pending_expert_review`, including newly raised issues. | E or E+V pre-review snapshot. |
| Expert review workload | Referred issue count and proportion by type (`referrals_by_type`, `referral_type_percent`) | Count referred issues of type k; percentage = that count ÷ all referred issues × 100. | The referred-issue subset. |

The baseline is the shared extractor review before branch-specific routing. An issue partly corrected but still open is not resolved. Reprocessing closures are attributed to the pipeline, not the verifier. If an issue was closed and later reopened, its final pre-review state determines its classification. History retains the intermediate changes. Verifier-contribution measures apply only to E+V; report them as not applicable for E.

The resolved and referred percentages need not sum to 100%: issues may remain in reprocessing or another pending state. New verifier issues are excluded from the initial-issue denominator.

E includes extraction and any separately linked processing runs. E+V includes that same extraction plus verification and any separately linked processing runs. The shared extraction is included once per configuration total. Runtime excludes human review and source preparation; stage boundaries are defined in Section 6.6.

### 8.2 After expert review

| Category | Metric | Calculation | Data used |
| --- | --- | --- | --- |
| Extraction quality | Record accuracy with partial credit (`record_accuracy_partial`) | Sum final-reference record scores ÷ number of final-reference records × 100. | `record_scores`. |
| Extraction quality | Fully correct record rate (`fully_correct_percent`) | Number of final-reference records scored 1 ÷ all final-reference records × 100. | `record_scores`. |
| Extraction quality | Additional-record count (`additional_records`) | Count distinct additional-item assessments against the initial reference. | `additional_records` after semantic matching. |
| Extraction quality | Support rate among additional records (`additional_support_percent`) | Additional items judged supported ÷ all additional items × 100. | `support_status`; complete judgments required. |
| Evidence support | Quotation support rate (`quotation_support_percent`) | Quotation uses with `supports_claim = true` ÷ all quotation uses assessed × 100. | `quotation_checks`. |
| Evidence support | Page-reference correctness (`page_correct_percent`) | Page checks with `correct = true` ÷ all quotation–page checks assessed × 100. | `quotation_checks.page_checks`. |
| Issue handling | Correctly flagged issue rate (`genuine_issue_percent`) | Issues judged genuine ÷ all pre-review issues assessed × 100. | `issue_assessments`; includes open and resolved issues. |
| Issue handling | Unflagged problem count (`unflagged_problems`) | Count distinct affected target groups with at least one expert-confirmed problem absent from recorded concerns. | `unflagged_problems`. |
| Verifier contribution | Expert-supported verifier resolutions (`supported_verifier_resolutions`, `unsupported_verifier_resolutions`, `verifier_resolution_support_percent`) | Count supported and unsupported verifier closures. Proposed percentage: supported closures ÷ all assessed verifier closures × 100. | Issue history and `verifier_resolution_supported`. |

The final verifier-resolution percentage is a proposed operational definition of the agreed expert check and requires review. Its denominator contains issues whose final pre-review status is `resolved` with `resolved_by = verifier`, including initial and newly raised issues. Earlier closures that were reopened are excluded. A justified confirmation of absence is a supported resolution, but not necessarily an error correction. Evidence and record-quality changes provide the separate assessment of the verifier's effect on outputs.

Experts first compare outputs to the initial reference to identify additions. Supported additions and other corrections produce one shared final reference. Both E and E+V are then scored against that version; additional-record counts remain tied to the initial version.

Quotation and page rates concern supplied evidence. Their assessment rows must cover every supplied quotation use and page reference; unassessed judgments cannot be omitted silently to improve a rate. Unsupported additional records do not lower reference-based extraction scores, so their count and support rate are reported alongside those scores.

### 8.3 Scoring rubric and reporting

| Score | Definition |
| --- | --- |
| 1 | All required substantive information is correct, with no unsupported substantive additions. |
| 0.5 | Some substantive information is correct, but at least one required part is incorrect or missing. |
| 0 | No substantive information is correct, or the reference record was omitted entirely. |

Different wording is acceptable when meaning is equivalent. An action identified correctly but assigned the wrong implementation status receives 0.5. Correctly recording that information is unavailable does not reduce the score. Evidence correctness is measured separately from content correctness.

The extraction-quality denominator is the total number of content records across the five final-reference lists. Plan metadata, individual target pairs, evidence objects, and issue concerns are not separate records in this denominator.

For ten reference records with six fully correct, two partial, and two omitted, partial-credit accuracy is `(6 + 2 × 0.5) / 10 = 70%`; the fully correct rate is `6 / 10 = 60%`. Preserve these underlying counts rather than reporting the percentages alone.

Calculate scores per plan and content category using the same definitions. Keep the two configurations paired by plan. The proposed overall summary is the mean of valid per-plan percentages, with the number of contributing plans shown; pooled counts may be reported separately and labeled. A plan/category with a zero denominator is excluded from that mean and reported as not applicable. This aggregation rule requires confirmation before comparison.

Retain initial and final expert references, all matching decisions, evidence for additional items, and expert explanations for partial scores. The second-expert checking procedure and disagreement resolution remain to be established on the development set.

## 9. Development records and reproducibility

Development records will describe the problem encountered, change made, reason, observed result, and remaining questions. These records will support the study's account of useful tools, model limitations, and expert intervention.

Before comparison, fix and version the schemas, prompts, models/settings, tools, document-processing strategy, retry limits, and evaluation rules. Later changes must identify affected runs and preserve earlier outputs.

Checks will cover page numbering, required fields, IDs and links, issue transitions, preservation of earlier outputs, metric calculations, and failure handling. Factual accuracy and semantic evidence support will require expert assessment.

Source files, software/model versions, settings, and processing history will be retained so the workflow can be repeated and inspected. Exact model outputs may still vary.

## 10. Implementation and repository structure

| Location | Purpose |
| --- | --- |
| `src/` | Document preparation, controller, model adapter, MCP tools, and analysis. |
| `schemas/`, `prompts/`, `configs/` | Versioned data specifications, instructions, and settings. |
| `tests/` | Checks of processing, validation, issue history, and calculations. |
| `data/raw/`, `data/processed/` | Source PDFs and prepared page text. |
| `models/`, `runs/`, `artifacts/`, `logs/` | Local weights, processing outputs, assessments, and diagnostics. |
| `data/release/`, `reports/` | Selected dataset releases and study summaries. |

Code, configuration without secrets, and project documents will be tracked in Git. Local instructions, credentials, model weights, raw/prepared sources, and generated run artifacts are excluded. Research artifacts will require a backup plan and a defined release location.

Implementation will proceed through document preparation, extraction, verification and issue history, expert assessment, and analysis. Development on two plans will establish the workflow before the ten-plan comparison. Expansion will follow analysis and selection of a configuration.

## 11. Open implementation decisions

- Hardware, model pair, runtime, and software versions.
- Whole-document or page-batched processing and record merging.
- Review of the proposed JSON contract, issue grouping/type rules, and expert assessment format.
- Retry limits, runtime-specific token reporting, and assessment procedures for incomplete outputs.
- Expert matching examples, claim-to-quotation assignment, proposed aggregation, and second-expert procedures.
- Expansion review coverage, release format, document redistribution permissions, and artifact storage.
