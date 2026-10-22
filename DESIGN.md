# Heat adaptation extraction workflow: technical design

**Status:** First draft for discussion; not an implemented system.

**Date:** 2026-10-22

**Basis:** The project proposal dated October 18, 2026, and subsequent design discussions.

This document distinguishes agreed study decisions from proposed implementation choices. Technical choices remain subject to review before implementation. The structured change log remains empty until entries are explicitly requested.

## 1. Purpose and scope

The primary contribution is practical knowledge about developing an expert–LLM extraction workflow using open-weight models and tools exposed through a local Model Context Protocol (MCP) server. The study will document setup, useful tools, limitations, failures, expert intervention, and the accuracy of the resulting records.

A focused comparison will examine an extractor alone (E) and the same extractor followed by a verifier using a different open-weight model (E+V). A curated extraction dataset is an important output. Fine-tuning a heat adaptation assistant is a possible future use, not a deliverable of this study.

### Agreed study decisions

- Develop the workflow on two plans, separate from ten comparison plans.
- Prepare an independent expert reference for the comparison plans without exposing experts to model outputs during initial coding.
- Use exactly the same saved extractor output as the starting point for E and E+V.
- Require the verifier to review both flagged issues and the complete extraction, including possible omissions.
- Group multiple problems concerning one affected extraction record into one issue. An action with an incorrect status and deadline has one issue describing both problems.
- Score extraction using both partial credit and a strict fully correct record rate.
- Separate measurements available before expert review from findings requiring expert assessment.
- Preserve extraction outputs, issue histories, run information, and expert assessments separately.
- Treat findings as evidence about the tested workflow and model pairing. Broader conclusions about verification, open-weight models, or MCP remain practical observations rather than controlled comparisons of those technologies.

The original expansion target was 50–100 unique plans in total. Expansion can be reduced to protect completion and analysis of the core study. One month is a planning preference, not a fixed deadline. Neither the expansion size nor a winning configuration is predetermined.

## 2. Source documents and extraction content

Eligible plans are final, publicly available government or public-agency documents in English, published or updated in 2010 or later, with recent versions prioritized. They must concern heat adaptation directly, or include a dedicated heat section with at least one heat-specific action. The full document must have readable text and stable PDF pages.

Each document version has a distinct plan identifier. Its extraction contains plan metadata and five lists:

1. Goals, including stated targets and deadlines.
2. Actions, including reported implementation status.
3. Monitoring and evaluation mechanisms.
4. Expected or reported benefits and impacts.
5. Financial costs and other resource requirements.

The proposal's detailed fields and coding rules are the starting point, not replaced by this architectural draft. Records retain exact supporting passages and PDF page numbers, with the first PDF page numbered 1 regardless of printed page labels. Related goals and actions are linked only when the source supports the relationship.

Unavailable values remain `null`, empty lists, or the applicable unspecified category. Routine missing details do not automatically create issues. An entirely empty answer category requires checking; an empty category alone does not prove the plan contains no relevant information.

## 3. Proposed architecture

Use a small Python application to coordinate a local model runtime and a local MCP server. Python is proposed as the main implementation language to keep document processing, validation, and analysis in one environment. Exact packages, model runtime, models, and versions have not been selected.

| Component | Responsibility | Why it is separate |
| --- | --- | --- |
| Document preparation | Convert each eligible PDF into page-preserving text and a collection record. | Source-reading failures can be distinguished from extraction errors. |
| Pipeline controller | Run stages in order, enforce limits, validate outputs, save artifacts, and record measurements. | The model does not control experiment scheduling or overwrite history. |
| Model adapter | Send messages and tool definitions to the selected model runtime; receive answers, tool requests, and usage information. | The workflow can change models without changing its research records. |
| MCP client | Connect the controller to the MCP server and execute permitted tool requests. | Model tool requests must be translated into actual tool calls. |
| MCP server | Provide document inspection and deterministic checking tools. | Both configurations use a documented tool interface. |
| Extractor and verifier | Perform their assigned reasoning and produce structured outputs. | Roles and outputs remain distinguishable. |
| Expert assessment files | Hold the independent reference, output assessments, and adjudications. | Evaluation information must not leak into model inputs. |
| Analysis | Derive the agreed measures from saved artifacts. | Reported metrics can be checked against their underlying records. |

An agent here means a model operating in a bounded loop: receive instructions and source context, request tools, inspect results, and submit a final structured answer. It does not imply an independently running service or an unrestricted autonomous system.

MCP supplies a protocol for exchanging context and invoking tools; it does not select models, manage their context, or define the extraction workflow. Those responsibilities belong to the controller and model adapter. This follows the distinction in the [official MCP architecture documentation](https://modelcontextprotocol.io/docs/2026-07-28/learn/architecture).

For the first implementation, propose a local MCP subprocess connected through standard input/output, often called **stdio**. This avoids deploying a separate web service. The official [Python SDK transport documentation](https://py.sdk.modelcontextprotocol.io/client/transports/) describes this connection option. SDK and protocol versions must be pinned together when implementation begins.

## 4. Model selection and document context

Select one extractor and a different verifier during development, considering available hardware, readable context capacity, structured-output reliability, tool use, and runtime. Open-weight does not automatically mean a model can run on the available computer or use the chosen tool interface reliably.

Ollama is one candidate runtime because it documents a tool-calling interface, but it is not selected in this draft. In a tool-calling loop, the application executes a requested tool and returns its result to the model; the request alone does not execute anything. See the [official Ollama tool-calling documentation](https://docs.ollama.com/capabilities/tool-calling). Compatibility must be demonstrated with the actual model/runtime combination.

Record the model identifier and revision or digest, weight precision or quantization, runtime version, generation settings, configured context limit, and hardware. Quantization means storing model weights at reduced numerical precision to reduce memory requirements. These settings can affect behavior and must remain fixed during the comparison.

Plans are supplied directly; no document-collection search system or vector database is proposed. Each agent receives the schema, instructions, plan identifier, and page-marked source text when it fits. Page tools allow further inspection of the supplied plan.

For a document that does not fit with room for instructions, tools, and output, develop a documented page-batching procedure. A page batch is a bounded group of pages processed in sequence. It requires coverage tracking, overlap rules where needed, and merging of repeated records. Never silently truncate a plan or treat a keyword search as proof of complete coverage. Choose and freeze the context strategy on the development plans before the comparison.

## 5. Proposed MCP tools

Begin with a small tool set. Add tools only when development evidence identifies a need.

| Proposed tool | Input and output | Limit of the check |
| --- | --- | --- |
| List plan pages | Given a plan identifier, return page count and readable-page information. | Readable text does not establish correct extraction. |
| Read page range | Given a plan identifier and bounded PDF page range, return page-marked text. | The model still has to interpret the text. |
| Check quotation | Given a quotation and claimed pages, return text-match results and source context. | A matching quotation may not support the claim. |
| Validate extraction | Check required fields, allowed values, unique IDs, page bounds, and valid links. | Structural validity does not establish factual correctness or completeness. |

A within-plan text search may be added if it helps navigation. It must not replace full document coverage or become a separate collection-retrieval system.

Tools should access only the registered source plan and submitted candidate records, not expert reference or evaluation files. Ordinary application logic will save outputs; agents do not need unrestricted file-writing or shell tools. Source text is evidence to analyze, not instructions to execute.

## 6. End-to-end workflow

### 6.1 Collect and prepare

Record official source URL, access date, jurisdiction, document version, study set, local source location, and a file checksum. A checksum is a fingerprint used to identify the exact file processed.

Extract text by PDF page, retain the original, and inspect preparation quality. Keep the original and any normalized text distinguishable. Any normalization used for quotation matching must be documented and preserve substantive wording, numbers, units, and qualifications.

Unreadable or incomplete sources enter a source-processing path, rather than producing apparently successful empty extractions. Reprocessing is bounded and recorded; it does not silently replace the source used by one comparison branch alone.

### 6.2 Extract once

The extractor reads the plan, fills the five record lists, supplies evidence, and raises issues. The controller runs structural checks and any permitted repair attempts under a fixed policy. Save the raw response, tool activity, validated output or failure, and issue state.

This saved artifact is the shared comparison starting point. Do not run a fresh extractor separately for E+V and call the resulting difference a verifier effect.

### 6.3 Preserve E and run E+V

E retains the saved extractor result, with unresolved issues routed according to the agreed review policy. Routing differences are workflow metadata, not changes to extracted content.

E+V receives a copy of that same result and the same source. The verifier checks all extracted categories, evidence, relationships, and flagged issues, and searches the plan for omissions. It may correct records, add supported records, identify unsupported records, raise new issues, or leave issues open. It cannot access expert reference answers.

Corrections preserve existing record IDs. New records receive new IDs. Removed or merged records remain traceable in saved history. IDs and links must remain valid after changes.

A verifier may resolve an empty-category issue by confirming that the relevant information is not reported after checking adequate readable source coverage. Such a resolution is not necessarily an error correction. Failure to read the source cannot justify confirming absence.

### 6.4 Capture pre-review results

Freeze both configuration outputs and their issue histories before expert correction. Derive operational measures, issue summaries, reported verifier resolutions, and the expert-review referral workload.

### 6.5 Expert assessment

Prepare the initial expert reference independently of model outputs. During evaluation, match output records to reference items by meaning rather than wording. Experts inspect the source when adjudicating disagreements or additional records.

Keep assessments separate from corrections. Score the saved E and E+V outputs as they originally stood. Expert-corrected release records must be a later artifact, not a replacement for the measured output.

If either configuration identifies a valid item missed by the initial reference, retain the adjudication and update a shared final reference. Reassess both configurations against that same final reference. Additional-record counts remain tied to the preserved initial reference.

The procedure for a second expert checking a subset, resolving disagreements, and organizing assessment order remains to be agreed. Where practical, conceal the configuration label during scoring to reduce expectation effects.

### 6.6 Curate and expand

Report comparison results before choosing an expansion workflow. Review pending issues and audit an agreed sample of unflagged outputs during expansion. Correct supported errors and exclude unresolved or unsupported material from the curated release. Review coverage remains explicit: accepted does not automatically mean every record received expert review.

## 7. Data and history records

Use plain JSON files initially, with table exports for expert review and analysis. A database is not required for the first implementation. The following are proposed logical records, not finalized field schemas.

| Record | Minimum information |
| --- | --- |
| Source manifest | Plan ID, source metadata, study set, document checksum, preparation version, page count, and source-processing status. |
| Extraction snapshot | Plan ID, run ID, stage, schema version, plan metadata, and the five extracted record lists with evidence and stable record IDs. |
| Review snapshot | Current issues and expert-review coverage, associated with an extraction snapshot. The proposal's `review` object may remain here or be linked from the plan artifact; the final storage layout is open. |
| Run record | Run ID, plan ID, configuration/stage, parent extractor run, model/settings, source/prompt/tool versions, timing, tokens, attempts, and outcome. |
| Issue history | Issue ID, affected record or plan/category, first-detected stage, all known concerns, and dated status changes with actor, explanation, and supporting evidence. |
| Expert reference | Initial and adjudicated versions, expert-coded records and evidence, plus reasons for revisions. |
| Expert assessment | Output snapshot being assessed, reference matches, record scores, additional-record judgments, evidence checks, and judgments about flags and resolutions. |

Generated IDs, version labels, and file locations must link these records. Saving a later stage creates a new snapshot rather than overwriting an earlier one.

### Issue grouping and status

One affected action or other extracted record has one issue containing its known problems. New concerns about that record extend the same issue. If an issue is closed and a further concern is identified, reopen it and preserve the prior resolution event. A partial fix leaves the issue open while recording the fix.

Record-level grouping does not yet settle how to group problems affecting a whole category, an omitted item with no record ID, or a source document. Those rules must be defined before counts are compared.

Retain the proposal's issue categories as a starting point: no records found, unclear meaning, conflicting evidence, source issue, and extraction-process issue. A bundled issue may span several fields and problem types. Decide during development whether reporting assigns one primary type or allows multiple types; percentages have different interpretations under those options.

Retain statuses for pending verification, pending reprocessing, pending expert review, and resolved. Preserve whether a resolution came from the verifier, the pipeline, or an expert. Verification must not set expert-review status to reviewed.

Distinguish the agent's explanation of a resolution from the expert's later judgment of whether it was justified. Record added verifier issues separately from initial extractor issues so the denominator for resolving initial issues stays fixed.

## 8. Evaluation measures

### 8.1 Pre-expert review

These measures describe what occurred during execution and what the pipeline reported. They do not establish that an answer or resolution was correct.

| Category | Measure and definition |
| --- | --- |
| Operational performance | Total runtime per plan/configuration; input and output tokens and their total; number of failed runs. |
| Issue handling | Total issue count, counts/proportions by type, and issue status at extractor and verifier stages. Distinguish all recorded issues from issues still open. |
| Verifier contribution | Initial extractor issues marked resolved by the verifier divided by total initial extractor issues; initial issues remaining unresolved and referred for expert review divided by that same denominator. Newly raised issues are reported separately. |
| Expert review workload | Number of issues referred for expert review and counts/proportions by type. This measures referrals, not expert time or task difficulty. |

For E+V, total runtime and tokens include the shared extraction plus verification; do not report only the verifier's cost. Save stages separately so the extra verification cost can also be identified. Shared extraction is not charged twice within E+V.

Define timing boundaries before comparison: source preparation, model loading, generation, tool execution, validation, and retries must have explicit inclusion rules. Record preparation and stage times separately, then derive the agreed total. Record whether the model was already loaded. Compare on documented hardware and execution conditions.

A retry is an attempt within a run; a failed run is a run that does not produce an acceptable stage result within the fixed limits. Preserve both attempt failures and final outcomes. Runtime and token totals include consumed retries. Report unavailable token measurements as unavailable, not zero; tokens from different tokenizers are not identical units of computation.

If verification fails, retain the successful E output and identify E+V as failed rather than silently treating E as a successful verified result. Unresolved processing issues must not be hidden to make the issue-resolution fractions add to 100%.

### 8.2 Post-expert review

These measures require expert judgment of the source and preserved outputs.

| Category | Measure and definition |
| --- | --- |
| Extraction quality | Record accuracy with partial credit: sum of reference-record scores divided by total final reference records. |
| Extraction quality | Fully correct record rate: number of reference records scored 1 divided by total final reference records. |
| Additional records | Number of extracted records with no match in the initial expert reference after semantic matching. |
| Additional records | Support rate: additional records confirmed as source-supported items missed by the initial reference divided by all additional records. |
| Evidence support | Quotations supporting their associated claims divided by total quotation uses; correct page references divided by total page references supplied. |
| Issue handling | Correctly flagged issues divided by total flagged issues; number of genuine problems not flagged. The counting rules must respect record-level issue grouping. |
| Verifier contribution | Expert judgment of whether reported resolutions were justified, interpreted alongside changes in extraction quality and evidence support. |

Additional records are not inherently errors. Some reveal omissions in the initial expert reference; others lack source support. An incorrect detail within an otherwise matched action is scored within that record, rather than automatically becoming an additional record.

Support-rate assessment must distinguish a valid newly identified item with imperfect details from a wholly unsupported item. The precise rule for partial support remains open. Duplicates and split/combined records need matching rules before additional-record counts are finalized.

An issue that correctly requests clarification is not necessarily a factual error. The definition of a correctly flagged issue must specify which genuine uncertainties, source problems, and processing failures qualify, as well as extraction errors.

Quotation matching and semantic support are separate. A quotation can occur on the cited page without supporting the claim. Define whether each quotation is evaluated against a specific claim or the entire record, particularly when several passages jointly support one record. Evidence accuracy among supplied quotations also does not measure whether required quotations were omitted; evidence completeness remains an open consideration rather than an agreed added metric.

### 8.3 Record scoring

Different wording receives full credit when substantive meaning is equivalent to the source-supported expert reference.

| Score | Rule |
| --- | --- |
| 1 | All required substantive information is correct, with no unsupported substantive additions. |
| 0.5 | At least some substantive information is correct, but one or more required parts are incorrect or missing. |
| 0 | No substantive information is correct, or the reference item was omitted entirely. |

An action identified correctly but assigned the wrong implementation status receives 0.5. More generally, all partial records receive the same credit regardless of error severity; this is a deliberate simplification. The strict measure awards credit only to records scored 1.

Unavailable source information does not count as an extraction omission. Missing a stated target differs from correctly recording that no deadline was specified. The rubric needs examples of substantive correctness, acceptable paraphrases, and required information before formal scoring.

For ten reference records with six fully correct, two partial, and two omitted, partial-credit accuracy is `(6 + 2 × 0.5) / 10 = 70%`; the fully correct rate is `6 / 10 = 60%`.

Both measures evaluate recovery of reference items; unsupported extra records do not reduce them. Additional-record counts and support rates must accompany the scores. Quotation and page correctness are assessed separately rather than silently folded into the record score.

### 8.4 Analysis rules to freeze

- Match by substantive meaning rather than exact text. Do not count a duplicated output twice or automatically penalize a different split/merge representation.
- Use the same final adjudicated reference for E and E+V, while preserving the initial reference for additional-record measures.
- Return not applicable for a zero denominator. An empty category or absence of flags is not automatically a score of zero or a perfect score.
- Report per-plan and per-category results before selecting an aggregate. Decide how to average across plans so a long plan does not silently determine the result.
- Preserve fully correct, partial, incorrect, and missing counts behind summary scores.
- Keep failed runs visible. Define how incomplete outputs enter quality reporting rather than excluding them without explanation.
- For issue counts, an affected record is the unit. Define how expert-discovered problems are mapped onto existing bundled issues so unflagged field errors are not incorrectly counted as multiple unflagged records.

## 9. Development, reproducibility, and checks

During the two-plan development phase, use the structured log for requested entries on meaningful changes, reasons, failed attempts, and observed results. Operational run records are machine-generated research artifacts; they are distinct from the human-readable change log.

Before processing comparison plans, freeze the schema, prompts, models/settings, tools, document-context strategy, retry limits, issue-counting rules, scoring rubric, and analysis definitions. If a critical change becomes necessary later, version it, explain why, and identify affected runs rather than combining incompatible results without notice.

The first implementation should have focused checks for page preservation, valid IDs/links, issue transitions and grouping, snapshot immutability, metric denominators, failure handling, and absence of expert-reference access from agent tools. Model factual accuracy remains an expert-evaluated outcome, not something a structural test establishes.

Record software versions, source fingerprints, model identifiers/settings, prompt/tool versions, and output histories. Reproducibility means documenting conditions and retaining artifacts; exact output identity is not guaranteed solely by choosing a random seed.

## 10. Proposed repository organization

Only the root documentation and `.gitignore` are being created now. The folders below describe a possible later implementation, not directories or code already created.

| Location | Purpose | Git policy |
| --- | --- | --- |
| `DESIGN.md`, `README.md`, `CHANGELOG.md` | Design, project entry point, and research change history. | Track. |
| `AGENTS.md` | Local instructions for the development assistant. | Ignore; retain on this computer. |
| `src/` | Controller, adapters, preparation, and MCP tools. | Track after approved implementation. |
| `schemas/`, `prompts/`, `configs/` | Versioned data rules, agent instructions, and settings without secrets. | Track. |
| `tests/` | Focused checks of consequential workflow behavior. | Track. |
| `data/raw/`, `data/processed/` | PDFs and prepared page text. | Ignore during development. |
| `models/`, `runs/`, `artifacts/`, `logs/` | Weights, run snapshots, evaluation files, and generated diagnostics. | Ignore during development; retain locally. |
| `data/release/`, `reports/` | Deliberately selected curated release and study summaries. | Track selected small files or link to a separately hosted release. |

Git exclusion is not deletion or backup. Research artifacts still require a retention/backup plan. Decide redistribution permissions and release location before publishing source text or document-derived artifacts. Ignored files already tracked by Git would remain tracked; `AGENTS.md` is currently untracked.

## 11. Proposed implementation sequence

Each step requires explanation and approval before code or system changes begin.

1. Review this draft and settle the issue unit, remaining grouping/type rules, record matching, and minimum rubric examples.
2. Inspect available hardware and select a runtime/model pair through small capability checks.
3. Define the versioned extraction, run, issue-history, reference, and assessment schemas.
4. Prepare the two development plans and validate page-preserving text.
5. Build the smallest useful MCP server and controller; establish one successful extraction with saved measurements.
6. Add verification, issue histories, shared-input branching, and preservation of both outputs.
7. Test failures and refine the workflow with experts on development plans. Finalize expert review procedures and freeze the comparison protocol.
8. Run the ten-plan comparison, complete expert assessment, and derive the agreed measures.
9. Analyze practical lessons and tradeoffs, select an expansion approach, and curate the dataset within available capacity.

## 12. Decisions still open

- Available hardware, model pair, runtime, and compatible SDK versions.
- Full-document versus page-batched processing and the merging procedure.
- Grouping of source/category/omitted-record issues, and primary versus multiple issue types.
- Record matching, duplicate handling, split/merge rules, and partial-credit examples.
- Definition of support for additional records and semantic support for quotation uses.
- Timing boundaries, retry budgets, failure treatment, zero-denominator handling, and aggregation.
- Second-expert coverage, assessment order, adjudication procedure, and expansion audit size.
- Final review-object storage layout, dataset release format, artifact backup, and publication location.

These are choices to settle during development, not reasons to expand the study into additional experimental configurations. The first implementation should remain small enough to understand, inspect, and explain.
