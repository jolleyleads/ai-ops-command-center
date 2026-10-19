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

Security consequence: production acceptance now requires OPERATOR_CONTROL_TOKEN from the existing GitHub Actions secret of the same name. If absent, CI reports BLOCKED without starting work. No public acceptance bypass remains. Do not copy secrets into logs, code or reports.

Rollback: revert repair commits; leave additive ownership/reporting tables and all existing business data intact. Rollback to a pre-security version reopens old public routes and should be avoided. No existing columns are removed or rewritten.

Latest validation: 696 local tests passed, 6 PostgreSQL-only tests skipped; real child-process integration terminates an invalid campaign with a persisted configuration failure and no provider calls. JavaScript syntax checks passed. PostgreSQL CI for the combined follow-up is pending. Live draft proof is still queued; no send or booking has been performed.
