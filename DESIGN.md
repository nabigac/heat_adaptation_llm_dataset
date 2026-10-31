# Heat Adaptation LLM dataset

**Study design and technical implementation (draft)**

**Last updated:** 2026-10-31

This draft defines the study workflow, proposed Python system, JSON records, and evaluation calculations. Model choices are provisional; Section 11 lists the open decisions.

Sections 1 to 4 describe the study and workflow. Section 5 describes the Python system; Section 6 defines the JSON records and examples. Sections 7 and 8 cover issue handling and evaluation. Sections 9 to 11 cover reproducibility, files, and open decisions.

## 1. Purpose

This study will develop and evaluate a workflow in which open weight large language models (LLMs) and a heat adaptation expert extract structured data from government plans. Each extracted record links to supporting source passages.

The study has two main questions:

1. How can open weight LLM agents and experts build an extraction dataset using Model Context Protocol (MCP) tools, and what practical lessons emerge?
2. How does adding a verifier using a different open weight model change extraction quality, issue handling, expert review requirements, and computational resources?

The dataset will describe what plans state about heat adaptation. Future work may use it for fine-tuning, or further training, an LLM.

## 2. Study design

| Study set | Size | Purpose |
| --- | --- | --- |
| Development | 2 plans | Develop prompts, tools, coding rules, and expert review procedures. |
| Comparison | 10 separate plans | Compare extraction with and without verification against an expert coded reference. |
| Expansion | To be determined | Apply the selected workflow and curate additional records. The original target is 50 to 100 unique plans in total. |

The comparison will use two configurations:

- **Extractor (E):** An agent reads a plan, creates records with supporting passages, and flags issues.
- **Extractor + verifier (E+V):** A second agent uses a different model to check the same extraction against the source. It reviews all records and flagged issues and looks for omissions.

Both configurations use the same saved extractor output. Development will test local and hosted models to choose the setup for this comparison. Section 9 defines what must be fixed before comparison; hosting is not a separate experimental configuration.

The expert will prepare the initial reference before seeing model outputs and assess outputs before correcting them. Findings apply to the tested workflow and model pair. The study does not isolate the effects of MCP or open weight models from other technologies.

## 3. Plans and extraction content

Eligible documents are final government or public agency plans that:

- Are publicly available in English and were published or updated in 2010 or later, with recent versions prioritized.
- Focus on heat adaptation or contain a dedicated heat section with at least one action specifically addressing heat.
- Have a readable full document and stable PDF page numbers.

Each plan has metadata, such as title and jurisdiction, and five content lists:

| List | Content |
| --- | --- |
| Goals | Stated heat adaptation goals, targets, and deadlines. |
| Actions | Proposed or reported actions and their implementation status. |
| Monitoring and evaluation | What is tracked or evaluated, how, and by whom. |
| Benefits and impacts | Expected or reported outcomes, including adverse impacts. |
| Costs and resources | Financial costs and other resource requirements. |

The researcher screens documents before import. The CLI accepts eligible documents without asking about eligibility or expert identity. Readability refers to the original PDF, including scans a person can read. Section 6.2 distinguishes recoverable text gaps from source access failures; these processing problems alone do not change eligibility.

Section 6 defines the fields, missing value rules, and evidence. Section 7 defines review requirements.

## 4. Processing workflow

| Stage | Main tasks | Saved outputs |
| --- | --- | --- |
| Collect and prepare | Register the PDF, automatically prepare page text, and identify text gaps and pages available as images. | Source metadata, original PDF, page marked text, page problems, and preparation status. |
| Extract | Read the whole plan, use MCP tools to investigate gaps, create records with evidence, and track issues. Check the final output format. | Extractor output, issue state, saved image/OCR results, tool activity, and run measurements. |
| Verify | Review a copy of the extraction against the source. Check records and issues, correct errors with source support, and find omissions. | Verifier output, record changes, issue history, and run measurements. |
| Summarize before expert review | Preserve both outputs and summarize execution, flags, resolutions, and referrals. | Measures before expert review for E and E+V. |
| Assess with experts | Match records to the reference, check correctness and evidence, and assess additional records and issue handling. | Expert assessments, reference revisions, and measures after expert review. |
| Curate and expand | Correct supported errors, exclude unresolved material, and apply the selected workflow to additional plans. | Curated dataset, review coverage, and processing history. |

Python automatically prepares page text before extraction. Both configurations use the same PDF and initial text. Section 6.2 defines when preparation allows processing to proceed; Section 5 defines tools for investigating gaps. Section 6.1 defines how versions are saved. Unreadable material must not be treated as absent information.

During expansion, the expert reviews referred issues and an agreed sample of unflagged outputs. Save which records were checked and how.

### 4.1 Register documents

Store accepted PDFs under `data/raw/` and list each document version in `data/registry/plans.json`. Section 6.10 defines the registry fields; Section 4.3 describes processing status.

Registration consists of:

1. Import the PDF through the CLI with its title, official source URL, access date, and study set. Complete required details before saving.
2. Calculate the PDF checksum, a value identifying its contents, and check for duplicates. Assign a plan ID, save the PDF path, and set whether processing is enabled.
3. Save the registry entry, prepare page text, and add the source record path to the entry.

Edit collection details after registration without importing the PDF again. Save the edit time and old and new values, using Section 6.10. One researcher runs the workflow, so operator IDs are not required.

A revised published PDF gets a new plan ID linked to the earlier version. Preparing the same PDF again creates a new source ID under its existing plan ID. Copying or renaming a PDF keeps its document version. Investigate a changed checksum before processing; preserve the registered source.

### 4.2 Select, skip, and rerun work

A **batch** is one CLI request to process one or more documents. Select the documents, E, E+V, or both, and **profiles** listed in `configs/profiles.json`. Profiles contain the model, prompt, tool, and processing settings. Each execution of an extractor or verifier step is one **run**.

For each document, run extraction once. E preserves that output for evaluation; E+V adds verification of a copy. Selecting both does not run the extractor twice.

**Starting a request**

1. Check that selected documents are registered, enabled, and accessible.
2. Prepare page text if needed and check that the whole document input fits the selected model settings under Section 5. Section 6.2 defines which source gaps can proceed through image/OCR tools and which problems block processing.
3. Check for saved work that can be reused.
4. Show what will be reused, started, or blocked. Start ready work after the researcher confirms the preview.

Other ready documents can proceed when one is blocked. Unregistered or disabled documents are skipped until imported or enabled. Successful processing means the output passes format checks; expert assessment determines accuracy separately.

**What the IDs identify**

The software assigns IDs automatically. Each ID is a separate label. Records connect by storing other IDs in their fields; IDs are not appended to one another.

| ID | What it identifies | When it changes |
| --- | --- | --- |
| `plan_id` | One published document version. | A revised published PDF gets a new ID. Rerunning the same document does not. |
| `source_id` | One saved preparation of the document. | Preparing text again or saving corrected source metadata creates a new ID. |
| `batch_id` | One processing request. | Every new request gets a new ID, even if it only reuses saved work. |
| `run_id` | One extractor, verifier, or separate text repair step. | A manual retry or deliberate repeat gets a new ID. Model and tool calls within the step keep that run ID. |
| `result_id` | One saved E or E+V result linking its source, runs, output, and review. | Using different runs creates a new result. Reusing the complete result keeps its ID. |

Outputs and reviews also have IDs, defined in Section 6. New versions are saved without overwriting earlier ones. Model calls and tools used within a run, including OCR, remain under that run ID.

**When work is reused or started again**

Reuse requires the same source and profile, with valid saved output and review files. Verification must also use the same extractor output. Section 6.11 defines the detailed matching rules and limits on hosted reuse.

| Situation | What happens and what to do |
| --- | --- |
| No matching run exists | Start the missing work. Verification waits for successful extraction. |
| Matching work succeeded | Reuse its output, IDs, and measurements without another model call. An E+V request adds verification if only extraction exists. |
| Source or settings changed | Reuse work matching the new request, or start the affected steps. Changing verifier settings alone can reuse extraction; changing extractor input or settings also requires matching extraction before verification. |
| A run failed | Address the error and explicitly request a retry. Keep the failure record; retry only failed or missing work and reuse valid completed work. |
| A matching run is still active | Wait and check status. Do not start a duplicate. |
| A process stopped unexpectedly or its state is uncertain | Check the original terminal or running process. Once stopped, mark the run failed through the CLI and request a retry. Keep partial files without treating them as completed output. |
| Saved files are missing or invalid | Restore them from backup or explicitly request replacement processing. Block reuse and keep the earlier record. |
| A successful result is deliberately repeated | Use the repeat option to start every step required by the selected configurations again. Repeating E+V creates new extractor and verifier runs; selecting both shares the new extraction. |
| Several successful runs match | List their IDs and ask which to use. Do not silently choose the latest. |

**Retrying a failed run**

Stop on run failure and report the error. The software does not retry automatically. After addressing the cause, request a retry through the CLI. This creates a new batch and run ID, preserving the earlier failure and its measurements. A finished run is not reopened. There is no retry count or retry limit setting.

For example:

1. `batch_0001` creates successful extractor run `run_extract_0001` and failed verifier run `run_verify_0001`. E is available; E+V is failed.
2. A retry creates `batch_0002`, reuses `run_extract_0001`, and starts `run_verify_0002`.
3. The new verifier record stores `parent_run_id: run_extract_0001` for its input and `retry_of_run_id: run_verify_0001` for the failure it retries. It reads the successful extraction, not failed verifier output.
4. A new E+V result links `run_extract_0001` and `run_verify_0002`. The earlier failure stays saved. The E result keeps its ID.

Reused runs keep their original batch IDs and measurements; the later batch links the saved results it used. Reuse does not create another runtime measurement. Record fields are defined in Sections 6.6, 6.7, and 6.11.

### 4.3 Processing summary

The CLI will display a table based on saved registry, source, and run records. For the selected profiles, show each plan's ID, title, study set, preparation status, extraction status, verification status, and next action. Use the labels not run, running, failed, complete, or blocked.

Status depends on the selected profiles. A plan may be complete with one set of settings and not run with another.

The first implementation will store records as JSON files and process one batch at a time through the CLI.

## 5. Proposed system

Use Python modules for the workflow, a small CLI for processing, and notebooks for inspection and research analysis. Run them on the development computer, starting with Ollama and later exploring Hugging Face hosted APIs.

- **Python modules** contain reusable functions for profiles, registration, document preparation, model requests, tools, storage, expert assessment, and calculations.
- **CLI (command line interface)** runs these functions from the terminal. Use it to select documents, configurations, and profiles; import PDFs; edit details; prepare text; start batches; and check status. It supports manual retries, repeats, and marking interrupted runs failed after the process has stopped. Supply details as command arguments or answer prompts for missing information. It shows planned work for confirmation before model calls. Eligibility and operator identity are handled as described in Section 3.
- **Notebooks** load saved outputs to inspect records and issues, compare configurations, and create tables and figures. They use the shared Python modules for calculations. Routine processing uses the CLI so it does not depend on notebook cell order.

| Component | Role |
| --- | --- |
| Document preparation | Automatically prepare page text and record gaps before model processing. |
| Workflow code | Select work from the registry, run stages in order, enforce limits, check output structure, and save results and measurements. |
| Model adapter | Convert model requests into the format expected by Ollama or the hosted API, and return responses in a common format. |
| MCP client and server | Connect the workflow code to document reading and checking tools. |
| Extractor and verifier | Use source text and tools to produce or check structured records. |
| Expert assessment and analysis | Store expert judgments and calculate measures from saved outputs. |

An agent uses a model to read instructions and source text, request tools, inspect results, and submit an answer within set limits. Python executes the requested tools and returns results to the model.

MCP connects the workflow to tools. Python manages model calls, the text supplied to models, step order, and saved outputs. See the [MCP architecture documentation](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture).

Python starts the MCP server locally and exchanges messages through **stdio**, the process's standard input and output. See the [Python SDK transport documentation](https://py.sdk.modelcontextprotocol.io/client/transports/).

### Local models first

Start development with Ollama on an Apple M5 Pro MacBook with 64 GB of unified memory. Python, MCP tools, documents, and outputs stay on that computer. The model adapter calls Ollama's local API.

The initial candidates are:

| Role | Model | Ollama tag | Reason for consideration |
| --- | --- | --- | --- |
| Extractor | Qwen3.5 27B | `qwen3.5:27b` | Instruction following and tool use capabilities relevant to reading plans and populating structured records. |
| Verifier | Gemma 4 31B | `gemma4:31b` | Reasoning and function calling capabilities from a different model family, relevant to checking records against source evidence. |

These candidates require development testing for this task. Different model families can still make similar errors. See the [Qwen model card](https://huggingface.co/Qwen/Qwen3.5-27B) and [Gemma model overview](https://ai.google.dev/gemma/docs/core).

On the development plans, test memory, document capacity, tools, JSON format, extraction quality, and runtime. Test image inputs with the actual serving setup and test OCR separately. Check whether verification finds omissions and corrects errors without adding new ones. Either model or role may change. Load models in sequence to leave memory for source text, the operating system, and other programs.

Test Ollama's [tool calling](https://docs.ollama.com/capabilities/tool-calling) and [schema constrained output](https://docs.ollama.com/capabilities/structured-outputs), which restricts responses to a specified JSON structure. Record quantization, the reduced numerical precision of model weights used to lower memory requirements.

### Later exploration of hosted APIs

After establishing the local workflow, explore [Hugging Face Inference Providers](https://huggingface.co/docs/inference-providers/index). The workflow code and MCP tools stay local while the model adapter sends requests to the provider. These requests include the plan text and tool results needed by the hosted model.

Choose hosted models based on availability, capabilities, cost, and development results. Published weights on Hugging Face do not guarantee a hosted API for that model.

Test the chosen model and provider for document limits, tool calls, JSON format constraints, token reporting, and request failures. Select a specific provider. The provider manages the GPU server.

Local and hosted model adapters use the same extraction, review, and assessment formats. Record deployment details under Section 6.6, leaving unavailable details unknown. Section 9 governs comparison settings and changes.

### Source context

Use **whole document processing**. Supply the full prepared plan text with PDF page numbers, instructions, and field definitions. The verifier also receives the saved extraction and issues. The context limit must accommodate these inputs, model output, and tool results retained during the run.

Check that each model request fits the selected context limit. If it cannot fit, stop and report the capacity problem so the researcher can adjust the profile or model. Keep the full source text; do not truncate it or switch to page groups automatically. Whole document processing can still involve several model and MCP tool calls. The context strategy version records these input and context rules. No collection search system is planned.

Start with prepared text. For gaps, garbled text, or unclear tables, request a page image or **OCR**, which converts text in an image into machine readable text. Check the returned material before using it; OCR and model interpretation can introduce errors.

Both agents can access the same PDF, initial text, and tools. Record their page and tool choices. Enable direct image reading only after testing both model setups. Otherwise, use OCR that returns text to both and record the limitation.

### Initial MCP tools

| Tool | Function | Limit |
| --- | --- | --- |
| List pages | Return page count, prepared text availability, and page problems. | Does not establish extraction completeness or detect every text problem. |
| Read pages | Return saved text for a specified PDF page range, with preparation warnings. | Interpretation remains the model's task. |
| Read page image | Render a requested PDF page and return the image with its source and page identifiers. | Requires tested image input support. Rendering does not establish correct interpretation. |
| OCR pages | Run the selected OCR procedure on requested PDF pages and return text with page identifiers and warnings. | OCR can misread wording, numbers, and table layout. |
| Check quotation | Locate a quotation in saved page text or OCR results and return surrounding text, or report that visual checking is needed. | A text match does not establish source accuracy or claim support; an OCR match alone is insufficient. |
| Validate extraction | Check required fields, allowed values, IDs, links, and page bounds. | Valid structure does not establish factual accuracy. |

Text search may help navigate a plan; it does not establish complete coverage.

Tools access registered sources and candidate records; expert reference files stay outside agent access. Python saves outputs. Treat source text as evidence, not agent instructions.

Save images and OCR results as **artifacts**, the files and records linked to their source, pages, and requesting run. Both agents can request saved artifacts through the tools. Keep initial prepared text unchanged. Preparing it again creates a new source version and follows the comparison rules before replacement results are produced. Sections 6.2 and 6.6 define artifact fields and runtime accounting.

## 6. JSON specification

Save collection, source, content, review, run, and assessment records in separate JSON files. A **schema** defines fields, types, and allowed values. An **enum** is a fixed list of values; **null** means no value is available. A **snapshot** is a saved extraction or review version. These specifications and examples are proposed; data files and validation schemas have not been implemented.

### 6.1 Common rules and file links

- All listed fields are required, including nested fields described in prose. Keep nullable fields present with `null` when unavailable.
- Use `[]` for empty lists. Use a defined missing information enum value instead of `null` where specified.
- Create records for distinct content items. Leave a category empty when it has no records.
- Validate IDs, versions, collection dates, and workflow fields.
- Dates use `YYYY-MM-DD`; timestamps use UTC in `YYYY-MM-DDTHH:MM:SSZ` form. Durations use seconds. File paths are relative to the project root.
- `schema_version` is initially `1` for the proposed implementation. Change it when the field structure or coding rules change.
- A document version has one `plan_id`. A saved extraction version has one `snapshot_id`; a stage execution has one `run_id`.
- Content IDs are unique within a snapshot and stay unchanged through corrections. Give additions new IDs; retain removed or merged records in earlier snapshots. Expert and model records are matched by meaning, since their local IDs may overlap.
- References from other files include the extraction's `snapshot_id`. Internal links use IDs from that snapshot. Page lists use unique numbers within the PDF's page range.
- Python supplies file links, run IDs, and measurements. Agents supply content and proposed issues. Experts supply assessment judgments.
- Reject unexpected fields and invalid enums in final output and mark the run failed. Drafts may be checked and corrected through normal tool use before final submission.

Each review snapshot describes one extraction snapshot. Save later outputs, reviews, and expert corrections as new versions. Update run and batch records while active, then retain them when finished. Section 10 shows file locations.

### 6.2 Source record

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `source_id` | String | ID for one PDF and prepared text version. Preparing it again creates a new source record. |
| `plan_id` | String | Document version identifier, such as `plan_0001`. |
| `study_set` | Enum | `development`, `comparison`, or `expansion`. |
| `source_url` | String | Official document or download page URL. |
| `date_accessed` | Date | Date supplied by collection. |
| `pdf_path` | String | Project relative path to the original PDF. |
| `document_sha256` | String | The PDF's 64 character hexadecimal SHA-256 checksum, copied from registration. |
| `prepared_text_sha256` | String or null | Checksum of initial page text and preparation details, including unavailable text; null only on preparation failure. |
| `preparation_version` | String | Version of the text preparation procedure. |
| `page_count` | Positive integer or null | Number of PDF pages; null only if preparation failed before the count could be determined. |
| `preparation_status` | Enum | `ready`, `ready_with_gaps`, or `failed`, as defined below. |
| `pages` | List of page objects | One item per PDF page. |
| `problem` | String or null | Preparation problem, if any. |

Each page object contains:

| Page field | Type | Description |
| --- | --- | --- |
| `page_number` | Positive integer | Original PDF page number. |
| `text_path` | String or null | Path to prepared text, if available. |
| `readable` | Boolean | Whether the prepared text is readable. |
| `image_available` | Boolean | Whether the original page can be rendered as an image. |
| `problem` | String or null | Preparation problem, if any. |

Include pages 1 through `page_count` exactly once. Distinguish blank pages from failed text recovery where possible.

| Preparation state | Meaning and processing rule |
| --- | --- |
| `ready` | Automatic checks found no text preparation problems. Agents may still find missing or incorrect text. |
| `ready_with_gaps` | The PDF is accessible but has missing or unreliable page text. Proceed with usable text or tested image/OCR tools. Keep unresolved pages flagged. |
| `failed` | The PDF cannot be opened, its pages cannot be identified, or neither usable text nor page images are available. Repair source access before processing. |

Use `page_count: null` and `pages: []` when opening or counting pages fails. Otherwise retain each known page, even on failure. A PDF available only as images is `ready_with_gaps`; processing requires a tested image/OCR route in the selected profiles.

Calculate the prepared text checksum from ordered objects with `page_number`, `text` (string or null), `readable`, `image_available`, and `problem`, using Section 6.11's serialization rule. Use null text for failed recovery and an empty string for a known blank page. Keep initial text unchanged; document any text normalization, such as spacing changes, used to match quotations. Supplemental artifacts do not change this checksum.

Each saved image or OCR result has a separate artifact record:

| Artifact field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Artifact format version. |
| `artifact_id`, `source_id`, `run_id` | Strings | Unique artifact, original source, and requesting stage run. |
| `page_numbers` | Nonempty list of positive integers | Original PDF pages represented. |
| `kind` | Enum | `page_image` or `ocr_text`. |
| `input_artifact_ids` | List of strings | Saved image inputs for OCR, if used; otherwise empty. |
| `path`, `sha256` | Strings or null | Saved output path and checksum; null if no output was produced. |
| `tool_name`, `tool_version` | Strings | Tool implementation used. |
| `settings` | Object | Actual rendering or OCR settings, including engine version and language where applicable. |
| `created_at` | Timestamp | Time the artifact was generated. |
| `status` | Enum | `succeeded` or `failed`. |
| `error` | String or null | Failure explanation; null on success. |

Save artifacts with the requesting run. Reuse keeps their original IDs and is recorded in each later tool trace. Artifacts must match the source checksum and fixed tool settings. Retain failed tool call records even if no file was produced.

### 6.3 Extraction snapshot

This record contains extracted content and links to its source, run, and review.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format and coding rule version. |
| `snapshot_id` | String | Unique identifier for this saved extraction. |
| `parent_snapshot_id` | String or null | Previous version, including the extractor version used by the verifier. |
| `source_id` | String | Source record used. |
| `run_id` | String or null | Stage run that produced the extraction; null for manual expert coding or correction. |
| `review_id` | String | Initial review for this extraction; a configuration result may link a later review of the same snapshot. |
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

Use document metadata or verified collection details. Assign responsibility for an action only when supported; issuing the plan is not enough.

**Evidence objects**

Every content record has an `evidence` list. Each evidence object contains:

| Field | Type | Description |
| --- | --- | --- |
| `quote` | String | An exact, continuous source passage. |
| `page_numbers` | Nonempty list of positive integers | PDF pages containing that passage. Count the first PDF page as 1, regardless of printed labels. |

Use one evidence object per continuous passage, which may cross pages. Preserve wording, numbers, units, and qualifications. Record links need source support. Flag unsupported records and exclude them from the accepted dataset until supported.

Image/OCR evidence must quote visible source wording and cite original PDF pages. Experts check the original page. Refer visual interpretations without the required quotation evidence for expert review; do not invent wording.

**Goal records: `plan_goals`**

| Field | Type | Description |
| --- | --- | --- |
| `goal_id` | String | Local ID, such as `goal_0001`. |
| `goal` | String | Explicitly stated goal, retaining relevant population and geographic scope. |
| `targets` | List of target objects | Each has `target` (string) and `deadline` (string or null). |
| `evidence` | List of evidence objects | Support for the goal and targets. |

Pair each target with its deadline. Keep quantities, units, baselines, and timing precision, such as `2030` or `within five years of adoption`. Targets may be qualitative. Goals must be stated, not inferred solely from actions or benefits.

**Action records: `plan_actions`**

| Field | Type | Description |
| --- | --- | --- |
| `action_id` | String | Local ID, such as `action_0001`. |
| `action` | String | Explicit action, beginning with an action verb. Include implementers, populations, locations, quantities, and timing where stated and relevant. |
| `action_status` | Enum | `planned`, `in_progress`, `completed`, `discontinued`, or `not_specified`. |
| `related_goal_ids` | List of strings | Goals explicitly associated with the action. |
| `evidence` | List of evidence objects | Support for the action, status, and links. |

| Status | Meaning |
| --- | --- |
| `planned` | Proposed or committed, without evidence work has begun. |
| `in_progress` | Underway or functioning. |
| `completed` | Finished. |
| `discontinued` | Stopped or withdrawn. |
| `not_specified` | The source does not establish a clear status. |

Combine repeated mentions. Give independently implementable actions separate records; components of one integrated measure may stay together.

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

| Scope | Rule |
| --- | --- |
| `linked` | At least one source supported goal or action link. |
| `plan_wide` | Explicitly applies to the overall heat plan or programme; both link lists are empty. |
| `unspecified` | The source does not establish scope; both link lists are empty. |

Unspecified scope alone does not create an issue.

Monitoring activity alone does not establish reduced heat risk. Distinguish expected, modelled, and observed benefits, retaining the plan's claims as reported. For costs, distinguish estimates, allocations, expenditure, and needs. Record shared budgets once and link relevant actions. Convert currencies or divide amounts only with source support.

### 6.4 Extraction example

This fictional one page plan shows linked source, extraction, and run records. Section 6.5 shows the review. The extraction intentionally has a wrong action status and omits a quantity and deadline.

The extraction links to checksums through `source_id` and `run_id`, as defined in Sections 6.2, 6.3, and 6.6.

| File | What it contains |
| --- | --- |
| `data/processed/plan_0001/source_0001.json` | PDF and prepared text checksums, plus page preparation details. |
| `runs/plan_0001/snapshots/snapshot_extract_0001.json` | Extracted content and links to the source, run, and review. |
| `runs/plan_0001/stages/run_extract_0001.json` | Profile checksum, run matching checksum, model settings, and measurements. |
| `runs/plan_0001/reviews/review_extract_0001.json` | Issues and review history shown in Section 6.5. |

Files, quotations, versions, timings, and token counts are illustrative. Repeated digit checksums and the model digest are placeholders; real runs calculate them from actual inputs. The linked profile record follows Section 6.11 and must match `profile_sha256`. No example files have been created.

**Source record**

```json
{
  "schema_version": 1,
  "source_id": "source_0001",
  "plan_id": "plan_0001",
  "study_set": "development",
  "source_url": "https://example.org/heat-plan.pdf",
  "date_accessed": "2026-10-24",
  "pdf_path": "data/raw/plan_0001.pdf",
  "document_sha256": "0000000000000000000000000000000000000000000000000000000000000000",
  "prepared_text_sha256": "1111111111111111111111111111111111111111111111111111111111111111",
  "preparation_version": "pdf_text_v1",
  "page_count": 1,
  "preparation_status": "ready",
  "pages": [
    {
      "page_number": 1,
      "text_path": "data/processed/plan_0001/page_0001.txt",
      "readable": true,
      "image_available": true,
      "problem": null
    }
  ],
  "problem": null
}
```

**Extraction snapshot**

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
      "page_numbers": [1]
    }, {
      "quote": "To meet this goal, the city will plant 5,000 trees around schools by 2030.",
      "page_numbers": [1]
    }]
  }],
  "plan_actions": [{
    "action_id": "action_0001",
    "action": "Plant trees around schools.",
    "action_status": "completed",
    "related_goal_ids": ["goal_0001"],
    "evidence": [{
      "quote": "To meet this goal, the city will plant 5,000 trees around schools by 2030.",
      "page_numbers": [1]
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
      "page_numbers": [1]
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
      "page_numbers": [1]
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
      "page_numbers": [1]
    }]
  }]
}
```

**Run record**

The output passes format checks but needs factual review. Prepared text goes directly to the model, with no image/OCR calls: `tool_artifact_paths` is empty and `tool_trace_path` is null. IDs match the linked records.

```json
{
  "schema_version": 1,
  "run_id": "run_extract_0001",
  "plan_id": "plan_0001",
  "source_id": "source_0001",
  "batch_id": "batch_0001",
  "profile_id": "local_extractor_v1",
  "profile_sha256": "2222222222222222222222222222222222222222222222222222222222222222",
  "profile_record_path": "runs/profiles/local_extractor_v1/2222222222222222222222222222222222222222222222222222222222222222.json",
  "run_key": "3333333333333333333333333333333333333333333333333333333333333333",
  "retry_of_run_id": null,
  "stage": "extractor",
  "parent_run_id": null,
  "input_snapshot_id": null,
  "output_snapshot_id": "snapshot_extract_0001",
  "status": "succeeded",
  "started_at": "2026-10-24T12:00:00Z",
  "ended_at": "2026-10-24T12:00:30Z",
  "elapsed_seconds": 30,
  "model": {
    "name": "qwen3.5:27b",
    "revision": "sha256:4444444444444444444444444444444444444444444444444444444444444444",
    "execution_mode": "local",
    "api_service": null,
    "provider": null,
    "endpoint": "http://localhost:11434",
    "runtime": "ollama",
    "runtime_version": "example-runtime-version",
    "quantization": null,
    "context_limit": 4096,
    "generation_settings": {
      "temperature": 0,
      "top_p": 1,
      "seed": 42,
      "max_output_tokens": 2048
    },
    "runtime_options": {
      "model_loaded_at_start": false
    },
    "hardware": "Apple M5 Pro, 64 GB unified memory"
  },
  "versions": {
    "code_commit": "0000000000000000000000000000000000000000",
    "code_dirty": false,
    "prompt_version": "extractor_v1",
    "tools_version": "document_tools_v1",
    "preparation_version": "pdf_text_v1",
    "model_client_version": "example-client-version"
  },
  "execution_policy": {
    "max_tool_calls": 10
  },
  "tool_artifact_paths": [],
  "model_calls": [
    {
      "call_id": "call_0001",
      "input_tokens": 1024,
      "output_tokens": 768,
      "response_path": "runs/plan_0001/responses/call_0001.json"
    }
  ],
  "tool_trace_path": null,
  "error": null
}
```

### 6.5 Review snapshot and issue history

Save review records separately to preserve issue history through verification and expert correction.

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

Categories use the five extraction list names. Review coverage records what the expert checked; issues may remain unresolved after review.

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
| `resolved_by` | Enum or null | `extractor`, `verifier`, `expert`, or `pipeline`; null while open. |
| `resolution` | String or null | Overall resolution explanation; null while open. |
| `concerns` | Nonempty list | Specific problems grouped within the issue. |
| `history` | Nonempty list | Ordered creation and change events. |

Each issue contains concerns:

| Concern field | Type | Description |
| --- | --- | --- |
| `concern_id` | String | Stable concern ID. |
| `field` | String | Field path within the record, or a full plan path. |
| `description` | String | Specific problem. |
| `status` | Enum | `open` or `resolved`. |
| `resolution` | String or null | Resolution explanation, if resolved. |

Count the bundled issue once, regardless of its concern count.

Each history event records:

| Event field | Type | Description |
| --- | --- | --- |
| `event_id` | String | Event ID. |
| `occurred_at` | Timestamp | Event time. |
| `actor` | Enum | `extractor`, `verifier`, `pipeline`, or `expert`. |
| `run_id` | String or null | Related run; null for manual expert actions. |
| `from_status` | Enum or null | Previous issue status; null on creation. |
| `to_status` | Enum | New issue status. |
| `change_type` | Enum | `created`, `routed`, `tool_attempt`, `corrected`, `confirmed_absent`, `reprocessed`, or `reopened`. |
| `note` | String | Explanation; link the tool trace and outcome for tool calls. |
| `evidence` | List | Quotation and page evidence; may be empty for routing or failed tool calls. |

Status values use the issue enum. A tool call may leave the status unchanged.

Section 7 defines how to group, route, and resolve issues.

Use these issue categories:

| Value | Use |
| --- | --- |
| `no_records_found` | A category is empty after processing a readable source; absence has not yet been established. |
| `unclear_meaning` | Meaning, classification, or relationship is uncertain. |
| `conflicting_evidence` | Passages make incompatible claims that context does not resolve. |
| `source_issue` | Missing or unreliable page text, images, or layout prevents reliable checking; may be resolved through supplemental tools or expert review. |
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
      "occurred_at": "2026-10-24T12:00:29Z",
      "actor": "extractor",
      "run_id": "run_extract_0001",
      "from_status": null,
      "to_status": "pending_verification",
      "change_type": "created",
      "note": "Flagged the action for verification.",
      "evidence": [{
        "quote": "To meet this goal, the city will plant 5,000 trees around schools by 2030.",
        "page_numbers": [1]
      }]
    }]
  }]
}
```

The extraction's `review_id` points to its initial review. The configuration result points to its final review before expert assessment. These can be different review versions of the same extraction snapshot.

### 6.6 Stage run record

A run covers one extractor, verifier, or reprocessing step. Save its model calls, tool trace, and any failure. The JSON field `stage` identifies the step. A failed model request, unhandled processing error, or invalid final output ends the run. Recoverable source gaps and tool results remain issues under Section 7.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `run_id`, `plan_id`, `source_id` | Strings | Execution and source identifiers. |
| `batch_id` | String | Batch that first scheduled this run. Reuse does not change it. |
| `profile_id`, `profile_sha256` | Strings | Execution profile and its settings checksum. |
| `profile_record_path` | String | Path to saved settings and technical versions for this run. |
| `run_key` | String | Checksum used to find equivalent completed work; defined in Section 6.11. |
| `retry_of_run_id` | String or null | Earlier failed run retried by a new execution; null otherwise. |
| `stage` | Enum | `extractor`, `verifier`, or `reprocessing`. |
| `parent_run_id` | String or null | Input extractor run for a verifier, or the stage requiring reprocessing. Separate from retry history. |
| `input_snapshot_id` | String or null | Input extraction; null for the first extraction. |
| `output_snapshot_id` | String or null | Output extraction; null if none was produced. |
| `status` | Enum | `running`, `succeeded`, or `failed`. |
| `started_at`, `ended_at` | Timestamp; end nullable | Run start and end times. |
| `elapsed_seconds` | Nonnegative number or null | Measured run duration; null until finished. |
| `model` | Object or null | Model and runtime settings; null for model free reprocessing. |
| `versions` | Object | Software, prompt, tool, and preparation versions. |
| `execution_policy` | Object | Contains `max_tool_calls` (positive integer) to bound the agent's tool loop. No automatic retry settings. |
| `tool_artifact_paths` | List of strings | Artifact record paths created or reused by this run, including failed tool calls. |
| `model_calls` | List of model call objects | All model requests made during this run, including failed requests. |
| `tool_trace_path` | String or null | Saved tool requests and results; null if no tools were called. |
| `error` | String or null | Final failure explanation. |

The model object records the requested model and the software serving it. Use null for unknown deployment details.

| Model field | Type | Description |
| --- | --- | --- |
| `name` | String | Exact model identifier requested. |
| `revision` | String or null | Exact weight revision or digest (model file checksum). Required for local reuse; null if a hosted provider does not disclose it. |
| `execution_mode` | Enum | `local` or `hosted_api`. |
| `api_service` | String or null | API service, such as `hugging_face`; null for local Ollama. |
| `provider` | String or null | Selected hosting provider; null for local execution. |
| `endpoint` | String | API base URL, without credentials or secret query parameters. |
| `runtime` | String or null | Software serving the model: `ollama` locally, or the hosted runtime if disclosed. |
| `runtime_version` | String or null | Serving software version, when available. |
| `quantization` | String or null | Weight precision/quantization format, when available. |
| `context_limit` | Positive integer or null | Configured or provider documented context limit. |
| `generation_settings` | Object | Requested and supported generation settings. |
| `runtime_options` | Object | Other recorded serving settings; empty if unavailable. |
| `hardware` | String or null | Local chip and memory, or disclosed hosted hardware. |

| Generation setting | Type | Meaning |
| --- | --- | --- |
| `temperature` | Nonnegative number or null | Controls randomness in response generation. |
| `top_p` | Number greater than 0 and at most 1, or null | Limits which candidate tokens are considered during sampling. |
| `seed` | Integer or null | Initializes random sampling where supported. |
| `max_output_tokens` | Positive integer | Requested output limit. |

Use null for settings the service cannot control. Record supported settings; sending an unsupported parameter does not establish that it was applied.

The `versions` object records `code_commit` (Git commit ID), `code_dirty` (Boolean for uncommitted changes), `prompt_version`, `tools_version`, `preparation_version`, and `model_client_version` (API client software/version). Use null for values that do not apply.

**Model calls and tool activity**

Record `model_calls` and `tool_trace_path` directly under the run. Each model call contains `call_id`, `input_tokens`, `output_tokens`, and `response_path`. Token counts are nonnegative integers or null if unavailable. The response path is null when no response was returned. A failure is described in the run's `error` field.

The tool trace records tools, arguments, results, and errors. Image/OCR traces also record source and page IDs, artifact IDs, tool duration, and reuse. Save image inputs and settings with model requests so the received material can be checked later.

**Time and token totals**

- Measure elapsed time from run start to finish, including model loading started within the run, calls, tools, validation, and draft corrections. Hosted time includes network and provider waits; undisclosed GPU or startup time remains unknown.
- Exclude initial automatic preparation and human review. Include image rendering and OCR requested within the run. Tool time is already part of run duration; do not add it again.
- Record `model_loaded_at_start` (Boolean or null) in the run's model `runtime_options`.
- Include every model call recorded for the run, including model calls made by OCR tools. If a required duration or token count is unavailable, report the total as null.
- Keep available traces and usage after interruption. The time at which a run is later recovered cannot establish how long it actually processed.

### 6.7 Configuration result

This record identifies the runs, output, and review used for one E or E+V result.

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

For runtime and token totals:

- E includes the extractor run and separately linked processing runs.
- E+V includes that same extractor run, verification, and separately linked processing runs.
- Count each run ID once per configuration. Calls and tool work inside a run are already included in its totals. Apply Section 6.6's timing rules.

If verification fails, E+V is failed and the successful E result remains available.

### 6.8 Expert reference and assessment

The expert reference uses the extraction content format with `extraction_method: expert` and `run_id: null`. One expert supplies the references and assessments, so expert IDs are not required. Issue history identifies expert, model, and software actions through `actor`.

| Reference set field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `reference_set_id` | String | Reference set ID. |
| `plan_id` | String | Document version ID. |
| `initial_snapshot_id` | String | Reference saved before model outputs are seen. |
| `final_snapshot_id` | String or null | Shared final reference; null until reference review is complete. |
| `revisions` | List | Each revision contains `record_ids`, `reason`, and `evidence`. |

Revision `record_ids` are a list of strings; `reason` is a string; `evidence` uses the quotation and page format.

1. Save the initial reference before the expert sees model outputs.
2. Match each output to that reference to identify additions.
3. Check additions and other corrections, then save one shared final reference.
4. Score both configurations against the final reference. Count additional records against the initial reference.

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

The lists above contain the objects below. Their IDs refer to the snapshots in the assessment record.

| Object | Required fields |
| --- | --- |
| Initial match | `reference_record_id` (string), `output_record_ids` (list of strings; empty if omitted). |
| Record score | `reference_record_id`, `output_record_ids`, `score` (0, 0.5, or 1), and `reason` (string). Omitted items have no output IDs and score 0. |
| Additional record | `additional_id`, `output_record_ids`, `support_status` (`supported`, `unsupported`, or `undetermined`), `final_reference_record_ids` (list), `reason`, and `evidence`. |
| Quotation check | `record_id`, `evidence_index` (zero based integer), `claim_fields` (nonempty list of field path strings), `supports_claim` (Boolean or null), `page_checks` (list), and `reason`. Each page check contains `page_number` and `correct` (Boolean or null). |
| Issue assessment | `issue_id`, `genuine` (Boolean or null), `verifier_resolution_supported` (Boolean or null), and `reason`. |
| Unflagged problem | `finding_id`, `target_key`, `output_record_ids`, `reference_record_ids`, `concerns` (list of strings), and `evidence`. |

Unless stated otherwise, IDs and reasons are strings; plural ID fields are lists of strings. Evidence uses the quotation and page format. A null judgment is pending.

Match records by meaning. One reference item may match several split output records; one combined output may cover several reference items. Credit each reference item once, regardless of duplicates.

Count split or duplicate outputs about the same new item as one addition. Wording differences alone do not make an addition. A supported addition is distinct information present in the source but missing from the initial reference. Assess its detailed correctness separately against the final reference.

For each quotation use, check all claims assigned in `claim_fields`, including qualifications. Mark support true only if all are supported. Check each cited page separately. A quotation repeated in different records counts as separate uses. Flag missing evidence as an extraction/review problem; quotation rates count supplied evidence only.

A genuine issue identifies a real error, uncertainty, source problem, or processing problem needing attention. Group missed concerns once per affected target in `unflagged_problems`. A record with both a valid flag and a different missed concern contributes once to each measure.

Complete assessment covers every final reference record, supplied quotation, page reference, and issue. Pending judgments make the corresponding rates null; report them as unassessed. Label partial subtotals with review coverage. Never score pending judgments as zero. Retain failed runs without output in operational results, leave quality unassessed, and report counts of assessed and failed plans.

### 6.9 Calculated metric record

Python calculates one metric record for each measure and grouping.

| Field | Type | Description |
| --- | --- | --- |
| `schema_version` | Integer | Format version. |
| `metric_id` | String | Stable measure name from Section 8. |
| `phase` | Enum | `pre_expert` or `post_expert`. |
| `stage` | Enum | `extractor`, `verifier`, `configuration_total`, or `expert_assessment`; identifies the stage summarized. |
| `category` | Enum | `operational_performance`, `issue_handling`, `verifier_contribution`, `expert_review_workload`, `extraction_quality`, or `evidence_support`. |
| `plan_id` | String or null | Null only when summarizing several plans. |
| `configuration` | Enum | `extractor_only` or `extractor_verifier`. |
| `content_category` | String or null | Extraction list name for category scores; otherwise null. |
| `issue_category` | String or null | Issue type for a count or rate by type; otherwise null. |
| `aggregation` | Enum | `per_plan`, `mean_across_plans`, or `pooled`. |
| `value` | Number or null | Calculated result; null if unavailable or not applicable. |
| `unit` | Enum | `seconds`, `tokens`, `count`, or `percent`. |
| `numerator`, `denominator` | Number or null | Raw values for a ratio; null for a simple count or total. |
| `contributing_plans` | Integer | Number of plans represented. |
| `status` | Enum | `complete`, `not_applicable`, or `incomplete`. |
| `reason` | String or null | Explanation for an unavailable result. |
| `input_ids` | List of strings | Result, run, review, or assessment IDs used. |

For percentages, `value = numerator / denominator × 100`. A zero denominator gives null with `status = not_applicable`; counts can be zero.

For a mean across plans, use the sum of valid per plan percentages as numerator and the number of those plans as denominator. Do not multiply this mean by 100 again. Keep its supporting per plan records.

A failed run supplies a failure count. Unavailable quality measures have incomplete status and are not scored zero.

### 6.10 Document registry

`data/registry/plans.json` contains `schema_version` (integer) and `plans` (list). Each plan entry has these fields:

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

Each edit event contains `edited_at` (timestamp), `changes` (nonempty list), and `reason` (string or null). Each change records `field` (string), `previous_value`, and `new_value` using the field's type: string, Boolean, or null.

Editable fields are `plan_title`, `source_url`, `date_accessed`, `study_set`, and `enabled`. Dates use date strings and all values follow their field definitions. PDF changes follow Section 4.1's version rules.

Keep metadata used by earlier runs in their source and extraction records. After a registry correction, create a new source record for future processing; correcting an existing output requires a new snapshot. Development plans cannot enter the comparison set. To exclude a registered plan, disable it and record the reason in edit history, preserving its earlier records.

This fictional registry entry links to Section 6.4. The checksum is a placeholder; registration calculates it from the PDF. Referenced files have not been created.

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
    "date_accessed": "2026-10-24",
    "enabled": true,
    "supersedes_plan_id": null,
    "source_record_paths": ["data/processed/plan_0001/source_0001.json"],
    "metadata_history": []
  }]
}
```

Processing status is calculated from the source, settings, and run records under Section 4.2; the registry has no `processed` flag.

### 6.11 Execution profiles and batch records

List profiles in `configs/profiles.json`, tracked in Git. Its root has `schema_version` (integer) and `profiles` (list). Each entry has a unique `profile_id` for one extractor, verifier, or reprocessing setup. Start with Section 5's candidate models and settings chosen during development.

**Adding and selecting profiles**

1. Copy an entry, give it a new `profile_id`, and edit its model, prompt, or other settings.
2. Select profile IDs through the CLI for a batch. It lists available entries by ID and role.
3. Python validates entries and files, reads available model and software versions, and calculates checksums. Resolve invalid or missing settings before processing; keep unknown hosted details null under Section 6.6.
4. Save the selected settings and detected details in `runs/profiles/<profile_id>/<profile_sha256>.json`. Runs link it through `profile_record_path`; batches record the selected IDs.

Edit settings directly in the JSON file. Keep used entries and earlier run records unchanged; use a new profile ID for changes. Adding another entry does not change an existing profile's checksum.

The complete saved record contains these fields. The last column shows which are edited in JSON and which Python supplies.

| Profile field | Type | Description | How it is set |
| --- | --- | --- | --- |
| `schema_version` | Integer | Profile format version. | JSON root; Python checks version support. |
| `profile_id` | String | Human readable versioned identifier. | JSON entry; must be unique. |
| `stage` | Enum | `extractor`, `verifier`, or `reprocessing`. | JSON entry. |
| `extraction_schema_version` | Integer | Extraction format and coding rule version. | JSON entry; Python checks schema availability. |
| `preparation_version` | String | Required source preparation procedure. | JSON entry; Python checks procedure availability. |
| `context_strategy_version` | String | Whole document input and context rules. | JSON entry; Python checks strategy availability. |
| `prompt_paths` | Ordered list of strings | Project relative prompt/template file paths in loading order; nonempty for model stages and empty for model free reprocessing. | JSON entry. |
| `prompt_sha256` | String | Checksum of the complete selected prompt/template files. | Python, from ordered paths and contents. |
| `tools_sha256` | String | Checksum of tool definitions and implementation. | Python, from enabled tools. |
| `code_sha256` | String | Checksum of the processing code, including uncommitted changes if used. | Python, from code files. |
| `model` | Object or null | Complete model settings from Section 6.6; null for model free reprocessing. | JSON settings plus detected details listed below. |
| `software_versions` | Object | Names and versions of the runtime, client, and relevant processing libraries. | Python, from installed software and model services. |
| `execution_policy` | Object | Tool call limit from Section 6.6. | JSON entry. |
| `document_tool_settings` | Object | Enabled image/OCR routes and frozen settings defined below. | JSON tool settings plus detected OCR version. |
| `timing_policy_version` | String | Rules for loading models and measuring stages. | Python, from the workflow's timing rules. |
| `profile_sha256` | String | Checksum of all other profile fields. | Python, after all fields are complete. |

Editable entries contain the fields marked JSON above, with these nested objects:

- `model`: `name`, `execution_mode`, `api_service`, `provider`, `endpoint`, `context_limit`, `generation_settings`, and configured `runtime_options`, using Section 6.6's types. Python adds `revision`, `runtime`, `runtime_version`, `quantization`, and `hardware`.
- `document_tool_settings`: all fields below except `ocr_version`, which Python supplies.

Python saves calculated checksums and detected versions with runs; they are not entered manually.

Calculate checksums with SHA-256. For structured inputs, use sorted JSON keys and consistent UTF-8 serialization, meaning a repeatable conversion of the values to bytes. Exclude credentials. Resolve local model tags to their actual model digest before calculating the profile checksum. Save details such as whether a model was already loaded in the run record.

Before a batch, compare a used entry, its prompt files, code, tools, and available deployment details with its saved record. Changes require a new profile ID or restoration of the recorded setup before running or reusing results. Use the selected entry's settings; keep earlier records unchanged.

| Document tool setting | Type | Meaning |
| --- | --- | --- |
| `image_input_enabled` | Boolean | Enable only after testing the model and serving setup. |
| `ocr_enabled` | Boolean | Whether the OCR tool is enabled. |
| `image_format` | Enum | `png`. |
| `image_render_dpi` | Positive integer | Page image resolution in dots per inch. |
| `ocr_engine` | String or null | OCR software; null when disabled. |
| `ocr_version` | String or null | Detected OCR version; null when disabled. |
| `ocr_language` | String or null | OCR language; null when disabled. |

Fix the same tool capabilities and settings for both agents before comparison. Include them in the profile checksum.

The `run_key` is a checksum of the processing step, plan ID, source ID, prepared text checksum, profile checksum, and input snapshot ID. Initial extraction has null input. Changing verifier input changes its key. The key identifies matching work; separate run IDs identify repeats.

Reuse requires valid referenced files and matching source checksums and profiles. For hosted models with an unknown revision, a matching key cannot confirm an unchanged deployment. Limit reuse to the same declared comparison batch; use a new batch and profile for a new assessment period.

Store batch requests under `runs/batches/<batch_id>.json`, using Section 4.2's definitions.

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
| `retry_failed`, `force_rerun` | Booleans | `retry_failed` retries failed or missing stages while reusing valid completed work. `force_rerun` repeats every stage needed by the selected configurations. They cannot both be true. |
| `entries` | List | Decisions and result links for each requested plan/configuration. |

Each entry contains `plan_id`, `configuration`, `source_id` (string or null), `decision` (`run`, `reuse`, `skip`, or `blocked`), `reason` (string or null), and `result_id` (string or null until linked). Use the ID and configuration definitions above. Read processing status from linked source and result records.

Save selection decisions before model calls. Link result IDs when scheduling work and retain the batch file. Each result identifies one fixed source and its runs. Reuse retains original measurements, as defined in Section 4.2.

## 7. Issue handling

### Unit and history

Count one issue per affected record. An action with a wrong status and deadline has one issue with two concerns. Add later concerns about that record to the same issue.

Proposed grouping also includes one issue per empty category and one per source problem. Give each suspected omission a separate target key; keep that key if a record is later added. Confirm these extensions before comparison.

Partial corrections leave the issue open. Reopen a closed issue for new concerns and retain its earlier resolution. Section 6.5 defines the history fields.

### Categories and status

Assign one primary category per issue for percentages by type. Retain all concerns. Section 6.5 defines categories and statuses.

Route extractor issues as follows:

- In E+V, content issues enter `pending_verification`.
- In E, content issues enter `pending_expert_review`.
- Retryable source or processing problems enter `pending_reprocessing` in either branch.

Start source issues for known preparation gaps, with page references and related pages grouped under one problem. Add gaps the agent finds later. Record tool calls and outcomes in issue history. Resolve the issue only after checking that returned material is usable and all concerns are addressed. Attribute resolution to the confirming `extractor` or `verifier`, or to `pipeline` for a separate processing step.

Use tools within the run's tool call limit. Refer remaining gaps for expert review when available recovery options have been used; otherwise keep `pending_reprocessing`. Save partial extractions with unresolved issues. Unreadable material is not confirmed absence.

Resolve an issue when all concerns are addressed or source checking confirms no correction is needed. Routine missing details and unspecified scope alone do not create issues. Check an empty category before confirming absence.

The verifier may correct a record or confirm absence after checking the relevant readable source. A justified absence confirmation is a supported resolution; it need not be an error correction. Expert review coverage follows Section 6.5.

Distinguish initial issues from new verifier issues. Save verifier explanations separately from later expert judgments.

## 8. Evaluation measures

Calculate measures per plan and configuration. Sections 6.8 and 6.9 define assessment records, missing judgments, and zero denominators.

### 8.1 Before expert review

| Category | Metric | Calculation | Data used |
| --- | --- | --- | --- |
| Operational performance | Total runtime (`runtime_seconds`) | Sum `elapsed_seconds` over the distinct stage run IDs linked to the configuration result. | Configuration result and stage runs. |
| Operational performance | Tokens used (`input_tokens`, `output_tokens`, `total_tokens`) | Sum input and output token counts across every model call in the linked runs. Report input, output, and total. | Run `model_calls`. |
| Operational performance | Failed runs (`failed_runs`) | Per plan: 1 if the configuration result failed, otherwise 0 once finished. Across plans: sum these indicators. Keep earlier failure records when manual retries produce new results. | Configuration result status. |
| Issue handling | Issues recorded (`issues_recorded`) | Count distinct `issue_id` values in the stage's review snapshot, including resolved issues. | Review snapshot. |
| Issue handling | Open issues (`open_issues`) | Count issues with `status != resolved`. | Review snapshot. |
| Issue handling | Issue count and proportion by type (`issues_by_type`, `issue_type_percent`) | Count issues of primary type k; percentage = that count ÷ all recorded issues × 100. Label any separate summary restricted to open issues explicitly. | `issue_category` in the same review snapshot. |
| Verifier contribution | Initial issues marked resolved (`initial_issues_resolved_percent`) | Initially open extractor issues marked resolved by the verifier at the final stage before expert review ÷ all initially open extractor issues × 100. | Baseline issue IDs and states, final verifier review, and history. |
| Verifier contribution | Initial issues referred to experts (`initial_issues_referred_percent`) | Initially open extractor issues whose final status is `pending_expert_review` ÷ all initially open extractor issues × 100. | Same baseline and final review. |
| Verifier contribution | Newly raised issues (`new_issues`) | Count issue IDs in the verifier review that were absent from the baseline extractor review. | Baseline and verifier reviews. |
| Expert review workload | Issues referred for expert review (`expert_referrals`) | Count final issues with `status = pending_expert_review`, including newly raised issues. | E or E+V snapshot saved before expert review. |
| Expert review workload | Referred issue count and proportion by type (`referrals_by_type`, `referral_type_percent`) | Count referred issues of type k; percentage = that count ÷ all referred issues × 100. | The referred issue subset. |

The baseline is the shared extractor review before routing issues to E or E+V. Use final states before expert review: reopened issues remain open and pipeline resolutions do not count as verifier resolutions. Verifier measures apply only to E+V.

Keep extractor resolved issues in counts and history. Exclude them from the initially open issues used for verifier resolution and referral percentages. Identify new verifier issues against all baseline IDs.

Resolved and referred percentages may total less than 100% because issues can remain pending. New verifier issues are excluded from the initially open denominator.

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

The proposed verifier resolution percentage needs review before comparison. Count final `resolved` issues with `resolved_by = verifier`, including initial and new issues. Exclude reopened issues. Interpret this measure with extraction and evidence scores and Section 7's resolution rules.

Section 6.8 defines reference revisions, matching by meaning, addition grouping, and evidence checks. Report additional record counts and support rates with extraction scores: unsupported additions do not lower scores based on reference records.

### 8.3 Scoring rubric and reporting

| Score | Definition |
| --- | --- |
| 1 | All required substantive information is correct, with no unsupported substantive additions. |
| 0.5 | Some substantive information is correct, but at least one required part is incorrect or missing. |
| 0 | No substantive information is correct, or the reference record was omitted entirely. |

Accept different wording with equivalent meaning. A correctly identified action with a wrong status scores 0.5. Correctly recorded unavailable information does not reduce the score. Score evidence separately from content.

The extraction quality denominator counts content records across the five final reference lists. It excludes plan metadata, individual target pairs, evidence objects, and issue concerns as separate records.

For ten reference records with six fully correct, two partial, and two omitted, partial credit accuracy is `(6 + 2 × 0.5) / 10 = 70%`; the fully correct rate is `6 / 10 = 60%`. Report the underlying counts too.

Score each plan and content category, keeping E and E+V paired by plan. The proposed overall summary is the mean of valid per plan percentages, with the number of contributing plans. Exclude zero denominators from the mean and report them as not applicable. Pooled counts may be reported separately and labeled. Confirm this summary rule before comparison.

One expert codes and assesses the records. Report this limitation; agreement between experts cannot be estimated. If another expert joins, define checking and disagreement procedures during development, add assessor identifiers, and retain the decisions.

## 9. Development records and reproducibility

Development records describe problems, changes, reasons, observed results, and remaining questions. Use them to explain useful tools, model limitations, and expert intervention.

Before comparison, fix and version schemas, prompts, model settings, serving setup and provider, tools, document processing, tool call limits, and evaluation rules. Save run settings in Section 6.11's profiles. Label new comparison runs separately and preserve earlier results when these choices change.

Check page numbering, required fields, IDs and links, issue status changes, saved versions, calculations, and failures. Expert assessment checks factual accuracy and whether evidence supports claims.

Keep sources, profiles, software and model versions, and processing history for inspection and repeat runs. Outputs may vary under the same settings.

## 10. Implementation and repository structure

| Location | Purpose |
| --- | --- |
| `src/` | Reusable Python modules for the workflow, model adapter, MCP tools, expert assessment, and analysis, plus the CLI that calls them. |
| `notebooks/` | Inspection of saved outputs, comparisons, research tables, and figures using the shared Python modules. |
| `schemas/`, `prompts/`, `configs/` | Versioned data specifications, instructions, and settings; `configs/profiles.json` lists the available profiles. |
| `data/registry/plans.json` | Registered document versions and links to preparation records; tracked in Git. |
| `tests/` | Checks of processing, validation, issue history, and calculations. |
| `data/raw/`, `data/processed/` | Source PDFs and prepared page text. |
| `models/`, `runs/`, `artifacts/`, `logs/` | Local weights, stage runs, batch records, extraction/review snapshots, assessments, metrics, and diagnostics. |
| `data/release/`, `reports/` | Selected dataset releases and study summaries. |

Track code, settings without secrets, registry metadata, and project documents in Git. Exclude local instructions, credentials, model weights, source/prepared files, and generated runs. Back up excluded research files and define where releases will be stored.

Proposed file layout for one plan is below. Image/OCR paths are optional and unused in Section 6.4's text only example. No processing files or folders have been created.

```text
data/registry/plans.json
data/raw/plan_0001.pdf
data/processed/plan_0001/source_0001.json
data/processed/plan_0001/page_0001.txt
configs/profiles.json
runs/batches/batch_0001.json
runs/profiles/local_extractor_v1/<profile_sha256>.json
runs/plan_0001/stages/run_extract_0001.json
runs/plan_0001/responses/call_0001.json
runs/plan_0001/artifacts/artifact_page_0001.json
runs/plan_0001/artifacts/page_0001.png
runs/plan_0001/artifacts/artifact_ocr_0001.json
runs/plan_0001/artifacts/page_0001_ocr.txt
runs/plan_0001/snapshots/snapshot_extract_0001.json
runs/plan_0001/reviews/review_extract_0001.json
runs/plan_0001/results/result_e_0001.json
runs/plan_0001/references/reference_set_0001.json
runs/plan_0001/assessments/assessment_0001.json
runs/plan_0001/metrics/metrics_0001.json
```

Implement registration and preparation, local extraction, verification and issue history, expert assessment, then analysis. Sections 2 and 5 define study sets and hosting development. Expand after comparison analysis and workflow selection.

## 11. Open implementation decisions

- Final local models and roles after testing Section 5's candidates; quantization, context settings, and Ollama version.
- Hosted Hugging Face models, provider, and serving setup for comparison.
- Context settings that fit the full plan, instructions, verifier input, and expected output on the selected models.
- Page rendering and OCR software, preparation gap checks, tested image support, and shared recovery settings.
- Review of all proposed JSON records, issue grouping and categories, and expert assessment format.
- Tool call limits, token reporting for each serving setup, and assessment of incomplete outputs.
- Expert matching examples, assigning claims to quotations, the summary rule, and optional second expert procedures.
- Expansion review coverage, release format, PDF redistribution permissions, and artifact storage.
