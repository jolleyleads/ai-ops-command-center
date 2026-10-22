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

Manual selection can send an unranked candidate after contact verification. It
does not promote that candidate or certify business/need/buyer evidence. Those
ranking checks remain mandatory for automatic prospect selection. Current source
and mailbox verification, suppression/opt-out, approved copy, résumé attachment
and existing safe-send checks still apply to manually selected contacts. Only the selected business enters this
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

## Activate all displayed businesses with email

The result list and filtered My Leads list now have **Activate all with email
(N)**. One explicit click submits the displayed, deduplicated business references
with a saved/source-observed email. Cards display the actual available email.
Businesses without email remain in research and are excluded from this action.

`POST /api/chat/workflows/activate-bulk` resolves every reference and its saved
email server-side before scheduling. Client-supplied company/email fields carry
no authority. It requires owner mailbox access, explicit activation, and the
existing session CSRF/Origin checks. A deterministic selection/offer key makes
repeat/reordered clicks observe the same saved batch, including after enrichment
changes a held contact.

One existing durable campaign job processes at most20 businesses. This avoids
creating20 competing queue jobs or bypassing queue capacity. Provider calls run
with bounded work; one click starts the batch, rather than requiring20 clicks.
The worker sends sequentially under existing limits, not an unlimited parallel
blast. Per-business185-second and total1200-second execution limits remain.
A per-business timeout requires review and other businesses may continue; overall
claim loss, cancellation, or deadline fences the batch. Durable per-business
progress survives polling/reload; unfinished or uncertain work never says Sent.

All current qualification, evidence, verified contact, suppression/opt-out,
approved two-emoji message/résumé, recipient locking, duplicate-send protection,
follow-up and Calendar requirements remain. An email being visible does not
guarantee sending. Each card reports Sent, Not sent plus the reason, or send
status unconfirmed. Follow-ups and booking continue only from actual workflow
events. Stop batch applies to remaining work and cannot undo an in-flight email.

Lists with more than20 email-bearing businesses require filtering before launch;
there is no silent truncation. No new infrastructure, migrations, credential
changes, or paid providers. Rollback is a code revert; preserve saved receipts
and review/cancel queued batches before reverting. No real email/Calendar tests
are authorized by this UI change.

### Customer-selected contact sending

New manual activations use `selected-contact-v1`. The activation click is final authorization; there is no additional approval screen. Business-fit, need and buyer ranking remains visible and independent of contact readiness. Manual sending requires a current source-backed company email and a positive independent mailbox receipt. Preparation reuses fresh receipts; otherwise it fetches company contact sources and verifies the selected email without rerunning automatic need qualification. Missing proof, Google connection failures and send failures produce explicit Not sent or unconfirmed states. Sent requires persisted provider receipt IDs, and does not mean delivered.

Automatic campaigns retain signed qualification requirements. The manual exception exists only in the running, owned selected job's recipient-bound context. Follow-ups and booking continue only from its durable grant and confirmed initial send; existing reply, opt-out and scheduling checks still apply. Old held jobs remain historical; a new explicit click can use the new policy. No page load, GET, provider recovery, or deployment launches a send.
