"""Apply only the final-response format repairs permitted by DESIGN.md Appendix F.

This module edits text, not research claims. It does not call models, access
files, fill missing fields, normalize IDs, or decide whether an answer is valid.
validation.validate_and_repair_agent_response runs the full checks afterward.
"""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal


# The future model adapter must translate provider-specific completion metadata
# into one of these states. "normal" requires positive evidence that the request
# finished normally; a parseable answer alone cannot establish that fact.
CompletionStatus = Literal["normal", "unknown", "truncated", "failed"]
COMPLETION_STATUSES = ("normal", "unknown", "truncated", "failed")
_JSON_WHITESPACE = " \t\r\n"
_RECORD_LISTS = {
    "plan_goals", "plan_actions", "plan_mon_eval", "plan_benefits", "plan_costs",
}
_FENCE = re.compile(
    r"[ \t\r\n]*```(?:json)?[ \t]*\r?\n(?P<body>.*?)\r?\n```[ \t\r\n]*",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class RepairChange:
    """One exact change, using the four string fields required by the report."""

    rule: str
    location: str
    before: str
    after: str


@dataclass(frozen=True)
class RepairResult:
    """The candidate text and its ordered audit trail; neither implies validity."""

    candidate_text: str
    repairs: tuple[RepairChange, ...]


@dataclass(frozen=True)
class _TextEdit:
    """An internal replacement of text[start:end], with an optional field path."""

    start: int
    end: int
    replacement: str
    location: str | None = None


def repair_agent_response(text: str, *, completion_status: CompletionStatus) -> RepairResult:
    """Return a separate candidate, applying allowed repairs once in fixed order.

    Failed or truncated requests receive no repairs. Unknown completion permits
    the other formatting rules, but never the missing-closing-delimiter rule.
    The caller retains the original string and must fully validate the result.
    """
    if completion_status not in COMPLETION_STATUSES:
        raise ValueError("Completion status must be normal, unknown, truncated, or failed.")
    if completion_status in ("truncated", "failed"):
        return RepairResult(text, ())

    changes = []
    candidate = text

    # Rule 1: remove a whole-response JSON fence only after checking that its
    # body is one JSON value, allowing the following permitted syntax repairs.
    # This look-ahead never publishes edits or permits surrounding commentary.
    match = _FENCE.fullmatch(candidate)
    if match and _fence_contains_one_answer(match["body"], completion_status):
        body = match["body"]
        changes.append(RepairChange("json_code_fence", "$", candidate, body))
        candidate = body

    # Rule 2: quotes and backslash escapes are scanned before looking for commas.
    # A quotation such as "Keep ,} exactly" must remain byte-for-byte unchanged.
    comma_candidate, comma_changes = _apply_edits(
        candidate, _trailing_comma_edits(candidate), "trailing_comma"
    )
    # Confirm that comma removal describes one JSON answer, possibly still
    # missing closers. Otherwise a comma-looking fragment might be prose or an
    # invalid quotation. Do not alter that ambiguous text. This check may inspect
    # hypothetical closers even when completion is unknown; it never appends them.
    if _is_strict_json(comma_candidate) or _with_missing_closers(comma_candidate) is not None:
        candidate = comma_candidate
        changes.extend(comma_changes)

    # Rule 3: the stack tells us which delimiters are open; a strict parse of
    # the proposed result proves that nothing besides closing them is missing.
    if completion_status == "normal":
        closed = _with_missing_closers(candidate)
        if closed is not None:
            suffix = closed[len(candidate):]
            changes.append(RepairChange(
                "missing_closing_delimiters", _text_location(candidate, len(candidate)), "", suffix
            ))
            candidate = closed

    # Rule 4: walk only syntactically unambiguous JSON and replace integer token
    # spans at known evidence paths. Do not reserialize the decoded dictionary:
    # doing so could change quotations, numeric spellings, and whitespace.
    if _is_strict_json(candidate):
        candidate, page_changes = _apply_edits(
            candidate, _single_page_number_edits(candidate), "single_page_number"
        )
        changes.extend(page_changes)

    return RepairResult(candidate, tuple(changes))


def _fence_contains_one_answer(body: str, completion_status: CompletionStatus) -> bool:
    """Reject prose, multiple JSON values, and bodies needing unapproved fixes."""
    edits = _trailing_comma_edits(body)
    candidate, _ = _apply_edits(body, edits, "trailing_comma")
    if _is_strict_json(candidate):
        return True
    return completion_status == "normal" and _with_missing_closers(candidate) is not None


def _outside_string_characters(text: str) -> Iterator[tuple[int, str]]:
    """Yield positions and characters outside strings, respecting escaped quotes.

    This is a small scanner, not a replacement JSON parser. Invalid strings stay
    invalid; the strict parser remains responsible for detecting syntax errors.
    """
    in_string = False
    escaped = False
    for index, character in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        else:
            yield index, character


def _trailing_comma_edits(text: str) -> list[_TextEdit]:
    edits = []
    for index, character in _outside_string_characters(text):
        if character != ",":
            continue
        following = index + 1
        while following < len(text) and text[following] in _JSON_WHITESPACE:
            following += 1
        if following < len(text) and text[following] in "}]":
            edits.append(_TextEdit(index, index + 1, ""))
    return edits


def _with_missing_closers(text: str) -> str | None:
    """Suggest only unambiguous closing characters after a complete JSON value."""
    stack = []
    for _, character in _outside_string_characters(text):
        if character in "{[":
            stack.append("}" if character == "{" else "]")
        elif character in "}]":
            if not stack or stack.pop() != character:
                return None  # A mismatched closer cannot be fixed by appending.

    # An empty container, dangling comma/colon, or missing value would require
    # more than closing a complete value. Do not infer empty objects or lists.
    ending = text.rstrip(_JSON_WHITESPACE)
    if not stack or not ending or ending[-1] in "{[:,":
        return None
    candidate = text + "".join(reversed(stack))
    # An unfinished string, number, literal, or field still fails this parse.
    # Duplicate fields also fail; we cannot choose which value was intended.
    return candidate if _is_strict_json(candidate) else None


def _is_strict_json(text: str) -> bool:
    """Check one JSON value without silently selecting duplicate field values.

    Decoding here is only a safety gate for text edits. It checks no schema or
    research rules, and its decoded result is never substituted for the text.
    """
    def unique_fields(pairs: list[tuple[str, object]]) -> dict:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON field.")
            result[key] = value
        return result

    def reject_constant(value: str):
        raise ValueError(f"Non-standard JSON number: {value}.")

    try:
        json.loads(text, object_pairs_hook=unique_fields, parse_constant=reject_constant)
    except ValueError:
        return False
    return True


def _single_page_number_edits(text: str) -> list[_TextEdit]:
    """Find positive integer values only at content record evidence paths.

    This walk runs only after a strict syntax check. raw_decode returns each
    value and the position just after it, letting us retain original text spans.
    """
    decoder = json.JSONDecoder()
    edits = []

    def skip_whitespace(index: int) -> int:
        while index < len(text) and text[index] in _JSON_WHITESPACE:
            index += 1
        return index

    def walk(index: int, path: tuple) -> int:
        index = skip_whitespace(index)
        if text[index] == "{":
            index = skip_whitespace(index + 1)
            while text[index] != "}":
                key, index = decoder.raw_decode(text, index)
                index = walk(skip_whitespace(index) + 1, path + (key,))  # Skip the colon.
                index = skip_whitespace(index)
                if text[index] == "}":
                    break
                index = skip_whitespace(index + 1)  # Skip the comma between fields.
            return index + 1
        if text[index] == "[":
            index = skip_whitespace(index + 1)
            item_number = 0
            while text[index] != "]":
                index = skip_whitespace(walk(index, path + (item_number,)))
                if text[index] == "]":
                    break
                index = skip_whitespace(index + 1)
                item_number += 1
            return index + 1

        value, end = decoder.raw_decode(text, index)
        is_evidence_page = (
            len(path) == 6 and path[0] == "content" and path[1] in _RECORD_LISTS
            and isinstance(path[2], int) and path[3] == "evidence"
            and isinstance(path[4], int) and path[5] == "page_numbers"
        )
        # bool is a subclass of int in Python, so use exact type equality. Text,
        # floats, zero, negatives, and unknown fields must not be interpreted.
        if is_evidence_page and type(value) is int and value > 0:
            location = f"$.content.{path[1]}[{path[2]}].evidence[{path[4]}].page_numbers"
            edits.append(_TextEdit(index, end, f"[{text[index:end]}]", location))
        return end

    walk(0, ())
    return edits


def _apply_edits(text: str, edits: list[_TextEdit], rule: str) -> tuple[str, list[RepairChange]]:
    """Log edits in reading order, then apply them backward to keep offsets valid."""
    changes = [RepairChange(
        rule, edit.location or _text_location(text, edit.start),
        text[edit.start:edit.end], edit.replacement,
    ) for edit in edits]
    # Later replacements cannot move any earlier span. Applying edits forward
    # would make stored positions incorrect whenever the text length changes.
    for edit in reversed(edits):
        text = text[:edit.start] + edit.replacement + text[edit.end:]
    return text, changes


def _text_location(text: str, index: int) -> str:
    """Use one-based line/column positions in the candidate before this rule."""
    line = text.count("\n", 0, index) + 1
    column = index - text.rfind("\n", 0, index)
    return f"line {line}, column {column}"
