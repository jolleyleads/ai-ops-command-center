# AutoMake public contact research

Contact-list requests (businesses/companies plus emails, contacts, enrichment, or
Hunter) use AutoMake's discovery and source collection before any mailbox check.
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

## Separate mailbox action

`POST /api/chat/contacts/verify` accepts only the ID of an owned saved public
contact. Existing authentication, CSRF, ownership, current-source, and stopped
conversation checks apply. It verifies the exact persisted address through the
configured mailbox verifier; it does not buy contacts, create drafts, send mail,
activate follow-ups, or book appointments. The button explicitly discloses
verification credit use. Optimistic writes prevent replacing concurrently
changed conversation evidence.

“Email found · Mailbox not verified” is the default. Published MX records do not
verify a mailbox. Unknown, invalid, mismatched, or expired receipts never produce
the verified label. Research verification does not replace the stricter current
mailbox and source checks at workflow activation.

The existing workflow activation remains the sending action. AutoMake-collected
contacts skip Hunter contact discovery when activated, while the independent
mailbox check and all sending restrictions remain in place.
