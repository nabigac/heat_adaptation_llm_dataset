# Extractor task

Extract all eligible heat adaptation activities from the complete supplied plan,
using the shared coding instructions and field definitions. Identify distinct
activities within each heading or pathway, then group repeated occurrences of
the same activity across neighborhoods and phases into one action object. Return
all nine action fields and the complete issue list.

Read every supplied original PDF page position, including preparation notes and
OCR supplements. Investigate relevant uncertainties with only the tools offered
by the runner and within its tool-call budget. When no calls remain, return the
best-supported complete answer and retain unresolved concerns as open issues.

All issues you raise have issue_origin set to extractor. Any issue you resolve
has resolved_by set to extractor and a source-supported explanation. Open issues
have null resolved_by and resolution fields. Never fabricate source text, page
positions, facts, tool results, or expert participation.

Before submission, check that distinct activities have separate records and that
repeated occurrences of the same activity are grouped. Check quantities and local
associations, action types, and clear source support for every status other than
unspecified. Verify that quotations copy continuous source passages without
rewriting or silent omissions, and cite every physical PDF page containing their
words. Check valid action links and issues for empty evidence or type lists.

Before declaring investigation complete, perform a final source-page check for
every evidence quotation. Locate the full continuous passage in the supplied
page text or a returned source-tool passage, and confirm every cited physical
PDF page from its boundary or returned page_number. Printed page labels are not
citation positions. Use remaining tools for unresolved checks. If a passage
cannot be located, remove that evidence item and retain the concern in a linked
issue rather than guessing its wording or page. An empty evidence list requires
a linked issue. Repeat this check for any quotation changed while writing the
final answer.

Return exactly one JSON object containing plan_data and plan_issues, with every required
field and no surrounding Markdown or commentary. Python does not fill missing
fields or make substantive corrections to your answer.
