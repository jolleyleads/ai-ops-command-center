# Search acceptance and availability

The public API keeps deterministic intent codes: jobs, contractors, businesses,
permits, permit_leads, and web_research. Planner prose remains research_intent.
The live smoke runs against the exact deployed commit and validates the returned
job and permit evidence receipts with the same source guards as the application.
Old intent strings, stale receipts, wrong roles, wrong cities, wrong employers,
and unsupported result rows fail the smoke.

Job searches show only currently checked role/city matches, including an enabled
application target bound to the posting. Discovery-only employers and unrelated
job titles are excluded from requested job results. Permit searches require a
fetched record page with a matching locality in its record heading or labeled
project/site/property/jurisdiction field. A company footer, another city's record,
or multiple numbered records cannot supply missing locality/date evidence.
"Recent", "new", "latest", and "current" records need an actual labeled issue
date within 90 days; provider publication estimates are not issue dates.
Record checks expire after one hour. Missing record dates remain unknown.

excluded_result_count and excluded_results report held-back sources/reasons.
availability_status distinguishes matching_results from no_confirmed_matches.
Scoped result summaries are built from the filtered results, so discarded model
claims cannot reappear in answer_summary. Empty results can pass the API contract
when no confirmed matches are available; they never establish lead availability.

Production Acceptance separately requires a new lead to pass qualification and
drafting (and a send receipt when configured). NO_FRESH_LEAD_REACHED_QUALIFIED_AND_DRAFTED
remains a failed acceptance result, not a passing receipt or a synthetic lead.
The polling script reports the actual failed stage and reason. Existing history,
Gmail, Calendar, follow-up, qualification, and safe-send behavior remain intact.
