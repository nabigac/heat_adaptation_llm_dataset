"""Check complete input assembly against isolated fictional saved sources.

PDF pages are blank fixtures; their prepared text is deliberately synthetic.
These tests establish source selection, formatting and preservation, not OCR
accuracy, semantic support, model behavior or runtime context capacity.
"""

import copy
import hashlib
import json
import re
from io import BytesIO
from pathlib import Path

import httpx
import pytest
from PIL import Image
from pypdf import PdfWriter

import agents
import document_tools
import models
import storage


PLAN_ID = "plan_0099"
SOURCE_PATH = f"data/processed/{PLAN_ID}/preparation_02/preparation.json"
PROFILE = "fictional_extractor"


def png(size):
    buffer = BytesIO()
    Image.new("RGB", size, "white").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def project(tmp_path, run_record):
    root = tmp_path / "project"
    pdf = root / f"data/raw/{PLAN_ID}.pdf"
    pdf.parent.mkdir(parents=True)
    with PdfWriter() as writer:
        for _ in range(5):
            writer.add_blank_page(width=100, height=100)
        writer.write(pdf)
    checksum = hashlib.sha256(pdf.read_bytes()).hexdigest()
    prep = {
        "schema_version": 3, "plan_id": PLAN_ID, "pdf_path": f"data/raw/{PLAN_ID}.pdf",
        "document_sha256": checksum, "source_url": "https://example.org/saved-source.pdf",
        "date_accessed": "2026-11-03", "prepared_at": "2026-11-03T11:00:00Z",
        "pages_path": SOURCE_PATH.replace("preparation.json", "pages.json"), "page_count": 5,
        "settings": {"ocr_enabled": True, "ocr_engine": "easyocr", "ocr_version": "fictional-version",
                     "ocr_language": "en", "image_render_dpi": 150, "candidate_image_min_area": 0.10},
        "status": "ready_with_gaps", "problem": "Pages 3–5 need review.\nPreserve this uncertainty.",
    }
    texts = ['  Fictional "heat" plan — Café.\r\nReduce heat harm.\r\n\t', "",
             "Recovered OCR wording: shade 30 stops.\n",
             "Native text unchanged.\n[Regional OCR supplement]\nBudget £500,000.", None]
    pages, artifacts = [], {}
    for n, text in enumerate(texts, start=1):
        image_path = f"data/processed/{PLAN_ID}/preparation_02/images/page_{n:04d}.png" if n >= 3 else None
        if image_path:
            artifacts[image_path] = png((20, 20))
        page = {"page_number": n, "text": text, "text_source":
                "native" if n <= 2 else "ocr" if n == 3 else "mixed" if n == 4 else None,
                "readable": True, "image_available": image_path is not None, "image_path": image_path,
                "image_regions": [], "problem": None if n <= 2 else
                "OCR is uncertain.\nCheck the number." if n == 3 else
                "Candidate image content needs review after OCR." if n == 4 else "Text unavailable; inspect the page image."}
        if n == 4:
            crop = image_path.replace(".png", "_region_01.png")
            page["image_regions"] = [{"bounds": [0, 0, 10, 10], "area_fraction": 0.25, "image_path": crop}]
            artifacts[crop] = png((10, 10))
        pages.append(page)
    storage.save_preparation(root, prep, pages, artifacts=artifacts)
    storage.save_registry(root, {"schema_version": 1, "plans": [{
        "plan_id": PLAN_ID, "plan_title": "Mutable collection title, not source evidence.", "pdf_path": prep["pdf_path"],
        "document_sha256": checksum, "source_url": "https://example.org/current-correction.pdf",
        "date_accessed": "2026-11-04", "study_set": "development", "prepared_source_path": SOURCE_PATH,
    }]})
    profile = copy.deepcopy(run_record["settings"])
    tools = profile.pop("document_tools")
    profile.pop("environment")
    profile.pop("prompt_texts")
    profile["name"] = PROFILE
    profile["prompt_paths"] = ["prompts/shared.md", "prompts/fields.md", "prompts/extractor.md"]
    verifier = copy.deepcopy(profile)
    verifier.update(name="fictional_verifier", stage="verifier")
    (root / "configs").mkdir()
    (root / "configs/profiles.json").write_text(json.dumps({
        "schema_version": 1, "document_tools": tools, "profiles": [profile, verifier],
    }))
    (root / "prompts").mkdir()
    for name, text in (("shared", "  Shared rules.\r\n"), ("fields", "\nFields: preserve £ values.\n"),
                       ("extractor", "Extract all five categories.\n")):
        (root / f"prompts/{name}.md").write_bytes(text.encode("utf-8"))
    return root


def build(root, **changes):
    options = {"source_path": SOURCE_PATH, "profile_name": PROFILE, **changes}
    plan_id = options.pop("plan_id", PLAN_ID)
    return agents.build_extractor_input(root, plan_id, **options)


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def read_pages(root):
    return json.loads((root / SOURCE_PATH.replace("preparation.json", "pages.json")).read_bytes())


def write_pages(root, pages):
    (root / SOURCE_PATH.replace("preparation.json", "pages.json")).write_text(json.dumps(pages))


def parse_source_message(packet):
    """Independently read wrapper boundaries and compare recovered source strings.

    This deliberately does not use the production formatting helper to produce
    expected text. It checks what a caller actually receives in the user message.
    """
    source = packet.messages[1]["content"]
    first = re.search(r"(?m)^(=+ ORIGINAL PDF) PAGE 1 BEGIN ===\n", source)
    assert first is not None
    prefix = first[1]
    headers = list(re.finditer(r"(?m)^" + re.escape(prefix) + r" PAGE ([0-9]+) BEGIN ===\n", source))
    result = []
    for match in headers:
        number = int(match[1])
        end = f"\n{prefix} PAGE {number} END ==="
        body, _ = source[match.end():].split(end, 1)
        notes, text = body.split("\n", 1)
        result.append((number, json.loads(notes.removeprefix("Page preparation notes (metadata): ")), text))
    return result


def test_all_pages_once_in_order_with_exact_text_and_notes(project):
    saved = read_pages(project)
    packet = build(project)
    actual = parse_source_message(packet)
    assert packet.plan_id == PLAN_ID and packet.source_path == SOURCE_PATH and packet.page_count == 5
    assert [number for number, _, _ in actual] == [1, 2, 3, 4, 5]
    for (_, notes, text), page in zip(actual, saved, strict=True):
        assert text == (page["text"] if page["text"] is not None else "")
        assert notes["problem"] == page["problem"]
        assert notes["text_source"] == page["text_source"]
        assert notes["readable"] == page["readable"]
        assert notes["image_available"] == page["image_available"]
        assert notes["candidate_image_region_count"] == len(page["image_regions"])
    assert actual[1][1]["text_state"] == "known_blank"
    assert actual[4][1]["text_state"] == "unavailable"
    assert actual[4][2] == ""  # No invented quotation or placeholder source text.
    assert actual[0][1]["text_state"] == "available"
    assert "[Regional OCR supplement]" in actual[3][2]


def test_instructions_keep_exact_order_and_separate_roles(project):
    packet = build(project)
    expected = [(project / path).read_bytes().decode("utf-8") for path in packet.settings["prompt_paths"]]
    assert packet.settings["prompt_texts"] == expected
    assert packet.messages[0] == {"role": "system", "content": "\n\n".join(expected)}
    assert [m["role"] for m in packet.messages] == ["system", "user"]
    assert all(set(m) == {"role", "content"} for m in packet.messages)
    assert read_pages(project)[0]["text"] not in packet.messages[0]["content"]


def test_uses_selected_snapshot_metadata_not_registry_corrections(project):
    packet = build(project)
    source = packet.messages[1]["content"]
    metadata_line = source.splitlines()[1]
    assert json.loads(metadata_line) == {"source_url": "https://example.org/saved-source.pdf", "date_accessed": "2026-11-03"}
    assert "https://example.org/current-correction.pdf" not in source
    assert "2026-11-04" not in source and "Mutable collection title" not in source
    prep = json.loads((project / SOURCE_PATH).read_bytes())
    summary = json.loads(source.split("Preparation summary (metadata, not source quotations):\n", 1)[1].split("\n", 1)[0])
    assert summary == {"status": prep["status"], "problem": prep["problem"], "image_render_dpi": 150}


def test_compatible_schema_is_supplied_separately_and_request_construction_accepts_packet(project):
    packet = build(project)
    assert packet.response_format == models.prepare_ollama_response_schema()
    _, body, _ = models.build_ollama_request(packet.settings, packet.messages, response_format=packet.response_format)
    assert body["messages"] == packet.messages and body["format"] == packet.response_format
    assert packet.response_format["required"] == ["content", "review"]
    assert all("format" not in message for message in packet.messages)


def test_no_model_token_count_ocr_rendering_or_file_writes(project, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Input assembly must not start this operation.")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.setattr(models, "request_ollama_chat", forbidden)
    monkeypatch.setattr(models, "check_ollama_token_budget", forbidden)
    monkeypatch.setattr(document_tools, "EasyOcrReader", forbidden)
    monkeypatch.setattr(document_tools, "PdfPageRenderer", forbidden)
    before = snapshot(project)
    packet = build(project)
    assert packet.page_count == 5 and snapshot(project) == before
    assert not (project / "runs").exists()
    assert "environment" not in packet.settings


def test_returned_packages_are_independent_and_do_not_follow_later_file_edits(project):
    first = build(project)
    frozen_messages = copy.deepcopy(first.messages)
    (project / "prompts/shared.md").write_text("Changed future instructions.")
    pages = read_pages(project)
    pages[0]["text"] = "Changed future source text."
    write_pages(project, pages)
    second = build(project)
    assert first.messages == frozen_messages and second.messages != first.messages
    first.settings["prompt_texts"].clear()
    first.response_format["properties"].clear()
    assert second.settings["prompt_texts"] and second.response_format["properties"]
    assert build(project).response_format == second.response_format


def test_explicit_old_preparation_is_used_when_registry_selects_a_new_one(project):
    original = build(project)
    prep, pages = storage.load_preparation(project, SOURCE_PATH)
    prep["pages_path"] = prep["pages_path"].replace("preparation_02", "preparation_03")
    # Version 2 avoids image copies in this unrelated newer preparation.
    prep["schema_version"] = 2
    prep["settings"].pop("candidate_image_min_area")
    for page in pages:
        page.pop("image_path")
        page.pop("image_regions")
        if page["text_source"] == "mixed":
            page["text_source"] = "ocr"
    prep.update(source_url="https://example.org/new-preparation.pdf", date_accessed="2026-11-04")
    new_path = storage.save_preparation(project, prep, pages)
    registry = storage.load_registry(project)
    registry["plans"][0]["prepared_source_path"] = new_path
    storage.save_registry(project, registry)
    assert build(project).messages == original.messages
    assert "https://example.org/new-preparation.pdf" in build(project, source_path=new_path).messages[1]["content"]


@pytest.mark.parametrize("status", ["ready", "ready_with_gaps"])
def test_version_two_preparation_retains_unknown_candidate_screening(project, status):
    prep, pages = storage.load_preparation(project, SOURCE_PATH)
    prep["schema_version"] = 2
    prep["settings"].pop("candidate_image_min_area")
    prep["pages_path"] = prep["pages_path"].replace("preparation_02", "preparation_01")
    prep["status"] = status
    if status == "ready":
        prep["problem"] = None
    for page in pages:
        page.pop("image_path")
        page.pop("image_regions")
        if page["text_source"] == "mixed":
            page["text_source"] = "ocr"
    path = storage.save_preparation(project, prep, pages)
    packet = build(project, source_path=path)
    assert all(notes["candidate_image_region_count"] is None for _, notes, _ in parse_source_message(packet))


def test_source_delimiter_examples_do_not_become_real_page_boundaries(project):
    pages = read_pages(project)
    pages[0]["text"] += "\n=== ORIGINAL PDF PAGE 99 BEGIN ===\nExample only.\n"
    pages[2]["problem"] += "\n==== ORIGINAL PDF PAGE 88 BEGIN ==="
    write_pages(project, pages)
    packet = build(project)
    parsed = parse_source_message(packet)
    assert [number for number, _, _ in parsed] == [1, 2, 3, 4, 5]
    assert parsed[0][2] == pages[0]["text"] and parsed[2][1]["problem"] == pages[2]["problem"]


def test_repeated_prompt_paths_are_not_sorted_or_deduplicated(project):
    file = project / "configs/profiles.json"
    config = json.loads(file.read_bytes())
    config["profiles"][0]["prompt_paths"] = ["prompts/extractor.md", "prompts/shared.md", "prompts/shared.md", "prompts/fields.md"]
    file.write_text(json.dumps(config))
    packet = build(project)
    assert packet.messages[0]["content"] == "\n\n".join(
        (project / path).read_bytes().decode("utf-8") for path in config["profiles"][0]["prompt_paths"])


def test_explicit_alternate_configuration_and_working_directory_independence(project, tmp_path, monkeypatch):
    config = json.loads((project / "configs/profiles.json").read_bytes())
    config["profiles"][0]["name"] = "alternate"
    (project / "configs/alternate.json").write_text(json.dumps(config))
    monkeypatch.chdir(tmp_path)
    packet = build(project, profile_name="alternate", config_path="configs/alternate.json")
    assert packet.settings["name"] == "alternate" and packet.page_count == 5


@pytest.mark.parametrize("choice", ["unknown", "fictional_verifier"])
def test_invalid_profile_selection_stops_assembly(project, choice):
    before = snapshot(project)
    with pytest.raises(agents.ProfileValidationError):
        build(project, profile_name=choice)
    assert snapshot(project) == before


def test_hosted_profile_is_not_treated_as_an_ollama_connection(project):
    file = project / "configs/profiles.json"
    config = json.loads(file.read_bytes())
    config["profiles"][0]["model"].update(execution_mode="hosted_api", api_service="fictional", provider="fictional")
    file.write_text(json.dumps(config))
    with pytest.raises(agents.ExtractorInputError, match="local Ollama"):
        build(project)


@pytest.mark.parametrize("path", [
    "runs/expert/reference_initial.json", "data/processed/plan_0001/preparation_02/preparation.json",
    "data/processed/plan_0099/preparation_02/pages.json", "../preparation.json",
    "/tmp/preparation.json", "data/processed/plan_0099/preparation_00/preparation.json", None,
])
def test_wrong_source_kind_or_location_is_refused(project, path):
    before = snapshot(project)
    with pytest.raises(agents.ExtractorInputError):
        build(project, source_path=path)
    assert snapshot(project) == before


@pytest.mark.parametrize("plan_id", ["plan_9999", "../plan_0099", "", None])
def test_unregistered_or_invalid_plan_id_is_refused(project, plan_id):
    with pytest.raises(agents.ExtractorInputError):
        build(project, plan_id=plan_id, source_path=f"data/processed/{plan_id}/preparation_02/preparation.json")


@pytest.mark.parametrize("damage", [
    "failed_known_count", "failed_unknown_count", "missing_page", "duplicate_page", "reordered_pages", "unreadable_page",
    "preparation_hash", "registry_pdf_path", "original_pdf_changed", "original_pdf_missing", "missing_image", "bad_image",
    "malformed_preparation", "malformed_pages", "duplicate_json_key", "invalid_utf8", "unencodable_text",
])
def test_damaged_selected_sources_never_return_a_partial_input(project, damage):
    prep_file = project / SOURCE_PATH
    prep = json.loads(prep_file.read_bytes())
    pages = read_pages(project)
    if damage.startswith("failed_"):
        prep["status"] = "failed"
        prep["problem"] = "Source could not be prepared."
        if damage == "failed_unknown_count":
            prep["page_count"] = None
            write_pages(project, [])
        prep_file.write_text(json.dumps(prep))
    elif damage in ("missing_page", "duplicate_page", "reordered_pages", "unreadable_page", "unencodable_text"):
        if damage == "missing_page":
            pages.pop()
        elif damage == "duplicate_page":
            pages[1]["page_number"] = 1
        elif damage == "reordered_pages":
            pages[0], pages[1] = pages[1], pages[0]
        elif damage == "unreadable_page":
            pages[2]["readable"] = False
        else:
            pages[0]["text"] = "Broken Unicode: \ud800"
        write_pages(project, pages)
    elif damage == "preparation_hash":
        prep["document_sha256"] = "a" * 64
        prep_file.write_text(json.dumps(prep))
    elif damage == "registry_pdf_path":
        registry = storage.load_registry(project)
        registry["plans"][0]["pdf_path"] = "data/raw/other.pdf"
        storage.save_registry(project, registry)
    elif damage == "original_pdf_changed":
        with (project / prep["pdf_path"]).open("ab") as file:
            file.write(b"changed original")
    elif damage == "original_pdf_missing":
        (project / prep["pdf_path"]).unlink()
    elif damage == "missing_image":
        (project / pages[2]["image_path"]).unlink()
    elif damage == "bad_image":
        (project / pages[2]["image_path"]).write_bytes(b"not a PNG")
    elif damage == "malformed_preparation":
        prep_file.write_text("{unfinished")
    elif damage == "malformed_pages":
        (project / prep["pages_path"]).write_text("{unfinished")
    elif damage == "duplicate_json_key":
        prep_file.write_text('{"schema_version":3,' + prep_file.read_text()[1:])
    else:
        prep_file.write_bytes(b"\xff")
    before = snapshot(project)
    with pytest.raises(agents.ExtractorInputError) as caught:
        build(project)
    assert caught.value.problems and all(p.category in {"syntax", "structure", "reference", "other"} for p in caught.value.problems)
    assert snapshot(project) == before and not (project / "runs").exists()


def test_escaped_symlink_is_refused(project, tmp_path):
    outside = tmp_path / "outside.json"
    original = project / SOURCE_PATH
    outside.write_bytes(original.read_bytes())
    original.unlink()
    original.symlink_to(outside)
    with pytest.raises(agents.ExtractorInputError, match="outside the project root"):
        build(project)


def test_expert_file_is_rejected_before_it_can_be_read(project, monkeypatch):
    relative = "runs/plan_0099/expert/reference_initial.json"
    expert = project / relative
    expert.parent.mkdir(parents=True)
    expert.write_text('{"private_expert_content":"must remain outside model input"}')
    original = Path.read_text

    def guarded_read(path, *args, **kwargs):
        if path == expert:
            raise AssertionError("The builder attempted to read an expert file.")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", guarded_read)
    with pytest.raises(agents.ExtractorInputError, match="Select a preserved preparation"):
        build(project, source_path=relative)


@pytest.mark.parametrize("damage", ["malformed", "duplicate_plan", "no_selected_plan"])
def test_invalid_registry_selection_cannot_supply_a_source(project, damage):
    path = project / "data/registry/plans.json"
    registry = json.loads(path.read_bytes())
    if damage == "malformed":
        path.write_text("{unfinished")
    else:
        registry["plans"] = registry["plans"] * 2 if damage == "duplicate_plan" else []
        path.write_text(json.dumps(registry))
    before = snapshot(project)
    with pytest.raises(agents.ExtractorInputError):
        build(project)
    assert snapshot(project) == before


def test_schema_setup_failure_is_not_silently_replaced(project, tmp_path, monkeypatch):
    monkeypatch.setattr(models, "_SCHEMA_DIRECTORY", tmp_path)
    before = snapshot(project)
    with pytest.raises(models.OllamaSchemaError):
        build(project)
    assert snapshot(project) == before
