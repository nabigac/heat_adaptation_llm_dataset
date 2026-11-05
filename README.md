# heat adaptation LLM dataset

this study pairs open-weight large language models (LLMs) with heat adaptation experts to extract structured, source-linked data from government plans. it examines whether a verifier improves extraction quality and changes expert review requirements, while documenting practical lessons from building the workflow.

## project documents

- [technical design draft](DESIGN.md): implementation, data formats, and evaluation approach.
- [structured change log](CHANGELOG.md): decisions, changes, and lessons learned during the study.

## current progress

part 1, document registration and preparation, is implemented. part 2, extraction, is in progress: Python modules now load profiles and prompts, assemble the full prepared document, connect to local Ollama, constrain and validate responses, apply permitted repairs, and save/load run records. these components still need an agent loop, MCP tools, and integration into a complete saved extraction. verification, expert files, and analysis remain planned.

the latest development check assembled all 46 pages of the first plan and confirmed that the request fits the current token budget. it did not generate an extraction. see the [development checkpoint](DESIGN.md#current-development-checkpoint-2026-11-04) for settings, evidence, limitations, and remaining work.

## command line interface

the available commands are `add`, `update`, `prepare`, and `list`. extraction and verification commands are not yet implemented.

### set up the environment

with [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, run from the project directory:

```bash
uv sync --locked
```

this installs the locked dependencies and CLI in `.venv`. `uv run` uses that environment without manual activation.

initialize the English OCR models once if using automatic OCR:

```bash
uv run --locked python -c "from document_tools import EasyOcrReader; EasyOcrReader(download_models=True)"
```

models are cached in `.cache/easyocr/`; normal preparation uses them offline. registration and preparation do not require an LLM model. local model development additionally requires a running Ollama service and the selected model weights; the [current profile](configs/profiles.json) uses `qwen3.5:27b`. Ollama manages those weights outside this repository. the token checker supports only the runtime/model/tokenizer setup validated in the [design](DESIGN.md#prompts-response-schema-and-token-budgeting).

### register a new PDF

experts [screen documents before import](DESIGN.md#2-plans-and-extracted-content). keep the supplied PDF outside `data/raw/`, for example in Downloads. replace the example values with actual collection details:

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

OCR can misread words and numbers; image screening can miss content and does not repair table reading order. check prepared text against the original PDF. the [design](DESIGN.md#prepare-text-automatically-investigate-gaps-with-tools) explains the rules and limitations.

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

add `--help` to any command for its options. commands use the current project directory; pass `--project-root "/path/to/project"` after the command to select another location. successful preparation, including `ready_with_gaps`, returns 0; failures return 1 and invalid arguments return 2.

real OCR checks require the cached models and are skipped when unavailable. tests do not establish extraction accuracy on every PDF. back up `data/raw/`, `data/processed/`, `runs/`, and `artifacts/` separately; all are excluded from Git. `artifacts/` holds local progress handoffs and development evidence and is absent from a fresh clone.
