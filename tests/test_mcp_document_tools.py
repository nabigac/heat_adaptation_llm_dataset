"""Check saved-text tools and a real MCP subprocess, without model requests or OCR.

The PDFs below are blank fixtures. Their prepared text is intentionally fictional:
these tests establish source selection, exact matching, error handling and MCP
delivery, not extraction accuracy or correspondence between OCR text and pixels.
"""

import asyncio
import hashlib
import json
import sys
from io import BytesIO
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from mcp import Client, StdioServerParameters
from PIL import Image
from pypdf import PdfWriter

import document_tools
import models
import storage


PLAN_ID = "plan_0099"
SOURCE_PATH = f"data/prepared_plans/{PLAN_ID}/preparation_02/preparation.json"
EXACT_QUOTE = "Plant 20 trees."


@pytest.fixture
def project(tmp_path):
    """Create a real saved source with native, blank, mixed and unavailable text."""
    root = tmp_path / "project"
    pdf_path = root / f"data/source_pdfs/{PLAN_ID}.pdf"
    pdf_path.parent.mkdir(parents=True)
    with PdfWriter() as writer:
        for _ in range(5):
            writer.add_blank_page(width=100, height=100)
        writer.write(pdf_path)
    checksum = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    preparation = {
        "schema_version": 3, "plan_id": PLAN_ID, "pdf_path": f"data/source_pdfs/{PLAN_ID}.pdf",
        "document_sha256": checksum, "source_url": "https://example.org/saved-plan.pdf",
        "date_accessed": "2026-11-05", "prepared_at": "2026-11-05T12:00:00Z",
        "pages_path": SOURCE_PATH.replace("preparation.json", "pages.json"), "page_count": 5,
        "settings": {"ocr_enabled": True, "ocr_engine": "easyocr", "ocr_version": "fictional-version",
                     "ocr_language": "en", "image_render_dpi": 150, "candidate_image_min_area": 0.1},
        "status": "ready_with_gaps", "problem": "OCR and image-only material need review.",
    }
    texts = ["  Café 2030\r\nPlant 20 trees.\nPlant 20 trees.\nPrinted page 99.\nBoundary",
             "Across pages.\nPreserve\tspacing.\n", "",
             "Native text.\n[Regional OCR supplement]\nPlant 20 trees.\nCost £500,000.", None]
    pages, images = [], {}
    for number, text in enumerate(texts, 1):
        image_path = f"data/prepared_plans/{PLAN_ID}/preparation_02/images/page_{number:04d}.png" if number >= 4 else None
        if image_path:
            with BytesIO() as output:
                Image.new("RGB", (20, 20), "white").save(output, format="PNG")
                images[image_path] = output.getvalue()
        pages.append({
            "page_number": number, "text": text,
            "text_source": "native" if number <= 3 else "mixed" if number == 4 else None,
            "readable": True, "image_available": image_path is not None,
            "image_path": image_path, "image_regions": [],
            "problem": None if number <= 3 else "OCR numbers need checking." if number == 4
            else "Text unavailable; the preserved image is a reading route.",
        })
        if number == 4:
            # Mixed text is valid only with a preserved candidate-region crop.
            # The fixture must satisfy the same source rules as a real preparation.
            crop_path = image_path.replace(".png", "_region_01.png")
            with BytesIO() as output:
                Image.new("RGB", (10, 10), "white").save(output, format="PNG")
                images[crop_path] = output.getvalue()
            pages[-1]["image_regions"] = [{
                "bounds": [0, 0, 10, 10], "area_fraction": 0.25, "image_path": crop_path,
            }]
    storage.save_preparation(root, preparation, pages, artifacts=images)
    storage.save_registry(root, {"schema_version": 1, "plans": [{
        "plan_id": PLAN_ID, "plan_title": "Fictional plan", "pdf_path": preparation["pdf_path"],
        "document_sha256": checksum, "source_url": "https://example.org/later-correction.pdf",
        "date_accessed": "2026-11-06", "study_set": "comparison", "prepared_source_path": SOURCE_PATH,
    }]})
    # This file must never be made available through a document tool.
    private = root / f"runs/{PLAN_ID}/reference_initial.json"
    private.parent.mkdir(parents=True)
    private.write_text('{"expert_only": "unrelated private reference"}')
    return root


def saved_pages(root):
    return json.loads((root / SOURCE_PATH.replace("preparation.json", "pages.json")).read_bytes())


def tools(root, **changes):
    options = {"plan_id": PLAN_ID, "source_path": SOURCE_PATH, **changes}
    return document_tools.PreparedDocumentTools(root, **options)


def snapshot(root):
    return {path.relative_to(root).as_posix(): path.read_bytes()
            for path in root.rglob("*") if path.is_file()}


async def call(root, name, arguments):
    server = document_tools.create_document_tool_server(root, PLAN_ID, source_path=SOURCE_PATH)
    async with Client(server, read_timeout_seconds=5) as client:
        return await client.call_tool(name, arguments)


def test_page_result_preserves_exact_text_physical_number_and_source_notes(project):
    result = tools(project).get_page_text(1)
    assert result["page"] == saved_pages(project)[0]
    assert result["page"]["text"].startswith("  Café 2030\r\n")
    assert result["page"]["page_number"] == 1  # Printed label 99 is just source text.
    assert result["source_path"] == SOURCE_PATH
    assert result["plan_id"] == PLAN_ID
    assert result["page_count"] == 5
    assert result["preparation_status"] == "ready_with_gaps"
    assert result["preparation_problem"] == "OCR and image-only material need review."
    assert result["document_sha256"] == hashlib.sha256((project / f"data/source_pdfs/{PLAN_ID}.pdf").read_bytes()).hexdigest()


def test_blank_unavailable_and_mixed_pages_keep_distinct_saved_meanings(project):
    document = tools(project)
    blank, mixed, unavailable = [document.get_page_text(n)["page"] for n in (3, 4, 5)]
    assert blank["text"] == "" and blank["text_source"] == "native"
    assert mixed["text_source"] == "mixed" and mixed["problem"] == "OCR numbers need checking."
    assert unavailable["text"] is None and unavailable["image_available"] is True
    assert unavailable == saved_pages(project)[4]


@pytest.mark.parametrize("page_number", [0, -1, 6, True, False, "1", 1.0, None, [], "../reference_initial.json"])
def test_python_tool_rejects_invalid_or_out_of_range_page_numbers(project, page_number):
    with pytest.raises(document_tools.DocumentToolError, match="physical PDF pages"):
        tools(project).get_page_text(page_number)


def test_quote_returns_all_matching_pages_once_and_identifies_unknown_text(project):
    result = tools(project).find_quote(EXACT_QUOTE)
    assert result["matching_page_numbers"] == [1, 4]
    assert result["unavailable_page_numbers"] == [5]
    assert result["quote"] == EXACT_QUOTE
    assert result["match_mode"] == "exact_case_sensitive_per_page"
    assert result["source_path"] == SOURCE_PATH


@pytest.mark.parametrize("quote", [
    "OCR and image-only material need review.", "OCR numbers need checking.", SOURCE_PATH,
])
def test_lookup_does_not_treat_preparation_notes_or_file_metadata_as_source_quotations(project, quote):
    assert tools(project).find_quote(quote)["matching_page_numbers"] == []


@pytest.mark.parametrize(("quote", "expected"), [
    ("plant 20 trees.", []), ("Plant  20 trees.", []),
    ("Café 2030\r\nPlant", [1]), ("Café 2030\nPlant", []),
    ("Cafe\u0301 2030", []), (" £500,000.", [4]),
    ("Preserve\tspacing.", [2]), ("Preserve spacing.", []),
    ("  Café", [1]), ("  Plant 20 trees.  ", []),
    ("Boundary\nAcross pages.", []), ("unrelated private reference", []),
])
def test_lookup_preserves_case_whitespace_unicode_and_page_boundaries(project, quote, expected):
    assert tools(project).find_quote(quote)["matching_page_numbers"] == expected


@pytest.mark.parametrize("quote", ["", "  ", "\r\n", None, True, 7, [], b"Plant", "\ud800"])
def test_lookup_rejects_blank_or_nontext_queries(project, quote):
    with pytest.raises(document_tools.DocumentToolError):
        tools(project).find_quote(quote)


def test_results_are_detached_and_calls_never_modify_project_files(project):
    before = snapshot(project)
    document = tools(project)
    result = document.get_page_text(4)
    result["page"]["image_regions"].append({"injected": True})
    result["page"]["text"] = "changed by caller"
    result["plan_id"] = "plan_0001"
    assert document.get_page_text(4)["page"] == saved_pages(project)[3]
    assert document.find_quote(EXACT_QUOTE)["matching_page_numbers"] == [1, 4]
    assert snapshot(project) == before


def test_server_uses_explicit_saved_snapshot_instead_of_newer_registry_selection(project):
    registry = storage.load_registry(project)
    registry["plans"][0]["prepared_source_path"] = SOURCE_PATH.replace("02", "03")
    storage.save_registry(project, registry)
    document = tools(project)
    # Calls keep the validated in-memory snapshot. They do not re-open arbitrary
    # paths or silently refresh if the filesystem is edited while a server runs.
    (project / SOURCE_PATH.replace("preparation.json", "pages.json")).write_text("corrupted after startup")
    assert document.get_page_text(1)["page"]["text"].startswith("  Café 2030")
    assert document.find_quote(EXACT_QUOTE)["matching_page_numbers"] == [1, 4]


@pytest.mark.parametrize("source_path", [
    "../preparation.json", "/tmp/preparation.json", "data/prepared_plans/plan_0001/preparation_02/preparation.json",
    f"runs/{PLAN_ID}/reference_initial.json", SOURCE_PATH.replace("02", "99"),
])
def test_source_selection_cannot_open_unrelated_or_missing_files(project, source_path):
    with pytest.raises(document_tools.DocumentToolError):
        tools(project, source_path=source_path)


def test_source_identity_is_checked_against_actual_pdf_bytes(project):
    with (project / f"data/source_pdfs/{PLAN_ID}.pdf").open("ab") as pdf:
        pdf.write(b"changed original")
    with pytest.raises(document_tools.DocumentToolError, match="checksum"):
        tools(project)


def test_unregistered_plan_and_invalid_preparation_stop_server_construction(project):
    with pytest.raises(document_tools.DocumentToolError):
        tools(project, plan_id="plan_0001")
    preparation = json.loads((project / SOURCE_PATH).read_text())
    preparation["status"] = "failed"
    (project / SOURCE_PATH).write_text(json.dumps(preparation))
    with pytest.raises(document_tools.DocumentToolError):
        document_tools.create_document_tool_server(project, PLAN_ID, source_path=SOURCE_PATH)


def test_unreadable_page_in_ready_preparation_is_rejected_by_shared_loader(project):
    pages = saved_pages(project)
    pages[4]["readable"] = False
    (project / SOURCE_PATH.replace("preparation.json", "pages.json")).write_text(json.dumps(pages))
    with pytest.raises(document_tools.DocumentToolError):
        tools(project)


def test_path_symlink_cannot_escape_selected_project(project, tmp_path):
    source = project / SOURCE_PATH
    outside = tmp_path / "outside-preparation.json"
    outside.write_bytes(source.read_bytes())
    source.unlink()
    source.symlink_to(outside)
    with pytest.raises(document_tools.DocumentToolError, match="outside"):
        tools(project)


def test_invalid_unicode_in_saved_text_is_rejected_before_serving(project):
    pages = saved_pages(project)
    pages[0]["text"] = "bad surrogate: \ud800"
    (project / SOURCE_PATH.replace("preparation.json", "pages.json")).write_text(json.dumps(pages))
    with pytest.raises(document_tools.DocumentToolError):
        tools(project)


def test_version_2_fields_are_retained_without_inventing_version_3_details(project):
    prep = json.loads((project / SOURCE_PATH).read_bytes())
    prep["schema_version"] = 2
    prep["settings"].pop("candidate_image_min_area")
    pages = saved_pages(project)
    for page in pages:
        page.pop("image_path")
        page.pop("image_regions")
        if page["text_source"] == "mixed":
            page["text_source"] = "ocr"
    (project / SOURCE_PATH).write_text(json.dumps(prep))
    (project / prep["pages_path"]).write_text(json.dumps(pages))
    document = tools(project)
    result = document.get_page_text(4)
    assert result["preparation_schema_version"] == 2
    assert result["page"] == pages[3]
    assert "image_regions" not in result["page"]
    assert document.find_quote(EXACT_QUOTE)["matching_page_numbers"] == [1, 4]


def test_real_mcp_discovery_declares_only_two_source_bound_read_only_tools(project):
    async def exercise():
        server = document_tools.create_document_tool_server(project, PLAN_ID, source_path=SOURCE_PATH)
        async with Client(server, read_timeout_seconds=5) as client:
            discovered = {tool.name: tool for tool in (await client.list_tools()).tools}
            assert set(discovered) == {"get_page_text", "find_quote"}
            for name, argument in [("get_page_text", "page_number"), ("find_quote", "quote")]:
                tool = discovered[name]
                assert set(tool.input_schema["properties"]) == {argument}
                assert tool.annotations.read_only_hint is True
                assert tool.annotations.open_world_hint is False
                assert tool.output_schema is not None
                result = await client.call_tool(name, {argument: 4 if name == "get_page_text" else EXACT_QUOTE})
                assert result.is_error is False
                Draft202012Validator(tool.output_schema).validate(result.structured_content)
                # The SDK supplies both JSON for the caller and a text content
                # block suitable for the eventual model-facing tool message.
                assert json.loads(result.content[0].text) == result.structured_content
    asyncio.run(exercise())


@pytest.mark.parametrize(("name", "arguments"), [
    ("get_page_text", {}), ("get_page_text", {"page_number": True}),
    ("get_page_text", {"page_number": "1"}), ("get_page_text", {"page_number": 1.0}),
    ("get_page_text", {"page_number": 0}), ("get_page_text", {"page_number": 6}),
    ("find_quote", {}), ("find_quote", {"quote": ""}), ("find_quote", {"quote": "  "}),
    ("find_quote", {"quote": 20}), ("find_quote", {"quote": None}),
    ("read_file", {"path": "runs/plan_0099/reference_initial.json"}),
])
def test_mcp_invalid_requests_return_error_results_instead_of_successful_answers(project, name, arguments):
    result = asyncio.run(call(project, name, arguments))
    assert result.is_error is True
    assert result.structured_content is None
    assert result.content


def test_extra_mcp_arguments_cannot_switch_the_bound_source(project):
    # The SDK may reject extra arguments or ignore them. Neither behavior may
    # permit access to another plan/file or return expert-reference content.
    result = asyncio.run(call(project, "get_page_text", {
        "page_number": 1, "plan_id": "plan_0001", "source_path": f"runs/{PLAN_ID}/reference_initial.json",
    }))
    if not result.is_error:
        assert result.structured_content["plan_id"] == PLAN_ID
        assert result.structured_content["source_path"] == SOURCE_PATH
        assert result.structured_content["page"] == saved_pages(project)[0]


def test_actual_stdio_subprocess_discovers_calls_and_survives_a_tool_error(project):
    before = snapshot(project)

    async def exercise():
        # Use this environment's interpreter and installed module, with no shell
        # and an unrelated working directory. No model/OCR service is involved.
        parameters = StdioServerParameters(
            command=sys.executable,
            args=["-m", "document_tools", "--project-root", str(project),
                  "--plan-id", PLAN_ID, "--source-path", SOURCE_PATH],
            cwd=project.parent,
        )
        async with asyncio.timeout(15):
            async with Client(parameters, read_timeout_seconds=5) as client:
                assert {tool.name for tool in (await client.list_tools()).tools} == {"get_page_text", "find_quote"}
                bad = await client.call_tool("get_page_text", {"page_number": 6})
                assert bad.is_error is True
                page = await client.call_tool("get_page_text", {"page_number": 4})
                assert page.is_error is False
                assert page.structured_content["page"] == saved_pages(project)[3]
                match = await client.call_tool("find_quote", {"quote": EXACT_QUOTE})
                assert match.is_error is False
                assert match.structured_content["matching_page_numbers"] == [1, 4]
                assert match.structured_content["unavailable_page_numbers"] == [5]
        # Leaving the client context closes the pipes and shuts down its server.
    asyncio.run(exercise())
    assert snapshot(project) == before


def test_entry_point_requires_explicit_selection_and_reports_startup_errors(project, capsys):
    with pytest.raises(SystemExit) as missing:
        document_tools.main([])
    assert missing.value.code == 2
    assert capsys.readouterr().out == ""
    with pytest.raises(SystemExit) as broken:
        document_tools.main(["--project-root", str(project), "--plan-id", PLAN_ID,
                             "--source-path", f"runs/{PLAN_ID}/reference_initial.json"])
    assert broken.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Cannot load selected document tools" in captured.err


def test_discovered_sdk_catalogue_converts_to_model_tools_without_rewriting_argument_rules(project):
    async def exercise():
        server = document_tools.create_document_tool_server(project, PLAN_ID, source_path=SOURCE_PATH)
        async with Client(server, read_timeout_seconds=5) as client:
            discovered = (await client.list_tools()).tools
        catalogue = [tool.model_dump(mode="json", by_alias=True) for tool in discovered]
        converted = models.prepare_document_tools(catalogue)
        assert [tool["function"]["name"] for tool in converted] == [tool.name for tool in discovered]
        for tool, original in zip(converted, discovered, strict=True):
            assert tool["function"]["parameters"] == original.input_schema
        page = next(tool for tool in converted if tool["function"]["name"] == "get_page_text")
        assert page["function"]["parameters"]["properties"]["page_number"]["minimum"] == 1
    asyncio.run(exercise())
