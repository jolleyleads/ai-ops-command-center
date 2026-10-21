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
