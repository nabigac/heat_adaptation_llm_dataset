"""Check CLI commands against temporary projects and the shared workflow code."""
# Most tests call cli.main with an argument list inside this process. capsys
# captures stdout/stderr so normal output and errors can be checked separately.
# The final subprocess tests additionally check the real command's exit status.

import subprocess
import sys
from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

import cli
import storage


@pytest.fixture
def project(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    return root


@pytest.fixture
def add_arguments(project: Path, tmp_path: Path) -> list[str]:
    # Return the complete command arguments, including the temporary project
    # root. Tests can remove/change one option while keeping the rest valid.
    pdf = tmp_path / "incoming plan.pdf"
    # Registration fixtures establish byte preservation, not PDF readability.
    pdf.write_bytes(b"%PDF-1.4\nFictional CLI registration fixture\n%%EOF\n")
    return [
        "add",
        str(pdf),
        "--project-root",
        str(project),
        "--title",
        "Example Heat Plan — 2026",
        "--source-url",
        "https://example.org/heat-plan.pdf",
        "--date-accessed",
        "2026-11-02",
        "--study-set",
        "development",
    ]


@pytest.fixture
def prepare_arguments(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> list[str]:
    """Register a real blank PDF to exercise a successful preparation command.

    Native-text accuracy is covered by the document-preparation tests. A known
    blank page is enough here to test CLI wiring, saved paths, and exit status.
    """
    # Replace the external fixture before registration; the preserved original
    # is never changed after import.
    with PdfWriter() as writer:
        writer.add_blank_page(width=300, height=300)
        writer.write(Path(add_arguments[1]))
    assert cli.main(add_arguments) == 0
    capsys.readouterr()
    return ["prepare", "plan_0001", "--project-root", str(project)]


def test_add_calls_registration_and_reports_saved_paths(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    result = cli.main(add_arguments)
    output = capsys.readouterr()

    assert result == 0
    assert "Registered plan_0001." in output.out
    assert "Original PDF: data/raw/plan_0001.pdf" in output.out
    assert "Registry: data/registry/plans.json" in output.out
    assert "Preparation: not_prepared" in output.out
    assert output.err == ""
    assert len(storage.load_registry(project)["plans"]) == 1


def test_duplicate_add_reports_reuse(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    assert cli.main(add_arguments) == 0
    capsys.readouterr()  # Discard the first call's captured output.

    assert cli.main(add_arguments) == 0
    output = capsys.readouterr()

    assert "Already registered as plan_0001" in output.out
    assert "Existing metadata retained" in output.out
    assert len(storage.load_registry(project)["plans"]) == 1


def test_list_of_new_project_creates_no_files(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    assert cli.main(["list", "--project-root", str(project)]) == 0

    assert capsys.readouterr().out == "No registered documents.\n"
    assert list(project.iterdir()) == []


def test_list_shows_registered_metadata(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    assert cli.main(add_arguments) == 0
    capsys.readouterr()

    assert cli.main(["list", "--project-root", str(project)]) == 0
    output = capsys.readouterr()

    assert "PLAN_ID" in output.out
    assert "plan_0001" in output.out
    assert "development" in output.out
    assert "not_prepared" in output.out
    assert "Example Heat Plan — 2026" in output.out
    assert output.err == ""


def test_default_project_is_current_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.chdir(project)

    assert cli.main(["list"]) == 0
    assert capsys.readouterr().out == "No registered documents.\n"


@pytest.mark.parametrize("missing_flag", ["--title", "--source-url", "--date-accessed", "--study-set"])
def test_add_requires_collection_details(
    project: Path,
    add_arguments: list[str],
    missing_flag: str,
    capsys: pytest.CaptureFixture,
) -> None:
    index = add_arguments.index(missing_flag)
    del add_arguments[index : index + 2]

    # argparse uses SystemExit for command syntax errors before registration runs.
    with pytest.raises(SystemExit) as error:
        cli.main(add_arguments)

    assert error.value.code == 2
    assert missing_flag in capsys.readouterr().err
    assert list(project.iterdir()) == []


def test_add_rejects_unknown_study_set(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    add_arguments[add_arguments.index("--study-set") + 1] = "pilot"

    with pytest.raises(SystemExit) as error:
        cli.main(add_arguments)

    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    assert list(project.iterdir()) == []


def test_invalid_date_reports_structure_problem_without_traceback(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    add_arguments[add_arguments.index("--date-accessed") + 1] = "2026-02-29"

    assert cli.main(add_arguments) == 1
    output = capsys.readouterr()

    assert "[structure] $.plans[0].date_accessed" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""
    assert list(project.iterdir()) == []


def test_missing_pdf_reports_file_error(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    add_arguments[1] = str(project / "missing.pdf")

    assert cli.main(add_arguments) == 1
    output = capsys.readouterr()

    assert "missing.pdf" in output.err
    assert "Error:" in output.err
    assert output.out == ""
    assert list(project.iterdir()) == []


def test_list_rejects_damaged_registry(project: Path, capsys: pytest.CaptureFixture) -> None:
    path = project / "data/registry/plans.json"
    path.parent.mkdir(parents=True)
    path.write_text("damaged JSON", encoding="utf-8")

    assert cli.main(["list", "--project-root", str(project)]) == 1
    output = capsys.readouterr()

    assert "[syntax]" in output.err
    assert output.out == ""
    assert path.read_text(encoding="utf-8") == "damaged JSON"


def test_list_reports_missing_registry_with_existing_raw_file(
    project: Path, capsys: pytest.CaptureFixture
) -> None:
    path = project / "data/raw/plan_0001.pdf"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"previously saved bytes")

    assert cli.main(["list", "--project-root", str(project)]) == 1

    assert "Restore the registry explicitly" in capsys.readouterr().err
    assert path.read_bytes() == b"previously saved bytes"
    assert not (project / "data/registry/plans.json").exists()


def test_list_reports_a_changed_original(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    assert cli.main(add_arguments) == 0
    capsys.readouterr()
    (project / "data/raw/plan_0001.pdf").write_bytes(b"changed saved original")

    assert cli.main(["list", "--project-root", str(project)]) == 1

    assert "no longer matches its checksum" in capsys.readouterr().err


def test_save_failure_displays_original_recovery_note(
    project: Path,
    add_arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    def fail_save(*args, **kwargs) -> None:
        raise OSError("Simulated registry-save failure")

    monkeypatch.setattr(storage, "save_registry", fail_save)

    assert cli.main(add_arguments) == 1
    output = capsys.readouterr()

    assert "Simulated registry-save failure" in output.err
    assert "completed PDF copy is retained at data/raw/plan_0001.pdf" in output.err
    assert output.out == ""
    assert (project / "data/raw/plan_0001.pdf").exists()


def test_cli_help_lists_available_commands(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr()
    assert "usage: heat-adaptation-llm-dataset" in output.out
    assert "add" in output.out
    assert "prepare" in output.out
    assert "list" in output.out


def test_prepare_reports_ready_and_saved_paths(
    project: Path, prepare_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    result = cli.main(prepare_arguments)
    output = capsys.readouterr()

    assert result == 0
    assert "Preparation for plan_0001." in output.out
    assert "Status: ready" in output.out
    assert "Page count: 1" in output.out
    assert "Preparation record: data/processed/plan_0001/preparation_01/preparation.json" in output.out
    assert "Page data: data/processed/plan_0001/preparation_01/pages.json" in output.out
    assert "Registry: data/registry/plans.json" in output.out
    assert output.err == ""
    record_path = storage.load_registry(project)["plans"][0]["prepared_source_path"]
    assert storage.load_preparation(project, record_path)[0]["status"] == "ready"


def test_failed_pdf_preparation_is_saved_but_returns_failure_exit_status(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    # This registration fixture has PDF-like bytes but no usable PDF page tree.
    assert cli.main(add_arguments) == 0
    capsys.readouterr()

    result = cli.main(["prepare", "plan_0001", "--project-root", str(project)])
    output = capsys.readouterr()

    assert result == 1
    assert "Status: failed" in output.out
    assert "Page count: unknown" in output.out
    assert "preparation_01/preparation.json" in output.out
    assert "Could not open or count PDF pages" in output.err
    assert "Review the saved preparation and page problems" in output.err
    assert "uv run --locked heat-adaptation-llm-dataset prepare plan_0001" in output.err
    assert "Traceback" not in output.err
    record_path = storage.load_registry(project)["plans"][0]["prepared_source_path"]
    preparation, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "failed"
    assert pages == []


def test_partly_readable_pdf_returns_ready_with_gaps_when_images_work(
    project: Path, add_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    with PdfWriter() as writer:
        # The first two pages are known blank. The third has visible drawing
        # content but no native text, so it must not be classified as blank.
        writer.add_blank_page(width=300, height=300)
        writer.add_blank_page(width=300, height=300)
        third_page = writer.add_blank_page(width=300, height=300)
        drawing = DecodedStreamObject()
        drawing.set_data(b"20 20 100 100 re f")
        third_page[NameObject("/Contents")] = writer._add_object(drawing)
        writer.write(Path(add_arguments[1]))
    assert cli.main(add_arguments) == 0
    capsys.readouterr()

    # This case isolates image fallback. Automatic OCR has separate integration tests.
    result = cli.main(["prepare", "plan_0001", "--no-ocr", "--project-root", str(project)])
    output = capsys.readouterr()

    assert result == 0
    assert "Status: ready_with_gaps" in output.out
    assert "Page count: 3" in output.out
    assert "PDF pages 3" in output.err
    assert "Page-image rendering checked" in output.err
    record_path = storage.load_registry(project)["plans"][0]["prepared_source_path"]
    preparation, pages = storage.load_preparation(project, record_path)
    assert preparation["status"] == "ready_with_gaps"
    assert [page["readable"] for page in pages] == [True, True, True]
    assert [page["image_available"] for page in pages] == [False, False, True]
    assert [page["text"] for page in pages] == ["", "", None]


def test_prepare_requires_a_plan_id(project: Path, capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["prepare", "--project-root", str(project)])

    assert error.value.code == 2
    assert "plan_id" in capsys.readouterr().err
    assert list(project.iterdir()) == []


def test_prepare_help_describes_plan_id_and_project_root(capsys: pytest.CaptureFixture) -> None:
    with pytest.raises(SystemExit) as error:
        cli.main(["prepare", "--help"])

    assert error.value.code == 0
    output = capsys.readouterr()
    assert "plan_id" in output.out
    assert "--project-root" in output.out
    assert output.err == ""


def test_prepare_rejects_unknown_plan_without_creating_an_attempt(
    project: Path, prepare_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    prepare_arguments[1] = "plan_9999"
    before = (project / "data/registry/plans.json").read_bytes()

    assert cli.main(prepare_arguments) == 1
    output = capsys.readouterr()

    assert "No registered document" in output.err
    assert "plan_9999" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""
    assert (project / "data/registry/plans.json").read_bytes() == before
    assert not (project / "data/processed").exists()


def test_prepare_defaults_to_current_project_directory(
    project: Path,
    prepare_arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    monkeypatch.chdir(project)

    assert cli.main(["prepare", "plan_0001"]) == 0
    assert "Status: ready" in capsys.readouterr().out
    assert storage.load_registry(project)["plans"][0]["prepared_source_path"] is not None


def test_each_prepare_command_creates_a_new_attempt(
    project: Path, prepare_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    assert cli.main(prepare_arguments) == 0
    first_path = storage.load_registry(project)["plans"][0]["prepared_source_path"]
    first_bytes = (project / first_path).read_bytes()
    capsys.readouterr()

    assert cli.main(prepare_arguments) == 0
    output = capsys.readouterr()

    assert "preparation_02/preparation.json" in output.out
    assert (project / first_path).read_bytes() == first_bytes
    assert len(list((project / "data/processed/plan_0001").iterdir())) == 2


def test_prepare_displays_structured_errors_for_damaged_saved_preparation(
    project: Path, prepare_arguments: list[str], capsys: pytest.CaptureFixture
) -> None:
    assert cli.main(prepare_arguments) == 0
    record_path = storage.load_registry(project)["plans"][0]["prepared_source_path"]
    preparation, _ = storage.load_preparation(project, record_path)
    (project / preparation["pages_path"]).write_text("[broken", encoding="utf-8")
    capsys.readouterr()

    assert cli.main(prepare_arguments) == 1
    output = capsys.readouterr()

    assert "Preparation validation failed:" in output.err
    assert "[syntax]" in output.err
    assert "pages.json" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""
    assert storage.load_registry(project)["plans"][0]["prepared_source_path"] == record_path
    assert not (project / "data/processed/plan_0001/preparation_02").exists()


def test_prepare_displays_recovery_note_when_registry_link_save_fails(
    project: Path,
    prepare_arguments: list[str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture,
) -> None:
    def fail_save(*args, **kwargs) -> None:
        raise OSError("Simulated preparation registry-link failure")

    monkeypatch.setattr(storage, "save_registry", fail_save)

    assert cli.main(prepare_arguments) == 1
    output = capsys.readouterr()

    assert "registry-link failure" in output.err
    assert "Completed preparation retained at" in output.err
    assert "preparation_01/preparation.json" in output.err
    assert "Traceback" not in output.err
    assert output.out == ""
    assert storage.load_registry(project)["plans"][0]["prepared_source_path"] is None
    assert (project / "data/processed/plan_0001/preparation_01/preparation.json").is_file()


def test_cli_reports_ready_with_gaps_without_marking_it_failed(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    # Isolate the CLI's status handling. Real rendering is checked independently
    # by the preparation and document-tools integration tests.
    def future_preparation(root: Path, plan_id: str, *, ocr_enabled: bool):
        assert root == project.resolve()
        assert plan_id == "plan_0001"
        assert ocr_enabled is True
        return (
            {
                "plan_id": plan_id,
                "status": "ready_with_gaps",
                "page_count": 3,
                "pages_path": "data/processed/plan_0001/preparation_01/pages.json",
                "problem": "A page needs the tested alternate reading route.",
            },
            "data/processed/plan_0001/preparation_01/preparation.json",
        )

    monkeypatch.setattr(cli.documents, "prepare_document", future_preparation)

    assert cli.main(["prepare", "plan_0001", "--project-root", str(project)]) == 0
    output = capsys.readouterr()

    assert "Status: ready_with_gaps" in output.out
    assert "alternate reading route" in output.err
    assert "retry" not in output.err


def test_failed_preparation_retry_command_quotes_project_path_with_spaces(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    project = tmp_path / "project with spaces"
    project.mkdir()

    def failed_preparation(root: Path, plan_id: str, *, ocr_enabled: bool):
        assert root == project.resolve()
        return (
            {
                "plan_id": plan_id,
                "status": "failed",
                "page_count": None,
                "pages_path": "data/processed/plan_0001/preparation_01/pages.json",
                "problem": "Simulated source-reading failure.",
            },
            "data/processed/plan_0001/preparation_01/preparation.json",
        )

    monkeypatch.setattr(cli.documents, "prepare_document", failed_preparation)

    assert cli.main(["prepare", "plan_0001", "--project-root", str(project)]) == 1
    output = capsys.readouterr()

    assert f"--project-root '{project.resolve()}'" in output.err


@pytest.mark.parametrize("readable_pdf", [True, False], ids=["ready", "failed"])
def test_prepare_exit_status_reaches_a_separate_python_process(
    project: Path,
    add_arguments: list[str],
    capsys: pytest.CaptureFixture,
    readable_pdf: bool,
) -> None:
    # A returned integer inside Python is not enough to prove shell behavior.
    # Starting a separate process checks that the entry point turns that value into
    # the actual exit status observed by terminal users or scripts.
    if readable_pdf:
        with PdfWriter() as writer:
            writer.add_blank_page(width=300, height=300)
            writer.write(Path(add_arguments[1]))
    assert cli.main(add_arguments) == 0
    capsys.readouterr()
    script = Path(__file__).resolve().parents[1] / "src/cli.py"

    # A separate process verifies that the integer returned by main() actually
    # becomes the terminal exit code through the __main__ entry point.
    result = subprocess.run(
        [sys.executable, str(script), "prepare", "plan_0001"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == (0 if readable_pdf else 1)
    assert f"Status: {'ready' if readable_pdf else 'failed'}" in result.stdout
    assert "preparation_01/preparation.json" in result.stdout
    assert "Traceback" not in result.stderr


def test_script_entry_point_works_in_another_directory(project: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "src/cli.py"
    # A subprocess runs a separate Python process, exercising __main__ and exit codes.
    result = subprocess.run(
        [sys.executable, str(script), "list"],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout == "No registered documents.\n"
    assert result.stderr == ""
    assert list(project.iterdir()) == []
