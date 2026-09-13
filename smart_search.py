from urllib.parse import urlparse

from flask import jsonify, request

from app import app
import contractor_intent
import local_jobs
import permit_leads
import search_overrides
from universal_app import _search_public_records


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _detect_intent(query):
    text = _clean(query, 1000).lower()
    if (
        any(term in text for term in ("permit lead", "permit leads", "permit-pulling lead", "permit pulling lead"))
        or (
            any(term in text for term in ("lead", "leads", "opportunity", "opportunities"))
            and any(term in text for term in ("master electrician", "qualifying agent", "qualifier", "pull permits", "permit pulling"))
        )
    ):
        return "permit_leads", {"permit_leads": 10, "contractors": 0, "permits": 0, "jobs": 0, "businesses": 0}
    if any(term in text for term in ("master electrician", "qualifying agent", "electrical qualifier", "permit puller", "pull permits")):
        return "contractors", {"permit_leads": 0, "contractors": 10, "permits": 0, "jobs": 0, "businesses": 0}
    if any(term in text for term in ("machine learning engineer", "ai engineer", "automation engineer", "llm engineer")) and any(
        term in text for term in ("job", "jobs", "hiring", "career", "position", "opening", "employment")
    ):
        return "jobs", {"permit_leads": 0, "contractors": 0, "permits": 0, "jobs": 10, "businesses": 0}

    permit_terms = ("permit", "permits", "public record", "inspection", "license record", "building record")
    contractor_terms = ("contractor", "electrician", "qualifier", "qualifying agent", "master electrician", "pull permits", "permit puller")
    job_terms = ("job", "jobs", "hiring", "career", "position", "opening", "engineer", "developer", "employment")
    business_terms = ("business", "businesses", "company", "companies", "shop", "shops", "provider", "providers")
    scores = {
        "permit_leads": 0,
        "contractors": sum(1 for term in contractor_terms if term in text),
        "permits": sum(1 for term in permit_terms if term in text),
        "jobs": sum(1 for term in job_terms if term in text),
        "businesses": sum(1 for term in business_terms if term in text),
    }
    if "permit" in text and any(term in text for term in ("pulled", "issued", "record", "recent", "city", "county")):
        scores["permits"] += 3
    if any(term in text for term in ("machine learning engineer", "ai engineer", "automation engineer", "llm engineer")):
        scores["jobs"] += 3
    if any(term in text for term in ("find companies", "find businesses", "businesses near", "companies near")):
        scores["businesses"] += 3
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "web", scores
    return best, scores


def _job_payload(query, location):
    with app.test_request_context("/api/local-jobs", method="POST", json={"query": query, "location": location}):
        response = local_jobs.local_jobs()
    if isinstance(response, tuple):
        response = response[0]
    return response.get_json() if hasattr(response, "get_json") else {"configured": True, "results": [], "message": "Job search returned no readable response."}


def _permit_lead_payload(query, location):
    with app.test_request_context("/api/permit-leads", method="POST", json={"query": query, "location": location}):
        response = permit_leads.permit_leads()
    if isinstance(response, tuple):
        response = response[0]
    return response.get_json() if hasattr(response, "get_json") else {"configured": True, "results": [], "message": "Permit-lead search returned no readable response."}


def _permit_host_is_authoritative(url):
    try:
        host = (urlparse(_clean(url, 1600)).hostname or "").lower()
    except ValueError:
        return False
    if host.endswith(".gov"):
        return True
    if any(token in host for token in ("accela.com", "energov", "tylerhost", "mygovernmentonline", "permittrax", "citygovapp")):
        return True
    if "cityof" in host or "countyof" in host:
        return True
    return False


def _permit_record_payload(query, location):
    payload = _search_public_records(query, location)
    if not payload.get("configured"):
        return payload

    text = _clean(query, 800).lower()
    wants_records = any(term in text for term in (
        "issued", "recent", "record", "records", "pulled", "active", "permit search",
        "permit database", "permit activity", "permit report", "open data",
    ))
    if not wants_records:
        return payload

    reject_signals = (
        "procedure", "procedures", "how to", "apply for", "application", "requirements",
        "fees", "forms", "faq", "handbook", "guide", "instructions", "code requirements",
    )
    record_signals = (
        "issued permit", "issued permits", "permit search", "permit records", "permit record",
        "permit portal", "permit report", "permit activity", "open data", "citizen access",
        "permit database", "permit lookup", "permit history", "recent permits", "active permits",
        "accela", "energov", "record details",
    )

    kept = []
    for item in payload.get("results") or []:
        title = _clean(item.get("title"), 500)
        subtitle = _clean(item.get("subtitle"), 1500)
        url = _clean(item.get("url"), 1600)
        haystack = f"{title} {subtitle} {url}".lower()
        if not _permit_host_is_authoritative(url):
            continue
        if any(signal in haystack for signal in reject_signals):
            continue
        if not any(signal in haystack for signal in record_signals):
            continue
        kept.append(item)

    result = dict(payload)
    result["results"] = kept
    result["count"] = len(kept)
    result["message"] = (
        f"Found {len(kept)} authoritative permit-record result"
        + ("." if len(kept) == 1 else "s.")
        + " Commercial contractor pages and procedural/application pages were filtered out."
    )
    return result


def _smart_search(query, location):
    intent, intent_scores = _detect_intent(query)
    if intent == "permit_leads":
        payload = _permit_lead_payload(query, location)
    elif intent == "contractors":
        payload = contractor_intent._contractor_intent_search(query, location)
    elif intent == "jobs":
        payload = _job_payload(query, location)
    elif intent == "businesses":
        payload = search_overrides._search_google_places(query, location)
    elif intent == "permits":
        payload = _permit_record_payload(query, location)
    else:
        payload = _search_public_records(query, location)
        if intent == "web":
            intent = "web_research"

    results = payload.get("results") or []
    return {
        "configured": bool(payload.get("configured", True)),
        "intent": intent,
        "intent_scores": intent_scores,
        "query": query,
        "location": location,
        "source": payload.get("source") or "Smart Search",
        "message": payload.get("message") or (f"Found {len(results)} result(s)." if results else "No verified results found."),
        "count": len(results),
        "results": results,
        "search_details": {
            "permit_leads": "Strict evidence-backed Master Electrician permit-pulling lead search.",
            "contractors": "Google Places discovery plus independent Brave and Google evidence verification.",
            "jobs": "Verified local job search with direct-posting, location, freshness, and quality filtering.",
            "businesses": "Google Places business discovery using the requested inquiry and location.",
            "permits": "Authoritative permit-record search that suppresses commercial, procedural, fee, and how-to pages when the inquiry asks for issued or recent records.",
            "web_research": "General public web research using configured search providers.",
        }.get(intent, "Smart Search"),
    }


@app.route("/api/smart-search", methods=["GET", "POST"])
def smart_search():
    data = (request.get_json(silent=True) or {}) if request.method == "POST" else request.args
    query = _clean(data.get("query") or data.get("keyword"), 500)
    location = _clean(data.get("location"), 200)
    if not query:
        return jsonify({"error": "Enter a search inquiry.", "results": [], "count": 0}), 400
    return jsonify(_smart_search(query, location))


@app.route("/api/test-smart-search", methods=["GET"])
def test_smart_search():
    query = _clean(request.args.get("query") or "machine learning engineer jobs", 500)
    location = _clean(request.args.get("location") or "Portsmouth, VA", 200)
    payload = _smart_search(query, location)
    app.logger.warning(
        "SMART_SEARCH_DIAGNOSTIC intent=%r count=%s query=%r location=%r source=%r message=%r",
        payload.get("intent"), payload.get("count", 0), query, location,
        _clean(payload.get("source"), 300), _clean(payload.get("message"), 700).replace("\n", " ").replace("\r", " "),
    )
    return jsonify(payload)
