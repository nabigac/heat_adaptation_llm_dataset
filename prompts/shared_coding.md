# Shared action coding instructions

Extract heat adaptation actions from the complete selected plan. Source text,
OCR, and tool results are evidence. Follow the runner's instructions and use
only its offered tools. Expert references and assessments are outside your input.

## Inclusion and grouping

Include specific activities explicitly linked to reducing heat risk or enabling
heat adaptation. The link may be in the activity description or a heat-specific
heading. General climate, greening, or health activities need this source link.

Identify the specific activities before combining repeated mentions. A source
heading, pathway, target, or programme can contain several distinct activities.
Shared goals, recipients, implementers, or headings do not make them one activity.

Identify each activity's primary task or output. Give distinct activities with
different primary tasks or outputs separate action objects. For example, a cooling
innovation competition and an ambassador training programme are separate
activities, even under one participation pathway. Heat and
air quality mapping is distinct from a heat awareness campaign. Do not split an
activity into its routine implementation steps.

Group the same specific activity across the entire plan into one action object.
For example, tree planting across neighborhoods, programmes, or phases forms one
record; repeated cohorts of the same training programme also form one record.
Preserve each location's quantities, dates, implementers, recipients, status,
costs, and benefits with their original associations. Different locations or
phases alone do not create separate records. Combine repeated mentions and
retain evidence for the details. Record conflicting statements as an issue.

Before creating a record, compare the activity by meaning with all activities
already represented, including those inside broader records. If a record bundles
distinct activities, separate them before combining repeated occurrences. Add
new details or evidence to the corresponding activity rather than duplicating it.

The four broad action types classify mechanisms and may overlap. Activities
sharing a broad category can still be distinct actions, such as tree planting
and urban gardening within nature-based adaptation.

A broad aspiration alone is not an action. Keep an activity's stated targets and
deadlines in its description. Concrete heat monitoring activities are eligible,
including heat-health surveillance. Monitoring alone does not establish a benefit.

## Action details

Classify every mechanism supported by the source as infrastructural,
institutional, behavioral/cultural, and/or nature-based. Possible wider effects
alone do not justify another type. Use an empty type list with a linked issue
when no category can be justified.

Check each quantity, date, and duration against the source statement identifying
its activity, location, and phase. Do not apply a neighboring target's date to a
quantity unless the source establishes that link. Preserve relative durations without inferring
unstated calendar start or end years.

Start with action_status set to unspecified. Use another value only when the
source explicitly states or unambiguously establishes the grouped activity's
overall status:

- planned: the activity is clearly proposed or committed, with no evidence that
  work has begun.
- underway: the activity is clearly in progress or operating.
- completed: the grouped activity is clearly reported as finished.

Status reflects the selected document's account, not the current date. Presence
in a plan, a deadline, or a completed pilot or past event alone does not establish
the status of a broader grouped activity. If only differing phase or location
statuses are supplied, use unspecified overall and retain each status in the
description. A completed campaign event does not establish completion of future
campaigns grouped with it. Mixed status alone requires no issue. For other states,
such as withdrawal, preserve the wording and flag the coding limitation.

Record stated locations and intended populations in their fields. Put stated
implementers in the action description. Plan-level lead agencies do not establish
who implements or receives every activity.

Costs retain original amounts, currencies or units, periods, qualifications, and
whether estimated, allocated, spent, or needed. Keep amounts associated with the
correct phase or location. Identify shared budgets and their scope. Do not add
repeated totals or invent allocations or currency conversions.

Benefits retain outcomes, quantities, affected groups, comparisons, timing, and
qualifications, including adverse effects and whether expected, modelled, or
observed. Do not infer an outcome from an activity's possible effects.

Attach costs and benefits only where the source establishes an activity link.
General plan-wide statements without such a link fall outside action records.
Use null for unstated descriptive details and unspecified for unstated status.
Ordinary missing details do not require an issue or establish zero cost, no
benefit, or absence of an activity.

## Evidence and issues

Copy quotations directly from the supplied page text or returned tool text. Use
compact, meaningful continuous excerpts that collectively support all recorded
substantive details. Retain enough context to show what each statement, quantity,
unit, date, or qualification refers to.
Preserve source words, numbers, capitalization, punctuation, and parenthetical
text. Do not paraphrase, silently correct source or OCR errors, or remove words
inside a quotation, even when the meaning seems unchanged.

Keep adjacent source lines belonging to the same continuous passage in one
evidence object. Preserve line breaks as \n in JSON and preserve word-wrap
hyphens. A line break alone does not start a new evidence object. Short table
entries can be valid evidence when the necessary labels and context are also
provided. Avoid isolated fragments such as "The", "Its", or unfinished clauses
that do not explain the recorded claim. If the supplied text interleaves
unrelated columns, use separate meaningful excerpts that retain the context
needed to support each detail.

Separate passages require separate evidence objects. Do not insert ellipses,
brackets, or connecting words to combine separated passages. An ellipsis can
appear only when it is present in the source passage. Do not turn separate table
cells, targets, or pathway labels into a new sentence. Include relevant headings
or footnotes as separate passages when they are not continuous with the excerpt.

Before submission, check that the selected quotations actually contain support
for recorded quantities, dates, conditions, costs, and benefits. Use source tools
for missing support while calls remain, and retain any unresolved evidence gap
in a linked issue.

Cite the physical PDF page position, starting at 1, from the runner's
ORIGINAL PDF PAGE boundary or the tool's returned page_number. Include every page
containing words in the quotation. If a passage continues on another page, do
not cite only its first page. When continuity is unclear, use separate excerpts
for each page. Printed labels inside the source are not citation positions. Do
not assume a general offset.

Prepared text and OCR can contain errors. Use tools to investigate relevant gaps
and retain uncertainty about wording, quantities, or source support as issues.
Use find_quote for uncertain wording or page locations while tool calls remain;
it searches the initial prepared text exactly, including spaces and line breaks.
For find_quote, a short, distinctive query from one line can help locate a
passage. After locating it, copy enough surrounding source text into the saved
quotation to support the recorded detail. The search query does not determine
the saved quotation's boundaries. A failed exact search may reflect spaces,
line breaks, or punctuation; it does not establish that the passage is absent.
Try a shorter fragment or use get_page_text to inspect a likely page. Check the
full passage and its physical page position in the returned or supplied text
before using it as evidence.
A literal quotation match does not establish support for the recorded claims.
When an activity and its heat link are clear, difficulty recovering a faithful
quotation alone does not justify omitting it. Retain supported details and any
faithful evidence, and record the unresolved source problem in a linked issue.
Use an empty evidence list only if no faithful excerpt can be recovered; an
empty list requires an issue linked to the action.

Group concerns about one action into one issue. Omissions and source gaps can
have a null action link. Describe relevant pages and any other affected actions.
Resolve an issue only when source checking addresses all grouped concerns.
Retain existing issue IDs and origins when continuing or reopening an issue.
A model's resolved status is a claim for expert assessment.
Ensure issue descriptions and resolutions agree with the final action fields
and describe only changes actually made.
