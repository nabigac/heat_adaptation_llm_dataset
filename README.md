# heat adaptation LLM dataset

this project develops and evaluates a pipeline pairing open-weight large language models (LLMs) with heat adaptation experts to build an instruction dataset for future fine-tuning. it documents how plans become structured, source-supported action records and compares an extractor alone with the same extractor followed by a different open-weight verifier.

eligible plans span city, county, regional, state, and national governments, with particular interest in city plans. broader plans can address heat adaptation across their jurisdiction without a specific urban focus.

## project documents

- [design document](DESIGN.md): context and problem, research objectives, methods, plan dataset fields, coding rules, and evaluation formulas.
- [implementation document](IMPLEMENTATION.MD): workflow execution, source recovery, saved runs and settings, expert-file processing, instruction dataset assembly, development evidence, and supporting file formats.
- [structured change log](CHANGELOG.md): decisions, changes, and lessons learned during the study.

## current progress

part 1, document registration and preparation, is implemented. part 2 now has a working local extraction command: Python loads the selected preparation, prompts, and profile; coordinates Ollama and MCP document tools; checks token budgets and responses; and preserves the run, measurements, and evidence as work proceeds. the tools provide saved page text, exact quotation lookup, and fresh page OCR when enabled.

the latest recorded full suite passed 1,804 tests. live fictional examples completed saved extraction and OCR through real Ollama and MCP. the first full Freetown attempt ran but failed final validation; no accepted full real-plan extraction exists yet. the agreed action-focused design has not been migrated into the current five-category schemas and prompts. verification, expert files, analysis, and instruction dataset assembly remain planned. see the [development checkpoint](IMPLEMENTATION.MD#current-development-checkpoint) for evidence and limitations.

## command line interface

the available commands are `add`, `update`, `prepare`, `extract`, and `list`. verification and expert-stage commands remain planned.

### set up the environment

with [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, run from the project directory:

```bash
uv sync --locked
```

this installs the locked dependencies and CLI in `.venv`. `uv run` uses that environment without manual activation.

initialize the English OCR models once if using preparation OCR or agent-requested OCR:

```bash
uv run --locked python -c "from document_tools import EasyOcrReader; EasyOcrReader(download_models=True)"
```

models are cached in `.cache/easyocr/`; normal preparation and MCP OCR use them offline on the CPU. registration and preparation do not require an LLM model. extraction additionally requires a running Ollama service and the selected model weights; the [current profile](configs/profiles.json) uses `qwen3.5:27b`. Ollama manages those weights outside this repository. the token checker supports only the runtime/model/tokenizer setup validated in the [implementation reference](IMPLEMENTATION.MD#prompts-response-schema-and-token-budgeting).

### register a new PDF

experts [screen documents before import](DESIGN.md#eligible-plans). keep the supplied PDF outside `data/raw/`, for example in Downloads. replace the example values with actual collection details:

```bash
uv run --locked heat-adaptation-llm-dataset add \
  "$HOME/Downloads/your-plan.pdf" \
  --title "Your plan title" \
  --source-url "OFFICIAL_SOURCE_URL" \
  --date-accessed "YYYY-MM-DD" \
  --study-set development
```

quote paths and titles containing spaces. use the actual access date in `YYYY-MM-DD` format and a study set of `development`, `comparison`, or `expansion`.

registration assigns an ID, preserves the PDF at `data/raw/<plan_id>.pdf`, and records metadata and a SHA-256 checksum in `data/registry/plans.json`. identical contents reuse the existing record; revised contents receive a new ID.

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

native extraction comes first. EasyOCR handles detected text failures and image regions covering at least 10% of a page with no native text inside their bounds. rendering defaults to 150 DPI. regional OCR supplements native text without replacing it. add `--no-ocr` to skip OCR while retaining image checks.

each attempt saves `preparation.json`, `pages.json`, and any rendered PNGs in a new folder under `data/processed/<plan_id>/`, then updates the registry link. originals and earlier attempts remain unchanged.

- `ready`: automatic checks found no problems or review flags.
- `ready_with_gaps`: a usable reading route exists, but content needs review, including successful OCR.
- `failed`: page counting or a required reading route failed; inspect the reported problems before retrying.

OCR can misread words and numbers; image screening can miss content and does not repair table reading order. check prepared text against the original PDF. the [implementation reference](IMPLEMENTATION.MD#prepare-text-automatically-investigate-gaps-with-tools) explains the rules and limitations.

### extract from a saved preparation

select the registered plan, exact preparation path, profile, and purpose explicitly. this example uses the current local Freetown development preparation; use `list` to find the saved path for your plan:

```bash
uv run --locked heat-adaptation-llm-dataset extract plan_0001 \
  --source-path data/processed/plan_0001/preparation_02/preparation.json \
  --profile qwen35_27b_extractor_development \
  --purpose development
```

the command supplies the whole prepared document. Python starts a local MCP subprocess, gives Ollama the available tools, executes requested tools within the configured limit, then requests one complete `content` and `review` answer using the response schema. every model request is counted before generation, including instructions, tool definitions, and accumulated history. direct image delivery and hosted providers are not yet supported; OCR returns text.

each invocation creates a new numbered folder under `runs/<plan_id>/run_extract_NNNN/`. `output.json` starts as `running` and records the selected settings, observed environment, model usage, and final outcome. requests, token checks, received responses, source/code snapshots, and any OCR files are preserved alongside it. `tool_log.json` records tool activity when present; `validation_report.json` records final-response checks when attempted. the terminal prints the actual saved status and available report paths. see the [saved execution details](IMPLEMENTATION.MD#saved-extractor-execution) for the file layout and failure behavior.

use `--purpose comparison` only for comparison-set work. `exploratory` identifies deliberate repeats outside the main comparison output. development/comparison purposes must match the registered study set, and formal comparison requires clean committed code. comparison-plan feedback, including exploratory repeats, hides claims, issues, response snippets, and repair details; detailed feedback stays restricted until a validated reference workflow exists.

after fixing a failed attempt, repeat the command with `--retry-of-run-id run_extract_0001` to link the new attempt to it. use the actual failed run ID. `--config-path` selects another project-relative profile file; its default is `configs/profiles.json`. earlier runs retain their saved prompts and settings.

Ctrl+C requests cancellation and preserves available evidence before returning 130. a saving failure can leave the record `running`; abrupt termination can also leave partial files without an end time or duration. inspect such attempts and confirm the process has stopped before recovery. the command does not automatically resume or retry.

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

real OCR checks require the cached models and are skipped when unavailable. most model tests use controlled HTTP replies; live model diagnostics are separate development evidence. passing tests and valid JSON do not establish extraction accuracy or completeness. back up `data/raw/`, `data/processed/`, `runs/`, and `artifacts/` separately; all are excluded from Git. `artifacts/` holds local progress handoffs and development evidence and is absent from a fresh clone.
