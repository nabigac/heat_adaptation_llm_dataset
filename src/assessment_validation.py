"""Read-only checks for manual assessment CSVs and their exact saved inputs.

Validity and review completion are separate. Blank/undetermined judgments are
pending; malformed data or broken provenance is invalid. This module checks
links and consistency, never the correctness of an expert's source judgments.
"""

import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from io import StringIO
import json
from pathlib import Path
import re

import assessments
import storage
import validation
from validation import ValidationProblem


TABLE_COLUMNS = {
    "action_scores.csv": assessments.ACTION_COLUMNS,
    "output_review.csv": assessments.OUTPUT_COLUMNS,
    "verifier_resolutions.csv": assessments.RESOLUTION_COLUMNS,
}
CONFIGURATIONS = ("E", "E+V", "C")


@dataclass(frozen=True)
class PendingJudgment:
    """An unfinished review field or coverage gap, separate from invalid data."""

    table: str
    location: str
    message: str
    configuration: str | None = None


@dataclass(frozen=True)
class AssessmentData:
    """Validated inputs and parsed judgments for later calculations.

    Numeric scores and JSON cells are parsed in memory. Source files are never
    rewritten. The fingerprint map identifies the exact four assessment files.
    Frozen dataclasses prevent field reassignment, not edits inside their dicts.
    """

    metadata: dict
    reference: dict
    runs: dict
    tables: dict
    fingerprints: dict


@dataclass(frozen=True)
class AssessmentValidation:
    """Withhold usable assessment data on any validation error."""

    data: AssessmentData | None
    problems: list[ValidationProblem]
    pending: list[PendingJudgment]
    readiness: dict

    @property
    def valid(self) -> bool:
        return self.data is not None and not self.problems

    @property
    def complete(self) -> bool:
        return self.valid and not self.pending


def _location(table, row=None, field=None):
    result = table if row is None else f"{table}:row {row}"
    return result if field is None else f"{result}.{field}"


def _assessment_file(root, folder, name):
    path = storage.resolve_project_path(root, f"{folder}/{name}")
    if path.is_symlink() or path.resolve() != path:
        raise ValueError("Assessment paths must not use symbolic links.")
    return path


def _input_context(root, plan_id, metadata):
    """Load every recorded ID explicitly; never choose today's latest runs."""
    for configuration, run in metadata["runs"].items():
        expected = f"runs/{plan_id}/{run['run_id']}/output.json"
        if run["record_path"] != expected:
            raise ValueError(f"{configuration} must identify its canonical saved output path.")
        if run["selected_via"] == "verifier_link" and configuration != "E":
            raise ValueError("Only E can be selected through a verifier link.")
    if (metadata["runs"]["E"]["selected_via"] == "verifier_link"
            and metadata["runs"]["E+V"]["selected_via"] != "explicit"):
        raise ValueError("An E selected through a verifier link requires an explicit V selection.")
    expected_reference = f"data/expert_references/{plan_id}/expert_reference.json"
    expected_freeze = f"data/expert_references/{plan_id}/reference_freeze.json"
    if (metadata["reference"]["path"] != expected_reference
            or metadata["reference"]["freeze_path"] != expected_freeze):
        raise ValueError("The assessment must identify this plan's canonical reference and freeze paths.")
    snapshots = assessments.select_assessment_runs(
        root, plan_id, extractor_run_id=metadata["runs"]["E"]["run_id"],
        verifier_run_id=metadata["runs"]["E+V"]["run_id"],
        collaboration_run_id=metadata["runs"]["C"]["run_id"],
    )
    for configuration, snapshot in snapshots.items():
        if snapshot["record_sha256"] != metadata["runs"][configuration]["record_sha256"]:
            raise ValueError(f"The selected {configuration} output differs from its assessment fingerprint.")
    reference, freeze, identity = assessments._reference_snapshot(root, plan_id)
    if identity != metadata["reference"]:
        raise ValueError("The reference or freeze differs from its assessment fingerprint.")
    source_path = snapshots["E"]["record"]["source_path"]
    _, preparation, pages = storage.load_plan_preparation(root, plan_id, source_path)
    expected_source = {
        "preparation_path": source_path,
        "fingerprint": storage.preparation_text_fingerprint(preparation, pages),
        "document_sha256": preparation["document_sha256"].lower(), "page_count": preparation["page_count"],
    }
    if metadata["source"] != expected_source:
        raise ValueError("Assessment source metadata must match the selected preparation.")
    if (expected_source["document_sha256"] != freeze["document_sha256"]
            or expected_source["page_count"] != freeze["page_count"]):
        raise ValueError("The frozen reference and selected preparation must identify the same original PDF.")
    return reference, snapshots


def _read_csv(raw, table, columns, problems):
    """Accept ordinary UTF-8 spreadsheet exports, preserving cell values.

    The default csv field limit can reject long evidence copied by our creator.
    Temporarily size it to this input and restore the process setting afterward.
    Row locations use logical spreadsheet rows, including cells with line breaks.
    """
    old_limit = csv.field_size_limit()
    try:
        text = raw.decode("utf-8-sig")
        csv.field_size_limit(max(old_limit, len(text)))
        reader = csv.reader(StringIO(text, newline=""), strict=True)
        headers = next(reader, None)
        if headers is None or len(headers) != len(set(headers)) or set(headers) != set(columns):
            problems.append(ValidationProblem("structure", table,
                "CSV headers must contain each expected column exactly once: " + ", ".join(columns)))
            return None
        rows = []
        for number, cells in enumerate(reader, 2):
            if not cells:  # Empty physical lines are not review rows.
                continue
            if len(cells) != len(headers):
                problems.append(ValidationProblem("structure", _location(table, number),
                    f"Expected {len(headers)} cells; found {len(cells)}."))
                continue
            rows.append((number, dict(zip(headers, cells))))
        return rows
    except (UnicodeError, csv.Error) as error:
        problems.append(ValidationProblem("syntax", table, f"Could not read CSV: {error}"))
        return None
    finally:
        csv.field_size_limit(old_limit)


class _ReviewCheck:
    """Keep error/pending collection and the three table checks together."""

    def __init__(self, reference, snapshots):
        self.reference = {action["action_id"]: action for action in reference["plan_data"]["actions"]}
        self.runs = {configuration: snapshot["record"] for configuration, snapshot in snapshots.items()}
        self.outputs = {configuration: {action["action_id"]: action for action in run["plan_data"]["actions"]}
                        for configuration, run in self.runs.items()}
        self.problems, self.pending = [], []
        self.readiness = {
            "reference_actions": dict.fromkeys(CONFIGURATIONS, True),
            "output_support": dict.fromkeys(CONFIGURATIONS, True),
            "output_evidence": dict.fromkeys(CONFIGURATIONS, True),
            "verifier_resolutions": True,
        }

    def problem(self, location, message, category="reference"):
        self.problems.append(ValidationProblem(category, location, message))

    def unfinished(self, table, row, field, message, configuration=None):
        self.pending.append(PendingJudgment(table, _location(table, row, field), message, configuration))

    def role(self, row, table, number):
        configuration = row["configuration"]
        if configuration not in self.runs:
            self.problem(_location(table, number, "configuration"), "Use E, E+V, or C.", "structure")
            return None
        if row["run_id"] != self.runs[configuration]["run_id"]:
            self.problem(_location(table, number, "run_id"), "Run ID must match the recorded configuration.")
            return None
        return configuration

    def identifiers(self, value, known, table, number, field, configuration, *, allow_empty):
        if not value.strip():
            self.unfinished(table, number, field, "ID links have not been reviewed.", configuration)
            return None
        try:
            result = validation._decode_json(value)
        except (ValueError, RecursionError) as error:
            self.problem(_location(table, number, field), f"Enter a JSON list of IDs: {error}", "syntax")
            return None
        if not isinstance(result, list) or any(not isinstance(item, str) or not item.strip() for item in result):
            self.problem(_location(table, number, field), "Enter a JSON list of nonblank string IDs.", "structure")
            return None
        if len(result) != len(set(result)):
            self.problem(_location(table, number, field), "ID lists must not contain duplicates.")
        if not result and not allow_empty:
            self.problem(_location(table, number, field), "An output activity must link at least one output record.")
        unknown = set(result) - set(known)
        if unknown:
            self.problem(_location(table, number, field), "Unknown output IDs: " + ", ".join(sorted(unknown)))
        return result

    def choice(self, value, table, number, field, configuration=None):
        result = value.strip().casefold()
        if not result:
            self.unfinished(table, number, field, "Judgment is pending.", configuration)
            return None
        if result not in {"yes", "no", "undetermined"}:
            self.problem(_location(table, number, field), "Use yes, no, or undetermined.", "structure")
            return None
        if result == "undetermined":
            self.unfinished(table, number, field, "Judgment remains undetermined.", configuration)
        return result

    def reason(self, value, table, number, configuration=None):
        if not value.strip():
            self.unfinished(table, number, "reason", "An explanation is pending.", configuration)
            return False
        return True

    def copied_text(self, value, expected, table, number, field):
        # Spreadsheet export can change line endings without changing the text.
        normalize = lambda text: text.replace("\r\n", "\n").replace("\r", "\n")
        if normalize(value) != normalize(expected if expected is not None else ""):
            self.problem(_location(table, number, field), "Copied context must match the recorded source.")

    def evidence(self, value, table, number, *, field="evidence", expected=None, allowed=None):
        try:
            result = validation._decode_json(value)
        except (ValueError, RecursionError) as error:
            self.problem(_location(table, number, field), f"Invalid copied evidence JSON: {error}", "syntax")
            return None
        # JSON type identity matters: a page number changed to true must not pass
        # merely because Python considers True equal to 1. Key order may change.
        canonical = lambda data: json.dumps(data, sort_keys=True, ensure_ascii=False)
        if not isinstance(result, list):
            self.problem(_location(table, number, field), "Evidence context must be a JSON list.", "structure")
        elif expected is not None and canonical(result) != canonical(expected):
            self.problem(_location(table, number, field), "Reference evidence must match the frozen reference.")
        elif allowed is not None:
            source_items = {canonical(source) for source in allowed}
            if any(canonical(item) not in source_items for item in result):
                self.problem(_location(table, number, field), "Evidence context must come from the linked output records.")
        return result

    def scores(self, rows):
        table, seen, parsed = "action_scores.csv", set(), []
        for number, row in rows:
            configuration = self.role(row, table, number)
            if configuration is None:
                continue
            identifier = row["reference_action_id"]
            if identifier not in self.reference:
                self.problem(_location(table, number, "reference_action_id"), "Unknown frozen-reference action ID.")
                continue
            key = configuration, identifier
            if key in seen:
                self.problem(_location(table, number), "Each reference activity needs exactly one row per configuration.")
            seen.add(key)
            action = self.reference[identifier]
            self.copied_text(row["reference_action"], action["action"], table, number, "reference_action")
            evidence = self.evidence(row["reference_evidence"], table, number, field="reference_evidence", expected=action["evidence"])
            matches = self.identifiers(row["matched_output_action_ids"], self.outputs[configuration], table, number,
                                       "matched_output_action_ids", configuration, allow_empty=True)
            score = None
            if not row["score"].strip():
                self.unfinished(table, number, "score", "Score is pending.", configuration)
            else:
                try:
                    value = Decimal(row["score"].strip())
                    if not value.is_finite() or value not in {Decimal(0), Decimal("0.5"), Decimal(1)}:
                        raise InvalidOperation
                    score = float(value)
                except InvalidOperation:
                    self.problem(_location(table, number, "score"), "Score must be 0, 0.5, or 1.", "structure")
            explained = self.reason(row["reason"], table, number, configuration)
            if matches == [] and score is not None and score != 0:
                self.problem(_location(table, number, "score"), "A confirmed omission ([]) must score zero.")
            if matches is None or score is None or not explained:
                self.readiness["reference_actions"][configuration] = False
            parsed.append({**row, "matched_output_action_ids": matches, "score": score, "reference_evidence": evidence})
        for configuration in CONFIGURATIONS:
            for identifier in self.reference:
                if (configuration, identifier) not in seen:
                    self.problem(table, f"Missing scoring row for {configuration} / {identifier}.")
        return parsed

    def groups(self, rows):
        table, seen, parsed = "output_review.csv", set(), []
        covered = {configuration: set() for configuration in CONFIGURATIONS}
        for number, row in rows:
            configuration = self.role(row, table, number)
            if configuration is None:
                continue
            identifier = row["output_activity_id"]
            if not identifier.strip():
                self.problem(_location(table, number, "output_activity_id"), "Activity group ID must be nonblank.", "structure")
            if (configuration, identifier) in seen:
                self.problem(_location(table, number, "output_activity_id"), "Activity group IDs must be unique within a configuration.")
            seen.add((configuration, identifier))
            links = self.identifiers(row["output_action_ids"], self.outputs[configuration], table, number,
                                     "output_action_ids", configuration, allow_empty=False)
            allowed = None
            if links is not None:
                covered[configuration].update(links)
                allowed = [evidence for link in links if link in self.outputs[configuration]
                           for evidence in self.outputs[configuration][link]["evidence"]]
            evidence = self.evidence(row["evidence"], table, number, allowed=allowed)
            described = bool(row["activity_description"].strip())
            if not described:
                self.unfinished(table, number, "activity_description", "Describe the activity group.", configuration)
            support = self.choice(row["activity_supported"], table, number, "activity_supported", configuration)
            adequate = self.choice(row["evidence_adequate"], table, number, "evidence_adequate", configuration)
            explained = self.reason(row["reason"], table, number, configuration)
            support_ready = bool(links) and described and explained and support in {"yes", "no"}
            if not support_ready:
                self.readiness["output_support"][configuration] = False
            if not support_ready or adequate not in {"yes", "no"}:
                self.readiness["output_evidence"][configuration] = False
            if support == "no" and adequate == "yes":
                self.problem(_location(table, number, "evidence_adequate"), "An unsupported activity cannot have adequate evidence.")
            parsed.append({**row, "output_action_ids": links, "evidence": evidence,
                           "activity_supported": support, "evidence_adequate": adequate})
        for configuration in CONFIGURATIONS:
            missing = set(self.outputs[configuration]) - covered[configuration]
            if missing:
                self.unfinished(table, None, "output_action_ids",
                    "Activity groups do not yet cover output records: " + ", ".join(sorted(missing)), configuration)
                self.readiness["output_support"][configuration] = False
                self.readiness["output_evidence"][configuration] = False
        return parsed

    def resolutions(self, rows, snapshots):
        table, seen, parsed = "verifier_resolutions.csv", set(), []
        expected = {row["issue_id"]: row for row in assessments._verifier_resolution_rows(snapshots)}
        for number, row in rows:
            identifier = row["issue_id"]
            if identifier not in expected:
                self.problem(_location(table, number, "issue_id"), "Issue is not an eligible V resolution claim for this E/V pair.")
                continue
            if identifier in seen:
                self.problem(_location(table, number, "issue_id"), "Resolution claim rows must not be duplicated.")
            seen.add(identifier)
            for field in assessments.RESOLUTION_COLUMNS:
                if field not in {"confirmed", "reason"}:
                    self.copied_text(row[field], expected[identifier][field], table, number, field)
            confirmed = self.choice(row["confirmed"], table, number, "confirmed", "E+V")
            explained = self.reason(row["reason"], table, number, "E+V")
            if confirmed not in {"yes", "no"} or not explained:
                self.readiness["verifier_resolutions"] = False
            parsed.append({**row, "confirmed": confirmed})
        for identifier in set(expected) - seen:
            self.problem(table, f"Missing eligible V resolution claim: {identifier}.")
        return parsed


def validate_assessment(project_root: Path | str, plan_id: str, assessment_id: str) -> AssessmentValidation:
    """Validate exact assessment inputs and manual CSVs without writing files.

    Validity does not require completed judgments. Readiness describes review
    tables, not scientific correctness or whether future metrics have nonzero
    denominators. Failure-reporting scope is separate from manual completion.
    """
    return _validate_assessment_folder(project_root, plan_id, assessment_id,
                                       f"data/assessments/{plan_id}/{assessment_id}")


def _validate_assessment_folder(project_root, plan_id, assessment_id, folder):
    """Share live and archived review checks without selecting newer judgments.

    The saved-metrics loader supplies its canonical assessment_inputs folder.
    Reference, source, and run identities still resolve through strict loaders.
    """
    check = None
    try:
        root = Path(project_root).resolve()
        storage._require_run_identifier(plan_id)
        match = re.fullmatch(r"assessment_([0-9]+)", assessment_id) if isinstance(assessment_id, str) else None
        if match is None or not match[1].strip("0"):
            raise ValueError("Select a numbered assessment_NNNN ID.")
        metadata_path = _assessment_file(root, folder, "metadata.json")
        raw_files = {"metadata.json": metadata_path.read_bytes()}
        metadata, problems = validation.parse_assessment_metadata_json(raw_files["metadata.json"].decode("utf-8"))
        if problems:
            return AssessmentValidation(None, [ValidationProblem(p.category, f"metadata.json:{p.location or '$'}", p.message)
                                                for p in problems], [], {})
        if metadata["plan_id"] != plan_id or metadata["assessment_id"] != assessment_id:
            raise ValueError("Assessment metadata must match the selected plan and folder IDs.")
        reference, snapshots = _input_context(root, plan_id, metadata)
        check = _ReviewCheck(reference, snapshots)
        tables = {}
        for name, columns in TABLE_COLUMNS.items():
            try:
                raw_files[name] = _assessment_file(root, folder, name).read_bytes()
            except (OSError, ValueError) as error:
                check.problem(name, f"Could not read assessment file: {error}")
                continue
            rows = _read_csv(raw_files[name], name, columns, check.problems)
            if rows is None:
                continue
            if name == "action_scores.csv":
                tables[name] = check.scores(rows)
            elif name == "output_review.csv":
                tables[name] = check.groups(rows)
            else:
                tables[name] = check.resolutions(rows, snapshots)
        # Detect edits during validation, including supporting run/source files.
        assessments._recheck_inputs(root, plan_id, metadata)
        for name, raw in raw_files.items():
            if _assessment_file(root, folder, name).read_bytes() != raw:
                raise ValueError(f"Assessment file changed during validation; save it and retry: {name}")
        if check.problems:
            readiness = {name: dict.fromkeys(CONFIGURATIONS, False) if isinstance(value, dict) else False
                         for name, value in check.readiness.items()}
            return AssessmentValidation(None, check.problems, check.pending, readiness)
        data = AssessmentData(metadata, reference, {key: value["record"] for key, value in snapshots.items()}, tables,
                              {name: assessments._fingerprint(raw) for name, raw in raw_files.items()})
        return AssessmentValidation(data, [], check.pending, check.readiness)
    except (OSError, ValueError, RecursionError) as error:
        problems = [] if check is None else list(check.problems)
        problems.append(ValidationProblem("reference", "assessment inputs", str(error)))
        return AssessmentValidation(None, problems, [] if check is None else check.pending, {})
