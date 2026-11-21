# heat adaptation LLM dataset

this research project examines how heat adaptation experts and open-weight large language models (LLMs) can be paired to build an extraction workflow. it will share practical lessons from the expert judgments, model outputs, and revisions involved in developing that workflow. the project uses open-weight models through hugging face.

the workflow extracts heat adaptation actions from government and public agency plans into structured records with supporting quotations. the study explores two configurations: **E** (extraction) and **E+V** (extraction + verification). **inkling 2 small** is the extractor in both configurations. **deepseek v4.1 flash 1017** checks and revises that exact saved extraction. both models use hugging face with deepinfra as the fixed host; formal assessment of verification quality remains pending. expert-curated answers will also support a pilot instruction dataset for possible future fine-tuning.

for setup and commands, see [getting started](#getting-started) and the [command line interface](#command-line-interface).

## project documents

- [design document](DESIGN.md): research objectives, methods, action fields, coding rules, and evaluation measures.
- [implementation document](IMPLEMENTATION.MD): current implementation, file directory, and technical details.
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

create a hugging face access token with inference providers permission and add account credits or billing. both model stages use this token.

in bash or zsh, run the following command, paste the token when the terminal waits, and press enter. token input is hidden:

```bash
read -r -s HF_TOKEN
```

then export it for commands in that terminal session:

```bash
export HF_TOKEN
```

run model commands in that same terminal session. the program reads `HF_TOKEN` from the environment; it does not load `.env` files automatically or save authentication headers.

### compatibility check

use these checks when changing models or hosting. the configured extractor and verifier have passed; checks are not needed for each plan.

check inkling with up to three **paid requests** using fictional inputs:

```bash
uv run --locked python -m huggingface_check
```

check deepseek, including a tool round trip, with up to five paid requests:

```bash
uv run --locked python -m huggingface_check \
  --model deepseek-ai/DeepSeek-V4.1-Flash-1017 \
  --check-tools
```

`--model` changes only the diagnostic, not the extraction profile. reports go to `artifacts/huggingface_checks/`. see the [diagnostic details](IMPLEMENTATION.MD#compatibility-diagnostics); compatibility does not establish full-plan quality.

for project-schema failures, `--isolate-project-schema` instead runs up to two paid request variants. use it without `--check-tools`; both results are saved even if one fails.

## command line interface

the usual workflow is `add_plan` → `prepare_plan` → `run_extract_mode` → `run_verify_mode`. use `list_plans` for IDs and preparation paths, and `update_plan_data` for metadata corrections. run commands from the project directory.

### add_plan: register a PDF

[screen eligibility](DESIGN.md#eligible-plans), then replace the example path and collection details:

```bash
uv run --locked heat-adaptation-llm-dataset add_plan \
  "$HOME/Downloads/your-plan.pdf" \
  --title "your plan title" \
  --source-url "https://example.org/your-plan.pdf" \
  --date-accessed "YYYY-MM-DD" \
  --study-set development
```

keep the supplied PDF outside `data/raw/`. registration copies it there and assigns a plan ID; identical PDFs reuse the existing record. study sets are `development`, `comparison`, and `expansion` (deferred).

### prepare_plan: prepare page text

```bash
uv run --locked heat-adaptation-llm-dataset prepare_plan plan_0001
```

uses native text and selective OCR; add `--no-ocr` to skip recognition. each attempt creates a new preparation folder. check the text against the PDF: `ready` means no automatic flags, `ready_with_gaps` needs review, and `failed` needs investigation before extraction. see [preparation details](IMPLEMENTATION.MD#prepare-text-automatically-investigate-gaps-with-tools).

### run_extract_mode: extract actions

use the exact preparation path shown by `list_plans`:

```bash
uv run --locked heat-adaptation-llm-dataset run_extract_mode plan_0001 \
  --source-path data/processed/plan_0001/preparation_01/preparation.json \
  --profile inkling2_small_hf_extractor \
  --purpose development
```

### run_verify_mode: verify a saved extraction

```bash
uv run --locked heat-adaptation-llm-dataset run_verify_mode plan_0001 \
  --profile deepseek_v4_1_flash_1017_hf_verifier \
  --purpose development
```

uses the latest validated, successful eligible E run and its exact preparation. add `--input-run-id run_extract_0008` to select a particular E run, including for consistent prompt comparisons.

### create_expert_reference: start an expert form

```bash
uv run --locked heat-adaptation-llm-dataset create_expert_reference plan_0001 \
  --prepared-by "your name or study ID"
```

saves `expert_references/plan_0001/expert_reference.json` with registered collection metadata and an empty action list. repeat `--prepared-by` for multiple experts. complete the form from the original PDF; for comparison plans, do so before viewing model outputs. requires registration only, makes no API calls, and refuses to overwrite an existing form.

### validate_expert_reference: check an expert form

```bash
uv run --locked heat-adaptation-llm-dataset validate_expert_reference plan_0001
```

checks the saved form's JSON, fields, registered plan ID, source URL/access date, unique action IDs, and physical page bounds against the original PDF. reports problems without changing files or calling the API. an empty action list is flagged but can pass structural checks; experts establish accuracy and completeness.

### list_plans: find IDs and preparation paths

```bash
uv run --locked heat-adaptation-llm-dataset list_plans
```

shows ID, study set, title, preparation status, and path; plans without preparation show `not_prepared`.

### update_plan_data: correct metadata

```bash
uv run --locked heat-adaptation-llm-dataset update_plan_data plan_0001 --title "corrected plan title"
```

editable fields are `--title`, `--source-url`, `--date-accessed`, and `--study-set`. omitted fields and saved preparations/runs are preserved. development assignments are fixed; other study-set changes require no saved model work.

### run options and results

use `--purpose development` for development plans or `exploratory` for investigations outside the formal comparison. formal comparison execution remains disabled; comparison-plan content is restricted pending the independent-reference workflow.

| optional flag | use |
| --- | --- |
| `--retry-of-run-id <failed_run_id>` | E/V: link a new attempt to a failed run. verifier retries retain their original E input. omit for a new development repeat. |
| `--config-path <path>` | E/V: select another project-relative profile file; default `configs/profiles.json`. |
| `--project-root "/path/to/project"` | any command: select another project directory; place after the command name. |

E and V print their saved status, selected inputs, and available report paths. each invocation preserves a new folder under `runs/<plan_id>/run_extract_NNNN/` or `run_verify_NNNN/`. both apply final JSON validation and quotation checks; source accuracy requires expert review. see [execution details](IMPLEMENTATION.MD#saved-execution) for files, limits, and failure handling.

press ctrl+c to request cancellation. a record left `running` needs inspection after confirming the process has stopped; recovery and retries are manual.

### help and checks

```bash
uv run --locked heat-adaptation-llm-dataset --help
uv run --locked heat-adaptation-llm-dataset run_verify_mode --help
uv run --locked pytest -q
```

add `--help` to any command for all flags. exit codes: 0 success, 1 failure, 2 invalid arguments, 130 model-run cancellation. automated model tests use controlled replies; real OCR tests require cached models. passing checks does not establish factual accuracy.

back up `data/raw/`, `data/processed/`, `expert_references/`, `runs/`, and `artifacts/` separately; all are excluded from git. see the [file directory](IMPLEMENTATION.MD#1-file-directory).
