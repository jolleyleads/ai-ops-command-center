# Shared mailbox verification and free Verifalia connection

The server uses one seven-day verification policy in research, saved contacts,
quality summaries, and final sending. Provider receipts are bound to the exact
address and retain both request and provider-result dates. A verified mailbox
never establishes a person's identity. Explicit decision-maker requests require
a source-supported person unless the user explicitly permits a company inbox.
Current company-page evidence still has its separate one-hour refresh policy.

## Connect

In the owner workspace, Settings → Free email verification accepts a Verifalia
API username and password after the owner confirms free-only use with no paid
credit packs or automatic top-ups. Create the Verifalia account separately;
AutoMake never creates accounts, accepts terms, or invents credentials.

Credentials are checked against the balance endpoint before being encrypted with
Fernet using a domain-separated key derived from the deployment's SECRET_KEY.
Storage requires at least 32 characters in that server secret and refuses the
insecure development default. Web and worker services must share that stable
SECRET_KEY to decrypt the same stored connection. Responses and verification receipts never contain
credentials. The existing authentication, owner-only middleware, origin checks,
and CSRF checks protect both connection routes. VERIFALIA_USERNAME and
VERIFALIA_PASSWORD environment secrets are also supported.

Connected Verifalia is preferred for mailbox checks. It never silently falls back
to Hunter. Unconnected installations retain the existing Hunter configuration.
Each new submission uses Standard quality for one address; the current account
must report no paid credit packs and sufficient free credits. A durable local
allowance caps this app at 25 new submissions per UTC day. There is no credit
purchase, plan-change, automatic-top-up, or paid-fallback operation. Concurrent
usage outside AutoMake also shares the provider account's allowance; keep that
account free-only without automatic top-ups as stated in the connection form.

Only a completed, address-matching raw Success result classified Deliverable,
with a fresh provider completion date, can verify an address. Risky, catch-all,
unknown, malformed, expired, and mismatched results remain unverified even if an
account customizes classification names. Confirmed results are cached through
the seven-day cutoff. Rejected and unknown completed results are cached a day.
Pending job IDs are durable and only polled on subsequent checks; no duplicate
POST is issued. A lost POST response is held a day instead of automatically
replaying an unknown credit-consuming request. Quota exhaustion is shown plainly;
it never triggers sending or purchases.

## Draft Send

An explicit reviewed-draft Send queues the same selected-contact worker as
Activate. Business scoring is not an extra barrier to an explicitly selected,
verified contact. Source, mailbox, suppression, recipient, ownership, résumé,
Gmail and duplicate-attempt checks remain required. The reviewed recipient,
subject and body are bound to the job; if verification changes them, sending is
held for a new review. The UI only polls saved jobs and never retries a POST on
network errors. Explicit retries of held jobs retain the review and existing
one-minute/four-per-hour limits. Generic automatic campaign qualification is
unchanged.

Official API references:
- https://verifalia.com/developers/authentication
- https://verifalia.com/developers/credits
- https://verifalia.com/developers/email-verifications/creating-jobs
- https://verifalia.com/developers/email-verifications/retrieving-jobs
