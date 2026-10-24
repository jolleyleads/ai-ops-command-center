# Optional Hunter mailbox verification

The integration is disabled by default. Activation requires these server-side
Render secrets/settings on the relevant existing AutoMake services:

- HUNTER_MAILBOX_VERIFICATION_ENABLED=true
- HUNTER_API_KEY=<the existing account's real API key>
- HUNTER_ACCOUNT_EMAIL=jolleyleads@gmail.com

Never put the API key in source control, customer pages, logs, chat or URLs. The
client uses the documented X-API-KEY header, fixed HTTPS endpoints and no redirects.
No account, subscription, purchase, sequence or contact-finding operation is created.

Before a credit-consuming verification, the account identity must match the
configured email, plan_name must be Free, and the account's current shared credit
balance must cover verification (or the legacy verification quota must remain).
There are no automatic purchases, upgrades or HTTP retries. Hunter's own Free-plan
quota limits usage shared with other account tools. Positive receipts are cached
for at most one day and expire before the seven-day result-age cutoff. A database
lease prevents different workers from checking the same account/address together;
lease tokens prevent old workers from overwriting newer receipts. Temporary or
pending results are cached briefly and remain unconfirmed.

The API can return a verification performed earlier than the request. Receipts
therefore retain both checked_at and provider_verified_on. Promotion needs a
matching response email, valid status, positive SMTP mailbox check, non-catch-all,
non-disposable/unblocked checks, and a matching valid verification within seven
days. Catch-all, unknown, webmail-only, stale, malformed, quota failure, privacy
restriction, missing credentials, and dummy test keys cannot become verified mailboxes.
Privacy restrictions persist as hashed address markers across cache expiry, key rotation and feature disablement; they block repeat provider processing and outgoing sends.
A provider-reported valid result is evidence, not an inbox-placement guarantee.

Both discovery/enrichment paths and the final safe-send gate share this check.
With the feature enabled, unresolved mailbox checks hold email qualification and
sending. Send-time receipts go into the immutable audit chain without rewriting
qualification evidence. Existing company/city/person, suppression, idempotency,
Gmail and calendar checks stay authoritative. No provider name/location suggestion
can replace those identity checks.

Official reference: https://hunter.io/api-documentation/v2#email-verifier
Account/credit reference: https://hunter.io/api-documentation/v2#account

Direct contact-list research uses a separate `research_only` verifier policy and
cache namespace: it can show Hunter's last reported valid result from up to 30
days ago, with the actual verification date, matching Hunter's documented API
response window. This is not send eligibility. The existing send-time verifier
still uses the seven-day policy and cannot reuse the research cache. Company
source proof, suppression and the displayed recipient are checked again during
activation.

Free account/Discover requests may reclaim a cached quota pause so that a restored
balance can be checked. Active leases and identity/plan blocks are never reclaimed
this way. Credit-consuming calls still check current available credits. For older
usage responses, a balance is derived only when both numeric total allocation and
numeric used values are present; allocation alone is never treated as balance.
