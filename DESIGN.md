# Heat Adaptation LLM dataset

**Study design and technical implementation (draft)**

**Last updated:** 2026-10-30

This document describes the study workflow, system components, JSON records, and evaluation calculations. It is a design for implementation, not an implemented system. Model choices are provisional, and remaining decisions are listed in Section 11.

Read Sections 1 to 4 for the study and processing workflow, Section 5 for the system, Section 6 for field definitions, Section 7 for issue handling rules, and Section 8 for measures. Sections 9 to 11 cover reproducibility, file locations, and open decisions.

## 1. Purpose

This research study will develop and evaluate a workflow that pairs open weight large language models (LLMs) with heat adaptation experts to extract structured data linked to source passages from government plans.

The study has two main questions:

1. How can open weight LLM agents and experts build an extraction dataset using Model Context Protocol (MCP) tools, and what practical lessons emerge?
2. How does adding a verifier using a different open weight model change extraction quality, issue handling, expert review requirements, and computational resources?

The dataset will describe what plans state about heat adaptation. It may support future fine-tuning, but model fine-tuning is outside this study.

## 2. Study design

| Study set | Size | Purpose |
| --- | --- | --- |
| Development | 2 plans | Develop prompts, tools, coding rules, and review procedures with experts. |
| Comparison | 10 separate plans | Compare extraction with and without verification against a reference coded by experts. |
| Expansion | To be determined | Apply the selected workflow to additional plans and curate the dataset. The original target is 50 to 100 unique plans in total. |

The comparison will use two configurations:

- **Extractor (E):** An agent reads a plan, produces structured records with supporting passages, and flags issues.
- **Extractor + verifier (E+V):** A second agent, using a different model, reviews the same extraction against the source. It checks flagged issues, examines all extracted records, and looks for omissions.

Both configurations will start with the same saved extractor output. Local and hosted execution will be explored during development; they are not additional experimental configurations. Section 9 sets out what must be fixed before comparison.

Experts will prepare the initial reference without seeing model outputs. The comparison will assess model outputs before expert correction. Findings will describe the tested workflow and model pairing; the study will not separately establish the effects of MCP or open weight models relative to alternative technologies.

## 3. Plans and extraction content

Eligible documents are final government or public agency plans that:

- Are publicly available in English and were published or updated in 2010 or later, with recent versions prioritized.
- Focus on heat adaptation or contain a dedicated heat section with at least one action specifically addressing heat.
- Have a readable full document and stable PDF page numbers.

Each registered plan will have document metadata, such as its title and jurisdiction, and five content lists:

| List | Content |
| --- | --- |
| Goals | Stated heat adaptation goals, targets, and deadlines. |
| Actions | Proposed or reported actions and their implementation status. |
| Monitoring and evaluation | What is tracked or evaluated, how, and by whom. |
| Benefits and impacts | Expected or reported outcomes, including adverse impacts. |
| Costs and resources | Financial costs and other resource requirements. |

The researcher screens documents against these criteria before import. Only eligible documents are supplied to the CLI; the software does not ask for eligibility confirmation or record a screening expert ID. A later text preparation failure blocks processing but does not, by itself, mean the document is ineligible.

Section 6 defines the fields, missing value rules, and source evidence required for these lists. Section 7 defines when information requires review.

## 4. Processing workflow

| Stage | Main tasks | Saved outputs |
| --- | --- | --- |
| Collect and prepare | Register the document, extract text by page, and check readability. | Source metadata, original PDF, page marked text, and preparation status. |
| Extract | Read the plan, populate records, provide evidence, and flag issues. Check output structure and apply the agreed retry policy. | Extractor output, issue state, tool activity, and run measurements. |
| Verify | Give a copy of the extractor output and the source to the verifier. Review records and issues, correct supported errors, and identify omissions. | Verifier output, record changes, issue history, and run measurements. |
| Summarize before expert review | Preserve both outputs and summarize execution, flags, resolutions, and referrals. | Measures before expert review for E and E+V. |
| Assess with experts | Match records to the reference, check correctness and evidence, and assess additional records and issue handling. | Expert assessments, reference revisions, and measures after expert review. |
| Curate and expand | Correct supported errors, exclude unresolved material, and apply the selected workflow to additional plans. | Curated dataset, review coverage, and processing history. |

Source preparation must be checked before extraction. A reading failure must not be treated as evidence that information is absent. Both comparison branches must use the same prepared source. Section 6.1 defines how saved versions and IDs are preserved.

During expansion, experts will review referred issues and check an agreed sample of unflagged outputs. The dataset will retain which records were reviewed and how.

### 4.1 Register documents

Store accepted PDFs under `data/raw/` and register each document version in `data/registry/plans.json`. The registry lists the documents supplied after prescreening. It does not track completed processing. Its fields are defined in Section 6.10.

Registration consists of:

1. Accept the PDF and collection details through the CLI import command: title, official source URL, access date, and study set. Required details must be complete before registration is saved. Section 5 describes how the CLI accepts these details.
2. Calculate the PDF checksum, a fingerprint of its contents, and check for an existing entry before adding a duplicate. Assign the plan ID, save the PDF path, and record whether processing is enabled.
3. Save the registry entry, prepare its page text, and add the source record's path to the entry.

Collection details can be edited after registration without importing the PDF again. Record when each edit occurred and the previous and replacement values. The workflow has one researcher, so operator IDs are not required. Section 6.10 defines this history and how edits affect saved outputs.

A revised published document receives a new plan ID linked to its predecessor. Reprocessing the same PDF creates a new source ID under the existing plan ID. Copying or renaming a PDF does not create a new document version. A changed checksum must be investigated before processing; it must not silently replace a registered source.

### 4.2 Select, skip, and rerun work

A **batch** is one request to process one or more registered documents with selected configurations and settings. It can contain a single document or several documents; it is not a fixed number of model calls. An **execution profile** is a saved set of model, prompt, tool, software, and processing settings. Section 6.11 defines profiles and batch records.

For one new document with both configurations selected, the batch runs extraction once and saves that output as E. It then gives a copy to the verifier and saves the resulting output as E+V. This produces two configuration results from one extractor stage and one verifier stage, each of which may require several model calls. A batch of ten new documents follows this sequence for each document. If an extractor output already exists with matching settings, a later batch can add verification without extracting again.

Before starting a batch, the workflow code will:

1. Read the requested plan IDs or study set, configurations, and execution profiles from the CLI.
2. Check that each selected document is registered and enabled, and that its source files are available and unchanged. Prepare the text if preparation has not yet been attempted.
3. Check saved runs against the requested source and settings. For verification, also check that the input is the exact saved extraction selected for this batch.
4. Show what will run, what will be reused, and what needs attention, with the next action for each document.
5. After the researcher starts the batch, run the required stages and retain earlier outputs. Documents with unresolved problems remain blocked; other ready documents can proceed.

Successful processing means the stage finished and its output passed structural validation. It does not mean an expert has confirmed accuracy or that all issues were resolved.

The following rules apply to each selected document and stage. A matching run used the same prepared source and execution profile; verification must also have used the same input extraction. **Reuse** means keep the saved result without another model call. **Skip** means the stage will not start in this request. **Blocked** means a problem must be addressed before it can start.

| Situation | What the workflow does | What the researcher does next |
| --- | --- | --- |
| Document is not registered or is disabled | Skip it and show the reason. | Import the document, or enable its registry entry, then submit a new request. |
| Text has not yet been prepared | Prepare it and check the result before any extraction. | No action if preparation succeeds; otherwise follow the preparation failure guidance below. |
| Registered source files are missing, changed, or failed preparation | Block processing and identify the affected file or page. Do not interpret unreadable text as absent information. | Restore the original file, correct the preparation problem and request preparation again, or register a revised published PDF as a new document version. |
| No extraction exists for this source and profile | Schedule extraction. If E+V is requested, schedule verification after extraction succeeds. | Check the work preview and start the batch. |
| Matching extraction succeeded and its saved files are valid | Reuse the extraction. If matching verification is also complete, reuse that too; if verification has never run, schedule only verification. | No action unless a deliberate repeat is wanted. |
| Requested source, settings, or verifier input differ from earlier runs | Look for a run matching the new request. Reuse a valid match, or schedule new work if none exists. Keep earlier results. | Check that the selected source and profiles are intended, then start the batch. |
| A completed run's saved output or review is missing or invalid | Block reuse and report which saved file failed checking. | Restore the saved files from backup, or explicitly request a replacement run. Earlier records remain retained. |
| A stage failed after its allowed attempts | Show the error and leave that stage failed. If verification failed, keep the successful extractor output. | Address the reported cause, then request a retry of failed work. Retry verification alone when its extractor input is still valid. |
| A matching stage is still running | Skip a duplicate start and show its run ID and status. | Wait for completion and check status again. |
| A process stopped unexpectedly, or its state is uncertain | Block a new start until it is known that the old process has stopped. Preserve partial outputs and available measurements. | Check the original terminal or running process. Once stopped, use the CLI to mark the interrupted run failed and request a retry. Partial output is not a completed result. |
| A deliberate repeat is requested despite valid completed work | Create a new run and retain the earlier result. If both configurations are repeated, extract once and share that new output. | Use the explicit repeat option and confirm the preview. |
| Several completed repeat runs match the request | Pause selection and list their run IDs instead of silently choosing the latest file. | Select the run ID to use for this batch. |

Each new stage execution has a new run ID. Attempts within a run follow its retry limits. A later batch retry creates a new run and links the earlier failed run as its retry predecessor. The verifier's parent remains its input extractor run, so retry and input relationships must use separate fields.

A deliberate repeat is a new observation; reusing an output is not. Comparison batches must record which extractor run supplies both E and E+V.

### 4.3 Processing summary

Derive a status table from the registry, source records, and run results for the requested profiles. Show plan ID, title, study set, preparation state, extraction state, verification state, and next action. Label work as not run, running, failed, complete, or blocked as appropriate.

This table is a view of the records, not a second source of truth. A plan may be complete for one profile and not run for another. The first implementation will use JSON files and process one batch at a time through the CLI; a database or distributed job queue is not required.

## 5. Proposed system

The project will use reusable Python modules for the workflow, a small CLI for processing, and notebooks for inspection and research analysis. These will run on the development computer, first using Ollama locally and later exploring Hugging Face hosted APIs.

- **Python modules** are files containing reusable functions for registration, document preparation, model requests, tools, output storage, expert assessment, and metric calculations. The workflow code calls these functions in order and follows the saved execution settings.
- **CLI (command line interface)** means commands run in the terminal. It will support importing documents, editing collection details, preparing sources, starting batches, and displaying processing status. It will also support explicit retries, repeats, and marking interrupted runs failed after the old process has stopped. Details can be supplied as command arguments; interactive use will prompt for missing required information. It will not ask about eligibility or operator identity. Before starting model calls, it will show the planned work and request confirmation.
- **Notebooks** will load saved outputs to inspect records and issues, compare configurations, and produce research tables and figures. They will import the same Python modules for calculations rather than maintain a separate copy of the processing or scoring logic. Routine processing will run through the CLI so it does not depend on notebook cell order.

The researcher chooses plans, configurations, and saved execution profiles through the CLI. Profiles specify the extractor and verifier models; the workflow code uses those settings. Both the CLI and notebooks call Python functions rather than act as additional LLM agents.

| Component | Role |
| --- | --- |
| Document preparation | Produce readable text while retaining PDF page boundaries. |
| Workflow code | Select work from the registry, run stages in order, enforce limits, check output structure, and save results and measurements. |
| Model adapter | Convert model requests into the format expected by Ollama or the hosted API, and return responses in a common format. |
| MCP client and server | Connect the workflow code to document reading and checking tools. |
| Extractor and verifier | Use source text and tools to produce or check structured records. |
| Expert assessment and analysis | Store expert judgments and calculate measures from saved outputs. |

An agent is a model working through a limited sequence of requests: read instructions and source text, request tools, inspect results, and submit an answer. The workflow code executes tool requests and returns the results; the model does not run the tools directly.

MCP provides the interface to tools. The Python modules remain responsible for model calls, document context, stage order, and output storage. See the [MCP architecture documentation](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture).

The workflow code will start the MCP server as a local process and exchange messages through standard input/output, called **stdio**. See the [Python SDK transport documentation](https://py.sdk.modelcontextprotocol.io/client/transports/).

### Local models first

The first development runs will use Ollama on an Apple M5 Pro MacBook with 64 GB of unified memory. The Python modules, MCP server, documents, and outputs will remain on the same computer. The model adapter will call Ollama's local API.

The initial candidates are:

| Role | Model | Ollama tag | Reason for consideration |
| --- | --- | --- | --- |
| Extractor | Qwen3.5 27B | `qwen3.5:27b` | Instruction following and tool use capabilities relevant to reading plans and populating structured records. |
| Verifier | Gemma 4 31B | `gemma4:31b` | Reasoning and function calling capabilities from a different model family, relevant to checking records against source evidence. |

These are provisional choices, not models validated for heat adaptation extraction or verification. Their documented capabilities motivate testing; using different families does not guarantee independent errors. See the [Qwen model card](https://huggingface.co/Qwen/Qwen3.5-27B) and [Gemma model overview](https://ai.google.dev/gemma/docs/core).

On the development plans, test memory use, document capacity, tool calls, JSON structure, extraction quality, and runtime. Check whether the verifier detects omissions and corrects errors without adding new ones. Either model or its role may change. Load models in sequence to leave memory for document context, the operating system, and other applications.

Ollama supports [tool calling](https://docs.ollama.com/capabilities/tool-calling) and [schema constrained output](https://docs.ollama.com/capabilities/structured-outputs), which restricts responses to a specified JSON structure. Test both with the selected models. Quantization reduces the numerical precision of model weights to lower memory use; its format is recorded in the run settings.

### Later exploration of hosted APIs

After establishing the local workflow, explore [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/index). The workflow code and MCP tools stay local while the model adapter sends requests to the provider. These requests include the plan text and tool results needed by the hosted model.

The hosted pair may differ from the local candidates because of availability, capabilities, cost, or development results. Model weights on Hugging Face are not necessarily available through a hosted provider.

Test the selected model/provider combination for document limits, tool calling, schema constrained output, token reporting, and request failures. Select an explicit provider rather than relying on automatic routing. Hosted APIs do not require renting or managing a GPU server.

Both adapters will use the same extraction, review, and assessment formats. Section 6.6 specifies deployment information to record; unavailable hosted details remain unknown. Serving choices and later changes follow the comparison rules in Section 9.

### Source context

Plans will be supplied directly, without a separate document collection search system. Each agent will receive instructions, the data specification, and page marked plan text when it fits within the model's context capacity.

For longer plans, define page batching: process groups of pages, track which pages were covered, and combine repeated records. Preserve information across page boundaries and do not silently truncate a plan. Store these rules in the versioned context strategy.

### Initial MCP tools

| Tool | Function | Limit |
| --- | --- | --- |
| List pages | Return page count and information about readable pages. | Does not establish extraction completeness. |
| Read pages | Return text for a specified PDF page range. | Interpretation remains the model's task. |
| Check quotation | Locate a quotation on the claimed pages and return surrounding text. | A text match does not establish that the passage supports the claim. |
| Validate extraction | Check required fields, allowed values, IDs, links, and page bounds. | Valid structure does not establish factual accuracy. |

Text search within a plan may be added for navigation. Search results alone will not establish complete coverage.

Tools will access the registered source and candidate records, not expert reference files. The workflow code will save outputs. Source text will be treated as evidence, not as instructions for the agent.

## 6. JSON specification

Use separate JSON files for collection, sources, extracted content, review history, execution, and expert assessment. A **schema** defines the required fields, types, and allowed values. In the tables below, an **enum** means a fixed list of allowed values, and **null** means no value is available. A **snapshot** is a saved version of an extraction or review. The examples describe the proposed format; no data files or validation schemas have been implemented.

### 6.1 Common rules and file links

- Every field listed in a table is required. A nullable field remains present with `null` when unavailable. Nested object fields described in prose are also required.
- Lists use `[]` when empty. Enumerated missing information values take precedence over `null`.
- Content records describe distinct items; do not create empty placeholder records to populate a category.
- IDs, versions, dates supplied by collection, and workflow fields must have valid values.
- Dates use `YYYY-MM-DD`; timestamps use UTC in `YYYY-MM-DDTHH:MM:SSZ` form. Durations use seconds. File paths are relative to the project root.
- `schema_version` is initially `1` for the proposed implementation. Change it when the field structure or coding rules change.
- A document version has one `plan_id`. A saved extraction version has one `snapshot_id`; a stage execution has one `run_id`.
- Goal, action, and other content IDs are unique within a snapshot and remain stable through corrections. Added records receive new IDs; removed or merged records remain traceable in earlier snapshots. Independent expert and model extractions may reuse local IDs; expert matching establishes correspondence, not ID equality.
- Record references outside an extraction include its `snapshot_id`. Links within an extraction refer to IDs in that same snapshot. Page lists contain unique page numbers within source bounds.
- The workflow code supplies file links and execution identifiers. Agents populate content and propose issues; they do not set their own runtime measurements or expert judgments.
- Reject unexpected fields and invalid enum values. Invalid output enters the recorded repair/failure procedure.

Each review snapshot describes one extraction snapshot. Save later extractions, reviews, and expert corrections as new versions; do not overwrite outputs being evaluated. Run and batch records may be updated while active, then retained when finished. Section 10 gives the file layout.

### 6.2 Source record

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `source_id` | String | Identifier for the PDF and prepared text version. Reprocessing creates a new source record. |
| `plan_id` | String | Document version identifier, such as `plan_0001`. |
| `study_set` | Enum | `development`, `comparison`, or `expansion`. |
| `source_url` | String | Official document or download page URL. |
| `date_accessed` | Date | Date supplied by collection. |
| `pdf_path` | String | Project relative path to the original PDF. |
| `document_sha256` | String | The PDF's 64 character hexadecimal SHA-256 checksum, copied from registration. |
| `prepared_text_sha256` | String or null | Fingerprint of page numbers and prepared text in PDF order; null if no complete text was produced. |
| `preparation_version` | String | Version of the text preparation procedure. |
| `page_count` | Positive integer | Number of PDF pages. |
| `preparation_status` | Enum | `ready` or `failed`. Only ready sources enter extraction. |
| `pages` | List of page objects | One item per PDF page. |
| `problem` | String or null | Preparation problem, if any. |

Each page object contains `page_number` (positive integer), `text_path` (string or null), `readable` (Boolean), and `problem` (string or null). Cover pages 1 through `page_count` exactly once. Calculate the prepared text checksum from the ordered page numbers and text, using the serialization rule in Section 6.11. Preserve original page text and document any normalization used for matching quotations.

### 6.3 Extraction snapshot

This object preserves the proposal's content fields and adds links to the source, run, and separate review file.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format and coding rule version. |
| `snapshot_id` | String | Unique identifier for this saved extraction. |
| `parent_snapshot_id` | String or null | Previous version, including the extractor version used by the verifier. |
| `source_id` | String | Source record used. |
| `run_id` | String or null | Stage run that produced the extraction; null for manual expert coding or correction. |
| `review_id` | String | Review snapshot created with this extraction. A configuration result can point to a later review of the same extraction. |
| `plan_id` | String | Document version identifier. |
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
| `page_numbers` | Nonempty list of positive integers | PDF pages containing that passage. Count the first PDF page as 1, regardless of printed labels. |

Use separate objects for separate passages. A continuous passage may cross pages. Preserve substantive wording, numbers, units, and qualifications. Record links require source support. Flag records without usable evidence; they cannot enter the accepted dataset without support.

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
| `plan_costs` | `cost_id` | `cost` | Financial costs or nonfinancial resource requirements, preserving amounts, currency/units, periods, and recurring or one-off character. |

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
| `issue_category` | Enum | Primary type used for issue type counts. |
| `issue` | String | Summary of the problem. |
| `origin_stage` | Enum | `extractor`, `verifier`, or `reprocessing`. |
| `origin_run_id` | String | Run in which the issue first appeared. |
| `status` | Enum | `pending_verification`, `pending_reprocessing`, `pending_expert_review`, or `resolved`. |
| `resolved_by` | Enum or null | `verifier`, `expert`, or `pipeline`; null while open. |
| `resolution` | String or null | Overall resolution explanation; null while open. |
| `concerns` | Nonempty list | Specific problems grouped within the issue. |
| `history` | Nonempty list | Ordered creation and change events. |

A concern contains `concern_id` (stable string), `field` (field path relative to the affected record, or a full plan path), `description` (string), `status` (`open` or `resolved`), and `resolution` (string or null). Concern counts are not issue counts.

An event contains `event_id`, `occurred_at`, `actor`, `run_id`, `from_status`, `to_status`, `change_type`, `note`, and `evidence`. IDs and notes are strings; `run_id` is null for manual expert actions; `from_status` is null on creation. Actors are `extractor`, `verifier`, `pipeline`, or `expert`. Status values follow the issue enum. Change types are `created`, `routed`, `corrected`, `confirmed_absent`, `reprocessed`, or `reopened`. Evidence uses the quotation page structure and may be empty for routing events.

Section 7 defines grouping, routing, and resolution rules. The fields here retain each concern and status change so those rules can be applied without losing history.

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

The extraction's `review_id` identifies its initial review. The configuration result identifies the final review snapshot saved before expert assessment for that branch, which may be a later review of the same extraction. Both review records must point to that extraction snapshot.

### 6.6 Stage run record

A run represents one extractor, verifier, or reprocessing stage. Its attempts and model calls are recorded even if the stage fails.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `run_id`, `plan_id`, `source_id` | Strings | Execution and source identifiers. |
| `batch_id` | String | Batch that first scheduled this run. Reuse does not change it. |
| `profile_id`, `profile_sha256` | Strings | Execution profile and its settings fingerprint. |
| `run_key` | String | Fingerprint used to find equivalent completed work; defined in Section 6.11. |
| `retry_of_run_id` | String or null | Earlier failed run retried by a new execution; null otherwise. |
| `stage` | Enum | `extractor`, `verifier`, or `reprocessing`. |
| `parent_run_id` | String or null | Input extractor run for a verifier, or the stage requiring reprocessing. Separate from retry history. |
| `input_snapshot_id` | String or null | Input extraction; null for the first extraction. |
| `output_snapshot_id` | String or null | Output extraction; null if none was produced. |
| `status` | Enum | `running`, `succeeded`, or `failed`. |
| `started_at`, `ended_at` | Timestamp; end nullable | Stage boundaries. |
| `elapsed_seconds` | Nonnegative number or null | Measured stage duration; null until finished. |
| `model` | Object or null | Model and runtime settings; null for model free reprocessing. |
| `versions` | Object | Software, prompt, tool, and preparation versions. |
| `execution_policy` | Object | Frozen limits: `max_attempts` and `max_tool_calls` as positive integers. |
| `attempts` | List of attempt objects | All attempts, including failed ones. |
| `error` | String or null | Final failure explanation. |

The model object contains the following fields. Use null for deployment details that are not known.

| Model field | Type | Description |
| --- | --- | --- |
| `name` | String | Exact model identifier requested. |
| `revision` | String or null | Exact weight revision or digest (model file fingerprint). Required for local reuse; null if a hosted provider does not disclose it. |
| `execution_mode` | Enum | `local` or `hosted_api`. |
| `api_service` | String or null | API service, such as `hugging_face`; null for local Ollama. |
| `provider` | String or null | Selected hosting backend; null for local execution. |
| `endpoint` | String | API base URL, without credentials or secret query parameters. |
| `runtime` | String or null | `ollama` locally; hosted serving runtime if disclosed. |
| `runtime_version` | String or null | Serving software version, when available. |
| `quantization` | String or null | Weight precision/quantization format, when available. |
| `context_limit` | Positive integer or null | Configured or provider documented context capacity. |
| `generation_settings` | Object | Requested and supported generation settings. |
| `runtime_options` | Object | Other recorded serving settings; empty if unavailable. |
| `hardware` | String or null | Local chip and memory, or disclosed hosted hardware. |

Generation settings are `temperature` (nonnegative number or null), `top_p` (number greater than 0 and at most 1, or null), `seed` (integer or null), and `max_output_tokens` (positive integer). Temperature and top-p control sampling; a seed initializes random sampling where supported. Use null for settings that cannot be controlled. Do not assume a provider applied an unsupported parameter.

The versions object contains `code_commit` (Git commit identifier), `code_dirty` (Boolean indicating uncommitted changes), `prompt_version`, `tools_version`, `preparation_version`, and `model_client_version` (API client software/version). Values that do not apply are null.

Each attempt contains `attempt_id`, `started_at`, `ended_at`, `status` (`succeeded` or `failed`), `error` (string or null), `model_calls` (list), and `tool_trace_path` (string or null). The tool trace records requested tools, arguments, returned results, and errors. Each model call contains `call_id`, `input_tokens`, `output_tokens`, and `response_path`. Token counts are nonnegative integers or null if unavailable; the response path is null if no response was returned.

Run duration includes model loading initiated within the stage, model calls, tools, validation, repairs, and retry waits. Hosted calls also include network and provider waiting time: this is elapsed workflow time, not GPU computation time. Record `model_loaded_at_start` (Boolean or null) under the run's `runtime_options`. Undisclosed hosted startup/compute time remains unknown. Exclude source preparation and human review from these stage totals.

Token totals include every call in every attempt. If a required token count or stage duration is unavailable, its total is null rather than treating the missing value as zero. Interrupted runs retain available traces and usage; do not infer actual processing time from the time of later recovery.

### 6.7 Configuration result

This record links the shared extractor run to E or E+V. It prevents extraction cost from being omitted or counted twice.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `result_id`, `plan_id`, `source_id` | Strings | Result and source identifiers. |
| `batch_id` | String | Batch that first created this result. Later batches may reference it without changing it. |
| `configuration` | Enum | `extractor_only` or `extractor_verifier`. |
| `extractor_run_id` | String | The same extractor run in both configurations. |
| `verifier_run_id` | String or null | Verifier run for E+V; null for E. |
| `reprocessing_run_ids` | List of strings | Additional stage runs charged to this result, with no repeated IDs. |
| `snapshot_id`, `review_id` | String or null | Output and review used for evaluation; null if unavailable. |
| `status` | Enum | `running`, `succeeded`, or `failed`. |
| `error` | String or null | Configuration failure explanation. |

Use distinct linked run IDs for totals: E includes extraction and separately linked processing; E+V includes that same extraction plus verification and separately linked processing. Do not count work inside attempts again as separate runs. Source preparation is excluded. E+V fails if verification fails; a successful E result remains available but is not a verified result.

### 6.8 Expert reference and assessment

The expert reference uses the same extraction content structure, with `extraction_method: expert` and `run_id: null`. A reference set record contains `reference_set_id`, `plan_id`, `initial_snapshot_id`, `final_snapshot_id` (string or null until adjudication is complete), and `revisions` (list of objects with `record_ids`, `reason`, and `evidence`). It also has `schema_version`. The current workflow has one expert, so references and assessments do not require expert IDs. Issue history still distinguishes expert actions from model and software actions through its `actor` field.

Save the initial reference before experts see model outputs. Experts first match each output to this reference to identify additions. Confirm supported additions and other corrections, save a shared final reference, and score both configurations against it. Additional record measures continue to use the initial reference.

| Assessment field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `assessment_id`, `result_id`, `plan_id` | Strings | Assessment and configuration result identifiers. |
| `snapshot_id`, `review_id` | Strings | Preserved pre correction output and review assessed. |
| `initial_reference_id`, `final_reference_id` | String; final nullable while draft | Reference snapshot IDs used. |
| `completed_at` | Timestamp or null | Null until assessment is complete. |
| `status` | Enum | `draft` or `complete`. |
| `initial_matches` | List | Initial reference matches used to identify additions. |
| `record_scores` | List | One score per final reference content record, including omitted records. |
| `additional_records` | List | Distinct additional items assessed against the initial reference. |
| `quotation_checks` | List | One assessment per quotation use in the output. |
| `issue_assessments` | List | One assessment per issue recorded before expert review. |
| `unflagged_problems` | List | Expert discovered problem groups missing from the recorded concerns. |

Nested assessment objects are defined below. Their IDs refer to the snapshots named in the parent object.

| Object | Required fields |
| --- | --- |
| Initial match | `reference_record_id` (string), `output_record_ids` (list of strings; empty if omitted). |
| Record score | `reference_record_id`, `output_record_ids`, `score` (0, 0.5, or 1), and `reason` (string). Omitted items have no output IDs and score 0. |
| Additional record | `additional_id`, `output_record_ids`, `support_status` (`supported`, `unsupported`, or `undetermined`), `final_reference_record_ids` (list), `reason`, and `evidence`. |
| Quotation check | `record_id`, `evidence_index` (zero based integer), `claim_fields` (nonempty list of field path strings), `supports_claim` (Boolean or null), `page_checks` (list), and `reason`. Each page check contains `page_number` and `correct` (Boolean or null). |
| Issue assessment | `issue_id`, `genuine` (Boolean or null), `verifier_resolution_supported` (Boolean or null), and `reason`. |
| Unflagged problem | `finding_id`, `target_key`, `output_record_ids`, `reference_record_ids`, `concerns` (list of strings), and `evidence`. |

Unless specified otherwise, identifiers and reasons in this table are strings; ID fields named in the plural are lists of strings. Evidence uses the common quotation page structure. Null judgments are pending, not false.

Expert matching allows a reference item to match several split output records, or one combined output record to cover several reference items. Each reference item receives credit once. Duplicate output records do not earn extra credit.

For counting additions, experts group split or duplicate outputs describing the same new item into one additional record assessment. An output already matched to the initial reference is not an addition merely because its wording differs. A supported additional item must represent distinct source backed information absent from that reference. If its details are imperfect, it is scored separately against the revised reference; support of the item does not imply full record correctness.

Quotation support is assessed for all substantive claim fields assigned to that passage in `claim_fields`. Mark support true only if the passage supports those claims without contradicting their qualifications. Page checks assess each pair of a quotation and a cited page. Identical quotes reused in different records are separate uses. Missing evidence is recorded as an extraction/review problem; it is not inserted into the denominator of a measure of supplied quotations.

A genuine issue identifies at least one real error, uncertainty, source problem, or processing problem requiring attention. Concerns discovered by an expert but absent from all flags saved before expert review are grouped once per affected target under `unflagged_problems`. A record may have a valid flagged concern and a different missed concern, contributing once to each measure.

Complete assessment requires one score per final reference record and checks for every supplied quotation, page reference, and issue. Resolve pending judgments or report them as unassessed. Rates with required judgments pending are null; label any partial subtotal with its review coverage. Never assign pending judgments zero. Failed runs without output remain in operational results, with quality not assessed and the numbers of assessed and failed plans reported.

### 6.9 Calculated metric record

Analysis writes one object per metric and grouping. These are derived outputs, not agent generated scores.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `metric_id` | String | Stable measure name from Section 8. |
| `phase` | Enum | `pre_expert` or `post_expert`. |
| `stage` | Enum | `extractor`, `verifier`, `configuration_total`, or `expert_assessment`; identifies the stage summarized. |
| `category` | Enum | `operational_performance`, `issue_handling`, `verifier_contribution`, `expert_review_workload`, `extraction_quality`, or `evidence_support`. |
| `plan_id` | String or null | Null only for an aggregate across plans. |
| `configuration` | Enum | `extractor_only` or `extractor_verifier`. |
| `content_category` | String or null | One of the five extraction list names for category level scores; otherwise null. |
| `issue_category` | String or null | Issue type for a type specific count/rate; otherwise null. |
| `aggregation` | Enum | `per_plan`, `mean_across_plans`, or `pooled`. |
| `value` | Number or null | Calculated result; null if unavailable or not applicable. |
| `unit` | Enum | `seconds`, `tokens`, `count`, or `percent`. |
| `numerator`, `denominator` | Number or null | Raw values for a ratio; null for a simple count or total. |
| `contributing_plans` | Integer | Number of plans represented. |
| `status` | Enum | `complete`, `not_applicable`, or `incomplete`. |
| `reason` | String or null | Explanation for an unavailable result. |
| `input_ids` | List of strings | Result, run, review, or assessment IDs used. |

For percentages, `value = numerator / denominator × 100`. A mean across plans uses the sum of valid per plan percentages as numerator and the number of those plans as denominator; it does not multiply by 100 again. Retain the per plan records supplying that mean. A failed run produces a complete failure count observation, but unavailable quality measures have incomplete status rather than being silently scored zero.

### 6.10 Document registry

`data/registry/plans.json` contains `schema_version` (integer) and `plans` (list of entries). Every entry contains the fields below.

| Field | Type | Description |
| --- | --- | --- |
| `plan_id` | String | Unique document version ID. |
| `plan_title` | String | Title recorded during collection. |
| `study_set` | Enum | `development`, `comparison`, or `expansion`. |
| `pdf_path` | String | Project relative original PDF path. |
| `document_sha256` | String | PDF checksum recorded at registration. |
| `source_url` | String | Official source URL. |
| `date_accessed` | Date | Collection date. |
| `enabled` | Boolean | Whether the accepted plan may be selected for processing. |
| `supersedes_plan_id` | String or null | Previous published version, if applicable. |
| `source_record_paths` | List of strings | Paths to saved preparation records, including failed and earlier versions. |
| `metadata_history` | List of edit events | Changes to collection details after registration; empty until an edit is made. |

Each edit event contains `edited_at` (timestamp), `changes` (nonempty list), and `reason` (string or null). Each change contains `field` (string), `previous_value`, and `new_value`. Values use the edited field's type: string, Boolean, or null. Editable collection fields are `plan_title`, `source_url`, `date_accessed`, and `study_set`; changes to `enabled` are also recorded. Dates use date strings. All values must meet their field definitions. Changing the PDF follows the document version rules in Section 4.1.

Source records and extraction snapshots preserve the metadata used at execution time; registry edits do not rewrite them. Before future processing, create a new source record with corrected collection details rather than modifying an earlier source record. Existing outputs retain their original metadata unless an explicit correction creates a new snapshot. Development plans cannot later enter the comparison set. If the researcher later discovers that a document should be excluded, disable it and record the reason in its edit history rather than deleting prior study records.

The following fictional entry illustrates registration. The checksum is a placeholder; real registration computes it from the PDF. The referenced files have not been created.

```json
{
  "schema_version": 1,
  "plans": [{
    "plan_id": "plan_0001",
    "plan_title": "Example City Heat Action Plan",
    "study_set": "development",
    "pdf_path": "data/raw/plan_0001.pdf",
    "document_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
    "source_url": "https://example.org/heat-plan.pdf",
    "date_accessed": "2026-10-25",
    "enabled": true,
    "supersedes_plan_id": null,
    "source_record_paths": ["data/processed/plan_0001/source_0001.json"],
    "metadata_history": []
  }]
}
```

There is no `processed` Boolean in the registry. Completion depends on the requested source, settings, and stage, as described in Section 4.2.

### 6.11 Execution profiles and batch records

Store profiles under `configs/execution/`. A profile describes a single stage. Changing its settings creates a new version rather than altering a profile already used in a run.

| Profile field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Profile format version. |
| `profile_id` | String | Human readable versioned identifier. |
| `stage` | Enum | `extractor`, `verifier`, or `reprocessing`. |
| `extraction_schema_version` | Integer | Extraction format and coding rule version. |
| `preparation_version` | String | Required source preparation procedure. |
| `context_strategy_version` | String | Whole document or page batching rules, including merging. |
| `prompt_sha256` | String | Fingerprint of the complete prompt/template files. |
| `tools_sha256` | String | Fingerprint of tool definitions and implementation. |
| `code_sha256` | String | Fingerprint of the processing code, including uncommitted changes if used. |
| `model` | Object or null | Resolved model settings from Section 6.6; null for model free reprocessing. |
| `software_versions` | Object | Names and versions of the runtime, client, and relevant processing libraries. |
| `execution_policy` | Object | Retry and tool call limits from Section 6.6. |
| `timing_policy_version` | String | Rules for loading models and measuring stages. |
| `profile_sha256` | String | Fingerprint of all other profile fields. |

Calculate fingerprints with SHA-256, using sorted JSON object keys and consistent UTF-8 serialization for structured inputs. Profiles contain no credentials. Resolve local model tags to their actual digest before calculating the profile fingerprint. Per run observations, such as whether the model happened to be loaded already, belong in the run record rather than the profile.

A stage's `run_key` is the fingerprint of its stage, plan ID, source ID, prepared text checksum, profile fingerprint, and input snapshot ID. The input snapshot is null for initial extraction. Verifier keys therefore change whenever their exact extractor input changes. A matching key identifies reusable work; run IDs still distinguish deliberate repeats.

Reuse only results whose referenced files exist and pass validation, whose source checksums match, and whose recorded profile matches the request. A matching key does not prove an undisclosed hosted deployment is unchanged. When its revision cannot be identified, reuse hosted results only within the same declared comparison batch; start a new batch/profile for a new assessment period.

Store each batch request, as defined in Section 4.2, under `runs/batches/<batch_id>.json`. Its ID identifies the request, not a document or a model call.

| Batch field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Batch format version. |
| `batch_id` | String | Unique batch identifier. |
| `created_at` | Timestamp | Time the request was recorded. |
| `study_set` | Enum or null | Requested study set; null for an explicit selection across sets during development. Formal comparison batches use `comparison`. |
| `requested_plan_ids` | List of strings | Fixed list resolved from the request, rather than a changing folder scan. |
| `configurations` | Nonempty list | `extractor_only`, `extractor_verifier`, or both. |
| `extractor_profile_id` | String | Selected extractor profile. |
| `verifier_profile_id` | String or null | Required when E+V is requested. |
| `retry_failed`, `force_rerun` | Booleans | Explicit requests to retry failures or repeat successful work. |
| `entries` | List | Decisions and result links for each requested plan/configuration. |

Each entry contains `plan_id`, `configuration`, `source_id` (string or null), `decision` (`run`, `reuse`, `skip`, or `blocked`), `reason` (string or null), and `result_id` (string or null until a result is linked). IDs and configuration values use the definitions above. Entries do not duplicate run statuses; the processing summary reads the linked source and result records.

The initial batch file records selection decisions before model calls. Link result IDs as work is scheduled and retain that file afterward. Reused results keep their original measurements and are not presented as newly measured runtime. Each result must identify one fixed source and the selected stage runs.

## 7. Issue handling

### Unit and history

Count one issue per affected extraction record, even if it has several problems. An action with a wrong status and deadline has one issue containing two concerns. Add further concerns about that record to the same issue.

The draft extends grouping as follows: one issue per empty category and one per source problem. A suspected omitted item receives a provisional target key that stays unchanged if a record is added. Distinct omitted items have distinct keys. These extensions require review before comparison.

A partial correction leaves the issue open. Reopen a closed issue if a new concern is identified, retaining its earlier resolution. Section 6.5 defines the fields and ordered history events that preserve this information.

### Categories and status

Use one primary issue category for nonoverlapping type percentages while retaining every concern. Category definitions and allowed status values are in Section 6.5.

Route the common extractor issues according to the configuration:

- In E+V, content issues enter `pending_verification`.
- In E, content issues enter `pending_expert_review`.
- Retryable source or processing problems enter `pending_reprocessing` in either branch.

Resolve an issue only when all concerns are addressed or source checking establishes that no correction is needed. Routine missing details and unspecified scope alone do not create issues. An entirely empty category must be checked before absence is confirmed.

The verifier may correct a record or confirm that a category is not reported after checking the relevant readable source. A justified confirmation of absence is a supported resolution, not necessarily an error correction. Verification does not change expert review coverage.

Keep initial extractor issues separate from issues newly raised during verification. Save the verifier's resolution explanation and the expert's later judgment separately.

## 8. Evaluation measures

Calculate the following measures per plan and configuration. The calculated record and rules for percentages, missing judgments, and zero denominators are in Sections 6.8 to 6.9. Counts may be zero.

### 8.1 Before expert review

| Category | Metric | Calculation | Data used |
| --- | --- | --- | --- |
| Operational performance | Total runtime (`runtime_seconds`) | Sum `elapsed_seconds` over the distinct stage run IDs linked to the configuration result. | Configuration result and stage runs. |
| Operational performance | Tokens used (`input_tokens`, `output_tokens`, `total_tokens`) | Sum input and output token counts across every model call and attempt in those runs. Report input, output, and total. | Stage run attempts. |
| Operational performance | Failed runs (`failed_runs`) | Per plan: 1 if the configuration result failed, otherwise 0 once finished. Across plans: sum these indicators. Attempt failures remain separately recorded. | Configuration result status. |
| Issue handling | Issues recorded (`issues_recorded`) | Count distinct `issue_id` values in the stage's review snapshot, including resolved issues. | Review snapshot. |
| Issue handling | Open issues (`open_issues`) | Count issues with `status != resolved`. | Review snapshot. |
| Issue handling | Issue count and proportion by type (`issues_by_type`, `issue_type_percent`) | Count issues of primary type k; percentage = that count ÷ all recorded issues × 100. Label any separate summary restricted to open issues explicitly. | `issue_category` in the same review snapshot. |
| Verifier contribution | Initial issues marked resolved (`initial_issues_resolved_percent`) | Initial extractor issues marked resolved by the verifier at the final stage before expert review ÷ all initial extractor issues × 100. | Baseline issue IDs, final verifier review, and history. |
| Verifier contribution | Initial issues referred to experts (`initial_issues_referred_percent`) | Initial extractor issues whose final status is `pending_expert_review` ÷ all initial extractor issues × 100. | Same baseline and final review. |
| Verifier contribution | Newly raised issues (`new_issues`) | Count issue IDs in the verifier review that were absent from the baseline extractor review. | Baseline and verifier reviews. |
| Expert review workload | Issues referred for expert review (`expert_referrals`) | Count final issues with `status = pending_expert_review`, including newly raised issues. | E or E+V snapshot saved before expert review. |
| Expert review workload | Referred issue count and proportion by type (`referrals_by_type`, `referral_type_percent`) | Count referred issues of type k; percentage = that count ÷ all referred issues × 100. | The referred issue subset. |

The baseline is the shared extractor review before branch specific routing. Count final states before expert review, rather than intermediate closures: a reopened issue is still open, and pipeline resolutions are not verifier resolutions. Verifier contribution measures apply only to E+V; report them as not applicable for E.

The resolved and referred percentages need not sum to 100%: issues may remain in reprocessing or another pending state. New verifier issues are excluded from the initial issue denominator.

Sections 6.6 to 6.7 define timing boundaries and how linked runs contribute to configuration totals.

### 8.2 After expert review

| Category | Metric | Calculation | Data used |
| --- | --- | --- | --- |
| Extraction quality | Record accuracy with partial credit (`record_accuracy_partial`) | Sum final reference record scores ÷ number of final reference records × 100. | `record_scores`. |
| Extraction quality | Fully correct record rate (`fully_correct_percent`) | Number of final reference records scored 1 ÷ all final reference records × 100. | `record_scores`. |
| Extraction quality | Additional record count (`additional_records`) | Count distinct additional item assessments against the initial reference. | `additional_records` after semantic matching. |
| Extraction quality | Support rate among additional records (`additional_support_percent`) | Additional items judged supported ÷ all additional items × 100. | `support_status`; complete judgments required. |
| Evidence support | Quotation support rate (`quotation_support_percent`) | Quotation uses with `supports_claim = true` ÷ all quotation uses assessed × 100. | `quotation_checks`. |
| Evidence support | Page reference correctness (`page_correct_percent`) | Page checks with `correct = true` ÷ all assessed pairs of quotations and cited pages × 100. | `quotation_checks.page_checks`. |
| Issue handling | Correctly flagged issue rate (`genuine_issue_percent`) | Issues judged genuine ÷ all assessed issues recorded before expert review × 100. | `issue_assessments`; includes open and resolved issues. |
| Issue handling | Unflagged problem count (`unflagged_problems`) | Count distinct affected target groups with at least one expert confirmed problem absent from recorded concerns. | `unflagged_problems`. |
| Verifier contribution | Expert supported verifier resolutions (`supported_verifier_resolutions`, `unsupported_verifier_resolutions`, `verifier_resolution_support_percent`) | Count supported and unsupported verifier closures. Proposed percentage: supported closures ÷ all assessed verifier closures × 100. | Issue history and `verifier_resolution_supported`. |

The verifier resolution percentage is proposed and requires review. Its denominator is issues finally marked `resolved` with `resolved_by = verifier`, including initial and newly raised issues; reopened issues are excluded. Interpret it alongside extraction and evidence scores, using the resolution rules in Section 7.

Section 6.8 defines reference revisions, semantic matching, additional item grouping, and quotation/page checks. The rows above use those units consistently. Unsupported additional records do not lower reference based extraction scores, so report their count and support rate alongside those scores.

### 8.3 Scoring rubric and reporting

| Score | Definition |
| --- | --- |
| 1 | All required substantive information is correct, with no unsupported substantive additions. |
| 0.5 | Some substantive information is correct, but at least one required part is incorrect or missing. |
| 0 | No substantive information is correct, or the reference record was omitted entirely. |

Different wording is acceptable when meaning is equivalent. A correctly identified action with the wrong implementation status receives 0.5. Correctly recording unavailable information does not reduce the score. Content and evidence correctness are assessed separately.

The extraction quality denominator is the total number of content records across the five final reference lists. Plan metadata, individual target pairs, evidence objects, and issue concerns are not separate records in this denominator.

For ten reference records with six fully correct, two partial, and two omitted, partial credit accuracy is `(6 + 2 × 0.5) / 10 = 70%`; the fully correct rate is `6 / 10 = 60%`. Preserve these underlying counts rather than reporting the percentages alone.

Calculate scores per plan and content category using the same definitions. Keep the two configurations paired by plan. The proposed overall summary is the mean of valid per plan percentages, with the number of contributing plans shown; pooled counts may be reported separately and labeled. A plan/category with a zero denominator is excluded from that mean and reported as not applicable. This aggregation rule requires confirmation before comparison.

The current workflow uses one expert for reference coding and assessment. Report this limitation; the study cannot estimate agreement between experts from these assessments. If a second expert is added later, establish the checking and disagreement procedure during development, extend the records to distinguish assessors, and retain those decisions.

## 9. Development records and reproducibility

Development records will describe the problem encountered, change made, reason, observed result, and remaining questions. These records will support the study's account of useful tools, model limitations, and expert intervention.

Before comparison, fix and version the schemas, prompts, models/settings, serving approach/provider, tools, document processing strategy, retry limits, and evaluation rules. Store executable stage settings in the profiles defined in Section 6.11. If any change requires new comparison runs, label them separately and preserve the earlier results.

Checks will cover page numbering, required fields, IDs and links, issue transitions, preservation of earlier outputs, metric calculations, and failure handling. Factual accuracy and semantic evidence support will require expert assessment.

Retain source files, profiles, software/model versions, and processing history so the workflow can be repeated and inspected. Exact model outputs may still vary under the same settings.

## 10. Implementation and repository structure

| Location | Purpose |
| --- | --- |
| `src/` | Reusable Python modules for the workflow, model adapter, MCP tools, expert assessment, and analysis, plus the CLI that calls them. |
| `notebooks/` | Inspection of saved outputs, comparisons, research tables, and figures using the shared Python modules. |
| `schemas/`, `prompts/`, `configs/` | Versioned data specifications, instructions, settings, and execution profiles. |
| `data/registry/plans.json` | Registered document versions and links to preparation records; tracked in Git. |
| `tests/` | Checks of processing, validation, issue history, and calculations. |
| `data/raw/`, `data/processed/` | Source PDFs and prepared page text. |
| `models/`, `runs/`, `artifacts/`, `logs/` | Local weights, stage runs, batch records, extraction/review snapshots, assessments, metrics, and diagnostics. |
| `data/release/`, `reports/` | Selected dataset releases and study summaries. |

Track code, configuration without secrets, registry metadata, and project documents in Git. Exclude local instructions, credentials, model weights, raw/prepared sources, and generated runs. Keep backups of excluded research files and choose a release location.

An example layout for one plan is shown below. These paths are proposed; no processing files or folders have been created.

```text
data/registry/plans.json
data/raw/plan_0001.pdf
data/processed/plan_0001/source_0001.json
data/processed/plan_0001/page_0001.txt
configs/execution/local_extractor_v1.json
runs/batches/batch_0001.json
runs/plan_0001/stages/run_extract_0001.json
runs/plan_0001/snapshots/snapshot_extract_0001.json
runs/plan_0001/reviews/review_extract_0001.json
runs/plan_0001/results/result_e_0001.json
runs/plan_0001/references/reference_set_0001.json
runs/plan_0001/assessments/assessment_0001.json
runs/plan_0001/metrics/metrics_0001.json
```

Implementation order is registration and preparation, local extraction, verification and issue history, expert assessment, and analysis. The hosting development sequence is in Section 5; study set roles are in Section 2. Expand after analyzing the comparison and selecting a workflow.

## 11. Open implementation decisions

- Final local model pair following tests of the provisional Qwen3.5 27B extractor and Gemma 4 31B verifier; quantization, context settings, and Ollama version.
- Hugging Face model/provider options and the serving approach selected for comparison.
- Whole document or page batched processing and record merging.
- Review of the proposed JSON fields, registry/profile/batch records, issue grouping/type rules, and expert assessment format.
- Retry limits, runtime specific token reporting, and assessment procedures for incomplete outputs.
- Expert matching examples, claim to quotation assignment, proposed aggregation, and optional second expert procedures if another assessor is added.
- Expansion review coverage, release format, document redistribution permissions, and artifact storage.
