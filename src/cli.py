"""Provide terminal commands for document preparation and saved extraction.

The CLI translates arguments into calls to shared modules, then displays results.
Document identity, validation, and file-preservation rules stay in those modules.
"""

import argparse
import asyncio
import logging
import shlex
import sys
from contextlib import contextmanager
from pathlib import Path, PurePosixPath

import agents
import documents
import storage


# Start reading at main(): arguments choose an operation, documents.py performs
# the work, and the small helpers below print its result. Extraction delegates
# its model/tool lifecycle, validation and saving to agents.run_extractor.
def main(argv: list[str] | None = None) -> int:
    """Run a command and return 0 on success or 1 when the requested operation fails.

    Tests can supply an argument list directly. With None, argparse reads the
    actual terminal arguments. Invalid command syntax is handled by argparse (2).
    """
    parser = _build_parser()
    # argparse returns a Namespace: named attributes such as args.command and
    # args.plan_id hold the values supplied in the terminal or a test's list.
    args = parser.parse_args(argv)
    if args.command == "update_plan_data" and all(
        getattr(args, field) is None for field in ("title", "source_url", "date_accessed", "study_set")
    ):
        parser.error("update_plan_data requires --title, --source-url, --date-accessed, or --study-set.")
    try:
        # expanduser handles a leading ~; resolve makes later paths independent
        # of relative spelling. The document functions check the project itself.
        root = args.project_root.expanduser().resolve()
        if args.command == "add_plan":
            _add_plan(root, args)
        elif args.command == "update_plan_data":
            _update_plan_data(root, args)
        elif args.command == "prepare_plan":
            # A failed attempt can be saved successfully. Return its operation
            # status instead of treating every completed function call as success.
            return _prepare_plan(root, args.plan_id, ocr_enabled=args.ocr_enabled)
        elif args.command == "run_extract_mode":
            return _run_extract_mode(root, args)
        elif args.command == "list_plans":
            _list_plans(root)
    except (OSError, ValueError) as error:
        # Expected file and data failures become readable terminal messages.
        # Unexpected programming errors still raise, making them visible in development.
        _display_error(error)
        return 1
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Describe commands and arguments; argparse generates their help messages."""
    parser = argparse.ArgumentParser(
        prog="heat-adaptation-llm-dataset",
        description="Register PDFs, update metadata, prepare pages, extract records, and list status.",
        allow_abbrev=False,
    )
    # Explicit option names prevent a shortened flag from acquiring a different
    # meaning as more commands/options are added to the project.
    # Subcommands select an operation; a required subcommand avoids an ambiguous run.
    commands = parser.add_subparsers(dest="command", required=True)
    add_plan_parser = commands.add_parser(
        "add_plan", help="Register a prescreened local PDF.", allow_abbrev=False
    )
    add_plan_parser.add_argument("pdf", type=Path, help="Path to the supplied local PDF.")
    add_plan_parser.add_argument("--title", required=True, help="Collected plan title.")
    add_plan_parser.add_argument("--source-url", required=True, help="Official source URL.")
    add_plan_parser.add_argument("--date-accessed", required=True, help="Access date as YYYY-MM-DD.")
    add_plan_parser.add_argument(
        "--study-set", required=True, choices=["development", "comparison", "expansion"]
    )
    _add_project_argument(add_plan_parser)

    update_plan_data_parser = commands.add_parser(
        "update_plan_data", help="Update collection metadata for a registered plan.",
        allow_abbrev=False,
    )
    update_plan_data_parser.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    update_plan_data_parser.add_argument("--title", help="Corrected plan title.")
    update_plan_data_parser.add_argument("--source-url", help="Corrected official source URL.")
    update_plan_data_parser.add_argument("--date-accessed", help="Corrected access date as YYYY-MM-DD.")
    update_plan_data_parser.add_argument(
        "--study-set", choices=["development", "comparison", "expansion"],
        help="Study set; development assignments and sets with saved model work are fixed.",
    )
    _add_project_argument(update_plan_data_parser)

    prepare_plan_parser = commands.add_parser(
        "prepare_plan", help="Prepare native page text for a registered PDF.", allow_abbrev=False
    )
    prepare_plan_parser.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    prepare_plan_parser.add_argument(
        "--no-ocr",
        dest="ocr_enabled",
        action="store_false",
        help="Skip automatic OCR fallback; retain native text and image checks.",
    )
    _add_project_argument(prepare_plan_parser)

    run_extract_mode_parser = commands.add_parser(
        "run_extract_mode",
        help="Run and save one hosted extractor attempt with local MCP document tools.",
        allow_abbrev=False,
    )
    run_extract_mode_parser.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    run_extract_mode_parser.add_argument(
        "--source-path", required=True,
        help="Project-relative path to the exact saved preparation.json.",
    )
    run_extract_mode_parser.add_argument("--profile", required=True, help="Exact extractor profile name in the configuration.")
    run_extract_mode_parser.add_argument(
        "--purpose", required=True, choices=["development", "comparison", "exploratory"],
        help="Reason for this attempt; development/comparison must match the registered study set.",
    )
    run_extract_mode_parser.add_argument(
        "--retry-of-run-id",
        help="Failed extractor run being manually retried; never resumes or overwrites it.",
    )
    run_extract_mode_parser.add_argument(
        "--config-path", default="configs/profiles.json",
        help="Project-relative profile configuration (default: configs/profiles.json).",
    )
    _add_project_argument(run_extract_mode_parser)

    list_plans_parser = commands.add_parser(
        "list_plans", help="List registered documents, saved preparation status, and links.", allow_abbrev=False
    )
    _add_project_argument(list_plans_parser)
    return parser


def _add_project_argument(parser: argparse.ArgumentParser) -> None:
    """Give each command the same explicit project-location option."""
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project directory containing data/ (default: current directory).",
    )


@contextmanager
def _comparison_logging(blind: bool):
    """Keep protocol/client logs from bypassing comparison feedback restrictions.

    This affects only this terminal invocation and is restored afterward. The
    saved runner preserves raw model responses, operational errors and MCP
    subprocess stderr separately; those files remain for authorized inspection.
    """
    saved = []
    if blind:
        for name in ("mcp", "httpx", "httpcore", "asyncio"):
            logger = logging.getLogger(name)
            saved.append((logger, logger.handlers[:], logger.propagate))
            logger.handlers = [logging.NullHandler()]
            logger.propagate = False
    try:
        yield
    finally:
        for logger, handlers, propagate in saved:
            logger.handlers, logger.propagate = handlers, propagate


def _error_categories(error: Exception) -> list[str]:
    """Use validated category labels, never quote exception text in blind output."""
    allowed = {"syntax", "structure", "reference", "other"}
    categories = {getattr(problem, "category", "other") for problem in getattr(error, "problems", [])}
    return sorted(categories & allowed) or ["other"]


def _run_extract_mode(root: Path, args: argparse.Namespace) -> int:
    """Bridge the synchronous terminal to one asynchronous saved run.

    Comparison plans stay blind even for exploratory repeats. The future expert
    workflow must establish a validated initial reference before feedback can be
    unlocked; a file merely named reference_initial.json is not sufficient.
    """
    blind = True  # Fail closed until registry identity/study set can be checked.
    try:
        registry = storage.load_registry(root)
        entry = next((p for p in registry["plans"] if p["plan_id"] == args.plan_id), None)
        if entry is None:
            raise ValueError("Select an existing registered plan ID.")
        blind = entry["study_set"] == "comparison" or args.purpose == "comparison"
        print(f"Starting extractor for {_display_text(args.plan_id)}.", flush=True)
        async def execute():
            try:
                result = await agents.run_extractor(root, args.plan_id, source_path=args.source_path,
                    profile_name=args.profile, purpose=args.purpose, retry_of_run_id=args.retry_of_run_id,
                    config_path=args.config_path)
                return result, False
            except agents.SavedExtractorCancelled as cancelled:
                # Catch inside asyncio.run: its SIGINT handler can otherwise
                # convert cancellation to KeyboardInterrupt and lose this result.
                return cancelled.result, True
        with _comparison_logging(blind):
            saved, cancelled = asyncio.run(execute())
    except KeyboardInterrupt:
        print("Extraction interrupted; final saved status is unknown. Inspect existing run records before retrying.", file=sys.stderr)
        return 130
    except Exception as error:
        if blind:
            print("Extraction setup failed.", file=sys.stderr)
            print("Error categories: " + ", ".join(_error_categories(error)), file=sys.stderr)
            print("Comparison details withheld until the reference workflow can validate an initial reference.", file=sys.stderr)
        elif isinstance(error, (OSError, ValueError)):
            _display_error(error)
        else:
            raise  # Unexpected programming errors remain visible in development.
        return 1

    record = saved.record  # Last published status, even when completion could not be saved.
    print(f"Status: {record['status']}")
    print(f"Run record: {saved.record_path}")
    folder = PurePosixPath(saved.record_path).parent
    report = saved.execution.final_validation.report if saved.execution and saved.execution.final_validation else None
    if report is not None:
        if storage.resolve_project_path(root, f"{folder}/validation_report.json").is_file():
            print(f"Validation report: {folder}/validation_report.json")
        else:
            print("Validation report: not saved.")
    if blind:
        categories = {e["category"] for e in report["remaining_errors"]} if report else set()
        if (record["error"] and not categories) or saved.persistence_error or cancelled:
            categories.add("other")
        if categories:
            print("Error categories: " + ", ".join(sorted(categories)), file=sys.stderr)
        print("Comparison details withheld until the reference workflow can validate an initial reference.")
    else:
        print(f"Model requests: {len(record['model_calls'])}")
        if record["tool_log_path"] is not None:
            print(f"Tool log: {record['tool_log_path']}")
        if report is not None:
            for repair in report["repairs"]:
                print(f"Repair [{repair['rule']}] {_display_text(repair['location'])}: {repair['before']!r} -> {repair['after']!r}")
            for problem in report["remaining_errors"]:
                print(f"  [{problem['category']}] {problem['location'] or '$'}: {problem['message']}", file=sys.stderr)
        if record["error"]:
            print(f"Error: {record['error']}", file=sys.stderr)
        if saved.persistence_error:
            print(f"Saving error: {saved.persistence_error}", file=sys.stderr)
        if cancelled:
            print("Extraction cancelled; available evidence was retained where saving succeeded.", file=sys.stderr)
    # A valid answer in memory is not a saved success. Running/failed records,
    # persistence failures and cancellation always produce a nonzero exit code.
    return 130 if cancelled else (0 if record["status"] == "succeeded" and not saved.persistence_error else 1)


def _add_plan(root: Path, args: argparse.Namespace) -> None:
    """Pass collected arguments to registration and show its saved result."""
    # Tuple unpacking gives names to both returned values: the registry entry
    # and whether this call created it or reused an identical registered PDF.
    entry, created = documents.register_document(
        project_root=root,
        pdf_path=args.pdf,
        plan_title=args.title,
        source_url=args.source_url,
        date_accessed=args.date_accessed,
        study_set=args.study_set,
    )
    if created:
        print(f"Registered {entry['plan_id']}.")
    else:
        print(f"Already registered as {entry['plan_id']}. Existing metadata retained.")
    print(f"Title: {_display_text(entry['plan_title'])}")
    print(f"Study set: {entry['study_set']}")
    print(f"Original PDF: {entry['pdf_path']}")
    print("Registry: data/registry/plans.json")
    print(f"Preparation: {entry['prepared_source_path'] or 'not_prepared'}")


def _prepare_plan(root: Path, plan_id: str, *, ocr_enabled: bool = True) -> int:
    """Run preparation, display its saved outcome, and return the stage exit status."""
    preparation, record_path = documents.prepare_document(root, plan_id, ocr_enabled=ocr_enabled)
    # Report paths returned by the workflow, rather than guessing which numbered
    # attempt was saved. A retained failed attempt also has useful report paths.
    print(f"Preparation for {preparation['plan_id']}.")
    print(f"Status: {preparation['status']}")
    page_count = preparation["page_count"]
    print(f"Page count: {page_count if page_count is not None else 'unknown'}")
    print(f"Preparation record: {record_path}")
    print(f"Page data: {preparation['pages_path']}")
    print("Registry: data/registry/plans.json")
    if preparation["problem"] is not None:
        # The saved summary remains available on stdout; problems go to stderr
        # so scripts can keep normal results and diagnostics in separate streams.
        print(f"Problem: {preparation['problem']}", file=sys.stderr)

    if preparation["status"] == "failed":
        print("Review the saved preparation and page problems before retrying.", file=sys.stderr)
        # Quote each argument for a shell, including project paths with spaces.
        # Retrying is manual and creates a new attempt; this command never retries itself.
        retry_command = shlex.join(
            [
                "uv", "run", "--locked", "heat-adaptation-llm-dataset", "prepare_plan", plan_id,
                "--project-root", str(root),
            ]
        )
        print("After resolving the problem, retry from the project directory:", file=sys.stderr)
        print(f"  {retry_command}", file=sys.stderr)
        return 1

    # A checked image route makes preparation ready_with_gaps. Model processing
    # must separately check the selected profile's image input or MCP OCR support.
    return 0


def _update_plan_data(root: Path, args: argparse.Namespace) -> None:
    """Apply only supplied fields, then show the saved collection details."""
    entry, changed = documents.update_document_metadata(
        root, args.plan_id, plan_title=args.title, source_url=args.source_url,
        date_accessed=args.date_accessed, study_set=args.study_set,
    )
    print(f"Updated collection metadata for {entry['plan_id']}." if changed
          else f"No metadata changes for {entry['plan_id']}.")
    print(f"Title: {_display_text(entry['plan_title'])}")
    print(f"Source URL: {entry['source_url']}")
    print(f"Access date: {entry['date_accessed']}")
    print(f"Study set: {entry['study_set']}")
    print(f"Original PDF: {entry['pdf_path']}")
    print(f"Preparation: {entry['prepared_source_path'] or 'not_prepared'}")
    print("Registry: data/registry/plans.json")


def _list_plans(root: Path) -> None:
    """Display records without creating files or inventing preparation readiness."""
    entries = documents.list_documents(root)
    if not entries:
        print("No registered documents.")
        return
    print(f"{'PLAN_ID':<14} {'STUDY_SET':<12} {'PREPARATION':<20} TITLE")
    # :<14 and the other widths left-align display columns; they do not change
    # stored values. _display_text only removes line breaks from terminal output.
    for entry in entries:
        print(
            f"{entry['plan_id']:<14} {entry['study_set']:<12} "
            f"{entry['preparation_status']:<20} {_display_text(entry['plan_title'])}"
        )
        if entry["prepared_source_path"] is not None:
            print(f"  Preparation: {entry['prepared_source_path']}")


def _display_text(value: str) -> str:
    """Keep table rows on one line; the saved metadata remains unchanged."""
    return " ".join(value.split())


def _display_error(error: Exception) -> None:
    """Send problems and any recovery notes to stderr, separate from normal output."""
    if isinstance(error, (storage.RegistryValidationError, storage.PreparationValidationError,
                          storage.RunValidationError, agents.ProfileValidationError, agents.ExtractorInputError)):
        label = ("Registry" if isinstance(error, storage.RegistryValidationError) else
                 "Preparation" if isinstance(error, storage.PreparationValidationError) else "Extraction")
        print(f"{label} validation failed:", file=sys.stderr)
        for problem in error.problems:
            location = problem.location or "unknown location"
            print(f"  [{problem.category}] {location}: {problem.message}", file=sys.stderr)
    else:
        print(f"Error: {error}", file=sys.stderr)

    # Registration and preparation attach recovery notes when completed files may
    # remain after an unsuccessful or uncertain save. Keep those notes visible.
    for note in getattr(error, "__notes__", []):
        print(f"  {note}", file=sys.stderr)


# This block runs for `python src/cli.py` or `python -m cli`, but not on import.
# The installed console command also calls main() and uses its integer exit status.
if __name__ == "__main__":
    raise SystemExit(main())
