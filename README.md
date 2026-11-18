# heat adaptation LLM dataset

this research project examines how heat adaptation experts and open-weight large language models (LLMs) can be paired to build an extraction workflow. it will share practical lessons from the expert judgments, model outputs, and revisions involved in developing that workflow. open-weight models publish their trained parameters; this study accesses them through hugging face APIs.

the workflow extracts heat adaptation actions from government and public agency plans into structured records with supporting quotations. **inkling 2 small is the extractor in both configurations:** **E** is its extraction, and **E+V** begins with that exact saved extraction, checked and revised by a different hosted open-weight model through hugging face. the verifier remains to be selected and implemented. expert-curated answers will also support a pilot instruction dataset for possible future fine-tuning.

## project documents

- [design document](DESIGN.md): research objectives, methods, action fields, coding rules, and evaluation measures.
- [implementation document](IMPLEMENTATION.MD): file directory, software responsibilities, execution, saved files, expert assessment, and remaining work. start with the [file directory](IMPLEMENTATION.MD#1-file-directory) and [module map](IMPLEMENTATION.MD#module-responsibilities).
- [structured change log](CHANGELOG.md): meaningful decisions, changes, failures, and lessons from development.

## extracted records

each model answer contains three components:

| component | contents |
| --- | --- |
| `plan_data.metadata` | document and jurisdiction metadata. |
| `plan_data.actions` | one record per specific heat adaptation activity across the plan. |
| `plan_issues.issues` | grouped concerns, uncertainties, conflicts, source gaps, and possible omissions. |

every action has nine fields: `action_id`, `action`, `action_type`, `action_status`, `action_location`, `action_recipient`, `action_cost`, `action_benefit`, and `evidence`. costs and benefits are recorded within their associated action. evidence uses exact continuous quotations and physical PDF page positions counted from 1. the [field definitions and coding rules](DESIGN.md#appendix-dataset-coding-rules-and-evaluation) specify permitted values and missing information.

issues retain stable IDs and origins through verification and curation. expert fixes are recorded in separate curated copies after assessment; model answers cannot claim an expert resolution. the saved model outputs remain the evidence for comparison.

## current implementation

| component | status |
| --- | --- |
| document registration, metadata updates, preparation, and listing | implemented. native text extraction, selective optical character recognition (OCR), and source preservation. |
| extraction | inkling 2 small through hugging face inference providers, pinned to deepinfra. compatibility checks and a full freetown development extraction succeeded. PDF preparation, OCR, and model context protocol (MCP) tools run locally. |
| action format and issue validation | implemented. the extraction format uses `plan_data.metadata`, `plan_data.actions`, and `plan_issues.issues`, with one current schema. |
| expert-curated answer validation | implemented, including expert resolutions. |
| verifier execution, expert reference and assessment workflow, metrics, and instruction export | planned. |

see the [development checkpoint](IMPLEMENTATION.MD#current-development-checkpoint) for engineering evidence and next steps.

## command line interface

the available commands are `add_plan`, `update_plan_data`, `prepare_plan`, `run_extract_mode`, and `list_plans`. verification and expert assessment commands remain planned.

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

OCR models are cached in `.cache/easyocr/`; normal preparation and MCP OCR use them offline on the CPU. registration and preparation do not require an LLM. extraction uses a hugging face API token and account credits or billing. LLM inference is hosted; the computer running this project handles PDF preparation, OCR, document tools, validation, and saving.

### add_plan: register a new PDF

experts [screen documents before import](DESIGN.md#eligible-plans). keep the supplied PDF outside `data/raw/`, for example in downloads. replace the example values with actual collection details:

```bash
uv run --locked heat-adaptation-llm-dataset add_plan \
  "$HOME/Downloads/your-plan.pdf" \
  --title "Your plan title" \
  --source-url "OFFICIAL_SOURCE_URL" \
  --date-accessed "YYYY-MM-DD" \
  --study-set development
```

quote paths and titles containing spaces. use the actual access date in `YYYY-MM-DD` format. the CLI accepts `development`, `comparison`, or `expansion` as the study set; expansion is deferred in the current study.

registration assigns an ID, preserves the PDF at `data/raw/<plan_id>.pdf`, and records metadata and a SHA-256 checksum, a fingerprint of the file's bytes, in `data/registry/plans.json`. identical contents reuse the existing record; revised contents receive a new ID.

### update_plan_data: update collection metadata

use the registered ID and supply only the fields to change:

```bash
uv run --locked heat-adaptation-llm-dataset update_plan_data plan_0001 --title "Corrected plan title"
```

editable fields are `--title`, `--source-url`, `--date-accessed`, and `--study-set`. at least one is required. omitted fields stay unchanged; invalid values reject the entire update. corrections change the registry without rewriting saved work.

development assignments remain fixed. other study-set changes are allowed only before model work is saved for that plan.

### prepare_plan: prepare a registered PDF

```bash
uv run --locked heat-adaptation-llm-dataset prepare_plan plan_0001
```

native text extraction comes first. easyocr handles detected text failures and image regions covering at least 10% of a page with no native text inside their bounds. rendering defaults to 150 DPI. regional OCR supplements native text without replacing it. add `--no-ocr` to skip OCR while retaining image checks.

each attempt saves `preparation.json`, `pages.json`, and any rendered PNGs in a new folder under `data/processed/<plan_id>/`, then updates the registry link. originals and earlier attempts remain unchanged.

- `ready`: automatic checks found no problems or review flags.
- `ready_with_gaps`: a usable reading route exists, but content needs review, including successful OCR.
- `failed`: page counting or a required reading route failed; inspect the reported problems before retrying.

OCR can misread words and numbers; image screening can miss content and does not repair table reading order. check prepared text against the original PDF. the [implementation reference](IMPLEMENTATION.MD#prepare-text-automatically-investigate-gaps-with-tools) explains the rules and limitations.

### run_extract_mode: extract from a saved preparation

select the registered plan, exact preparation path, profile, and purpose explicitly. use `list_plans` to find the preparation path. the extractor configuration is:

| setting | value |
| --- | --- |
| profile | `inkling2_small_hf_extractor_development` |
| model | `thinkingmachines/Inkling-2-Small` |
| API and fixed host | hugging face inference providers, deepinfra |
| context limit | 1,048,576 tokens |
| output allowance | 32,768 tokens per request, including reported reasoning tokens |
| document tool budget | 10 submitted calls per extraction, including failed submissions |
| model-request timeout | 1,800 seconds |
| tool-request timeout | 120 seconds |

#### API access

create a hugging face access token with inference providers permission and arrange account credits or billing. in bash or zsh, first run this command, then paste the token when the terminal waits and press enter; token input is hidden:

```bash
read -r -s HF_TOKEN
```

the program reads `HF_TOKEN` from the environment. it does not load a `.env` file automatically or save authentication headers in run artifacts. after entering the token, export it:

```bash
export HF_TOKEN
```

#### compatibility check

when first using a model/provider setup or changing its serving settings, run the separate diagnostic:

```bash
uv run --locked python -m huggingface_check \
  --profile inkling2_small_hf_extractor_development
```

the diagnostic makes up to three paid requests using fictional inputs: a small strict schema, the adapted extraction schema, and a 64-token output-limit check. the first two output allowances are 2,048 and 4,096 tokens. the fictional extraction is checked against the complete original contract. the diagnostic stops at the first failure, saves requests and observations under `artifacts/huggingface_checks/`, and does not launch extraction or modify study files. caps are requested limits, not a guaranteed billing ceiling. passing establishes compatibility for those requests, not general extraction accuracy. an already validated setup does not require repeating the diagnostic for every plan.

#### run extraction

after registration and preparation, run an extraction with the validated setup:

```bash
uv run --locked heat-adaptation-llm-dataset run_extract_mode plan_0001 \
  --source-path data/processed/plan_0001/preparation_01/preparation.json \
  --profile inkling2_small_hf_extractor_development \
  --purpose development
```

the command supplies the whole prepared document through the hugging face API. python starts a local MCP document tool server, gives inkling the available tools, executes requested tools within the configured limit, then requests one complete JSON answer. tools provide saved page text, exact quotation lookup, and fresh page OCR when enabled. input is text-only; OCR returns text, and direct image delivery is not supported.

final generation requests strict JSON schema output. the copy sent to deepinfra retains field names, required fields, types, and permitted values, but omits `uniqueItems` and conditional issue-status rules (`if`, `then`, and `else`). the original schemas and python validators retain every acceptance rule, including uniqueness and issue-status relationships. unsupported schema requests fail without automatic fallback. structural validation does not establish factual accuracy or quotation fidelity; expert assessment remains necessary.

before each request, input capacity is estimated as the full UTF-8 request size in bytes plus 8,192 tokens of headroom, with the maximum output reserved separately. this deliberately loose estimate includes instructions, schema, tools, and history. it is not an exact count or a certified bound on the provider's hidden prompt formatting. oversized estimates stop the request without shortening the plan. API-reported usage is saved separately; unavailable usage remains null. reported output usage above the configured limit still fails. the client does not automatically retry, redirect, or change the selected host.

each invocation creates a new numbered folder under `runs/<plan_id>/run_extract_NNNN/`. `output.json` starts as `running` and records the selected settings, observed environment, model usage, and final outcome. requests, token checks, received responses, source/code snapshots, and any OCR files are preserved alongside it. loading a successful run requires its saved input and checks the preparation text against the startup fingerprint. `tool_log.json` records tool activity when present; `validation_report.json` records final-response checks when attempted. the terminal prints the actual saved status and available report paths. see the [saved execution details](IMPLEMENTATION.MD#saved-extractor-execution) for the file layout and failure behavior.

use `--purpose development` for development plans. `exploratory` identifies deliberate repeats outside the main comparison output. formal comparison execution remains disabled while the verifier and reference workflow are being developed; it will require fixed settings, clean committed code, and matching study-set assignments. comparison-plan feedback, including exploratory repeats, hides claims, issues, response snippets, and repair details; detailed feedback stays restricted until a validated reference workflow exists.

after fixing a failed attempt, repeat the command with `--retry-of-run-id run_extract_0001` to link the new attempt to it. use the actual failed run ID. `--config-path` selects another project-relative profile file; its default is `configs/profiles.json`. earlier runs retain their saved prompts and settings.

ctrl+c requests cancellation and preserves available evidence before returning 130. a saving failure can leave the record `running`; abrupt termination can also leave partial files without an end time or duration. inspect such attempts and confirm the process has stopped before recovery. the command does not automatically resume or retry.

### list_plans: list registered documents

```bash
uv run --locked heat-adaptation-llm-dataset list_plans
```

shows each document's ID, study set, title, and linked preparation status and path. documents without a preparation show `not_prepared`; damaged linked files produce an error.

### help and checks

```bash
uv run --locked heat-adaptation-llm-dataset --help
uv run --locked pytest -q
```

add `--help` to any command for its options. commands use the current project directory; pass `--project-root "/path/to/project"` after the command to select another location. successful preparation, including `ready_with_gaps`, and successfully saved extraction return 0. failures return 1, invalid arguments return 2, and extraction cancellation returns 130. a valid answer in memory is not a successfully saved run.

real OCR checks require the cached models and are skipped when unavailable. most model tests use controlled HTTP replies; live model diagnostics are separate development evidence. passing tests and valid JSON do not establish extraction accuracy or completeness.

back up `data/raw/`, `data/processed/`, `runs/`, and `artifacts/` separately; all are excluded from git. `artifacts/` holds development evidence and is absent from a fresh clone. generated files and source documents require separate preservation from the code repository.
