"""Locate quotations and conservatively correct single-page citations.

These source-based checks follow structural validation, not factual assessment.
Whitespace is collapsed; words, case, punctuation and hyphens are preserved.
Only a unique alternative page can replace a single available cited page.
Unmatched quotations and ambiguous locations remain review flags. Functions
return independent data without editing inputs or reading/writing files.
"""

from copy import deepcopy
import json
import re


QUOTATION_PAGE_REPORT_PATH = "artifacts/quotation_page_report.json"


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _successful_ocr_readings(tool_log, page_numbers: set[int]):
    """Use only successful run_ocr results agreeing with their requested page.

    The caller supplies logs bound to this preparation by the saved runner.
    Prepared-text tools need no separate reading because pages already contain
    their source. Fresh OCR is an additional reading, not a replacement for it.
    """
    for entry in tool_log:
        if entry.get("tool") != "run_ocr" or entry.get("error") is not None:
            continue
        reply = entry.get("result")
        if not isinstance(reply, dict) or reply.get("isError"):
            continue
        data = reply.get("structuredContent")
        if data is None:
            # The MCP adapter also accepts text containing a JSON tool result.
            blocks = reply.get("content", [])
            if not isinstance(blocks, list):
                continue
            texts = [b.get("text") for b in blocks if isinstance(b, dict) and b.get("type") == "text"]
            if len(texts) != 1 or not isinstance(texts[0], str):
                continue
            try:
                data = json.loads(texts[0])
            except ValueError:
                continue
        if not isinstance(data, dict) or data.get("text_source") != "ocr":
            continue
        page = data.get("page_number")
        text = data.get("text")
        requested = entry.get("arguments", {}).get("page_number")
        if (type(page) is int and page in page_numbers
                and type(requested) is int and page == requested
                and isinstance(text, str) and text.strip()):
            yield page, _normalize(text)


def _matches_cited_span(quote: str, cited: list[int], readings: dict[int, list[str]]) -> bool:
    """Confirm that a match actually uses text from every cited page.

    Check the prepared reading and a second view using the latest successful OCR
    reading where available. Avoid constructing synthetic passages by joining
    alternative readings of the same page. Other multi-page OCR combinations
    remain unconfirmed rather than expanding a potentially exponential search.
    This checks text location, not whether the PDF layout forms one passage.
    """
    if any(right != left + 1 for left, right in zip(cited, cited[1:])):
        return False  # Do not join pages across an uncited intervening page.
    for version in (0, -1):
        chunks = [readings[n][version] for n in cited]
        combined = " ".join(chunks)
        ranges = []
        cursor = 0
        for page, text in zip(cited, chunks):
            ranges.append((page, cursor, cursor + len(text)))
            cursor += len(text) + 1
        start = combined.find(quote)
        while start >= 0:
            end = start + len(quote)
            covered = [page for page, low, high in ranges if low < end and high > start and high > low]
            if covered == cited:
                return True
            start = combined.find(quote, start + 1)
    return False


def diagnose_quotation_pages(plan_data: dict, pages: list[dict], *, tool_log=()) -> dict:
    """Check all evidence in a validated answer against source-bound readings.

    The runner has already checked IDs, page ranges, preparation integrity and
    tool provenance. Repeated text on another page does not invalidate a match
    on the cited page. Missing/unreadable text and unmatched spans need review;
    neither means the quotation was fabricated. Evidence indices are zero-based.
    """
    readings = {p["page_number"]: [_normalize(p["text"] or "")] for p in pages}
    ocr_pages = set()
    for page, text in _successful_ocr_readings(tool_log, set(readings)):
        ocr_pages.add(page)
        if text != readings[page][-1]:
            readings[page].append(text)

    summary = {"checked": 0, "matched": 0, "possible_page_mismatch": 0,
               "unmatched_quote": 0, "unconfirmed_page_span": 0}
    findings = []
    # Repeated evidence is common across actions; locate each distinct text once.
    locations = {}
    for action in plan_data["actions"]:
        for index, evidence in enumerate(action["evidence"]):
            summary["checked"] += 1
            quote = _normalize(evidence["quote"])
            cited = sorted(evidence["page_numbers"])
            if quote not in locations:
                locations[quote] = [page for page, versions in sorted(readings.items())
                                    if any(quote in text for text in versions if text)]
            matching = locations[quote]
            if ((len(cited) == 1 and cited[0] in matching)
                    or (len(cited) > 1 and _matches_cited_span(quote, cited, readings))):
                summary["matched"] += 1
                continue
            if matching and not set(cited).intersection(matching):
                kind = "possible_page_mismatch"
            elif len(cited) > 1:
                kind = "unconfirmed_page_span"
            else:
                kind = "unmatched_quote"
            summary[kind] += 1
            findings.append({
                "action_id": action["action_id"], "evidence_index": index,
                "quote": evidence["quote"], "cited_page_numbers": evidence["page_numbers"][:],
                "matching_page_numbers": matching[:], "finding_type": kind,
                "cited_pages_without_text": [n for n in cited if not any(readings[n])],
            })
    return {"schema_version": 1, "normalization": "whitespace_only",
            "ocr_page_numbers": sorted(ocr_pages), "summary": summary, "findings": findings}


def correct_quotation_pages(plan_data: dict, pages: list[dict], *, tool_log=()) -> tuple[dict, dict]:
    """Return a copied answer and a report of repairs and remaining flags.

    Require an available single cited page, no match there, and exactly one
    matching alternative physical page across all available source readings.
    Unavailable cited text cannot establish a mismatch; repeated or multi-page
    passages require review. Only evidence.page_numbers can change. The caller
    must validate the returned candidate before accepting or saving it.
    """
    initial = diagnose_quotation_pages(plan_data, pages, tool_log=tool_log)
    candidate = deepcopy(plan_data)
    positions = {action["action_id"]: index for index, action in enumerate(candidate["actions"])}
    repairs = []
    for finding in initial["findings"]:
        if (finding["finding_type"] != "possible_page_mismatch"
                or len(finding["cited_page_numbers"]) != 1
                or len(finding["matching_page_numbers"]) != 1
                or finding["cited_pages_without_text"]):
            continue
        action_index = positions[finding["action_id"]]
        evidence_index = finding["evidence_index"]
        pages_after = finding["matching_page_numbers"][:]
        candidate["actions"][action_index]["evidence"][evidence_index]["page_numbers"] = pages_after
        repairs.append({
            "rule": "quotation_page_number",
            "location": f"$.plan_data.actions[{action_index}].evidence[{evidence_index}].page_numbers",
            "action_id": finding["action_id"], "evidence_index": evidence_index,
            "quote": finding["quote"], "before": finding["cited_page_numbers"][:], "after": pages_after[:],
        })
    final = diagnose_quotation_pages(candidate, pages, tool_log=tool_log) if repairs else initial
    report = {**final, "schema_version": 2, "initial_summary": initial["summary"].copy(),
              "summary": {**final["summary"], "corrected": len(repairs)}, "repairs": repairs}
    return candidate, report
