# Current hiring evidence

Search, semantic promotion, campaign gap filling, identity joins, and result
ranking use the same current-job guard. Model confidence or an old Verified Lead
label cannot replace the guard.

A hiring result must come from a fetched HTTP 200 employer page or a recognized
ATS page with an exact hiring-organization match. A query label or generated
answer is insufficient. The page needs a matching job title, the requested job
city/state, and an enabled application control in the job content whose target
contains the selected posting's job identifier. Unbound JavaScript buttons and
recommended-job application links remain unverified. Structured
JobPosting metadata is read per posting, not pooled across jobs. Multi-posting
listing pages with ambiguous detail URLs remain candidates. Unstructured pages
need a specific role heading and a labeled worksite address.

The guard rejects closure/filled/expired messages, past validThrough dates,
malformed or future posting dates, disabled/hidden application controls, and
postings older than 90 days. Checks older than one hour are not current. These
90-day and one-hour limits are platform policy, not claims about how all
employers recruit. A long-running opening may need a new dated source before it
can be promoted.

The API preserves the observed job title, job locations, application signal,
check timestamp, source URL/content digest, publication date, and expiry date in
job_validation. Missing publication/expiry dates stay unknown; fetching a page
now never manufactures a new posting date. The application signal means an
enabled application option was observed, not that an application was submitted
or that the employer guarantees the position will remain open.

Remote-only or nationwide eligibility does not establish a job in a particular
city. A requested remote role needs explicit remote evidence as well as the
requested location. City in a company footer/HQ or another posting cannot
supply a missing worksite. Explicit query city and location-field constraints
must both be supported.

Unavailable, blocked, script-only, ambiguous, or insufficient pages remain
unverified candidates with reason codes. The verifier does not bypass access
restrictions, invent missing dates, or loosen outreach qualification/send gates.
Previously stored lead history is retained; this change governs new research
and campaign promotion.
