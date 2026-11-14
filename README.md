# Heat adaptation LLM dataset

This research project examines how heat adaptation experts and open-weight large language models (LLMs) can be paired to build an extraction workflow. It will share practical lessons from the expert judgments, model outputs, and revisions involved in developing that workflow. Open-weight models have downloadable trained parameters and can be run locally.

The workflow extracts heat adaptation actions from government and public agency plans into structured records with supporting quotations. The study will compare an extractor alone (**E**) with the same extraction checked and revised by a different model (**E+V**). Expert-curated answers will also support a pilot instruction dataset for possible future fine-tuning.

## Project documents

- [Design document](DESIGN.md): research objectives, methods, action fields, coding rules, and evaluation measures.
- [Implementation document](IMPLEMENTATION.MD): software responsibilities, execution, saved files, expert assessment, and remaining work. It includes the [module map](IMPLEMENTATION.MD#2-system-architecture-and-responsibilities) and [file directory](IMPLEMENTATION.MD#files-and-identifiers).
- [Structured change log](CHANGELOG.md): template for recording meaningful decisions, changes, failures, and lessons. Its previous entries have been cleared for the fresh start.

## Study overview

The planned sample contains **two development plans** for refining the workflow and **five separate comparison plans** for evaluating E and E+V under fixed settings. Experts will prepare independent initial references before viewing comparison outputs, then assess both outputs against a shared final reference.

Eligible sources are final, publicly available English plans published or updated in 2010 or later, issued by governments or public agencies, and supplied as readable PDFs. They address heat directly or contain a dedicated heat section with at least one action. City, county, regional, state, and national plans are eligible, with particular interest in city plans. See the [eligibility and sampling protocol](DESIGN.md#eligible-plans).

The comparison uses three quality measures:

- **Action score percentage:** correctness and completeness against the final reference, using scores of 0, 0.5, or 1 for each activity.
- **Unsupported action count:** invented or ineligible activities, reported alongside the total distinct output activities.
- **Actions with adequate evidence:** the percentage of output activities whose quotations support all recorded substantive details and reproduce the PDF faithfully on the correct pages.

Two issue measures describe open issues and expert-confirmed verifier resolutions relative to claimed resolutions of initially open E issues. Runtime, provider-reported tokens, and failures describe computational requirements. The [evaluation protocol](DESIGN.md#g-evaluation-measures-and-calculations) defines the calculations and interpretation. These measures and the formal comparison remain planned.

## Extracted records

Each model answer contains three components:

| Component | Contents |
| --- | --- |
| `content.plan_info` | Document and jurisdiction metadata. |
| `content.plan_actions` | One record per specific heat adaptation activity across the plan. |
| `review.issues` | Grouped concerns, uncertainties, conflicts, source gaps, and possible omissions. |

All tree planting within a plan forms one action, even when neighborhoods, programmes, or phases differ. Each location's quantities, dates, implementers, status, costs, and benefits retain their associations. Drinking fountain installation forms a separate action. The broad action types classify mechanisms; they do not determine which activities are grouped together.

Every action has nine fields: `action_id`, `action`, `action_type`, `action_status`, `action_location`, `action_recipient`, `action_cost`, `action_benefit`, and `evidence`. Costs and benefits are recorded within their associated action. Evidence uses exact continuous quotations and physical PDF page positions counted from 1. The [field definitions and coding rules](DESIGN.md#appendix-dataset-coding-rules-and-evaluation) specify permitted values and missing information.

Issues retain stable IDs and origins through verification and curation. Expert fixes are recorded in separate curated copies after assessment; model answers cannot claim an expert resolution. The saved model outputs remain the evidence for comparison.

## Current implementation

| Component | Status |
| --- | --- |
| Document registration, metadata updates, preparation, and listing | Implemented. Native text extraction, selective optical character recognition (OCR), and source preservation. |
| Local extraction | Implemented with Ollama and document tools connected through Model Context Protocol (MCP). |
| Action format and issue validation | Implemented. New runs use version 2; version 1 files remain readable through preserved schemas. |
| Expert-curated answer validation | Implemented, including expert resolutions. |
| Verifier execution, expert reference and assessment workflow, metrics, and instruction export | Planned. |

The active registry and research folders have been reset for a fresh start. Begin by registering and preparing development plans. Automated checks and a small fictional live extraction have passed; extraction quality and completeness on real plans under the new format are **not yet tested**. See the [development checkpoint](IMPLEMENTATION.MD#current-development-checkpoint) for engineering evidence and next steps.

## Command line interface

The available commands are `add`, `update`, `prepare`, `extract`, and `list`. Verification and expert assessment commands remain planned.

### Set up the environment

With [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, run from the project directory:

```bash
uv sync --locked
```

This installs the locked dependencies and command line interface (CLI) in `.venv`. `uv run` uses that environment without manual activation.

Initialize the English OCR models once if using preparation OCR or agent-requested OCR:

```bash
uv run --locked python -c "from document_tools import EasyOcrReader; EasyOcrReader(download_models=True)"
```

OCR models are cached in `.cache/easyocr/`; normal preparation and MCP OCR use them offline on the CPU. Registration and preparation do not require an LLM. Extraction additionally requires a running Ollama service and the selected model weights; the [current profile](configs/profiles.json) uses `qwen3.5:27b`. Ollama manages those weights outside this repository. The token checker supports only the runtime, model, and tokenizer setup validated in the [implementation reference](IMPLEMENTATION.MD#prompts-response-schema-and-token-budgeting).

### Register a new PDF

Experts [screen documents before import](DESIGN.md#eligible-plans). Keep the supplied PDF outside `data/raw/`, for example in Downloads. Replace the example values with actual collection details:

```bash
uv run --locked heat-adaptation-llm-dataset add \
  "$HOME/Downloads/your-plan.pdf" \
  --title "Your plan title" \
  --source-url "OFFICIAL_SOURCE_URL" \
  --date-accessed "YYYY-MM-DD" \
  --study-set development
```

Quote paths and titles containing spaces. Use the actual access date in `YYYY-MM-DD` format. The CLI accepts `development`, `comparison`, or `expansion` as the study set; expansion is deferred in the current study.

Registration assigns an ID, preserves the PDF at `data/raw/<plan_id>.pdf`, and records metadata and a SHA-256 checksum, a fingerprint of the file's bytes, in `data/registry/plans.json`. Identical contents reuse the existing record; revised contents receive a new ID.

### Update collection metadata

Use the registered ID and supply only the fields to change:

```bash
uv run --locked heat-adaptation-llm-dataset update plan_0001 --title "Corrected plan title"
```

Editable fields are `--title`, `--source-url`, `--date-accessed`, and `--study-set`. At least one is required. Omitted fields stay unchanged; invalid values reject the entire update. Corrections change the registry without rewriting saved work.

Development assignments remain fixed. Other study-set changes are allowed only before model work is saved for that plan.

### Prepare a registered PDF

```bash
uv run --locked heat-adaptation-llm-dataset prepare plan_0001
```

Native text extraction comes first. EasyOCR handles detected text failures and image regions covering at least 10% of a page with no native text inside their bounds. Rendering defaults to 150 DPI. Regional OCR supplements native text without replacing it. Add `--no-ocr` to skip OCR while retaining image checks.

Each attempt saves `preparation.json`, `pages.json`, and any rendered PNGs in a new folder under `data/processed/<plan_id>/`, then updates the registry link. Originals and earlier attempts remain unchanged.

- `ready`: automatic checks found no problems or review flags.
- `ready_with_gaps`: a usable reading route exists, but content needs review, including successful OCR.
- `failed`: page counting or a required reading route failed; inspect the reported problems before retrying.

OCR can misread words and numbers; image screening can miss content and does not repair table reading order. Check prepared text against the original PDF. The [implementation reference](IMPLEMENTATION.MD#prepare-text-automatically-investigate-gaps-with-tools) explains the rules and limitations.

### Extract from a saved preparation

Select the registered plan, exact preparation path, profile, and purpose explicitly. After registering and preparing your first plan, use `list` to find its exact preparation path. A first preparation would typically use the following path:

```bash
uv run --locked heat-adaptation-llm-dataset extract plan_0001 \
  --source-path data/processed/plan_0001/preparation_01/preparation.json \
  --profile qwen35_27b_extractor_development \
  --purpose development
```

The command supplies the whole prepared document. Python starts a local MCP document tool server, gives Ollama the available tools, executes requested tools within the configured limit, then requests one complete answer using the response schema. The tools provide saved page text, exact quotation lookup, and fresh page OCR when enabled. Every model request is counted before generation, including instructions, tool definitions, and accumulated history. Direct image delivery and hosted providers are not yet supported; OCR returns text.

Each invocation creates a new numbered folder under `runs/<plan_id>/run_extract_NNNN/`. `output.json` starts as `running` and records the selected settings, observed environment, model usage, and final outcome. Requests, token checks, received responses, source/code snapshots, and any OCR files are preserved alongside it. Loading a successful version 2 run requires its saved input and checks the preparation text against the startup fingerprint. `tool_log.json` records tool activity when present; `validation_report.json` records final-response checks when attempted. The terminal prints the actual saved status and available report paths. See the [saved execution details](IMPLEMENTATION.MD#saved-extractor-execution) for the file layout and failure behavior.

Use `--purpose comparison` only for comparison-set work. `exploratory` identifies deliberate repeats outside the main comparison output. Development/comparison purposes must match the registered study set, and formal comparison requires clean committed code. Comparison-plan feedback, including exploratory repeats, hides claims, issues, response snippets, and repair details; detailed feedback stays restricted until a validated reference workflow exists.

After fixing a failed attempt, repeat the command with `--retry-of-run-id run_extract_0001` to link the new attempt to it. Use the actual failed run ID. `--config-path` selects another project-relative profile file; its default is `configs/profiles.json`. Earlier runs retain their saved prompts and settings.

Ctrl+C requests cancellation and preserves available evidence before returning 130. A saving failure can leave the record `running`; abrupt termination can also leave partial files without an end time or duration. Inspect such attempts and confirm the process has stopped before recovery. The command does not automatically resume or retry.

### List registered documents

```bash
uv run --locked heat-adaptation-llm-dataset list
```

Shows each document's ID, study set, title, and linked preparation status and path. Documents without a preparation show `not_prepared`; damaged linked files produce an error.

### Help and checks

```bash
uv run --locked heat-adaptation-llm-dataset --help
uv run --locked pytest -q
```

Add `--help` to any command for its options. Commands use the current project directory; pass `--project-root "/path/to/project"` after the command to select another location. Successful preparation, including `ready_with_gaps`, and successfully saved extraction return 0. Failures return 1, invalid arguments return 2, and extraction cancellation returns 130. A valid answer in memory is not a successfully saved run.

Real OCR checks require the cached models and are skipped when unavailable. Most model tests use controlled HTTP replies; live model diagnostics are separate development evidence. Passing tests and valid JSON do not establish extraction accuracy or completeness.

Back up `data/raw/`, `data/processed/`, `runs/`, and `artifacts/` separately; all are excluded from Git. `artifacts/` holds local development evidence and is absent from a fresh clone. Generated files, source documents, and model assets require separate preservation from the code repository.
