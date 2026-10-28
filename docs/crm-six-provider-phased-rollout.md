# Six CRM integrations — phased implementation and release gates

Target: authenticated /chat-operator workflow menu > CRM Integrations > HubSpot, Salesforce, Pipedrive, ServiceTitan, Jobber, Clio.

## Phase 1 — Navigation and truthful readiness
- Expandable submenu for six providers; each opens a provider-specific integration detail.
- Show `Not configured`, `Ready to connect`, `Connected`, `Expired`, or `Error` based on server-side state. Never label a placeholder as connected.
- Preserve homepage, existing workflows, Google Drive, and existing login.
- Test menu accessibility, session protection, provider IDs, and existing release suite.

## Phase 2 — Provider OAuth setup
- Register AutoMake AI as a developer application with each provider; configure redirect URLs, client IDs/secrets, required scopes, and any partner approval.
- HubSpot: OAuth authorization code; CRM contact/company read scopes first.
- Salesforce: OAuth authorization code with PKCE where supported; instance URL and refresh-token handling.
- Pipedrive: OAuth authorization code; organization/person read scopes first.
- ServiceTitan: provider-specific tenant/app registration, OAuth client credentials or user authorization as supported by the relevant API product; tenant/account configuration.
- Jobber: OAuth authorization code and GraphQL API.
- Clio: OAuth authorization code and region-specific API host.
- Provider-specific consent must be initiated by the business user. No credential collection in AutoMake AI.

## Phase 3 — Secure per-business connections
- Server-side encrypted credential storage with authenticated encryption and key rotation plan; never store access tokens in browser storage or plaintext logs.
- Tenant-owned connections and authorization checks on every operation; no shared CRM access across customers.
- State/nonce verification, PKCE when supported, expiry/refresh, disconnect/revoke, scoped permissions, safe error handling, rate-limit/backoff.
- Record audit events and redact PII/secrets.

## Phase 4 — Read-only verification and testing
- Per-provider `Test connection` retrieves a minimal authorized identity/account and a limited record page; report success only on real API responses.
- Normalize contacts, organizations, opportunities where supported. Handle pagination and vendor-specific permissions.
- Mocked CI tests for all six OAuth flows, refresh/revoke, tenant isolation, provider errors, and 401/403/429; live sandbox tests only with actual authorized accounts.

## Phase 5 — Workflow integration and staged rollout
- Map CRM records into lead research/outreach with deduplication and explicit customer permissions.
- Gate writes, messaging, and automation actions behind existing user authorization and workflow safeguards.
- Release one provider at a time after sandbox smoke tests; verify production health and roll back on regression.

## External prerequisites (cannot be bypassed by code)
Each provider needs an app registration and credentials, sometimes developer/partner approval. End users must grant consent. Without these, a `Connect` button cannot honestly establish a working connection. ServiceTitan may require additional commercial/API access. Production secrets must be set in Render, not committed to GitHub.

## Current state
Six-provider catalog and nested workflow menu are implemented on the feature branch; **actual CRM OAuth, connection persistence, API sync, and live provider verification are not yet implemented**. Do not deploy them as functional until complete.
