"""Check deterministic location diagnostics, independently of LLM quality."""

import copy
import json

import pytest

from quotation_diagnostics import correct_quotation_pages, diagnose_quotation_pages


def diagnose(quote, cited, texts, *, tool_log=()):
    data = {"actions": [{"action_id": "action_0001", "evidence": [
        {"quote": quote, "page_numbers": cited}]}]}
    pages = [{"page_number": n, "text": text} for n, text in enumerate(texts, 1)]
    before = copy.deepcopy((data, pages, tool_log))
    report = diagnose_quotation_pages(data, pages, tool_log=tool_log)
    assert (data, pages, tool_log) == before
    assert json.loads(json.dumps(report)) == report
    return report


def ocr(page, text):
    return {"tool": "run_ocr", "arguments": {"page_number": page}, "error": None,
            "result": {"isError": False, "structuredContent": {
                "page_number": page, "text_source": "ocr", "text": text}}}


def test_whitespace_normalization_preserves_an_exact_location():
    report = diagnose("We will plant 100 trees.", [1], ["We\nwill\tplant\u00a0100  trees."])
    assert report["summary"]["matched"] == report["summary"]["checked"] == 1
    assert report["findings"] == []


def test_quote_found_on_another_page_is_flagged_without_rewriting():
    report = diagnose("Plant 100 trees.", [2], ["Plant 100 trees.", "Other activity."])
    assert report["summary"]["possible_page_mismatch"] == 1
    finding = report["findings"][0]
    assert finding["cited_page_numbers"] == [2]
    assert finding["matching_page_numbers"] == [1]
    assert finding["quote"] == "Plant 100 trees."
    assert finding["action_id"] == "action_0001" and finding["evidence_index"] == 0


def test_repeated_text_elsewhere_does_not_invalidate_a_correct_citation():
    report = diagnose("Plant 100 trees.", [2], ["Plant 100 trees.", "Plant 100 trees."])
    assert report["summary"]["matched"] == 1 and not report["findings"]


@pytest.mark.parametrize("source", [None, "", "Plant 200 trees.", "plant 100 trees.", "Plant 100 trees!"])
def test_missing_or_different_text_is_unmatched_not_declared_fabricated(source):
    report = diagnose("Plant 100 trees.", [1], [source])
    assert report["summary"]["unmatched_quote"] == 1
    assert report["findings"][0]["matching_page_numbers"] == []


def test_an_unreadable_cited_page_is_identified_when_text_matches_elsewhere():
    report = diagnose("Plant 100 trees.", [1], [None, "Plant 100 trees."])
    assert report["findings"][0]["cited_pages_without_text"] == [1]
    assert report["findings"][0]["finding_type"] == "possible_page_mismatch"


def test_punctuation_and_line_end_hyphens_are_not_silently_repaired():
    report = diagnose('The "real-time" system.', [1], ['The “real-\ntime” system.'])
    assert report["summary"]["unmatched_quote"] == 1


def test_multi_page_match_must_use_text_from_every_cited_page():
    report = diagnose("will plant 100 trees", [2, 1], ["The plan will plant", "100 trees in North Ward."])
    assert report["summary"]["matched"] == 1
    extra = diagnose("100 trees", [1, 2], ["Plant 100 trees.", "Another activity."])
    assert extra["summary"]["unconfirmed_page_span"] == 1
    assert extra["findings"][0]["matching_page_numbers"] == [1]


def test_nonconsecutive_pages_are_not_joined_into_a_continuous_quotation():
    report = diagnose("will plant 100 trees", [1, 3],
                      ["The plan will plant", "Intervening passage.", "100 trees in North Ward."])
    assert report["summary"]["unconfirmed_page_span"] == 1


def test_successful_ocr_is_an_additional_source_reading():
    report = diagnose("Plant 100 trees.", [1], [None], tool_log=[ocr(1, "Plant\n100 trees.")])
    assert report["summary"]["matched"] == 1
    assert report["ocr_page_numbers"] == [1]


def test_an_earlier_ocr_reading_remains_available_for_single_page_matches():
    logs = [ocr(1, "Plant 100 trees."), ocr(1, "Plant 200 trees.")]
    assert diagnose("Plant 100 trees.", [1], [None], tool_log=logs)["summary"]["matched"] == 1


def test_ocr_alternatives_on_one_page_are_not_joined_into_a_fake_passage():
    report = diagnose("Plant 100 trees.", [1], ["Plant 100"], tool_log=[ocr(1, "trees.")])
    assert report["summary"]["unmatched_quote"] == 1


def test_ocr_can_support_a_multi_page_span_without_discarding_prepared_text():
    report = diagnose("will plant 100 trees", [1, 2], [None, "100 trees in North Ward."],
                      tool_log=[ocr(1, "The plan will plant")])
    assert report["summary"]["matched"] == 1


@pytest.mark.parametrize("problem", ["failed", "is-error", "wrong-page", "boolean-page", "empty-text", "other-tool"])
def test_failed_or_inconsistent_ocr_is_not_used_as_location_evidence(problem):
    entry = ocr(1, "Plant 100 trees.")
    if problem == "failed":
        entry["error"] = "Recognition failed."
    elif problem == "is-error":
        entry["result"]["isError"] = True
    elif problem == "wrong-page":
        entry["result"]["structuredContent"]["page_number"] = 2
    elif problem == "boolean-page":
        entry["arguments"]["page_number"] = True
    elif problem == "empty-text":
        entry["result"]["structuredContent"]["text"] = None
    else:
        entry["tool"] = "get_page_text"
    report = diagnose("Plant 100 trees.", [1], [None], tool_log=[entry])
    assert report["summary"]["unmatched_quote"] == 1


def test_mcp_json_text_fallback_is_available_when_structured_metadata_is_missing():
    entry = ocr(1, "Plant 100 trees.")
    data = entry["result"].pop("structuredContent")
    entry["result"]["content"] = [{"type": "text", "text": json.dumps(data)}]
    assert diagnose("Plant 100 trees.", [1], [None], tool_log=[entry])["summary"]["matched"] == 1


def test_unusable_raw_ocr_content_is_ignored():
    entry = ocr(1, "Plant 100 trees.")
    entry["result"] = {"content": None}
    report = diagnose("Plant 100 trees.", [1], [None], tool_log=[entry])
    assert report["summary"]["unmatched_quote"] == 1


def test_empty_evidence_produces_no_claim_about_source_adequacy():
    report = diagnose_quotation_pages({"actions": [{"action_id": "action_0001", "evidence": []}]}, [])
    assert report["summary"]["checked"] == report["summary"]["matched"] == 0
    assert report["findings"] == []


def correct(quote, cited, texts, *, tool_log=()):
    data = {"metadata": {"title": "Fictional plan"}, "actions": [{
        "action_id": "action_0001", "action": "Plant trees.", "evidence": [{
            "quote": quote, "page_numbers": cited}]}]}
    pages = [{"page_number": n, "text": text} for n, text in enumerate(texts, 1)]
    before = copy.deepcopy((data, pages, tool_log))
    candidate, report = correct_quotation_pages(data, pages, tool_log=tool_log)
    assert (data, pages, tool_log) == before
    assert candidate is not data and candidate["actions"] is not data["actions"]
    assert json.loads(json.dumps(report)) == report
    return candidate, report


def test_unique_full_quotation_corrects_only_the_page_and_preserves_audit_values():
    candidate, report = correct("Plant 100 trees.", [2], ["Plant\n100 trees.", "Other activity."])
    assert candidate["metadata"] == {"title": "Fictional plan"}
    assert candidate["actions"] == [{"action_id": "action_0001", "action": "Plant trees.",
                                   "evidence": [{"quote": "Plant 100 trees.", "page_numbers": [1]}]}]
    assert report["schema_version"] == 2 and report["normalization"] == "whitespace_only"
    assert report["initial_summary"]["possible_page_mismatch"] == 1
    assert report["summary"]["corrected"] == report["summary"]["matched"] == 1
    assert report["summary"]["possible_page_mismatch"] == 0 and report["findings"] == []
    assert report["repairs"] == [{
        "rule": "quotation_page_number", "action_id": "action_0001", "evidence_index": 0,
        "location": "$.plan_data.actions[0].evidence[0].page_numbers",
        "quote": "Plant 100 trees.", "before": [2], "after": [1],
    }]


@pytest.mark.parametrize("cited,texts", [
    ([2], ["Plant 100 trees.", "Other activity.", "Plant 100 trees."]),
    ([2], ["Plant 100 trees.", None]),
    ([2], ["Plant 100 trees.", ""]),
    ([1, 2], ["Other activity.", "Other activity.", "Plant 100 trees."]),
    ([2], ["Plant 200 trees.", "Other activity."]),
    ([2], ["plant 100 trees.", "Other activity."]),
    ([2], ["Plant 100 trees!", "Other activity."]),
    ([2], ["Plant 100\ntre-es.", "Other activity."]),
])
def test_ambiguous_unavailable_multi_page_and_inexact_locations_are_not_corrected(cited, texts):
    candidate, report = correct("Plant 100 trees.", cited, texts)
    assert candidate["actions"][0]["evidence"][0]["page_numbers"] == cited
    assert report["summary"]["corrected"] == 0 and report["repairs"] == []
    assert report["findings"]


def test_correct_citation_is_retained_even_when_other_pages_match():
    candidate, report = correct("Plant 100 trees.", [2], ["Plant 100 trees.", "Plant 100 trees."])
    assert candidate["actions"][0]["evidence"][0]["page_numbers"] == [2]
    assert report["summary"]["matched"] == 1 and report["repairs"] == []


def test_successful_ocr_can_locate_a_unique_alternative_page():
    candidate, report = correct("Plant 100 trees.", [1], ["Other activity.", None],
                                tool_log=[ocr(2, "Plant 100 trees.")])
    assert candidate["actions"][0]["evidence"][0]["page_numbers"] == [2]
    assert report["ocr_page_numbers"] == [2] and report["summary"]["corrected"] == 1


def test_available_ocr_on_the_cited_page_prevents_an_unnecessary_correction():
    candidate, report = correct("Plant 100 trees.", [1], [None, "Plant 100 trees."],
                                tool_log=[ocr(1, "Plant 100 trees.")])
    assert candidate["actions"][0]["evidence"][0]["page_numbers"] == [1]
    assert report["summary"]["matched"] == 1 and report["repairs"] == []


def test_repeated_evidence_across_actions_is_corrected_independently_and_only_once():
    data = {"metadata": {}, "actions": [{"action_id": f"action_{n:04d}", "evidence": [{
        "quote": "Plant trees.", "page_numbers": [2]}]} for n in (1, 2)]}
    before = copy.deepcopy(data)
    pages = [{"page_number": 1, "text": "Plant trees."}, {"page_number": 2, "text": "Another activity."}]
    candidate, report = correct_quotation_pages(data, pages)
    assert data == before
    assert report["summary"]["corrected"] == report["summary"]["matched"] == 2
    assert [change["action_id"] for change in report["repairs"]] == ["action_0001", "action_0002"]
    unchanged, second_report = correct_quotation_pages(candidate, pages)
    assert unchanged == candidate and second_report["repairs"] == []
    assert second_report["summary"]["corrected"] == 0
