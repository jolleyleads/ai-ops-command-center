# Contact evidence and decision-maker certainty

Company ownership, requested city/branch, role relevance, person-to-email association,
and email routing are separate checks. Search, campaign orchestration and outreach
enrichment share these checks. Campaigns pass the requested city and business need
into current company-owned contact research rather than trusting provider contact
labels. Social profiles and snippets remain discovery hints requiring primary-source
corroboration. Unknown fields stay unconfirmed; ambiguity never creates a percentage
confidence claim.

HTML contact cards exclude navigation and footer addresses. A local role/name pair
must fit the hiring, technical or business function requested, or have an explicit
relevant responsibility statement. Former staff are withheld. Multiple equally
supported people remain ambiguous. Personal email association requires one named
person in a source card and an actually published address consistent with that name.
Addresses are never generated from a name. Shared inboxes remain company contacts,
not a named person's mailbox. Personal greetings require the chosen email, person,
locality and responsibility evidence to agree; unconfirmed names cannot leak into
generated greetings. Contact research continues within its existing bounded budget
when only a generic inbox has been found.

Campaign email validation makes bounded DNS requests for the domain only, without
sending a message or sharing the address with a paid verification service. MX, null
MX, implicit A/AAAA routing, nonexistent domains and temporary DNS failures have
separate receipts. Explicitly invalid or non-mail domains cannot qualify as email
contacts. MX and implicit routing do not prove that a particular mailbox exists,
accepts a message, belongs to the decision-maker, or reaches the inbox. Catch-all
behavior and mailbox deliverability remain unconfirmed. Actual mailbox verification
requires a separately configured trustworthy verification service or delivery evidence;
this change does not invent that evidence or purchase a service.

References: RFC 7505 (null MX and implicit A/AAAA routing), and dnspython resolver
lifetime documentation. All observations and DNS checks retain timestamps and source
URLs in enrichment/audit receipts. Existing qualification, suppression, send, and
calendar gates remain authoritative.
