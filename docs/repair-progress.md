# AutoMake AI six-priority repair record

Base: 00e208e00647bcd4e656bacf4b5637a3ac05532e (observed live 2026-10-19).

1. IN PROGRESS. Runtime logs confirm Gunicorn WORKER TIMEOUT at 2026-10-18 09:45:04 UTC, SIGKILL and replacement worker. Persisted campaign claim remained running; prior expiry was 60 minutes, longer than the acceptance client's 45 minute deadline. Repair bounds campaign execution in a supervised child process, expires dead claims during status polling, adds phase progress and pre-send checks, bounds SDK retries/timeouts, and makes acceptance draft-only regardless of production autosend. No claim of fresh production qualification yet.
2. Pending: customer frontend smoke contract.
3. Pending: authentication experience.
4. Pending: research progress and explicit limits.
5. Pending: route protection and workspace isolation.
6. Pending: campaign outcomes and reporting.

No emails or Calendar writes authorized for verification. Preserve existing data and integrations. Local tests use disposable SQLite; PostgreSQL CI remains required.

## Implementation checkpoint (2026-10-19)

Priority 1: PR #150 passed PostgreSQL CI and deployed as 022e2b31bdeec307ea124a7a89c5946baea004a1. A controlled draft-only landscaping acceptance job was submitted, but remains queued behind existing work; no fresh production qualification PASS claimed. Additional queue-position and worker-error diagnostics included in follow-up.
Priority 2: Restored customer interface contract validates controls/navigation/API wiring and retains separate search API/evidence assertions. Focused tests passed.
Priority 3: Public access hints, protected sending choices, pending prompt preservation and explicit sign-in context implemented. Focused signed-out/authentication checks passed.
Priority 4: Source-backed candidate progress and cancellation implemented. 10/20 supported; 100 rejected before starting (422, maximum_results=20). Large-batch execution is intentionally not advertised on this single-worker deployment.
Priority 5: Additive resource_ownership table; existing single-owner workspace preserved as legacy scope. Known owner accounts are jolleyleads@gmail.com and neyolabs@gmail.com, overridable with AUTOMAKE_WORKSPACE_OWNER_EMAILS. Other approved Google identities receive separate read scopes and cannot use the owner's mailbox, settings, legacy APIs or campaigns. New anonymous research is browser-session-owned; legacy research remains owner-only. Two verified identity isolation, anonymous rejection, ownership and CSRF tests passed. This is not full multi-customer sending: each customer still needs a separately isolated integration before that can be enabled.
Priority 6: Additive campaign_membership and campaign_reply_outcome tables. New lead attribution is first-campaign-only. Confirmed sends, reply classifications and Calendar receipts supply live rates. Historical snapshots retained; campaigns without durable membership state that live attribution is unavailable. Delivery/customer/revenue metrics stay unavailable without evidence. Dashboard supports explicit offsets and page totals.

Production acceptance uses the existing OPERATOR_CONTROL_TOKEN secret when available, otherwise short-lived GitHub OIDC. OIDC trust is restricted to this repository ID, this workflow on main, the exact deployed SHA, GitHub-hosted push/manual runs, a dedicated audience and the run-bound acceptance job. It grants no general workspace/sending access. JWT signatures and expiry are verified using GitHub public keys and google-auth. No public acceptance bypass or new long-lived secret is introduced.

Rollback: revert repair commits; leave additive ownership/reporting tables and all existing business data intact. Rollback to a pre-security version reopens old public routes and should be avoided. No existing columns are removed or rewritten.

Latest validation: 696 local tests passed, 6 PostgreSQL-only tests skipped; real child-process integration terminates an invalid campaign with a persisted configuration failure and no provider calls. JavaScript syntax checks passed. PostgreSQL CI for the combined follow-up is pending. Live draft proof is still queued; no send or booking has been performed.

PR #151 initial head passed PostgreSQL CI. Follow-up adds narrow GitHub OIDC acceptance authentication so verification does not depend on manually copying a secret. Signed-token tests exercise tampering, expiry, branch/repository/workflow/SHA/audience restrictions, job binding, and denial of general operator access.

## Fork-safety verification follow-up

Live application logs show initialization before Gunicorn startup. Process-local ThreadPoolExecutor/Future/Lock state was not reset on forks, a possible cause of newly queued jobs never being claimed in a preloaded worker. Both research and campaign executors now initialize lazily, reset after fork, and check process identity before using a lock or Future. Regression checks simulate an inherited running Future and held lock and prove only a fresh executor is used. Final production qualification must still be demonstrated after deployment.


## Verified checkpoint and follow-up (2026-10-21)

Current production/main: 5854e60d0cbfc3ba5a3fe1bdaea45b5862af1418. PostgreSQL CI: 720 passed. Live search smoke run 39340031696 passed all interface, intent and evidence-contract assertions. A separate browser-owned, read-only HVAC/Norfolk research job completed with one verified business and 17 live pages fetched; 20 early candidates remained labeled unverified. A second browser received 404 for the job. Requests for 100 results were rejected before work began; this deployment supports at most 20 per run.

Priority 1 FAIL: acceptance run 39340031793 reached contact enrichment around 23:18 UTC on Oct 19 and stayed there until the supervised 40-minute deadline. It returned EXECUTION_DEADLINE_EXCEEDED_REVIEW_REQUIRED rather than claiming success or replaying work. No fresh qualified/drafted receipt exists for this run. The exact inner enrichment cause remains unknown. Follow-up isolates contact enrichment to a 180-second Unix child timer, logs only code stack locations on timeout, records sub-stages, and preserves the last durable stage in terminal failures. Do not repeat production acceptance until that diagnostic change is tested/deployed.

Priority 2 PASS: exact deployed interface and search smoke checked.
Priority 3 BLOCKED for real Google-account login: signed-out public/protected behavior and simulated verified-identity tests passed; the secure account-selection request was interrupted. Do not request credentials again unless the user asks. No credentials entered.
Priority 4 PASS within explicit 20-result limit: parser/budget/cancel regressions plus genuine progressive production research; 100-result execution unsupported and clearly rejected before launch.
Priority 5 follow-up: retain independent cron-token authentication for inbound reply processing; make GET search free of outreach ingestion. POST mutations retain owner authentication and CSRF. Two-identity and route-isolation tests passed. This remains a single-mailbox deployment, not full multi-customer sending.
Priority 6 implemented/tested: durable first-campaign attribution and persisted event tests prevent cross-campaign inflation. Private production dashboard and real reply/booking updates remain unverified without account authentication and a separately authorized controlled recipient/calendar.

No emails or Calendar writes performed for verification. Existing scheduled automation is independent of these tests. Additive ownership/reporting tables preserve existing rows. No credential replacement, network-allowlist change, new spending or destructive migration was performed. Rollback: revert follow-up code, retaining all additive tables and business records. Avoid reverting route-security repairs to the original public administrative routes.


## Progressive implementation checkpoint

Master prompt: Progressive Research and Verified Outreach (user-authorized).

PR #153: PostgreSQL CI passed; deployed b8c3130ccb23fcd191bc57fe5ed19b54df147fe4 as dep-dbc3svmq1p3s73biqeeg. New draft-only acceptance run 39543865887 is running. Root cause inside the old stalled enrichment remains under investigation; no fresh draft success claimed.

Follow-up in development: publish candidates after each provider response, preserve partial results on failure, reuse browser-owned research submission keys, restore polling after reload, display verified business results before contact checks, and isolate each campaign business in durable tasks with at most two forked workers. Each worker only qualifies/prepares drafts; only the authorized parent may call the existing safe-send gate. Cancellation fences task updates. Additive campaign_business_task and research_request tables; no existing records reassigned or deleted. Display draft progress and live campaign membership before overall completion. Acceptance now binds freshness to this attempt's returned lead IDs and requires a persisted qualification receipt plus actual saved draft.

Verification in progress: real disposable-DB process test proves a fast draft completes while a slow contact remains running, duplicate businesses collapse to one task, cancellation terminates the slow worker, and no send function is invoked. Additional tests cover early provider results, partial provider failure, persisted partial research, and browser-owned idempotency. Full regression and PostgreSQL CI must pass before production deployment. Production progressive/contact proof and final browser verification remain pending.


Verification scope: the progressive workflow's next live receipt uses a controlled draft-only search for three HVAC businesses serving Norfolk. The prior public research run demonstrated source-verified HVAC discovery there. This tests successful contact-to-draft processing with more than one candidate and the new independent workers; it does not establish all industries or guarantee the requested count. Existing API acceptance retains the cross-industry catalog for separately requested broad verification. Safe-send gates are unchanged; sending remains disabled for acceptance.


## Enrichment parser reproduction

A local, provider-free reproduction located pathological rescanning in outreach_bridge._page_emails: unbounded email/obfuscation regexes each exceeded 0.2 seconds on only 20KB of repeated dotted/percent-encoded text. Stack diagnostics identify the exact matcher lines. Replaced those patterns with shared bounded source-address matchers and token boundaries across enrichment/contact assessment/orchestration. Regression checks retain actual published and obfuscated addresses, reject overlong local parts and process 500KB adversarial tokens within a two-second test deadline (observed about 0.016 seconds locally). This demonstrates a real enrichment parser defect; the exact fetched page from the old production stall is unavailable, so that historical causal link remains unproven.

The b8c3130 broad acceptance finished at 04:33 UTC on Oct 21 without hanging. It failed fresh proof: two campaigns had no verified matches, and the other two selected existing review-required leads. No fresh contact enrichment ran in that receipt. Do not present it as a successful draft proof or evidence that the old stall was reproduced.

Current final local suite: 726 passed, seven environment-specific PostgreSQL checks skipped. The independent-process test also passed against disposable PostgreSQL in PR CI before the parser-only follow-up. Final combined CI/deployment/live proof remain pending.

## Final live-verification repair — 2026-10-21

- Exact production a1a4df0: progressive candidates and reload recovery verified; public/private access checks and live search smoke passed. PostgreSQL CI: 733 passed.
- Fresh Norfolk HVAC acceptance completed in about 145 seconds without hanging, saved one verified business, and truthfully held it (HUNTER_NO_DOMAIN_CONTACTS; MISSING_VALIDATED_CONTACT; INTENT_SIGNAL_UNPROVEN). No fresh qualified draft was proved. No messages or Calendar writes performed.
- Live Stop clicks were intercepted by the fixed composer's transparent gradient. Repair makes only the composer itself capture pointer events, scopes cancellation to its result bubble, and renders the server's cancellation response immediately. Pending territory is restored with the job.
- Found a separate evidence handoff defect: fetched primary business text was nested only in contact metadata, so qualification could lose industry evidence, especially on mailbox failure. Preserve the already identity/host-checked fetched rows as evidence independently of mailbox success. Missing contact remains a hold; no qualification gate is waived.
- Rejected business cards now say rejected and do not claim contact verification ran.
- Local full regression after these changes: 727 passed, 7 PostgreSQL-only skips. Deployment and final live cancellation pending.
- Limits: at most 20 businesses per research run; 100 rejected before launch. Owner integration only; multi-customer sending, signed-in Google behavior, controlled Gmail/reply/Calendar and fresh qualified production draft remain unverified.

### Final deployed verification and explicit research retry

- Commit 1ef8f946514bc4613662916cca65686ba109777f / Render dep-dbc4e0lg1s2s738df70g live; main CI 734 passed; live search smoke passed.
- Browser: Stop confirmed cancelled, kept 18 discovered candidates, and stayed cancelled under further polling. A new electrical research request showed 19 source-backed candidates while running; reload restored its prompt and Norfolk territory. Stop also cancelled that request.
- Acceptance run 39547166043 terminated truthfully without fresh proof: three returned businesses comprised two candidates and one rejected business; none passed business verification, so eligible/saved/qualified/drafted/sent all zero. This does not prove production qualification/drafting. Prior a1a4df0 run saved a verified business but found no validated contact.
- Explicit retry of the same cancelled public research request reproduced a client key reuse bug. Clear only the public-research request key on confirmed cancellation/failure; retain campaign/draft keys and all server send idempotency protections. New browser-function regression covers failed/cancelled research, campaigns and drafts. Local full suite: 728 passed, 7 PostgreSQL-only skips.
- No additional configuration or destructive migration for either final repair; no external sends/bookings. New revision CI/deployment/live retry verification pending.

## Per-contact activation and conversation-shell update — 2026-10-21

- Research in the signed-in customer interface now uses the authenticated draft-only job path. Public research remains read-only. The customer composer never launches bulk sending; a ready contact's explicit Activate outreach action is required.
- Added owned, CSRF-protected activation using existing qualification, source/domain, suppression, mailbox, message, attachment and durable-send gates. Confirmed duplicate clicks return saved active state; uncertain attempts remain held. A persisted confirmed initial receipt can restore its follow-up handoff without sending again or reactivating an opt-out.
- Contact cards, progressive job results and My Leads expose readiness and actual initial/follow-up/Calendar states. Gmail acceptance does not claim delivery; Calendar shows confirmed only with its durable event receipt.
- Full-height collapsible side menu, shared conversation styling and workspace styles preserve the logo and tagline-only welcome. Desktop sidebar pushes the conversation; narrow layouts use a dismissible overlay. Existing controls and source-backed research remain intact.
- Local full suite: 736 passed, 7 PostgreSQL-only skips. Additional small New chat/prompt-preservation changes passed focused basic/frontend checks. Tests cover approved two-emoji first touch plus real résumé attachment, no send during preparation (even with legacy global autosend enabled), explicit activation, duplicate protection, scheduler handoff, uncertain attempts, expired-grant preflight, ownership, CSRF, opt-out preservation and rendering without automatic sends.
- Live infrastructure inspection: enabled five-minute inbound/outreach cron exists. Its recent OAuth probe fails and provider errors report invalid_grant while a stored refresh grant is present. Reauthorization is required; no credentials replaced and no live outreach/Calendar tests performed.
- No migrations, new providers or infrastructure/spending. Deployment and final UI checks pending. Rollback is a normal revert of this change; retain genuine records and existing durable provider receipts.
# Job-source connector onboarding — October 21, 2026

- Base: merged main `27e253e0c8249af47d7322c7eb31b6da27946d27`.
- Implemented a staged Adzuna US adapter, research-tool wiring, independent feed
  failure handling and authenticated provider access states. Disabled by default;
  both credentials and `ADZUNA_USE_APPROVED=true` are required.
- Confirmed Adzuna terms require written agreement for lead generation. Indeed
  requires the appropriate partner/search entitlement. ZipRecruiter MCP initial
  connection returned HTTP 429; no search schema or live result was obtained.
- Provider applications/inquiry text and exact activation/rollback steps are in
  `docs/job-source-onboarding.md`. No applications were submitted, credentials
  changed, accounts created, purchases made, emails sent or Calendar events added.
- Focused tests: 46 passed. Local full regression: 753 passed, 7 PostgreSQL-only
  skips. Provider tests are isolated simulations, not proof of approved live access.
- Next: PR CI, then approved provider onboarding and a bounded read-only live
  search before enabling each source. Indeed/ZipRecruiter direct search and
  Adzuna production enablement remain BLOCKED on their stated external access.

## Evidence-led prospects — 2026-10-22

- Base main/deployed revision `6f1747ba69d57e79e1c5dc4d4dae134df86d37e7`.
  Isolated branch `feature/evidence-led-prospects`; no unrelated work replaced.
- Added independent fit, documented need and responsible-buyer/mailbox assessment,
  five-question cards, fit/need ranking, actual shortfall and persisted reporting.
  Progressive discovery and per-business contact work remain separate. Existing
  protected activation, approved email/two emojis/résumé, ownership and suppression
  gates remain. Initial sender and hardened Gmail sender both enforce freshness.
- A new direct-sender test exposed the runtime hardened-sender override bypassing
  the original sender check. Added a shared guard before either creates an attempt;
  failure corrected, not waived. Follow-ups retain existing independent gates.
- New customer preparation adds the policy. Unsent existing leads are held and
  scheduled for read-only reassessment when the offer changes or evidence expires;
  sent/uncertain records and active recovery leases are preserved.
- Local full regression before final reassessment test: 768 passed, 7 PostgreSQL-only
  skips. Added offer-change/no-duplicate/no-send test then focused 22 passed.
  Final local full suite: 769 passed, 7 PostgreSQL-only skips; JavaScript syntax
  and diff-whitespace checks passed. GitHub PostgreSQL CI and deployment pending.
- Read-only production pilot requested ten HVAC businesses in Hampton Roads:
  durable job returned HTTP 202 and progress reached discovery/verification.
  Status observation then timed out; final real results, ten supported prospects
  and fresh real contact-to-draft success remain UNVERIFIED. No prospect mail or
  calendar writes were performed. Do not treat discovered counts as supported leads.
- Operating limits/configuration/rollback: `docs/evidence-led-prospects.md`.
  No migration, infrastructure, credential replacement or new spending.
- Next: final regression/diff review, publish PR, inspect CI, merge approved change,
  monitor automatic deployment, verify exact revision and read-only live behavior.

## Select any research business — 2026-10-22

- Base `377f54d1345157393d705810f29243fe743e49b1`, isolated branch
  `feature/select-any-workflow`.
- Confirmed cause: plain result cards had no outreach action; held saved leads
  exposed a disabled ready-only action. Added selection references and an
  Activate workflow button before contact/draft readiness.
- Existing durable jobs now process exactly the selected owned business, prepare
  evidence/contact/draft work, then invoke the shared protected send path under
  an explicit scoped grant. Queue-ranking eligibility can defer to manual choice;
  qualification, contact, approved copy/résumé and all send gates still apply.
- Duplicate clicks, result reordering, cross-browser ownership, CSRF, cancellation,
  duplicate recipients, uncertain sends, bounded retries, reload observation and
  login restoration have targeted coverage. No real prospect emails or Calendar
  writes were performed. No migrations/infrastructure/secret changes.
- Full local regression: 781 passed, 7 PostgreSQL-only skips. Final focused
  publication checks: 37 passed, including canonical selection idempotency.
  GitHub PostgreSQL CI and deployment verification pending.
- Rollback keeps legacy generic campaign flags draft-only. Operating details and
  limitations: `docs/selected-business-workflows.md`.
- Next: final regression/diff review, CI, merge/deploy and verify the exact live
  revision plus the button on genuine source-backed candidate cards.

## Clear email send status — 2026-10-22

- Base `d3dd372f5a489b3acbf73c2c42fec9eb4a76dd58`, branch
  `fix/clear-send-status`. Screenshot confirmed that a held activation showed
  Retry workflow without an explicit email outcome.
- Cards now separate Sent, Not sent, and Send status unconfirmed from the
  workflow action. Held attempts offer Retry verification with their saved reason.
  Confirmed sends stay Sent even if follow-ups stop or a job snapshot was held.
- Read-only status uses a persisted initial-send receipt or the existing complete
  message/thread/timestamp record. Partial receipts require review. Terminal job
  observation refreshes the latest owned lead status without sending or retrying.
- No sending/qualification gate, message, attachment, provider credential, schema
  or infrastructure changes. No real emails or Calendar writes in verification.
- Local regression: 781 passed, 7 PostgreSQL-only skips; one new frontend
  test initially failed because its isolated browser fixture lacked a DOM method.
  Corrected that fixture; final focused suite: 38 passed. Full CI and exact
  deployed revision pending. Next: CI, deploy,
  verify live assets and the customer card. Rollback: revert this code change;
  no data migration or configuration reversal is required.

## One-click email batch — 2026-10-22

- Base `58d972b00aac95ff658bb444214750efe6235812`, branch
  `feature/bulk-email-activation`. User wants one activation for all displayed
  businesses with email, rather than one click per card.
- Added the list-level batch control, visible sourced/saved emails, private
  atomic selection validation, and one durable bounded batch with per-business
  outcomes. Existing send gates and approved message/résumé remain authoritative.
- Repeated/reordered clicks are idempotent. First focused run identified a retry
  lookup after mutable email validation; moved existing-batch lookup before
  that mutable check while preserving ownership checks. Full local suite:
  786 passed, 7 PostgreSQL-only skips. Final focused checks:42 passed.
  CI/deployment verification pending.
- No real external emails or Calendar writes in testing. No schema, provider,
  secret or infrastructure changes. Limits and rollback documented in
  `docs/selected-business-workflows.md`.
- Next: focused/full regression, diff review, PR/CI, main auto-deploy, exact commit
  and live batch-control verification.

## Final public research email handoff — 2026-10-22

- Bulk change merged in PR165 (`3b8e1cc32bf8cc31df3faf95f0d1173eddda0550`),
  CI793 passed, Render deploy `dep-dbd4gb142hec73ae1860` live. Exact production
  health SHA confirmed; unauthenticated bulk POST401.
- Live read-only research completed with two candidates and a disabled
  Activate all with email(0) control. Inspection confirmed the completion
  handler replaced final results with the earlier business-progress projection,
  which is recorded before source contact attachment and has no email fields.
- Public completed research now renders final persisted result rows and their
  contacts. Campaign drafting still uses its per-business task projection.
  Updated composer/menu guidance for bulk activation. No sending or gate change.
- Focused frontend checks:8 passed, including a final sourced-email result
  surviving a stale progress projection. CI/deploy/live verification pending.
- This does not prove the live run found any valid email. Preserve that unknown
  until the actual final data is visible. No prospect email or Calendar writes.

## Manual activation sends a customer-selected verified contact (2026-10-22)

Confirmed production evidence: the recent selected-workflow run reached Hunter/mailbox checks and completed with qualified=0, drafted=0, sent=0. There was no second-confirmation stage; the automatic offer/need/buyer qualification pipeline was preventing the selected business from sending.

Repair: new explicit single/bulk activations use selected-contact-v1. A customer's authenticated, CSRF-protected click authorizes that selected business and exact verified recipient; it does not certify business fit or documented need. Reuse current primary-source and independent mailbox receipts, otherwise verify the source email automatically, persist approved copy, and call the existing receipt-backed sender. No second confirmation. Automatic campaign qualification remains unchanged. Existing jobs retain their original policy; old completed holds do not prevent a fresh explicit activation under the new policy. Reload never authorizes work.

Controls retained: workspace/resource ownership, source-company/domain/email proof, current mailbox verification, suppression and opt-outs, pinned résumé and approved two-emoji copy, recipient serialization, duplicate/uncertain-send protection, cancellation/claim fences, exact provider receipts and existing reply/booking gates. Continuation authority requires the durable selected-contact grant plus an actual confirmed initial send for that same recipient. No qualification receipt is forged.

Verification: full local regression passed (793 tests, 7 PostgreSQL-only skips); final focused checks including the additional old-bulk-to-manual-policy regression passed (150 tests). GitHub CI and exact live deployment evidence pending. No live prospect emails or Calendar writes used for testing. No migrations, credentials or infrastructure changes. Rollback: revert this release's code and redeploy; already-confirmed sends and follow-ups cannot be undone by a code rollback.


### Manual-send deployment and source-email follow-up

PR #167: CI run 39831905691 passed 801 tests. Merge c341a9a313e284e5176f2872074572fcfea172a3 went live in Render deploy dep-dbd5djifngtc73fm570g. Production /api/health returned that SHA and served access.js matched local SHA256. Both signed-out activation endpoints returned 401; post-deploy error-log query empty. Browser reload restored genuine research with the new final-authorization copy. No live email or Calendar test performed.

The public research check exposed a directory support address listed against a different business. Sending rejected the cross-domain address. Follow-up repair filters company-domain addresses in bulk eligibility and card display; individual activation ignores an unrelated preferred address and seeks a real mailbox from the business's own fetched source. It never substitutes guessed or third-party addresses. Local full regression: 795 passed, 7 PostgreSQL-only skips. Follow-up CI/deployment pending; do not infer actual external send success from these tests.

### Directory identity correction after live follow-up verification

PR #168 CI passed 802 tests; merge 0f9bb95ca852726f32772dc3f13f7bd23675537f became live in dep-dbd5h6rl550s73aoh59g. Exact health SHA, frontend hash and unauthenticated rejection checks passed. The saved public result still showed the directory email because the directory itself had been saved as its company website. Thus the domain-only display repair was insufficient; do not report that live contact issue as fixed by #168.

Correction: mark the observed directory threebestrated.com as shared infrastructure, reject its contact identity on server and frontend, and recover a primary website only if exactly one non-shared site for the same business name was already observed in the owned research. The recovered site remains an unverified discovery hint until the worker fetches company identity and verifies its actual email/mailbox. Conflicting primary sites remain held. Existing records are preserved. Full local regression: 797 passed, 7 PostgreSQL-only skips. Final CI/deployment and browser confirmation pending.

## Plain customer statuses, stacked chat, and manual Hunter enrichment (2026-10-22)

User screenshot IMG_7557.png shows chat messages compressed side by side on mobile and verbose workflow copy. The feed's empty-screen centering used an implicit horizontal flex layout and relational selectors to switch layouts. Make the feed always a vertical column with full-width messages; use explicit empty/assistant/user classes instead of relational selectors for those states. Preserve logo/menu/composer, independent polling, authorization and all real send-state semantics.

Customer copy: confirmed receipts display Sent; pending work Sending…; uncertain outcomes Checking status; known no-send Not sent. Technical reasons, intent/fit evidence and detailed progress remain available in closed Details sections. Do not convert an uncertain attempt to Sent. Show the actual persisted recipient and supported contact name after enrichment.

Hunter investigation: manual activation used mailbox verification but did not call the existing decision-maker discovery/enrichment helper. Wire current primary-source person extraction and durable Hunter discovery association into manual preparation. Prefer a supported buyer; independently verify the exact mailbox. If the original request explicitly requires a named decision-maker, do not substitute a generic inbox. General inboxes remain unlabelled as people. Persist the real association, mailbox receipt and contact name. Reuse fresh safe evidence; preserve source/company, suppression, idempotency, claim and existing follow-up protections.

Verification: full local suite 799 passed, 7 PostgreSQL-only skips. Added isolated Hunter integration cases for a source-supported owner whose email comes from Hunter and a provider-only name that must not send. Frontend checks cover receipt-priority Sent, simple pending/unknown labels and hidden diagnostic codes. Production Hunter credentials/account quota and mobile browser behavior still require live checks. No real email or Calendar tests. No migrations/new spending. Rollback by reverting this release and redeploying; external effects cannot be undone by code rollback.

## Independent candidate contact research (2026-10-23)

Confirmed live: draft-only campaign nDnK3HFq4GEU29sRdT7tZLfBvpG5ck2r completed with one Ocean View Heating and Cooling candidate, no saved lead/contact/draft, and zero sends. The per-business worker invoked the serial orchestrator, whose discovery score/Verified Lead prefilter silently skipped that candidate before primary identity/contact/Hunter work. This was a handoff failure, not evidence that Hunter rejected that company's mailbox.

Repair: permit draft-only contact research for non-rejected Candidate rows with a non-shared company website. Fresh primary-source identity, exact person/company association, independent mailbox verification and existing qualification remain required; no discovery status is promoted by this change. Rejected, directory-only and unbound candidates remain excluded. Persist distinct contact-check receipts and carry them through isolated per-business results. A verified contact may remain held for business/offer evidence; the UI explains those states separately.

Verification: local regression 805 passed, 7 PostgreSQL-only skipped. Cases demonstrate a low-score candidate reaching real-shaped isolated Hunter discovery and persisting the supported owner email while an unproven offer cannot qualify/draft/send; snippet-only company identity cannot reach Hunter; rejected/shared-site/missing-site candidates stay excluded. Fork tests verify receipt aggregation and independent progress. Frontend test checks that a verified contact is not mislabeled as failed when qualification is held. CI/deployment/fresh live proof pending.

No migrations or environment changes. Approved email/resume and external action protections unchanged. Rollback: revert this code change and deploy; retained contact evidence is additive and compatible. No live test sends or Calendar writes authorized.
