# heat adaptation LLM dataset

this research study will develop and evaluate a workflow that pairs open-weight large language models (LLMs) with heat adaptation experts to extract structured, source-linked data from government heat adaptation plans. it will document practical lessons from building the workflow and examine whether adding a verifier agent improves extraction quality and changes expert review requirements.

## project documents

- [technical design draft](DESIGN.md): proposed implementation and evaluation approach.
- [structured change log](CHANGELOG.md): decisions, changes, and lessons learned during the study.

## command line interface

the CLI registers PDFs, updates collection metadata, prepares page text, and lists registered documents with preparation status. model processing, expert files, and analysis are planned steps described in the design.

each preparation saves `preparation.json` for its metadata, settings, and status, and `pages.json` for page text, text sources, and problems. these files are kept together in a separate folder for each preparation, with an `images/` folder when page images or candidate crops are produced.

### set up the environment

with [uv](https://docs.astral.sh/uv/getting-started/installation/) installed, open a terminal in the project directory and run:

```bash
uv sync --locked
```

this uses the project's Python version setting, creates or updates `.venv`, and installs the locked dependencies and CLI. the commands below use `uv run`, so activating `.venv` manually is optional.

### register a new PDF

experts screen documents before import using the [eligibility rules in the design](DESIGN.md#2-plans-and-extracted-content). the software accepts prescreened documents without asking for eligibility confirmation. start with a development plan.

keep the downloaded PDF outside `data/raw/`, for example in Downloads. record its title, official source URL, access date, and study set. then run the following from the project directory, replacing the example path, title, URL, and date with the actual collection details:

```bash
uv run --locked heat-adaptation-llm-dataset add \
  "$HOME/Downloads/your-plan.pdf" \
  --title "Your plan title" \
  --source-url "OFFICIAL_SOURCE_URL" \
  --date-accessed "YYYY-MM-DD" \
  --study-set development
```

keep paths and titles in quotes when they contain spaces. the access date is the date the source was accessed, written as `YYYY-MM-DD`. the study set must be `development`, `comparison`, or `expansion`.

registration assigns a document ID, preserves an unchanged copy at `data/raw/<plan_id>.pdf`, and saves collection details and a SHA-256 checksum in `data/registry/plans.json`. this registry is the index of document records; the PDFs are separate files. back up preserved PDFs and preparations separately because `data/raw/` and `data/processed/` are excluded from Git.

importing identical contents again returns the existing record without changing its metadata. a conflicting study set is rejected. a revised PDF with different contents gets a new document ID; the earlier original remains unchanged.

### update collection metadata

use the registered document ID to correct collection details without importing the PDF again. supply only the fields that should change, replacing these example values with the actual corrections:

```bash
uv run --locked heat-adaptation-llm-dataset update plan_0001 \
  --title "Corrected plan title" \
  --source-url "https://example.org/corrected-plan.pdf" \
  --date-accessed "2026-11-02"
```

the editable fields are `--title`, `--source-url`, `--date-accessed`, and `--study-set`. at least one is required; omitted fields retain their saved values. all proposed values are checked before saving, so an invalid field rejects the entire update. supplying values already saved reports no changes and does not replace the registry.

the command changes the registry only. document IDs, PDF paths, checksums, and preparation links are managed by the workflow. saved originals, preparations, and model work remain unchanged. new preparations copy the current source URL and access date; titles and study sets remain in the registry. the software checks URL syntax, while experts remain responsible for source provenance.

development assignments remain fixed to keep those plans outside comparison. other study-set assignments can be corrected with `--study-set development`, `--study-set comparison`, or `--study-set expansion` before any model work is saved for that plan. once model work exists, study-set changes are rejected. title, URL, and access-date corrections remain available.

### prepare a registered PDF

initialize the English OCR models once after installing the environment:

```bash
uv run --locked python -c "from document_tools import EasyOcrReader; EasyOcrReader(download_models=True)"
```

this downloads EasyOCR's detection and English recognition models into `.cache/easyocr/`, which is excluded from Git. normal preparation uses these cached models without downloading during a run. no LLM model is needed for this step.

prepare a document by its registered ID:

```bash
uv run --locked heat-adaptation-llm-dataset prepare plan_0001
```

native extraction is the first choice. rendering defaults to 150 DPI. preparation also checks for individual image regions occupying at least 10% of the visible page with no native text inside their bounds. these regions are candidates for missing content; photographs can qualify, while smaller charts and images with partial text layers can be missed. the rule does not certify completeness or repair table reading order.

pages with detected text failures receive full-page OCR. candidate regions on otherwise readable pages receive OCR of their crops, appended after the unchanged native text with a labeled separator. page text is stored once, with `text_source` set to `native`, `ocr`, `mixed`, or null when unavailable. known blank pages and native pages without candidates or problems do not load OCR models. preparation settings record the configured engine, installed package version, language, rendering DPI, and candidate area threshold.

affected pages are preserved as PNGs under the new preparation's `images/` folder, together with crops of candidate regions when rendering and cropping succeed. `pages.json` records their paths, crop bounds, and candidate areas. crop bounds are pixel coordinates measured from the top-left of the saved page image. missing or damaged referenced PNGs stop loading, rather than silently removing the image route. candidates retain review notes after successful OCR; no recognized OCR text does not prove an image has no information.

the command shows status, page count, saved paths, and problems. `ready` means automatic checks found no problems or review flags. `ready_with_gaps` means each page has a usable reading route, but some text or image content needs review; it includes successful OCR awaiting review, not only confirmed missing text. `failed` means a reliable page count or required image route could not be established, or a page has no usable reading route.

`ready` and `ready_with_gaps` return exit code 0; a saved `failed` preparation returns 1 and prints a manual retry command. known PDF-reading and rendering failures are saved when possible. identity, validation, or storage errors also return 1 and may prevent a complete preparation from being saved. invalid command arguments return 2. earlier completed attempts remain unchanged. OCR can misread text and layout, so inspect prepared text against the original PDF during development. an image-only gap still requires tested model image support or a working OCR route before model processing.

to explicitly skip automatic OCR while keeping native extraction and image checks:

```bash
uv run --locked heat-adaptation-llm-dataset prepare plan_0001 --no-ocr
```

each preparation creates a new numbered folder and updates the registry link. new preparations use format version 3; version 2 records remain readable without rewriting. earlier preparations and the original PDF remain unchanged. later agent-requested OCR will be exposed through MCP and saved with its run.

### list registered documents

```bash
uv run --locked heat-adaptation-llm-dataset list
```

the listing shows each document's ID, study set, preparation status, and title, followed by its linked preparation path when present. status is `not_prepared`, `ready`, `ready_with_gaps`, or `failed`. it is read from the exact preparation linked in the registry, rather than inferred from file existence or the newest folder. damaged linked data produces an error instead of a readiness label. registration and preparation are separate commands.

these commands use the current directory as the project root. pass `--project-root` after the command to select another data location:

```bash
uv run --locked heat-adaptation-llm-dataset list --project-root "/path/to/project"
```

### help and checks

```bash
uv run --locked heat-adaptation-llm-dataset --help
uv run --locked heat-adaptation-llm-dataset add --help
uv run --locked heat-adaptation-llm-dataset update --help
uv run --locked heat-adaptation-llm-dataset prepare --help
uv run --locked heat-adaptation-llm-dataset list --help
```

run the automated checks with:

```bash
uv run --locked pytest -q
```

most checks use controlled data and temporary projects. two OCR integration checks use the cached English models and are skipped when those models are unavailable; they do not download models during testing. passing checks establish the tested behavior, not complete or accurate extraction from every PDF.
