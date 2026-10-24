# Research and campaign execution

Full research and campaign discovery call the same Smart Search engine with the
same bounded policy: `max(240, min(540, 180 + target_count * 24))` seconds.
`target_count` is bounded to 1–20 and defaults to 10 (420 seconds). A sending limit
is independent of the research target. A budget is a maximum opportunity to
retrieve and verify evidence, not a promise to find enough leads.

`intent` is the stable query category: jobs, contractors, businesses, permits,
permit_leads, or web_research. The planner's description is `research_intent`.
Search responses report `runtime_budget_seconds`, `budget_exhausted`, and
`target_met`. The synchronous preview uses 25 seconds; the deployment smoke
preview uses 12 seconds. Full background research and campaign execution use
minutes.

`POST /api/demo/campaigns/launch` now returns HTTP 202 with `job_id`, `status`, and
`poll_url`. Poll that URL for queued/running/completed/failed status. Terminal
responses include `result` and `result_http_status`. The demo UI handles polling.
Supply an `Idempotency-Key` header to reuse a job after a transport interruption;
reusing a key for different input returns HTTP 409. Do not submit another launch
just because a response was slow.

The production acceptance POST uses the same asynchronous contract. Its workflow
uses a distinct idempotency key per workflow run and attempt, polls for the actual receipt, and fails if no fresh qualified and drafted lead is
proved. It does not count a successful queue submission as acceptance success.

Jobs persist in the existing application database and use a single in-process
execution worker with atomic database claims. Queued work resumes when launch or
polling starts the worker. Execution interrupted after a claim is never replayed
automatically: after 60 minutes it fails with a review-required status. Existing
send receipts and the side-effect outbox remain authoritative. This is a durable
queue for the current single-worker deployment; a dedicated worker service is a
future scaling improvement.

The live search smoke waits for the exact deployed commit and validates stable
labels, response shape, failure flags, verified counts, and source URLs. It is an
API contract test. Empty verified results are reported honestly; full lead
availability, relevance, and outreach require separate acceptance evidence.

## Direct business contact research

Plain business/company lists now use Hunter Discover when Hunter is configured,
followed by Domain Search filtered to named decision makers and valid addresses,
then the independent mailbox verifier. Prompts explicitly requesting Hunter or
verified emails report missing configuration instead of silently using another
provider. Hiring, permit, and evidence-of-need requests keep the evidence research
engine. A location in the chat prompt overrides the saved territory for the direct
contact path.

The list reports company, named contact, role, verified email, and the provider's
verification date. It streams the company list first and updates individual
contact results. Hunter associations are stored as provider evidence, not as a
claim that the company website published those people or addresses. Business
purchase intent is not implied by a valid mailbox. Research does not draft,
send, or book appointments.

Public read-only jobs store results only in the requesting browser's owned
research job. They neither read nor write the owner's private lead list. Signed-in
contact preparation saves unsent leads. Existing sent conversations are retained.
The existing selected workflow handles activation, requires current company-domain
proof and mailbox checks, and preserves the displayed recipient. Follow-ups,
reply handling, suppression, Gmail receipts, and Calendar booking remain on the
existing automation path.
