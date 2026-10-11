# Discovery and contact accuracy first

Existing role, city, employer, current-opening, record-locality and qualification
guards remain authoritative. Full research reserves eight seconds of its existing
budget for up to three verified employers' explicit contact/home pages. Domains
come from verified primary evidence or an exact employer's page-authored
organization link; company names are never converted into guessed URLs. Redirects
to other domains, conflicting ownership, and unsupported identities stay unresolved.

Search contact attachment and downstream enrichment require a fetched HTTP 200
page checked within one hour. Snippets, generated answers and RAG history cannot
supply missing emails, phones or names. A verified source URL can bind an unlabeled
direct job page, but conflicting company labels cannot cross that binding. Contacts
still need matching company domain and local branch context. Decision-maker names
need an explicit name/title pair, not a nearby capitalized phrase. Email observation
does not establish deliverability or permission to contact; existing qualification,
suppression and send gates continue to apply.

# Approved replies

Supported scheduling FAQs remain grounded in actual booking configuration. Optional
business answers come only from operator-configured AUTOMAKE_APPROVED_BUSINESS_FAQ,
a JSON list of objects with approved: true, questions: [exact complete questions],
answer: literal approved text, and optional expires_at: an aware ISO timestamp.
Expired, malformed, unapproved or conflicting records cannot answer automatically.
Matching ignores case and trailing question punctuation; it does not reinterpret
extra questions or manufacture prices, services or guarantees. No business facts
have been populated on the user's behalf.

# Clear date interpretation

Full month/day/year or YYYY-MM-DD dates with AM/PM are supported. Valid named
timezones (including Europe and Australia) are respected. Explicit ISO start/end
timestamps need a named timezone whose offset agrees with both timestamps. Current
reply content is interpreted before quoted history. Relative days, multiple times,
ambiguous abbreviations, invalid/past dates, contradictory weekdays, and ambiguous
or nonexistent daylight-saving times trigger a specific clarification. A time is
confirmed only through the existing availability check and durable calendar receipt.
