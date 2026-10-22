# Job-source onboarding for AutoMake AI

As of October 21, 2026. This is staged integration work, not proof of active access.

## Current implementation

The existing Remotive feed remains available. The optional Adzuna US job-search
adapter is wired into the research job tool and hiring-company research. It is
disabled unless both credentials and an explicit approved-use setting exist.
No Indeed or ZipRecruiter search adapter is advertised as active.

Source access states are available to the authenticated owner through
`GET /api/universal-search/capabilities`, under `jobs.providers`. Configuration
does not mean the connection has passed a live search test.

One Adzuna request retrieves at most 20 listings on page 1; this is not an
implementation of a 100-result provider sweep. Each feed runs independently,
with finite network timeouts, no automatic retries and an 18-second collection
deadline. Provider failures are distinct from empty results. Successful results
from other feeds remain usable. Duplicate source URLs are removed.

Listings contain the provider's actual employer name, title, location, source
link and publication field, with a separately recorded observation time. They
remain candidates. A listing does not establish an open current position,
company identity, verified contact, qualification or send authorization.
Primary-source checks and all existing outreach gates remain authoritative.

## Adzuna: agreement and credentials required

Official references:
- https://developer.adzuna.com/overview
- https://developer.adzuna.com/docs/search
- https://developer.adzuna.com/docs/terms_of_service
- Commercial contact linked by Adzuna: https://www.adzuna.co.uk/jobs/contact-us.html

The terms explicitly require written agreement for sales prospecting and lead
generation. A free evaluation key is not sufficient for AutoMake's commercial
outreach use. Obtain a licence covering research, evidence storage, attribution,
retention, company/contact enrichment and the proposed downstream use. Confirm
required attribution in the customer interface before enabling production.

After approval, register the application and supply `ADZUNA_APP_ID` and
`ADZUNA_APP_KEY` securely to Render. Do not paste keys into chat, commit them,
or expose request URLs in logs. Set `ADZUNA_USE_APPROVED=true` only after the
approved scope and display requirements are met. Apply these settings to any
worker/cron executing research, using the existing environment source of truth.
No such configuration has been applied by this change.

Before enablement, perform a bounded live US search, confirm real links,
location/title relevance, attribution, provider limits and production secret
redaction, then run a research-only integration check without sending.

## Indeed: approved search access required

Official partner application: https://partners.indeed.com/
Integration guide: https://docs.indeed.com/getstarted/integrate-and-call-apis

Request approved US job-search/job-retrieval access for the exact product use.
Job Sync manages postings and is not general search access. The integration
guide contains a `jobSearch` example but also demonstrates the access-denied
response when the app lacks the job-retrieval service entitlement. Do not treat
an OAuth credential or employer integration as permission to search the full
marketplace. Confirm storage, display and outreach use with Indeed first.

No guessed API contract, unapproved scraping, OAuth credentials, or new Indeed
connection is introduced in this change.

## ZipRecruiter: contract verification blocked

Official documentation: https://api.ziprecruiter.com/mcp/docs
MCP endpoint: https://api.ziprecruiter.com/mcp

The documented MCP advertises `search_jobs`. A bounded `initialize` request on
October 21 returned HTTP 429, before a tool schema or real result could be
retrieved. This is a rate-limit response, not evidence that authentication or a
particular account is required. No `tools/call` search was performed.

Next: establish supported access with ZipRecruiter, confirm business usage and
quotas, retrieve the current `tools/list` schema and structured result contract,
and validate a read-only search before implementing against that verified
contract. Do not invent parameters, bypass access restrictions, or treat posting
API credentials as job-search entitlement.

## Prepared provider inquiry (not submitted)

AutoMake AI (https://automakeai.live) is a conversational business-research and
outreach product operated by Matthew Jolley. Customers would search US job
listings by role and location to identify hiring companies. We propose showing
source-linked candidate companies, independently checking their official sites,
then using separately verified business contacts for customer-authorized
outreach. No applicant or résumé database access is requested.

Please confirm whether this use is permitted, which search product and
credentials are required, any commercial licence and fees, rate limits,
attribution requirements, permitted evidence storage/retention, and downstream
enrichment/outreach restrictions. We will not enable your source for this use
until the required access is approved.

No inquiry has been sent and no account or paid agreement has been created.

## Rollback and limits

Unset `ADZUNA_USE_APPROVED` to disable Adzuna immediately without discarding
genuine records or changing the customer interface. Revert this commit to remove
the staged adapter. There are no migrations or new infrastructure dependencies.
Indeed and ZipRecruiter remain unavailable as direct structured search sources
until their respective access and live contracts are established. Existing web
research can still discover public sources; it must not claim direct API access.
