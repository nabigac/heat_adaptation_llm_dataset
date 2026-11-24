"""Provide terminal commands for document processing and expert reference setup.

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
import collaboration_runner
from collaboration_contracts import (
    DEFAULT_COLLABORATION_PROFILE, load_collaboration_configuration, load_collaboration_profiles,
)
import documents
import expert_files
import storage
from quotation_diagnostics import QUOTATION_PAGE_REPORT_PATH


# Start reading at main(): arguments choose an operation, workflow modules perform
# the work, and the small helpers below print its result. Model commands delegate
# lifecycle and saving to agents.py (E/V) or collaboration_runner.py (C).
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
        elif args.command in {"run_extract_mode", "run_verify_mode"}:
            return _run_model_mode(root, args)
        elif args.command == "run_collaboration_mode":
            return _run_collaboration_mode(root, args)
        elif args.command == "list_plans":
            _list_plans(root)
        elif args.command == "list_profiles":
            _list_profiles(root, args)
        elif args.command == "create_expert_reference":
            _create_expert_reference(root, args)
        elif args.command == "validate_expert_reference":
            _validate_expert_reference(root, args.plan_id)
        elif args.command == "edit_expert_reference":
            _edit_expert_reference(root, args)
        elif args.command == "freeze_expert_reference":
            _freeze_expert_reference(root, args)
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
        description="Register and prepare PDFs, run extraction, verification or collaboration, and manage expert forms.",
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
    run_extract_mode_parser.add_argument(
        "--source-path", required=True,
        help="Project-relative path to the exact saved preparation.json.",
    )
    _add_model_run_arguments(run_extract_mode_parser, stage="extractor")

    run_verify_mode_parser = commands.add_parser(
        "run_verify_mode",
        help="Verify a saved extraction and preserve a separate revised answer.",
        allow_abbrev=False,
    )
    run_verify_mode_parser.add_argument(
        "--input-run-id",
        help="Exact successful extractor run ID; default: latest validated, successful eligible E run. Retries retain their original E input.",
    )
    _add_model_run_arguments(run_verify_mode_parser, stage="verifier")

    collaboration_parser = commands.add_parser(
        "run_collaboration_mode", help="Coordinate three hosted models from a prepared development plan.",
        allow_abbrev=False,
    )
    collaboration_parser.add_argument("plan_id", help="Registered development plan ID.")
    collaboration_parser.add_argument("--source-path", required=True, help="Exact project-relative preparation.json.")
    collaboration_parser.add_argument(
        "--profile", default=DEFAULT_COLLABORATION_PROFILE,
        help=f"Named C binding (default: {DEFAULT_COLLABORATION_PROFILE}).",
    )
    collaboration_parser.add_argument("--purpose", required=True, choices=["development"])
    collaboration_parser.add_argument("--retry-of-run-id", help="Failed C attempt for the same preparation; starts a new attempt.")
    collaboration_parser.add_argument("--config-path", default="configs/collaboration.json", help="Project-relative C bindings.")
    collaboration_parser.add_argument("--model-config-path", default="configs/profiles.json", help="Project-relative model profiles.")
    _add_project_argument(collaboration_parser)

    list_plans_parser = commands.add_parser(
        "list_plans", help="List registered documents, saved preparation status, and links.", allow_abbrev=False
    )
    _add_project_argument(list_plans_parser)

    list_profiles_parser = commands.add_parser(
        "list_profiles", help="List selectable E/V/C profiles, models, and configured limits.",
        allow_abbrev=False,
    )
    list_profiles_parser.add_argument(
        "--config-path", default="configs/profiles.json", help="Project-relative model profiles.",
    )
    list_profiles_parser.add_argument(
        "--collaboration-config-path", default="configs/collaboration.json",
        help="Project-relative C bindings.",
    )
    _add_project_argument(list_profiles_parser)

    reference_parser = commands.add_parser(
        "create_expert_reference",
        help="Create a guided expert reference with a blank action and issue.",
        allow_abbrev=False,
    )
    reference_parser.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    reference_parser.add_argument(
        "--prepared-by", action="append", required=True,
        help="Expert name or study ID; repeat for multiple experts.",
    )
    _add_project_argument(reference_parser)

    validate_reference_parser = commands.add_parser(
        "validate_expert_reference",
        help="Check an expert form against its registered source and physical PDF pages.",
        allow_abbrev=False,
    )
    validate_reference_parser.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    _add_project_argument(validate_reference_parser)

    edit_reference_parser = commands.add_parser(
        "edit_expert_reference", help="Add or remove records in an expert reference draft.",
        allow_abbrev=False,
    )
    edit_reference_parser.add_argument("--plan-id", required=True, help="Plan ID selecting its expert_reference.json.")
    operations = edit_reference_parser.add_mutually_exclusive_group(required=True)
    operations.add_argument("--add-action", action="store_true", help="Append a guided blank action with the next ID.")
    operations.add_argument("--add-issue", action="store_true", help="Append a guided blank expert issue with the next ID.")
    operations.add_argument(
        "--remove-action", nargs="?", const="", metavar="ACTION_ID",
        help="Remove an exact action ID, or the highest-ID untouched blank when no ID is supplied.",
    )
    operations.add_argument(
        "--remove-issue", nargs="?", const="", metavar="ISSUE_ID",
        help="Remove an exact issue ID, or the highest-ID untouched blank when no ID is supplied.",
    )
    _add_project_argument(edit_reference_parser)
    freeze_reference_parser = commands.add_parser(
        "freeze_expert_reference",
        help="Confirm a completed reference is ready for assessment and freeze its identity.",
        allow_abbrev=False,
    )
    freeze_reference_parser.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    freeze_reference_parser.add_argument(
        "--frozen-by", action="append", required=True,
        help="Reviewer confirming readiness for assessment; repeat for multiple reviewers.",
    )
    _add_project_argument(freeze_reference_parser)
    return parser


def _add_model_run_arguments(parser: argparse.ArgumentParser, *, stage: str) -> None:
    """Keep shared flags explicit and consistent across the two model commands."""
    parser.add_argument("plan_id", help="Registered document ID, such as plan_0001.")
    parser.add_argument("--profile", required=True, help=f"Exact {stage} profile name in the configuration.")
    parser.add_argument(
        "--purpose", required=True, choices=["development", "comparison", "exploratory"],
        help="Reason for this attempt; development/comparison must match the registered study set.",
    )
    parser.add_argument(
        "--retry-of-run-id",
        help=f"Failed {stage} run being manually retried; never resumes or overwrites it.",
    )
    parser.add_argument(
        "--config-path", default="configs/profiles.json",
        help="Project-relative profile configuration (default: configs/profiles.json).",
    )
    _add_project_argument(parser)


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


def _run_model_mode(root: Path, args: argparse.Namespace) -> int:
    """Bridge the synchronous terminal to one asynchronous saved run.

    Comparison plans stay blind even for exploratory repeats. The future expert
    workflow must establish a validated initial reference before feedback can be
    unlocked; a file merely named reference_initial.json is not sufficient.
    """
    verifying = args.command == "run_verify_mode"
    stage = "verifier" if verifying else "extractor"
    operation = "Verification" if verifying else "Extraction"
    blind = True  # Fail closed until registry identity/study set can be checked.
    try:
        registry = storage.load_registry(root)
        entry = next((p for p in registry["plans"] if p["plan_id"] == args.plan_id), None)
        if entry is None:
            raise ValueError("Select an existing registered plan ID.")
        blind = entry["study_set"] == "comparison" or args.purpose == "comparison"
        print(f"Starting {stage} for {_display_text(args.plan_id)}.", flush=True)
        async def execute():
            try:
                options = dict(profile_name=args.profile, purpose=args.purpose,
                    retry_of_run_id=args.retry_of_run_id, config_path=args.config_path)
                if verifying:
                    result = await agents.run_verifier(root, args.plan_id, input_run_id=args.input_run_id, **options)
                else:
                    result = await agents.run_extractor(root, args.plan_id, source_path=args.source_path, **options)
                return result, False
            except agents.SavedAgentCancelled as cancelled:
                # Catch inside asyncio.run: its SIGINT handler can otherwise
                # convert cancellation to KeyboardInterrupt and lose this result.
                return cancelled.result, True
        with _comparison_logging(blind):
            saved, cancelled = asyncio.run(execute())
    except KeyboardInterrupt:
        print(f"{operation} interrupted; final saved status is unknown. Inspect existing run records before retrying.", file=sys.stderr)
        return 130
    except Exception as error:
        if blind:
            print(f"{operation} setup failed.", file=sys.stderr)
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
    if verifying:
        print(f"Extractor input: {_display_text(record['input_run_id'])}")
    folder = PurePosixPath(saved.record_path).parent
    report = saved.execution.final_validation.report if saved.execution and saved.execution.final_validation else None
    diagnostic = getattr(saved.execution, "quotation_diagnostics", None)
    if report is not None:
        if storage.resolve_project_path(root, f"{folder}/validation_report.json").is_file():
            print(f"Validation report: {folder}/validation_report.json")
        else:
            print("Validation report: not saved.")
    if diagnostic is not None:
        diagnostic_path = f"{folder}/{QUOTATION_PAGE_REPORT_PATH}"
        if storage.resolve_project_path(root, diagnostic_path).is_file():
            print(f"Quotation/page diagnostic: {diagnostic_path}")
        else:
            print("Quotation/page diagnostic: not saved.")
    if blind:
        categories = {e["category"] for e in report["remaining_errors"]} if report else set()
        if (record["error"] and not categories) or saved.persistence_error or cancelled:
            categories.add("other")
        if categories:
            print("Error categories: " + ", ".join(sorted(categories)), file=sys.stderr)
        print("Comparison details withheld until the reference workflow can validate an initial reference.")
    else:
        print(f"Model requests: {len(record['model_calls'])}")
        if diagnostic is not None:
            summary = diagnostic["summary"]
            if summary.get("corrected", 0):
                print(f"Quotation/page corrections: {summary['corrected']}")
            print(f"Quotation/page flags: {summary['possible_page_mismatch']} possible page mismatches; "
                  f"{summary['unmatched_quote']} unmatched quotations; "
                  f"{summary['unconfirmed_page_span']} unconfirmed spans.")
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
            print(f"{operation} cancelled; available evidence was retained where saving succeeded.", file=sys.stderr)
    # A valid answer in memory is not a saved success. Running/failed records,
    # persistence failures and cancellation always produce a nonzero exit code.
    return 130 if cancelled else (0 if record["status"] == "succeeded" and not saved.persistence_error else 1)


def _run_collaboration_mode(root: Path, args: argparse.Namespace) -> int:
    """Display published C status, including cancellation and saving failures."""
    async def execute():
        try:
            result = await collaboration_runner.run_collaboration(root, args.plan_id,
                source_path=args.source_path, profile_name=args.profile, purpose=args.purpose,
                retry_of_run_id=args.retry_of_run_id, config_path=args.config_path,
                model_config_path=args.model_config_path)
            return result, False
        except collaboration_runner.SavedCollaborationCancelled as cancelled:
            return cancelled.result, True
    print(f"Starting collaboration for {_display_text(args.plan_id)}.", flush=True)
    try:
        saved, cancelled = asyncio.run(execute())
    except KeyboardInterrupt:
        print("Collaboration interrupted; inspect saved records before retrying.", file=sys.stderr)
        return 130
    print(f"Status: {saved.record['status']}")
    print(f"Run record: {saved.record_path}")
    print(f"Model requests: {len(saved.record['model_calls'])}")
    if saved.record["tool_log_path"]:
        print(f"Tool log: {saved.record['tool_log_path']}")
    folder = PurePosixPath(saved.record_path).parent
    for name, label in (("validation_report.json", "Validation report"),
                        (QUOTATION_PAGE_REPORT_PATH, "Quotation/page diagnostic")):
        if storage.resolve_project_path(root, f"{folder}/{name}").is_file():
            print(f"{label}: {folder}/{name}")
    if saved.quotation_diagnostics is not None:
        summary = saved.quotation_diagnostics["summary"]
        print(f"Quotation/page corrections: {summary['corrected']}")
        print(f"Quotation/page flags: {summary['possible_page_mismatch']} possible page mismatches; "
              f"{summary['unmatched_quote']} unmatched quotations; {summary['unconfirmed_page_span']} unconfirmed spans.")
    for label, error in (("Error", saved.record["error"]), ("Saving error", saved.persistence_error)):
        if error:
            print(f"{label}: {error}", file=sys.stderr)
    if cancelled:
        print("Collaboration cancelled; available evidence was retained where saving succeeded.", file=sys.stderr)
    return 130 if cancelled else (0 if saved.record["status"] == "succeeded" and not saved.persistence_error else 1)


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


def _create_expert_reference(root: Path, args: argparse.Namespace) -> None:
    """Create a form without model calls, then show where the expert can edit it."""
    path = expert_files.create_expert_reference(
        root, args.plan_id, prepared_by=args.prepared_by
    )
    print(f"Expert reference: {path}")
    print("Added guided blank action action_0001 and expert issue issue_0001.")
    print("Replace TODO: guidance and remove unused blanks before validation; use the original PDF.")
    print("For comparison plans, complete it before viewing model outputs.")


def _validate_expert_reference(root: Path, plan_id: str) -> None:
    """Report checks without marking the expert's scientific assessment complete."""
    reference = expert_files.validate_expert_reference(root, plan_id)
    actions = reference["plan_data"]["actions"]
    print(f"Expert reference validation passed for {_display_text(plan_id)}.")
    print(f"Actions: {len(actions)}")
    print(f"Issues: {len(reference.get('plan_issues', {}).get('issues', []))}")
    freeze = storage.load_expert_reference_freeze(root, plan_id)
    if freeze is not None:
        print("Frozen reference and source fingerprints verified.")
    if not actions and freeze is None:
        print("Actions are empty; the form still needs expert completion.")
    print("Checks cover structure, source links, and page bounds. Experts still assess accuracy and completeness.")


def _edit_expert_reference(root: Path, args: argparse.Namespace) -> None:
    """Expose one explicit edit per invocation, leaving human coding in the form."""
    if args.add_action or args.add_issue:
        operation = "add_action" if args.add_action else "add_issue"
        record_id = None
    else:
        operation = "remove_action" if args.remove_action is not None else "remove_issue"
        record_id = getattr(args, operation) or None
    path, affected_id = expert_files.edit_expert_reference(
        root, args.plan_id, operation=operation, record_id=record_id,
    )
    print(f"Expert reference: {path}")
    verb = "Added blank" if operation.startswith("add_") else "Removed"
    print(f"{verb} {affected_id}.")


def _freeze_expert_reference(root: Path, args: argparse.Namespace) -> None:
    """Record the named reviewer's confirmation without starting model work."""
    path = expert_files.freeze_expert_reference(root, args.plan_id, frozen_by=args.frozen_by)
    freeze = storage.load_expert_reference_freeze(root, args.plan_id)
    print(f"Expert reference freeze: {path}")
    print(f"Reference SHA-256: {freeze['reference_sha256']}")
    print("Reference frozen for assessment; editor changes are blocked.")
    print("Use this reference fingerprint when recording judgments. Freezing does not enable comparison runs.")


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


def _list_profiles(root: Path, args: argparse.Namespace) -> None:
    """Show command-level choices without credentials, inference, or file writes."""
    configuration = agents.load_profiles(root, config_path=args.config_path)
    commands = {"extractor": ("E", "run_extract_mode"), "verifier": ("V", "run_verify_mode")}
    profiles = [
        agents.load_profile(root, profile["name"], stage=profile["stage"], config_path=args.config_path)
        for profile in configuration["profiles"] if profile["stage"] in commands
    ]
    bindings = load_collaboration_profiles(root, config_path=args.collaboration_config_path)
    collaborations = [
        load_collaboration_configuration(
            root, binding["name"], config_path=args.collaboration_config_path,
            model_config_path=args.config_path,
        )
        for binding in bindings["profiles"]
    ]
    # Validate all choices before printing so a damaged binding cannot produce a
    # partial listing that looks complete. Internal C roles are nested under C.
    for profile in profiles:
        mode, command = commands[profile["stage"]]
        print(f"{mode}: {_display_text(profile['name'])} ({command})")
        _print_profile_model("model", profile)
        # Historical profiles omit the independent cap and keep their tool-derived
        # bound. All request ceilings include final generation.
        requests = profile.get("max_model_requests", profile["max_tool_calls"] + 1)
        print(f"  Model requests: up to {requests}; "
              f"document-tool calls: {profile['max_tool_calls']}")
        if "max_estimated_tokens" in profile:
            print(f"  Configuration estimated-token allowance: {profile['max_estimated_tokens']:,} "
                  "(E+V shares E and V)")
        ceiling = profile.get("max_elapsed_seconds")
        print(f"  Elapsed ceiling: {_elapsed_ceiling(ceiling)}")
        if "final_generation_seconds" in profile:
            print(f"  Protected final window: {_elapsed_ceiling(profile['final_generation_seconds'])}; "
                  "E+V reserves this for the final V answer")
    for binding, actors in collaborations:
        print(f"C: {_display_text(binding['name'])} (run_collaboration_mode; development only)")
        for actor, profile in actors.items():
            _print_profile_model(actor, profile)
        limits = binding["limits"]
        print(f"  Shared ceilings: {limits['max_model_requests']} model requests; "
              f"{limits['max_document_tool_calls']} document-tool calls; "
              f"{_elapsed_ceiling(limits['max_elapsed_seconds'])}")
        print(f"  Aggregate estimated-token allowance: {limits['max_estimated_tokens']:,}")
        reserve = limits.get("final_generation_seconds", actors["coordinator"]["model_timeout_seconds"])
        print(f"  Protected final window: {_elapsed_ceiling(reserve)} for the coordinator")
    print("Model requests include final generation. E+V combines stage request limits and shares elapsed time; "
          "V subtracts its linked E duration.")


def _print_profile_model(label: str, profile: dict) -> None:
    """Keep per-request limits and each actor's document-tool cap visible."""
    print(f"  {label}: {_display_text(profile['model']['name'])} "
          f"(Hugging Face / {_display_text(profile['model']['provider'])})")
    print(f"    Context/request: {profile['context_limit']:,}; "
          f"output/request: {profile['generation']['max_output_tokens']:,}; "
          f"document-tool calls: {profile['max_tool_calls']}")


def _elapsed_ceiling(seconds: float | None) -> str:
    """Display historical profiles with no ceiling without inventing one."""
    return "not configured" if seconds is None else f"{seconds / 60:g} min"


def _display_text(value: str) -> str:
    """Keep table rows on one line; the saved metadata remains unchanged."""
    return " ".join(value.split())


def _display_error(error: Exception) -> None:
    """Send problems and any recovery notes to stderr, separate from normal output."""
    if isinstance(error, (storage.RegistryValidationError, storage.PreparationValidationError,
                          storage.RunValidationError, storage.ExpertReferenceValidationError,
                          agents.ProfileValidationError, agents.ExtractorInputError)):
        label = ("Registry" if isinstance(error, storage.RegistryValidationError) else
                 "Preparation" if isinstance(error, storage.PreparationValidationError) else
                 "Expert reference" if isinstance(error, storage.ExpertReferenceValidationError) else "Extraction")
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
