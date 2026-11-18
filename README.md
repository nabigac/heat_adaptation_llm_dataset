# heat adaptation LLM dataset

this research project examines how heat adaptation experts and open-weight large language models (LLMs) can be paired to build an extraction workflow. it will share practical lessons from the expert judgments, model outputs, and revisions involved in developing that workflow. the project uses open-weight models through hugging face.

the workflow extracts heat adaptation actions from government and public agency plans into structured records with supporting quotations. the study explores two configurations: **E** (extraction) and **E+V** (extraction + verification). **E+V** begins with that exact saved extraction, checked and revised by a different hosted open-weight model. **inkling 2 small** is the extractor in both configurations; the verifier model remains to be selected and implemented. expert-curated answers will also support a pilot instruction dataset for possible future fine-tuning.

for setup and commands, see [getting started](#getting-started) and the [command line interface](#command-line-interface).

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

| stage | procedure and saved result | status |
| --- | --- | --- |
| 1. registration and preparation | the original PDF, collection metadata, page text, and preparation problems are preserved. native text extraction and selective optical character recognition (OCR) run locally. | implemented. |
| 2. extraction (E) | inkling 2 small receives the whole prepared plan through the hugging face API, pinned to deepinfra. its answer, issues, settings, tool activity, and execution records are saved. | implemented; compatibility checks and a freetown development extraction succeeded. |
| 3. verification (E+V) | a different hosted model through hugging face will check the exact saved E output, including unflagged content and possible omissions. its full revised answer will be saved. | planned; verifier model not yet selected. |
| 4. independent reference preparation | after successful E and V runs, experts will code the original PDF before viewing model outputs. this independent initial reference will be preserved. | planned. |
| 5. expert assessment | experts will match activities by meaning, review possible reference corrections, and assess both outputs against one shared final reference. revisions will record reasons and source evidence. | planned. |
| 6. analysis and dataset assembly | lessons about pairing experts and LLMs will be synthesized, paired outputs compared, and instruction examples assembled from expert-curated answers and their supporting inputs. | planned. |

JSON validation is implemented for extracted and expert-curated answers, including issue links and expert resolutions. source accuracy and completeness require expert assessment. model context protocol (MCP) connects the extractor to local tools for page text, quotation lookup, and OCR.

see the [development checkpoint](IMPLEMENTATION.MD#current-development-checkpoint) for engineering evidence and next steps.

## getting started

complete setup from the project directory before running extraction.

### set up the environment

install [uv](https://docs.astral.sh/uv/getting-started/installation/), then run:

```bash
uv sync --locked
```

this installs the locked dependencies and CLI in `.venv`. `uv run` uses that environment automatically.

### set up OCR

initialize the english OCR models once:

```bash
uv run --locked python -c "from document_tools import EasyOcrReader; EasyOcrReader(download_models=True)"
```

models are cached in `.cache/easyocr/`. PDF preparation and OCR run locally; LLM inference uses the hugging face API. registration and preparation do not require an API token.

### API access

create a hugging face access token with inference providers permission and add account credits or billing. the extractor uses inkling 2 small through hugging face, pinned to deepinfra.

in bash or zsh, run the following command, paste the token when the terminal waits, and press enter. token input is hidden:

```bash
read -r -s HF_TOKEN
```

then export it for commands in that terminal session:

```bash
export HF_TOKEN
```

the program reads `HF_TOKEN` from the environment; it does not load `.env` files automatically or save authentication headers in run artifacts.

### compatibility check

when adopting a new model or serving setup, run:

```bash
uv run --locked python -m huggingface_check
```

this defaults to `inkling2_small_hf_extractor` and makes up to three **paid requests** using fictional inputs. reports are saved under `artifacts/huggingface_checks/`. an already validated setup does not need this check repeated for each plan. see the [diagnostic details](IMPLEMENTATION.MD#compatibility-diagnostics) for checks, limits, and interpretation.

## command line interface

the usual workflow is `add_plan` → `prepare_plan` → `run_extract_mode`. use `list_plans` to find document IDs and preparation paths, and `update_plan_data` to correct collection metadata. commands use the current project directory unless `--project-root` is supplied.

### add_plan: register a new PDF

[screen eligibility](DESIGN.md#eligible-plans) first. keep the supplied PDF outside `data/raw/`, and replace these examples with actual collection details:

```bash
uv run --locked heat-adaptation-llm-dataset add_plan \
  "$HOME/Downloads/your-plan.pdf" \
  --title "Your plan title" \
  --source-url "OFFICIAL_SOURCE_URL" \
  --date-accessed "YYYY-MM-DD" \
  --study-set development
```

quote paths and titles containing spaces. registration assigns an ID, copies the PDF to `data/raw/`, and records metadata in `data/registry/plans.json`. identical PDF contents reuse the existing record. study sets are `development`, `comparison`, or `expansion`; expansion is deferred.

### prepare_plan: prepare a registered PDF

```bash
uv run --locked heat-adaptation-llm-dataset prepare_plan plan_0001
```

preparation reads native text and uses OCR for detected gaps. add `--no-ocr` to skip recognition. each attempt creates a new folder under `data/processed/<plan_id>/`; earlier preparations remain unchanged.

- `ready`: automatic checks found no problems or review flags.
- `ready_with_gaps`: a reading route exists, with content needing review.
- `failed`: inspect the reported problems before retrying.

check prepared text against the PDF. see [preparation details](IMPLEMENTATION.MD#prepare-text-automatically-investigate-gaps-with-tools) for OCR and image-screening rules.

### run_extract_mode: extract from a saved preparation

use `list_plans` to find the exact preparation path, then run:

```bash
uv run --locked heat-adaptation-llm-dataset run_extract_mode plan_0001 \
  --source-path data/processed/plan_0001/preparation_01/preparation.json \
  --profile inkling2_small_hf_extractor \
  --purpose development
```

inkling receives the prepared plan and can request local document tools. python validates its JSON answer before accepting the run. the terminal prints the saved status and paths. each attempt creates a new folder under `runs/<plan_id>/run_extract_NNNN/`, containing `output.json`, responses, and available tool/validation reports. source accuracy still requires expert review.

- **purpose:** use `development` for development plans. `exploratory` labels runs outside the formal comparison, including deliberate repeats. formal `comparison` execution remains disabled; comparison-plan feedback stays restricted pending the reference workflow.
- **retry:** after fixing a failure, repeat the command with `--retry-of-run-id run_extract_0001`, using the actual failed run ID. earlier attempts are preserved; retries are manual.
- **cancel:** press ctrl+c to retain available evidence and stop. if a record remains `running`, confirm the process has stopped and inspect the files before recovery.

profiles define model settings independently of study set and purpose. see [model configuration and request checks](IMPLEMENTATION.MD#4-hugging-face-configuration-and-requests) and [saved execution details](IMPLEMENTATION.MD#saved-extractor-execution) for limits, schemas, capacity estimates, and failure handling.

### list_plans: find registered plans and preparation paths

```bash
uv run --locked heat-adaptation-llm-dataset list_plans
```

shows each plan's ID, study set, title, preparation status, and path. plans without a preparation show `not_prepared`.

### update_plan_data: correct collection metadata

supply the registered ID and only the fields to change:

```bash
uv run --locked heat-adaptation-llm-dataset update_plan_data plan_0001 --title "Corrected plan title"
```

editable fields are `--title`, `--source-url`, `--date-accessed`, and `--study-set`. omitted values and saved preparations/runs stay unchanged. development assignments are fixed; other study-set changes are allowed only before saved model work.

### help and checks

```bash
uv run --locked heat-adaptation-llm-dataset --help
uv run --locked heat-adaptation-llm-dataset run_extract_mode --help
uv run --locked pytest -q
```

add `--help` to any command for optional flags, including extraction's `--config-path`. use `--project-root "/path/to/project"` after a command to select another project directory. exit codes are 0 for success, 1 for failure, 2 for invalid arguments, and 130 for extraction cancellation.

automated model tests use controlled replies; live compatibility diagnostics are separate. real OCR tests require cached models. passing tests or JSON validation does not establish extraction accuracy.

back up `data/raw/`, `data/processed/`, `runs/`, and `artifacts/` separately; all are excluded from git. the [implementation directory](IMPLEMENTATION.MD#1-file-directory) describes the saved files.
