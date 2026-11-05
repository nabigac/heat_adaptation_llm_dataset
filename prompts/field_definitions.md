# Content and review field definitions

Return one JSON object with exactly `content` and `review`. These definitions
follow DESIGN.md Appendices B and C. Every field listed is required unless
explicitly marked optional. Unknown fields are not allowed. Do not include run
metadata, settings, measurements, or validation reports in the agent answer.

## Content and plan information

`content` contains exactly `plan_info`, `plan_goals`, `plan_actions`,
`plan_mon_eval`, `plan_benefits`, and `plan_costs`. Each of the five record
categories is a list; use an empty list when no records are established after
checking the source and retain any uncertainty in `review.issues`.

`plan_info` contains:

- `plan_title`: string or null if unavailable.
- `jurisdiction_name`: string or null if unavailable.
- `country`: string or null if unavailable.
- `plan_scale`: `city`, `county`, `region`, `state`, `country`, or null.
- `plan_type`: `heat_specific_plan`, `broader_climate_plan`, or null.
- `publication_year`: integer or null if unavailable.
- `lead_agencies`: list of agency-name strings; empty if none are established.
- `source_url`: the exact supplied collection source URL.
- `date_accessed`: the exact supplied collection date, in `YYYY-MM-DD` format.
- `language`: `English`.

Read other metadata from the source without guessing. Strings must be nonblank
where a string is required; use null only for explicitly nullable fields.

## Evidence and record IDs

Every content record has an `evidence` list. Each evidence object has exactly:

- `quote`: one exact continuous passage, a nonblank string.
- `page_numbers`: a nonempty list of unique positive integers identifying the
  physical PDF pages containing that passage, counted from 1. Numbers must not
  exceed the supplied source page count.

Separate passages use separate evidence objects. Evidence must support the
record's stated details, status, and links. If supporting evidence cannot be
established, do not invent a quotation: retain an empty evidence list and flag
the missing or unsupported evidence in an issue for review.

Use unique record ID strings across all five content lists, for example
`goal_0001`, `action_0001`, `mon_eval_0001`, `benefit_0001`, and `cost_0001`.
Every linked ID must identify an existing record of the appropriate category.
Do not create a relationship merely because two records concern a similar topic.

## Goals

Each `plan_goals` entry has exactly:

- `goal_id`: unique record ID string.
- `goal`: a nonblank description of the stated goal, including relevant
  population and geography.
- `targets`: a list of objects, each containing `target` (nonblank string) and
  `deadline` (nonblank string or null). Pair each target with its own deadline.
  Targets may be qualitative. Preserve quantities, units, baselines, and the
  source's timing precision. Use an empty list if no target is established.
- `evidence`: evidence objects supporting this record.

Do not infer a goal solely from actions or benefits.

## Actions

Each `plan_actions` entry has exactly:

- `action_id`: unique record ID string.
- `action`: a nonblank description beginning with an action verb. Include stated
  implementers, populations, locations, quantities, and timing.
- `action_status`: one of `planned`, `in_progress`, `completed`, `discontinued`,
  or `not_specified`.
- `related_goal_ids`: a list of explicitly associated existing goal IDs; empty
  when the source establishes no such relationship.
- `evidence`: evidence objects supporting this record, including status and links.

`planned` means proposed or committed without evidence work has begun;
`in_progress` means underway or functioning; `completed` means finished;
`discontinued` means stopped or withdrawn. Use `not_specified` when the source
does not establish status. A past deadline does not establish completion.

## Monitoring and evaluation, benefits, and costs

Each entry contains an ID and description specific to its list:

- `plan_mon_eval`: `mon_eval_id` and `mon_eval`. Describe stated indicators,
  methods, frequency, responsibility, and reporting.
- `plan_benefits`: `benefit_id` and `benefit`. Describe stated outcomes, quantities,
  affected groups, comparisons, timing, and qualifications, including adverse
  impacts. Preserve whether outcomes are expected, modelled, or observed.
- `plan_costs`: `cost_id` and `cost`. Describe stated amounts, currency or other
  units, periods, and recurring or one-off character. Distinguish estimates,
  allocations, expenditure, and needs.

All IDs and descriptions are nonblank strings. Every entry also has exactly
`scope`, `related_goal_ids`, `related_action_ids`, and `evidence`:

- `scope`: `linked` when at least one explicit goal or action link is present;
  `plan_wide` for an explicitly overall plan/programme statement without specific
  links; `unspecified` when scope is unclear and both link lists are empty.
- `related_goal_ids`: list of explicitly associated existing goal IDs.
- `related_action_ids`: list of explicitly associated existing action IDs.
- `evidence`: evidence objects supporting the description, scope, and links.

Unspecified scope alone does not create an issue. Record shared budgets once
and link applicable actions; do not invent allocations or convert currencies.

## Review and issues

`review` contains exactly `issues`, a list. Each issue has:

- `issue_id`: an issue ID string unique within the list, such as `issue_0001`.
- `related_record_id`: the affected content record ID, or null for an omission,
  category, source problem, or removed record without a current record.
- `description`: a nonblank description of the grouped concerns. Identify
  categories and pages for problems without a record.
- `type`: optional; if supplied, `unclear_meaning`, `conflicting_evidence`,
  `source_issue`, `extraction_process_issue`, `no_records_found`, or null.
- `origin_stage`: `extractor` or `verifier`.
- `status`: `open` or `resolved`.
- `resolved_by`: `extractor`, `verifier`, or null while open.
- `resolution`: a nonblank explanation when resolved, or null while open.

Group multiple concerns for the same affected record in one issue. An open
issue must have null `resolved_by` and `resolution`. A resolved issue requires
both fields. Keep IDs and origin stages stable across verification, retain
baseline issues, and assign new IDs to new issues. Reopening an issue retains
its identity. Resolution requires all grouped concerns to be addressed.
