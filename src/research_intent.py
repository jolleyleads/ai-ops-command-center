"""Intent-aware research presentation, independent from outreach qualification.

This module is deliberately pure: no database writes, sends or external requests.
"""
import re
from src.research_policy import COUNT_WORDS

_FIELDS = {
    "email": r"\b(?:emails?|e-mails?|email addresses?)\b",
    "phone": r"\b(?:phones?|phone numbers?|telephone|numbers?|call(?:ing)?|mobile|cellphones?|cell numbers?)\b",
    "decision_maker": r"\b(?:decision[\s\u2010-\u2015-]*makers?|owners?|founders?|presidents?|ceos?|managers?|directors?)\b",
    "website": r"\b(?:websites?|domains?|urls?)\b",
}
_OUTREACH = re.compile(r"\b(?:send|email them|start outreach|activate (?:the )?workflow|launch campaign)\b", re.I)
_FOLLOWUP = re.compile(r"\b(?:their|them|those|same companies|these companies)\b", re.I)
_COUNT = re.compile(r"\b(?:find|give me|show|list|get)\s+(?:me\s+)?(?:up to\s+)?(\d{1,3})\b", re.I)


def parse_research_request(query, previous=None):
    """Determine requested display fields without granting send authority."""
    query = str(query or "").strip()
    previous = previous or {}
    requested = [field for field, pattern in _FIELDS.items() if re.search(pattern, query, re.I)]
    contact_bundle = bool(re.search(r'\bcontacts?\b', query, re.I)) and not any(f in requested for f in ('phone','email'))
    if contact_bundle:
        requested = ["company", "decision_maker", "email", "phone", "website"]
    elif not requested:
        requested = ["company", "website", "location"]
    else:
        requested = ["company"] + (["decision_maker"] if "decision_maker" in requested else []) + [f for f in requested if f != "decision_maker"]
    match = _COUNT.search(query)
    word_count = re.search(r'\b('+'|'.join(COUNT_WORDS)+r')\s+(?:[a-z-]+\s+){0,4}(?:companies|businesses|prospects|leads|owners|decision[ -]?makers)\b', query, re.I)
    count = min(100, max(1, int(match.group(1)))) if match else COUNT_WORDS.index(word_count.group(1).lower())+1 if word_count else previous.get("count", 20)
    reuse = bool(previous and _FOLLOWUP.search(query))
    return {
        "query": query,
        "count": count,
        "fields": list(dict.fromkeys(requested)),
        "reuse_previous_results": reuse,
        "research_only": not bool(_OUTREACH.search(query)),
        "send_authorized": False,
        "contact_bundle": contact_bundle,
    }


def format_research_results(rows, intent):
    """Return matching discovered records, without requiring verified email."""
    requested = intent["fields"]
    output = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = row.get("company") or row.get("title") or row.get("name")
        if not name:
            continue
        key = (name.strip().casefold(), (row.get("website") or "").strip().casefold())
        if key in seen:
            continue
        seen.add(key)
        result = {"company": name}
        for field in requested:
            if field == "company":
                continue
            if field == "decision_maker":
                result[field] = row.get("contact_name") or row.get("decision_maker") or None
                result["decision_maker_role"] = row.get("contact_role") or None
            elif field == "phone":
                direct = row.get("direct_phone") if row.get("direct_phone_verified") else None
                result[field] = direct or None
                result["phone_type"] = "direct" if direct else "business_or_unconfirmed" if row.get("contact_phone") else "not_found"
                result["business_phone"] = row.get("contact_phone") or None
            elif field == "email":
                result[field] = row.get("contact_email") or None
                result["email_status"] = row.get("email_status") or "unverified"
            else:
                result[field] = row.get(field) or None
        result["source_url"] = row.get("source_url") or row.get("website") or None
        result["decision_makers"] = row.get("decision_makers") or []
        result["email_type"] = row.get("contact_type") or "Published contact; person association unconfirmed"
        result["sources"] = [
            {"label": label, "url": row[key]}
            for label, key in [("Decision-maker source", "decision_maker_source_url"),
                               ("Email source", "email_source_url"), ("Phone source", "phone_source_url")]
            if row.get(key)
        ]
        result["observed_at"] = row.get("research_observed_at") or row.get("email_observed_at")
        result["location"] = row.get("location") or None
        result["contact_issue"] = row.get("contact_issue") or ""
        output.append(result)
        if len(output) >= intent["count"]:
            break
    return output
