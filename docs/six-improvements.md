# AutoMake AI: recovery, contact coverage, replies and deployment

These changes are additive and intended for review on a feature branch. They do
not change production configuration or send test outreach. The existing DOE
research → verification → qualification → execution gates remain authoritative.

| Area | Implementation | Verification |
| --- | --- | --- |
| Held leads | Persisted per-lead recovery, bounded backoff, fenced leases and fresh contact research | Pending-to-draft, exhausted retries, stopped leads, occupied/expired/lost leases |
| Decision-maker coverage | Campaign context bound into new signed receipts; optional named-person requirement; additional title separators | Shared inbox rejection, wrong-city rejection, existing contact certainty suite |
| Hunter quota | Account-wide lease and one-hour quota/configuration pause; fail-closed restrictions; provider result recovery states | Different-address contention, quota pauses, account/key restrictions and send gates |
| Grounded replies | Narrow paraphrase equivalence, operator-approved aliases, multiple questions and mixed scheduling clarification | Approved answers, unsupported remainder, conflicts and existing reply/booking suite |
| Worker reliability | Reuses existing cron, shared cycle lease, queue fencing, recovery heartbeat and queue age | Overlapping cycles, expired leases, research restart and failure reporting |
| Dependencies | Exact direct/transitive lock; Python 3.12 in CI/Docker/Render runtime file | Clean install, startup, regression suite and pip dependency check |

## Recovery behavior

New held discovery leads are registered automatically. Rediscovering an older
unsent `needs_evidence` lead registers it without inserting a second lead.
Existing leads that were never rediscovered are not retrospectively assigned a
guessed campaign or company domain. Their original request/evidence must be
recovered before safe enrollment.

The existing scheduler processes up to three recoveries per cycle. It re-fetches
company contact evidence, requalifies from persisted campaign context, and drafts
again. **Recovery ends at drafted.** It does not automatically fire an old campaign
when credits return. An operator or a separately authorized campaign action must
send the draft through the unchanged final gates.

The queue never rewrites leads with send/booking attempts, active conversations,
paused/opted-out/negative states. Temporary states retry with exponential backoff;
quota/configuration waits recheck after one hour. Eight failed attempts require
review. Address rejection and processing restrictions never retry automatically.
No automatic purchases, paid upgrades, guessed addresses or Hunter email-finder
calls are added. Hunter remains an optional verifier, disabled by default.

Provider quota also applies to follow-ups, automatic replies and confirmations.
Their existing processors retry eligible blocked work on later cycles; unresolved
mailbox checks are never bypassed. Free quotas are shared with other Hunter tools,
so this application cannot guarantee their remaining balance.

## Contact and reply configuration

Send `require_decision_maker: true` in a campaign/search payload, or explicitly
request a decision-maker in the query. A confirmed person, relevant responsibility
and that person's published company email must agree. Shared inboxes remain valid
company contacts for campaigns that do not require a named person. All modes retain
company and locality checks. New campaign context is included in signed evidence;
legacy receipts without that marker retain their existing digest structure.

`AUTOMAKE_APPROVED_BUSINESS_FAQ` still requires `approved: true`, literal `answer`,
and `questions`. It now also accepts an optional list of approved `paraphrases`.
Only narrow whole-question equivalences are automatic (polite wrappers and basic
price/duration phrasing). This is not unrestricted semantic answering. Multiple
questions must all be supported. Conflicting or expired answers require review.
Mixed supported FAQ/scheduling requests get grounded answers plus clarification;
booking still waits for an explicit unambiguous date/time and availability check.

Authenticated operator routes:

- `/api/operator/lead-recovery`: queue state, reasons, attempts and next checks.
- `/api/operator/automation-health`: all worker heartbeats, queue age and uncertainty.
- `/operator`: each lead's recovery receipt in its evidence details.

## Existing deployment inventory, observed 2026-10-12

The primary service is `srv-d81ra5vaqgkc73ctg7sg` in Oregon. Render reports the base
commit `ec4f74dd6b9068a1fc00a220b69095e031329589` as live. Existing cron
`crn-das4gsfavr4c738vsi6g` runs every five minutes in Oregon; the older HTTP follow-up
cron `crn-daovl0o0cd8s73b7ad20` runs hourly in Virginia. Both had recent successful
runs during read-only inspection. Staging and the Virginia web service also exist.

Database `dpg-dal0fqdg1s2s73dq761g-a` (`ai-ops-command-center-db`, Oregon) is available,
but external SQL access is blocked. Table counts and each service's actual
connection binding could not be verified. Do not relax its network protection to
complete this review. Before rollout, run binding/count checks from the already
authorized private-network service and confirm the existing leads/bookings.

Reuse the five-minute cron; no new worker or paid resource is required. Before
changing its command, confirm its DATABASE_URL resolves to the same existing
database as the primary web service. The branch provides a safer entrypoint:

```sh
python scripts/run_scheduler.py
```

It returns nonzero on failure and prints a summary instead of nested customer
messages/provider responses. Keep `OUTREACH_INPROCESS_SCHEDULER=0` when using cron.
The new lease suppresses overlapping direct cycles; existing per-send receipts
and follow-up window gates still protect the older HTTP cron.

Use `pip install -r requirements.txt` everywhere. It includes `requirements.lock`.
Python 3.12 is selected in `.python-version`, CI and Docker. Check the live Render
Python version before rollout; a dashboard PYTHON_VERSION override takes precedence.
Docker now starts `commercial_app:app` to load the same modules as production.
Recommended existing web start command: `gunicorn --workers 1 --timeout 300 commercial_app:app`.
Keep `/api/health` as application liveness, and use authenticated automation health
for workflow readiness. Neither establishes provider acceptance on its own.

## Settings to verify without printing values

- Shared persistent `DATABASE_URL`; production `SECRET_KEY`; `OPERATOR_CONTROL_TOKEN`.
- `QUALIFICATION_SIGNING_KEY_VERSION` and existing `QUALIFICATION_SIGNING_KEYS`.
- Existing `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, persisted Gmail OAuth connection,
  `GMAIL_FROM_EMAIL`, Calendar settings and scopes. Do not replace refresh tokens.
- Existing OpenAI/Exa/search settings; no new provider credentials are required.
- If Hunter is desired: `HUNTER_MAILBOX_VERIFICATION_ENABLED=true`, real `HUNTER_API_KEY`,
  `HUNTER_ACCOUNT_EMAIL=jolleyleads@gmail.com`, correct Free account and quota.
- Existing `OUTREACH_AUTOSEND_ENABLED` and approved FAQ data. Defaults remain unchanged.

`python scripts/check_configuration.py` checks configuration presence offline. It
does not call providers, validate credentials or claim a successful live workflow.

## Migration and rollback

Startup `create_all` adds `lead_recovery`, `hunter_account_guard`, and
`scheduler_lease`. No existing columns/tables/data are replaced. The queue table's
lead key and provider/cycle primary keys support atomic competing claims. Test the
new tables against a disposable PostgreSQL database before rollout.

Preserve a normal database backup and existing settings before a separately
approved deployment. Rollback is reverting this feature commit and restoring the
previous runtime/start command if changed. Leave the additive tables in place;
do not drop data. Preserve hashed Hunter restriction markers. Old workers ignore
the new queue tables and continue using existing send/booking receipts.

The feature branch's local tests use an isolated SQLite database and mocked
providers. PostgreSQL-only checks run in CI's disposable database. Real Hunter,
Gmail, Calendar and full production acceptance remain separate live checks;
no cold messages or calendar invitations were generated during this work.
