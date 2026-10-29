# AutoHunt public contact research

Contact-list requests (businesses/companies plus emails, contacts, enrichment, or
Hunter or AutoHunt) use AutoHunt, AutoMake’s discovery and source collection before any mailbox check.
Hiring, permit, and buying-signal workflows keep their separate evidence rules.

## Collection

- Reuse matching, workspace-owned company pages observed within one hour.
- Use configured Google Places and Exa searches for additional discovery hints.
  These services can have their own usage costs; collection does not call Hunter
  Discover, Domain Search, Email Finder, or Email Verifier, or an OpenAI model.
- Fetch public company pages using the existing bounded public fetcher, including
  its DNS pinning, redirect validation, byte limits, and owned-domain checks.
- Bind identity using current primary-page metadata. Collect only addresses
  actually published there; never generate address patterns or invent people.
- Preserve source URLs, timestamps, phone sources, DNS routing receipts, and the
  original request in the existing owned lead record. Public research does not
  save contacts into the owner workspace.
- Match requested industry terms and geography conservatively. Additional
  unsupported conditions remain explicitly unconfirmed. An unavailable page or
  search source does not prove that no matching business exists.

## Manual mailbox retry

`POST /api/chat/contacts/verify` accepts only the ID of an owned saved public
contact. Existing authentication, CSRF, ownership, current-source, and stopped
conversation checks apply. It verifies the exact persisted address through the
Hunter when enabled, otherwise the configured mailbox verifier; it does not buy contacts, create drafts, send mail,
activate follow-ups, or book appointments. The button explicitly discloses
verification credit use. Optimistic writes prevent replacing concurrently
changed conversation evidence.

“Email found · Mailbox not verified” is the default. Published MX records do not
verify a mailbox. Unknown, invalid, mismatched, or expired receipts never produce
the verified label. Research and sending share the seven-day mailbox policy. Current company-source
checks remain separate at workflow activation.

The existing workflow activation remains the sending action. AutoMake-collected
contacts skip Hunter contact discovery when activated, while the independent
mailbox check and all sending restrictions remain in place.

## Automatic Hunter verification

When `HUNTER_MAILBOX_VERIFICATION_ENABLED=true`, email/contact-information
research runs AutoHunt collection followed by Hunter Email Verifier on each
selected, source-supported email. This explicitly chooses Hunter even when
Verifalia is also connected. Phone-only research does not use verification
credits. Current Hunter receipts are reused; pending, rejected, catch-all,
stale, or quota-blocked results remain unverified and retain the business and
published email with the provider reason. Progress and final counts reflect
actual verified receipts. Other published addresses remain separately labeled
unverified. The manual verification button uses Hunter when enabled as well.
This uses the existing Hunter account identity, free-plan quota guard, cache,
and seven-day freshness policy. It never buys a plan or activates outreach.

## Decision-maker research results

Owner/decision-maker contact requests also route to AutoHunt without requiring
"companies" in the prompt. "Contacts" means names, emails, and phones unless a
channel is explicitly requested. Documented company leaders remain visible
without an outreach relevance score. Published company phone numbers remain
labeled as main lines, never reclassified as personal numbers.

When public company pages lack a named email, Hunter Domain Search supplements
the research with company-associated named contacts. Hunter's verification
result is shown alongside them; pending verification does not hide the address.
Provider-only research contacts are stored separately from the persisted sending
recipient and cannot silently replace public-source or outreach authorization
evidence. Existing qualified/active conversations are unchanged.

Research tries additional companies when requested channels are missing. A
source error or time limit preserves already collected contact results instead
of returning a blank failure. The saved-lead score badge calls low-scored records
"Contact research" rather than "Needs more research".
