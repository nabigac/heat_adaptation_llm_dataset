# Extractor task

Extract all eligible heat adaptation activities from the complete supplied plan,
using the shared coding instructions and field definitions. Group each specific
activity across all neighborhoods, phases, and repeated mentions into one action
object. Return all nine action fields and the complete issue list.

Read every supplied original PDF page position, including preparation notes and
OCR supplements. Investigate relevant uncertainties with only the tools offered
by the runner and within its tool-call budget. When no calls remain, return the
best-supported complete answer and retain unresolved concerns as open issues.

All issues you raise have issue_origin set to extractor. Any issue you resolve
has resolved_by set to extractor and a source-supported explanation. Open issues
have null resolved_by and resolution fields. Never fabricate source text, page
positions, facts, tool results, or expert participation.

Before submission, check activity grouping, quantities and local associations,
action types and overall status, exact continuous quotations, physical PDF page
positions, valid action links, and issues for empty evidence or type lists.

Return exactly one JSON object containing plan_data and plan_issues, with every required
field and no surrounding Markdown or commentary. Python does not fill missing
fields or make substantive corrections to your answer.
