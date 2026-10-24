# heat adaptation LLM dataset

**Study design and technical implementation — draft**

**Last updated:** 2026-10-24

This document describes the study workflow, proposed system components, data records, and evaluation measures. Models, software packages, and detailed data schemas will be selected during development.

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

The detailed fields and coding rules in the project proposal remain the starting specification. Each record will include exact supporting passages and PDF page numbers. The first PDF page is page 1, regardless of printed labels. Links between records require source support.

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

## 6. Data records

The first implementation will use JSON files with table exports for expert assessment. Each processing stage will save a separate version, or **snapshot**, linked to its source and run.

| Record | Required information |
| --- | --- |
| Source record | Plan ID, collection metadata, study set, source URL, access date, page count, preparation version, and file checksum identifying the document. |
| Extraction snapshot | Plan ID, run ID, stage, schema version, metadata, and the five record lists with evidence. |
| Review record | Issues and current expert-review status linked to an extraction snapshot. |
| Run record | Configuration, stage, parent extractor run, model/settings, source/prompt/tool versions, timing, tokens, attempts, and outcome. |
| Issue history | Affected record or category, concerns, stage first detected, status changes, responsible actor, and resolution explanations. |
| Expert reference | Initial and revised expert-coded records, evidence, and reasons for revisions. |
| Expert assessment | Output assessed, reference matches, record scores, additional-record judgments, evidence checks, and assessment of flags and resolutions. |

The extraction, run information, and expert assessment will remain separate. The proposal's `review` object will be revised to link the extraction to its review record and issue history. Exact fields and file organization remain to be defined.

## 7. Issue handling

### Unit and history

Multiple problems within one extracted record will count as one issue. For example, an action with an incorrect status and deadline has one issue describing both problems. Further concerns about that record will be added to the same issue.

Each issue will identify:

- Its stable ID and affected record, plan, or answer category.
- The problem type and affected fields.
- The stage at which it was first detected.
- Its status and changes in status.
- The actor responsible for each change and the supporting explanation.

Partial fixes will be recorded while the issue remains open. A closed issue may be reopened, with its earlier resolution retained. Rules for grouping source problems, empty categories, and omitted records will be settled during development.

### Categories and status

The proposal's issue categories will be retained initially: no records found, unclear meaning, conflicting evidence, source issue, and extraction-process issue. A bundled issue may concern several problem types. The reporting rule for assigning one primary type or multiple types remains open.

Statuses will distinguish pending verification, pending reprocessing, pending expert review, and resolved. Resolutions will identify whether they came from the verifier, pipeline, or expert. Verification does not count as expert review.

The verifier may resolve an issue through a supported correction or by confirming that a category is not reported after checking the relevant readable source. Confirmation of absence is not necessarily an error correction.

Initial extractor issues and newly raised verifier issues will remain distinguishable. A verifier-reported resolution and the expert's judgment of that resolution will be stored separately.

## 8. Evaluation

### Before expert review

These measures describe execution and reported issue handling.

| Category | Measures |
| --- | --- |
| Operational performance | Total runtime per plan/configuration, tokens used, and failed runs. |
| Issue handling | Number of issues, counts and proportions by type, and status before and after verification. Distinguish recorded issues from issues still open. |
| Verifier contribution | Initial issues marked resolved by the verifier ÷ total initial extractor issues; initial issues left unresolved and referred to experts ÷ the same denominator. Report newly raised issues separately. |
| Expert review workload | Number of referred issues and counts and proportions by type. This measures referrals rather than expert time. |

Runtime and tokens for E+V will include extraction and verification, with stages recorded separately. Retry costs will be included. Timing rules will specify treatment of preparation, model loading, tools, validation, and retries.

A failed run is one that does not produce an acceptable stage output within the agreed limits. Attempts and final outcomes will be retained. A failed verifier run will remain a failed E+V result even if the extractor succeeded. Unavailable token counts will not be recorded as zero.

### After expert review

These measures assess the preserved model outputs against the expert reference and source.

| Category | Measures |
| --- | --- |
| Extraction quality | **Record accuracy with partial credit:** sum of reference-record scores ÷ total final reference records. **Fully correct record rate:** reference records scored 1 ÷ total final reference records. |
| Additional records | Number of extracted records absent from the initial expert reference; supported additional records missed by that reference ÷ total additional records. |
| Evidence support | Quotations supporting their associated claims ÷ total quotation uses; correct page references ÷ total page references provided. |
| Issue handling | Genuine problems among flagged issues ÷ total flagged issues; number of genuine problems not flagged. |
| Verifier contribution | Expert assessment of whether reported resolutions were justified, alongside changes in extraction quality and evidence support. |

Additional records are part of the extraction-quality assessment. They may be supported items missed by the expert or unsupported additions. An incorrect detail within a matched record will be assessed within that record.

Experts will match records by meaning, allowing different wording. If either configuration identifies a valid item absent from the initial reference, the reference will be revised and both configurations assessed against the same final version. Additional-record measures will remain tied to the initial reference.

### Record scoring

| Score | Definition |
| --- | --- |
| 1 | All required substantive information is correct, with no unsupported substantive additions. |
| 0.5 | Some substantive information is correct, but at least one required part is incorrect or missing. |
| 0 | No substantive information is correct, or the reference record was omitted entirely. |

An action correctly identified but assigned the wrong implementation status receives 0.5. All partial records receive the same credit. The strict measure awards credit only to records scored 1.

Correctly recording that information is unavailable will not reduce the score. For ten reference records with six fully correct, two partial, and two omitted, partial-credit accuracy is 70% and the fully correct rate is 60%.

Unsupported additional records do not reduce these reference-based scores. Additional-record counts and support rates must therefore accompany them. Evidence support will be assessed separately from record-content correctness.

### Assessment rules to finalize

Before comparison, define:

- Matching rules for duplicates and records split or combined differently.
- Examples of substantive correctness and partial credit.
- Support criteria for additional records with imperfect details.
- How quotations are assigned to claims when several passages support a record.
- Which uncertainties, source problems, and processing failures count as genuine flags.
- How unflagged problems are counted consistently with record-level issue grouping.
- Treatment of incomplete runs and aggregation across plans and categories.

A zero denominator will be reported as not applicable. Results will retain underlying counts and be reported by plan and extraction category. The second-expert checking procedure, disagreement resolution, and assessment order will be established during development.

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
- Detailed schemas, review-object links, and expert assessment format.
- Issue grouping beyond existing records and assignment of issue types.
- Timing boundaries, token reporting, retry limits, and failure treatment.
- Record matching, evidence assessment, aggregation, and second-expert procedures.
- Expansion review coverage, release format, document redistribution permissions, and artifact storage.
