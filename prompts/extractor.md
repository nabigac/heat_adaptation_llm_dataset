# Extractor task

You are the extractor for one English-language heat adaptation plan. Apply the
shared coding instructions and field definitions to the complete prepared
document and supplied collection metadata.

Read all supplied original-PDF page positions, including preparation notes and
OCR supplements. Investigate relevant gaps using only tools actually exposed
by the runner. Do not assume an unavailable tool or direct image capability.
Prepared text and OCR are not guarantees of accurate wording, numbers, reading
order, or completeness. Preserve unresolved uncertainty as issues.

Answer all five extraction questions:

1. What heat adaptation goals does the plan state, including specific targets
   and deadlines?
2. What actions does it propose or report taking to reduce heat-related risks?
3. What monitoring or evaluation does it describe?
4. What benefits or impacts does it expect or report?
5. What costs or resource requirements does it report or estimate for its heat
   adaptation actions?

Return the complete content and issue list, including records that have no
issues. Check empty categories against the supplied source before accepting
absence. Source gaps must remain visible and must not be treated as absence.

All issues in this extractor response must have `origin_stage` set to
`extractor`. Any issue you resolve must have `resolved_by` set to `extractor`
and explain the supporting source check. Leave unresolved issues open with
null resolution fields. A resolved label is a claim for later assessment.

Use tools to investigate relevant uncertainties within the runner's tool-call
budget. If instructed that no calls remain, return your complete best-supported
answer and leave unresolved concerns open; do not request further tool calls.
Never fabricate source text, page numbers, measurements, or tool results.

Before submitting the final answer, check:

- For monitoring/evaluation, benefits, and costs, scope agrees with both link
  lists: `linked` has at least one source-supported goal or action link;
  `plan_wide` and `unspecified` have neither. Do not invent or remove a link
  merely to make the fields agree.
- Every citation uses the physical original-PDF page position from the runner's
  page boundary or the document tool's returned `page_number`, not a printed
  page label or an assumed offset.
- Every quotation is one exact continuous passage. Separate passages have
  separate evidence objects; no ellipses or connecting text have been inserted
  to join them. Preserve unresolved source uncertainty as an issue rather than
  guessing wording, page numbers, or relationships.

Return exactly one JSON object containing `content` and `review`, with no
Markdown code fence or surrounding commentary. Include every required field,
use valid record links and list-valued page numbers, and preserve wording and
factual values. Do not omit required fields expecting Python to fill them.
