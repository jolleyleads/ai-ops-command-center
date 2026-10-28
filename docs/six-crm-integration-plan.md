# AutoMake AI: Six CRM integration implementation plan

Status: NOT IMPLEMENTED. This document is a development contract, not evidence of functioning integrations.

## Scope
Integrate HubSpot, Salesforce, Pipedrive, ServiceTitan, Jobber, and Clio into the existing authenticated /chat-operator integrations dropdown. Preserve existing customer UI, lead research, Hunter enrichment, Gmail, Google Calendar, Google Drive, outreach, and follow-ups. Never change the public homepage for this feature.

## Discovery before coding
- Identify the actual route handler/template for /chat-operator, existing integration registry, auth/session tenant identity, SQLAlchemy migration strategy, and Salesforce work in progress.
- Inspect existing Salesforce PR and avoid parallel incompatible implementations.
- Confirm the live Render service and its domain, and check deployment configuration before release.
- Use official provider documentation for OAuth, supported scopes, resource APIs, and rate limits.

## Implementation contract
- Provider adapters implement authorization, callback, connection verification, token refresh/revoke when supported, and resource synchronization with capability flags.
- Store credentials encrypted at rest, scoped by authenticated tenant and provider account; never store raw credentials in logs or client-side JavaScript.
- OAuth callbacks validate state and PKCE where supported; reject tenant mismatches.
- Connection state is verified by the backend; missing client credentials and external provider approval must show Setup Required, not Connected.
- Connect/disconnect/reconnect controls appear only in authenticated workflow dropdown; preserve existing menu behavior and mobile layout.
- Support supported contact/company/lead/deal/task/activity records by provider; ServiceTitan and Clio capabilities must be verified for each specific product/account.
- CRM sync must deduplicate, use idempotent writes, respect pagination and rate limits, and report per-record failures without claiming complete success.
- Existing outreach sends and calendar bookings must use their existing authorization and only show Sent/Booked after provider acknowledgement.
- Do not automatically write to every CRM: choose destination explicitly, with an optional tenant default.

## Acceptance tests
1. OAuth success, invalid state, expired/revoked token, insufficient scope, refresh and disconnect.
2. Tenant isolation and unauthorized access attempts.
3. API create/update/list/pagination, rate limit and retry handling, duplicate prevention.
4. Dropdown rendering and authenticated access on desktop/mobile.
5. Research -> CRM, approved outreach -> CRM activity, reply -> CRM, booking -> CRM.
6. Regression suite for existing workflows, Salesforce, Google integrations and outbound email.
7. Production build and staging verification; live end-to-end tests require provider test accounts and credentials.

## Release gates
- No deploy or merge while required CI fails.
- Never claim a provider is live-tested without actual successful authorized API calls.
- Do not create new Render services/databases or overwrite secrets.
- Provide a provider-by-provider status matrix (UI/OAuth/API/sync/live-tested), CI links, deployment ID and blockers.
