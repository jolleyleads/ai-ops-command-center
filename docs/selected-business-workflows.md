# Choose a business and activate its workflow

Every persisted research candidate/result and saved lead has an **Activate
workflow** action. A draft need not exist before selecting it. The card explains
that this click authorizes contact verification, preparation of the approved
message/résumé, and sending only if all required checks pass. The existing owner
workspace must be authenticated; other accounts cannot use the owner's mailbox.

## Execution and trust boundaries

The POST `/api/chat/workflows/activate` accepts an explicit `activate: true`,
a server-issued selection reference and the customer's offer. Company/contact
fields supplied by the browser are ignored. The server resolves the reference
from owned persisted research, campaign business tasks or saved leads. References
are stable across result reordering and source URL paths. The original request,
location, source row, offer and scoped authorization are saved in an existing
durable campaign job; no new tables or migrations are needed.

Manual selection starts evidence work even for an unranked candidate. It does
not promote that candidate or waive qualification. Business/need/buyer evidence,
mailbox verification, suppression/opt-out, approved copy, résumé attachment and
existing safe-send checks still apply. Only the selected business enters this
job. Existing unsent records are refreshed; sent, suppressed, uncertain or
actively leased records are preserved. Duplicate canonical records require review.
A recipient lock and prior-attempt check prevent duplicate initial outreach
through different source identities.

Preparation runs without send authority. The scoped grant is consumed in the
same current job execution through the shared verified-contact activation helper.
Claim/cancellation checkpoints run before sending. An interrupted/uncertain send
is never automatically replayed. Recovery can improve evidence and prepare drafts,
but a workflow that ended held requires a new explicit retry before it may send.

The generic legacy campaign flags remain `draft_only: true` and
`send_authorized: false`. Selection send permission uses a separate internal
`_selection_send_authorized` flag so an older release cannot reinterpret it as
permission to search and send to another prospect during rollback.

## Customer behavior

The card shows queued/running/active/held/stopped state and actual hold reasons.
Repeated clicks resolve to the same durable job. Reloading only observes saved
work; it creates no authorization. The plus/menu, interface and research remain
intact. The last research job is restored after login/reload; the opaque public
research ownership token survives login while authentication and CSRF are renewed.
Another browser cannot access that research or activate its businesses.

A held workflow can be retried explicitly after one minute, at most four attempts
per selection/offer in an hour. A retry cannot replay an existing send attempt.
Cancelled or failed jobs require review; page reload does not restart them.
Stop remaining work cannot undo an email already in flight. Gmail acceptance is
not delivery; the existing reply/follow-up and confirmed-booking workflow continues
only from actual send/thread and Calendar receipts.

## Deployment and limits

No new infrastructure, secrets, credentials or provider access. Deploy through
normal PR CI and main auto-deploy. Full local/CI checks cover candidate selection
before drafting, exact-source binding despite reordering, one chosen recipient,
duplicate clicks, cross-browser/owner/CSRF protection, held evidence, expired
Google grant, cancellation, uncertain attempts, recipient deduplication and bounded
retries. Provider sends in tests are isolated simulations, not real emails.

Verify the deployed commit, candidate-card button and signed-out rejection in
production without sending messages. Live owner-authenticated send/reply/Calendar
checks still require a separately authorized controlled recipient/calendar.
Unverified contacts and businesses remain visible with held states. Existing
max-20 research limit and conservative need-evidence policy are unchanged.

Rollback through the normal code-revert deployment. Cancel/review queued selected
work before reverting when possible; preserve genuine leads, receipts and external
history. Legacy campaign flags fail closed for sending if an older worker sees a
selection payload. Reverting code does not undo emails or bookings.
