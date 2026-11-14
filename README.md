# heat adaptation LLM dataset

this research project examines how heat adaptation experts and open-weight large language models (LLMs) can be paired to build an extraction workflow. it will share practical lessons from the expert judgments, model outputs, and revisions involved in developing that workflow. open-weight models have downloadable trained parameters and can be run locally.

the workflow extracts heat adaptation actions from government and public agency plans into structured records with supporting quotations. the study will compare an extractor alone (**E**) with the same extraction checked and revised by a different model (**E+V**). expert-curated answers will also support a pilot instruction dataset for possible future fine-tuning.

## project documents

- [design document](DESIGN.md): research objectives, methods, action fields, coding rules, and evaluation measures.
- [implementation document](IMPLEMENTATION.MD): software responsibilities, execution, saved files, expert assessment, and remaining work. it includes the [module map](IMPLEMENTATION.MD#2-system-architecture-and-responsibilities) and [file directory](IMPLEMENTATION.MD#files-and-identifiers).
- [structured change log](CHANGELOG.md): template for recording meaningful decisions, changes, failures, and lessons. its previous entries have been cleared for the fresh start.

## study overview

the planned sample contains **two development plans** for refining the workflow and **five separate comparison plans** for evaluating E and E+V under fixed settings. experts will prepare independent initial references before viewing comparison outputs, then assess both outputs against a shared final reference.

eligible sources are final, publicly available english plans published or updated in 2010 or later, issued by governments or public agencies, and supplied as readable PDFs. they address heat directly or contain a dedicated heat section with at least one action. city, county, regional, state, and national plans are eligible, with particular interest in city plans. see the [eligibility and sampling protocol](DESIGN.md#eligible-plans).

the comparison uses three quality measures:

- **action score percentage:** correctness and completeness against the final reference, using scores of 0, 0.5, or 1 for each activity.
- **unsupported action count:** invented or ineligible activities, reported alongside the total distinct output activities.
- **actions with adequate evidence:** the percentage of output activities whose quotations support all recorded substantive details and reproduce the PDF faithfully on the correct pages.

two issue measures describe open issues and expert-confirmed verifier resolutions relative to claimed resolutions of initially open E issues. runtime, provider-reported tokens, and failures describe computational requirements. the [evaluation protocol](DESIGN.md#g-evaluation-measures-and-calculations) defines the calculations and interpretation. these measures and the formal comparison remain planned.

## extracted records

each model answer contains three components:

| component | contents |
| --- | --- |
| `content.plan_info` | document and jurisdiction metadata. |
| `content.plan_actions` | one record per specific heat adaptation activity across the plan. |
| `review.issues` | grouped concerns, uncertainties, conflicts, source gaps, and possible omissions. |

all tree planting within a plan forms one action, even when neighborhoods, programmes, or phases differ. each location's quantities, dates, implementers, status, costs, and benefits retain their associations. drinking fountain installation forms a separate action. the broad action types classify mechanisms; they do not determine which activities are grouped together.

every action has nine fields: `action_id`, `action`, `action_type`, `action_status`, `action_location`, `action_recipient`, `action_cost`, `action_benefit`, and `evidence`. costs and benefits are recorded within their associated action. evidence uses exact continuous quotations and physical PDF page positions counted from 1. the [field definitions and coding rules](DESIGN.md#appendix-dataset-coding-rules-and-evaluation) specify permitted values and missing information.

issues retain stable IDs and origins through verification and curation. expert fixes are recorded in separate curated copies after assessment; model answers cannot claim an expert resolution. the saved model outputs remain the evidence for comparison.

## current implementation

| component | status |
| --- | --- |
| document registration, metadata updates, preparation, and listing | implemented. native text extraction, selective optical character recognition (OCR), and source preservation. |
| local extraction | implemented with ollama and document tools connected through model context protocol (MCP). |
| action format and issue validation | implemented. new runs use version 2; version 1 files remain readable through preserved schemas. |
| expert-curated answer validation | implemented, including expert resolutions. |
| verifier execution, expert reference and assessment workflow, metrics, and instruction export | planned. |

the active registry and research folders have been reset for a fresh start. begin by registering and preparing development plans. automated checks and a small fictional live extraction have passed; extraction quality and completeness on real plans under the new format are **not yet tested**. see the [development checkpoint](IMPLEMENTATION.MD#current-development-checkpoint) for engineering evidence and next steps.

## command line interface

the available commands are `add`, `update`, `prepare`, `extract`, and `list`. verification and expert assessment commands remain planned.

### set up the environment

with [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, run from the project directory:

```bash
uv sync --locked
```

this installs the locked dependencies and command line interface (CLI) in `.venv`. `uv run` uses that environment without manual activation.

initialize the english OCR models once if using preparation OCR or agent-requested OCR:

```bash
uv run --locked python -c "from document_tools import EasyOcrReader; EasyOcrReader(download_models=True)"
```

OCR models are cached in `.cache/easyocr/`; normal preparation and MCP OCR use them offline on the CPU. registration and preparation do not require an LLM. extraction additionally requires a running ollama service and the selected model weights; the [current profile](configs/profiles.json) uses `qwen3.5:27b`. ollama manages those weights outside this repository. the token checker supports only the runtime, model, and tokenizer setup validated in the [implementation reference](IMPLEMENTATION.MD#prompts-response-schema-and-token-budgeting).

### register a new PDF

experts [screen documents before import](DESIGN.md#eligible-plans). keep the supplied PDF outside `data/raw/`, for example in downloads. replace the example values with actual collection details:

```bash
uv run --locked heat-adaptation-llm-dataset add \
  "$HOME/Downloads/your-plan.pdf" \
  --title "Your plan title" \
  --source-url "OFFICIAL_SOURCE_URL" \
  --date-accessed "YYYY-MM-DD" \
  --study-set development
```

quote paths and titles containing spaces. use the actual access date in `YYYY-MM-DD` format. the CLI accepts `development`, `comparison`, or `expansion` as the study set; expansion is deferred in the current study.

registration assigns an ID, preserves the PDF at `data/raw/<plan_id>.pdf`, and records metadata and a SHA-256 checksum, a fingerprint of the file's bytes, in `data/registry/plans.json`. identical contents reuse the existing record; revised contents receive a new ID.

### update collection metadata

use the registered ID and supply only the fields to change:

```bash
uv run --locked heat-adaptation-llm-dataset update plan_0001 --title "Corrected plan title"
```

editable fields are `--title`, `--source-url`, `--date-accessed`, and `--study-set`. at least one is required. omitted fields stay unchanged; invalid values reject the entire update. corrections change the registry without rewriting saved work.

development assignments remain fixed. other study-set changes are allowed only before model work is saved for that plan.

### prepare a registered PDF

```bash
uv run --locked heat-adaptation-llm-dataset prepare plan_0001
```

native text extraction comes first. easyocr handles detected text failures and image regions covering at least 10% of a page with no native text inside their bounds. rendering defaults to 150 DPI. regional OCR supplements native text without replacing it. add `--no-ocr` to skip OCR while retaining image checks.

each attempt saves `preparation.json`, `pages.json`, and any rendered PNGs in a new folder under `data/processed/<plan_id>/`, then updates the registry link. originals and earlier attempts remain unchanged.

- `ready`: automatic checks found no problems or review flags.
- `ready_with_gaps`: a usable reading route exists, but content needs review, including successful OCR.
- `failed`: page counting or a required reading route failed; inspect the reported problems before retrying.

OCR can misread words and numbers; image screening can miss content and does not repair table reading order. check prepared text against the original PDF. the [implementation reference](IMPLEMENTATION.MD#prepare-text-automatically-investigate-gaps-with-tools) explains the rules and limitations.

### extract from a saved preparation

select the registered plan, exact preparation path, profile, and purpose explicitly. after registering and preparing your first plan, use `list` to find its exact preparation path. a first preparation would typically use the following path:

```bash
uv run --locked heat-adaptation-llm-dataset extract plan_0001 \
  --source-path data/processed/plan_0001/preparation_01/preparation.json \
  --profile qwen35_27b_extractor_development \
  --purpose development
```

the command supplies the whole prepared document. python starts a local MCP document tool server, gives ollama the available tools, executes requested tools within the configured limit, then requests one complete answer using the response schema. the tools provide saved page text, exact quotation lookup, and fresh page OCR when enabled. every model request is counted before generation, including instructions, tool definitions, and accumulated history. direct image delivery and hosted providers are not yet supported; OCR returns text.

each invocation creates a new numbered folder under `runs/<plan_id>/run_extract_NNNN/`. `output.json` starts as `running` and records the selected settings, observed environment, model usage, and final outcome. requests, token checks, received responses, source/code snapshots, and any OCR files are preserved alongside it. loading a successful version 2 run requires its saved input and checks the preparation text against the startup fingerprint. `tool_log.json` records tool activity when present; `validation_report.json` records final-response checks when attempted. the terminal prints the actual saved status and available report paths. see the [saved execution details](IMPLEMENTATION.MD#saved-extractor-execution) for the file layout and failure behavior.

use `--purpose comparison` only for comparison-set work. `exploratory` identifies deliberate repeats outside the main comparison output. development/comparison purposes must match the registered study set, and formal comparison requires clean committed code. comparison-plan feedback, including exploratory repeats, hides claims, issues, response snippets, and repair details; detailed feedback stays restricted until a validated reference workflow exists.

after fixing a failed attempt, repeat the command with `--retry-of-run-id run_extract_0001` to link the new attempt to it. use the actual failed run ID. `--config-path` selects another project-relative profile file; its default is `configs/profiles.json`. earlier runs retain their saved prompts and settings.

ctrl+c requests cancellation and preserves available evidence before returning 130. a saving failure can leave the record `running`; abrupt termination can also leave partial files without an end time or duration. inspect such attempts and confirm the process has stopped before recovery. the command does not automatically resume or retry.

### list registered documents

```bash
uv run --locked heat-adaptation-llm-dataset list
```

shows each document's ID, study set, title, and linked preparation status and path. documents without a preparation show `not_prepared`; damaged linked files produce an error.

### help and checks

```bash
uv run --locked heat-adaptation-llm-dataset --help
uv run --locked pytest -q
```

add `--help` to any command for its options. commands use the current project directory; pass `--project-root "/path/to/project"` after the command to select another location. successful preparation, including `ready_with_gaps`, and successfully saved extraction return 0. failures return 1, invalid arguments return 2, and extraction cancellation returns 130. a valid answer in memory is not a successfully saved run.

real OCR checks require the cached models and are skipped when unavailable. most model tests use controlled HTTP replies; live model diagnostics are separate development evidence. passing tests and valid JSON do not establish extraction accuracy or completeness.

back up `data/raw/`, `data/processed/`, `runs/`, and `artifacts/` separately; all are excluded from git. `artifacts/` holds local development evidence and is absent from a fresh clone. generated files, source documents, and model assets require separate preservation from the code repository.
