# Plan dataset fields

Complete answers from E, V, and C contain exactly plan_data and plan_issues. C workers
return their assigned task-result structure instead; these definitions govern any
plan content they propose. Every field below is required except issue_type. Unknown
fields are not allowed. Python records run IDs, settings, measurements, and
validation reports separately.

## Plan data

plan_data contains exactly metadata and actions. actions is a list of
action objects. An empty list follows a completed search for eligible activities,
with any unresolved source gap retained as an issue.

metadata has these fields.

- plan_title: nonblank string or null, as stated in the plan.
- jurisdiction_name: nonblank string or null, the covered jurisdiction.
- country: nonblank string or null, supported by the source.
- plan_scale: city, county, region, state, country, or null.
- plan_type: heat_specific_plan, broader_climate_plan, or null.
- publication_year: integer or null, for the selected document version.
- lead_agencies: list of nonblank agency names, empty if unknown.
- source_url: exact URL supplied in the selected preparation's collection metadata.
- date_accessed: exact supplied collection date in YYYY-MM-DD format.
- language: English.

Each actions object has exactly these nine fields.

- action_id: stable nonblank local ID, such as action_0001, unique within the plan.
- action: nonblank description of one specific activity across the plan, retaining
  quantities, implementers, dates, conditions, and local or phase-specific details.
- action_type: list of unique values from infrastructural, institutional,
  behavioral/cultural, and nature-based. Empty if none is justified, with an issue.
- action_status: planned, underway, completed, or unspecified. Default to
  unspecified unless the source clearly establishes the grouped activity's
  overall status under the shared coding rules.
- action_location: nonblank string containing all stated places or coverage, or null.
- action_recipient: nonblank string containing intended populations or groups, or null.
- action_cost: nonblank description of stated amounts, units, periods, and cost
  character with the relevant location or phase associations, or null.
- action_benefit: nonblank description of stated outcomes and qualifications,
  preserving whether expected, modelled, or observed, or null.
- evidence: list of supporting evidence objects, empty only with a linked issue.

Action types have these meanings.

- infrastructural: changes to built assets, equipment, or physical services.
- institutional: policies, governance, planning, financing, coordination, or formal
  service and monitoring systems.
- behavioral/cultural: changes to knowledge, practices, routines, or social norms.
- nature-based: vegetation, ecosystems, or ecological processes linked to heat.

Each evidence object contains exactly quote and page_numbers. quote is a nonblank
continuous passage copied verbatim from source text, without rewriting or silent
omissions. page_numbers is a nonempty list of unique positive integers within the
physical original PDF page range. A passage may span pages; cite every page
containing its words. Separate passages use separate evidence objects. Together,
quotations support the activity and all its recorded substantive details.

## Plan issues

plan_issues contains exactly issues, a list that may be empty. Each issue has these
fields, with concerns about the same action grouped into one issue.

- issue_id: nonblank issue ID unique in the list, such as issue_0001.
- related_action_id: existing affected action_id, or null for an omission, source
  or plan-level problem, or a removed action. At most one issue links each action.
- issue_description: nonblank explanation of all grouped concerns and relevant pages.
- issue_type: optional. unclear_meaning, conflicting_evidence, source_issue,
  extraction_process_issue, no_records_found, or null.
- issue_origin: who first raised the issue. E uses extractor; V retains existing
  origins and uses verifier for new issues. C uses worker_1, worker_2, or coordinator.
- issue_status: open or resolved.
- resolved_by: the resolving role from the same workflow: extractor or verifier for
  E/V; worker_1, worker_2, or coordinator for C. Null while open.
- resolution: nonblank explanation addressing every concern when resolved,
  null while open.

Issue types have these meanings.

- unclear_meaning: wording or context permits multiple interpretations.
- conflicting_evidence: incompatible source statements need reconciliation.
- source_issue: missing, unreadable, or unreliable source text limits checking.
- extraction_process_issue: extraction, tool use, or coding problems affect accuracy
  or completeness.
- no_records_found: no eligible activities were found and that finding needs review.

The value expert for resolved_by is reserved for later expert-curated copies.
A model answer must never claim that an expert performed a resolution.
