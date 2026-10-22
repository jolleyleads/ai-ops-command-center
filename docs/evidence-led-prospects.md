# Evidence-led prospect preparation

Research remains progressive: public discovery returns source-backed candidates
without waiting for contacts. Signed-in preparation adds independent assessments
of business fit, documented offer need and named-buyer/contact readiness. Research
and preparation never activate sending. Each ready contact requires explicit
activation and the existing qualification, suppression, approved-copy, résumé,
mailbox, ownership and durable-attempt checks.

## Actual implemented checks and limits

- Edit **Your offer** in Task options. The original request, geography and offer
  are persisted together; explicit empty offers are rejected before preparation.
- Fit requires recent directly fetched company identity, requested industry terms
  and geography in company text. Query text and search snippets are not proof.
- Need supports current source-authored offer-relevant jobs with application
  evidence, or explicit ongoing first-person manual-process/help language.
  These are workload indicators; interest, budget and urgency remain unconfirmed.
  Expansion, reviews and generic scheduling buttons are not automatically need.
- Need collection performs one company fetch, at most one existing-provider Exa
  search and two additional owned-source fetches. Collection stops scheduling at
  its 25-second budget; in-flight calls retain provider timeouts and the per-business
  process deadline. Contacts remain independent, with existing bounded concurrency.
- A named responsible buyer needs source-supported responsibility and email
  association; mailbox verification is independent. Evidence freshness is one hour.
  Expired eligibility holds initial activation; repeat preparation schedules a
  read-only reassessment. A different offer also invalidates unsent eligibility.
  Sent, uncertain and actively leased historical work is never rewritten here.
- Ranking uses fit and need only: strong fit 20, partial fit 10, supported need 2.
  Email validity adds zero. Existing discovery scores remain discovery scores.
- Existing safe count limits remain: up to 20 per run, with honest rejection of
  100 before launch. This change does not advertise 100-business execution.
- Initial target is ten well-supported businesses, not ten guaranteed findings.
  Requested, researched, supported, buyer/contact readiness and shortfall are
  separate. A supported business can still lack an outreach-ready contact.
- Legacy qualification receipts remain intact. Only new preparation uses this
  policy; unsent reusable leads are reassessed. No multi-customer readiness claim.

## Reporting definitions

Each lead retains its first originating campaign. Its discovery source labels are
combined into one bucket, avoiding duplicate attribution across sources. Quality
metrics use persisted qualification snapshots, not continually changing historical
freshness. Current cards and activation recheck freshness separately.

Recorded replies count contacts with any stored reply. Classified conversations
require a nonautomatic reply classified interested or question; this is a proxy,
not a guaranteed sales conversation. Automatic/out-of-office/bounce patterns are
excluded from positive replies and conversations. Bookings require confirmed event
receipts; Gmail acceptance does not prove delivery. Customer, delivery and revenue
metrics remain unavailable without actual recorded evidence. Small-sample outcomes
never increase volume automatically.

## Configuration, deployment and rollback

No new migrations, credentials, services or environment variables. Existing signing,
research, Hunter and app Google authorization requirements still apply. Disabled
job feeds remain disabled pending documented provider approval and credentials.

Deploy via passing repository PR checks and the existing Render main auto-deploy.
Verify the exact deployed revision, customer screen, protected endpoints and genuine
read-only discovery. Do not test sends or calendar writes without a separately
authorized controlled recipient/calendar. Revert this commit through the same
process to roll back behavior; preserve persisted evidence, signed receipts,
existing records and external-send/booking history. A code revert does not undo
external effects.
