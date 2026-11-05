"""Provide terminal commands for registration, metadata updates, and preparation.

The CLI translates arguments into calls to shared modules, then displays results.
Document identity, validation, and file-preservation rules stay in those modules.
"""

import argparse
import shlex
import sys
from pathlib import Path

import documents
import storage


# Start reading at main(): arguments choose an operation, documents.py performs
# the work, and the small helpers below print its result. The model/run-record
# functions are currently library code; this CLI exposes only Part 1 commands.
def main(argv: list[str] | None = None) -> int:
    """Run a command and return 0 on success or 1 when the requested operation fails.

    Tests can supply an argument list directly. With None, argparse reads the
    actual terminal arguments. Invalid command syntax is handled by argparse (2).
    """
    parser = _build_parser()
    # argparse returns a Namespace: named attributes such as args.command and
    # args.plan_id hold the values supplied in the terminal or a test's list.
    args = parser.parse_args(argv)
    if args.command == "update" and all(
        getattr(args, field) is None for field in ("title", "source_url", "date_accessed", "study_set")
    ):
        parser.error("update requires --title, --source-url, --date-accessed, or --study-set.")
    try:
        # expanduser handles a leading ~; resolve makes later paths independent
        # of relative spelling. The document functions check the project itself.
        root = args.project_root.expanduser().resolve()
        if args.command == "add":
            _add_document(root, args)
        elif args.command == "update":
            _update_document(root, args)
        elif args.command == "prepare":
            # A failed attempt can be saved successfully. Return its operation
            # status instead of treating every completed function call as success.
            return _prepare_document(root, args.plan_id, ocr_enabled=args.ocr_enabled)
        else:
            _list_documents(root)
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
        description="Register PDFs, update collection metadata, prepare pages, and list status.",
        allow_abbrev=False,
    )
    # Explicit option names prevent a shortened flag from acquiring a different
    # meaning as more commands/options are added to the project.
    # Subcommands select an operation; a required subcommand avoids an ambiguous run.
    commands = parser.add_subparsers(dest="command", required=True)
    add = commands.add_parser(
        "add", help="Register a prescreened local PDF.", allow_abbrev=False
    )
    add.add_argument("pdf", type=Path, help="Path to the supplied local PDF.")
    add.add_argument("--title", required=True, help="Collected plan title.")
    add.add_argument("--source-url", required=True, help="Official source URL.")
    add.add_argument("--date-accessed", required=True, help="Access date as YYYY-MM-DD.")
    add.add_argument(
        "--study-set", required=True, choices=["development", "comparison", "expansion"]
    )
    _add_project_argument(add)

    update = commands.add_parser(
        "update", help="Update collection metadata for a registered document.", allow_abbrev=False
    )
    update.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    update.add_argument("--title", help="Corrected plan title.")
    update.add_argument("--source-url", help="Corrected official source URL.")
    update.add_argument("--date-accessed", help="Corrected access date as YYYY-MM-DD.")
    update.add_argument(
        "--study-set", choices=["development", "comparison", "expansion"],
        help="Study set; development assignments and sets with saved model work are fixed.",
    )
    _add_project_argument(update)

    preparation = commands.add_parser(
        "prepare", help="Prepare native page text for a registered PDF.", allow_abbrev=False
    )
    preparation.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    preparation.add_argument(
        "--no-ocr",
        dest="ocr_enabled",
        action="store_false",
        help="Skip automatic OCR fallback; retain native text and image checks.",
    )
    _add_project_argument(preparation)

    listing = commands.add_parser(
        "list", help="List registered documents, saved preparation status, and links.", allow_abbrev=False
    )
    _add_project_argument(listing)
    return parser


def _add_project_argument(parser: argparse.ArgumentParser) -> None:
    """Give each command the same explicit project-location option."""
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Project directory containing data/ (default: current directory).",
    )


def _add_document(root: Path, args: argparse.Namespace) -> None:
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


def _prepare_document(root: Path, plan_id: str, *, ocr_enabled: bool = True) -> int:
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
                "uv", "run", "--locked", "heat-adaptation-llm-dataset", "prepare", plan_id,
                "--project-root", str(root),
            ]
        )
        print("After resolving the problem, retry from the project directory:", file=sys.stderr)
        print(f"  {retry_command}", file=sys.stderr)
        return 1

    # A checked image route makes preparation ready_with_gaps. Model processing
    # must separately check the selected profile's image input or MCP OCR support.
    return 0


def _update_document(root: Path, args: argparse.Namespace) -> None:
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


def _list_documents(root: Path) -> None:
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
    if isinstance(error, (storage.RegistryValidationError, storage.PreparationValidationError)):
        label = "Registry" if isinstance(error, storage.RegistryValidationError) else "Preparation"
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
