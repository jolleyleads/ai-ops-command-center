from urllib.parse import urlparse
import re

from flask import jsonify, request

from app import app
import contractor_intent
import local_jobs
import permit_leads
import search_overrides
from universal_app import _search_public_records


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _dedupe_results(results):
    kept, seen = [], set()
    for item in results:
        if not isinstance(item, dict):
            continue
        key = (_clean(item.get("url"), 1600).lower() or
               (_clean(item.get("title"), 500).lower() + "|" + _clean(item.get("subtitle"), 800).lower()))
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(item)
    return kept


def _detect_intent(query):
    """Use intent only to choose specialized providers; discovery itself stays broad."""
    text = _clean(query, 1000).lower()
    scores = {"permit_leads": 0, "contractors": 0, "permits": 0, "jobs": 0, "businesses": 0}
    if any(x in text for x in ("job", "jobs", "hiring", "career", "position", "opening", "employment", "vacancy")):
        scores["jobs"] += 4
    if any(x in text for x in ("permit record", "permit records", "issued permit", "issued permits", "permit database", "public record", "inspection record")):
        scores["permits"] += 5
    if any(x in text for x in ("contractor", "electrician", "plumber", "hvac", "roofer", "builder")):
        scores["contractors"] += 2
    if any(x in text for x in ("qualifying agent", "qualified agent", "qualifier", "master electrician", "license holder", "pull permits", "permit pulling")):
        scores["permit_leads"] += 4
        scores["contractors"] += 2
    if any(x in text for x in ("looking for", "seeking", "needed", "needs", "hiring", "wanted")) and scores["permit_leads"]:
        scores["permit_leads"] += 3
    if any(x in text for x in ("business", "businesses", "company", "companies", "shop", "provider")):
        scores["businesses"] += 2
    best = max(scores, key=scores.get)
    return (best if scores[best] else "web"), scores


# Semantic expansions are discovery hints, never hard verification requirements.
_CONCEPT_GROUPS = (
    (("qualifying agent", "qualified agent", "qualifier"),
     ("qualifying agent", "qualified agent", "license qualifier", "license holder", "qualifying individual", "responsible individual")),
    (("master electrician",),
     ("master electrician", "licensed master electrician", "responsible master electrician", "designated master electrician", "master electrical license")),
    (("pull electrical permits", "pull permits", "permit pulling"),
     ("pull electrical permits", "pull permits", "permit pulling", "permit responsibility", "electrical permitting", "permit qualifier")),
    (("looking for", "seeking", "needed", "needs", "hiring", "wanted"),
     ("looking for", "seeking", "needed", "hiring", "wanted", "required")),
)


def _semantic_queries(query):
    q = _clean(query, 500)
    lower = q.lower()
    variants = [q]
    concepts = []
    for triggers, synonyms in _CONCEPT_GROUPS:
        if any(t in lower for t in triggers):
            concepts.append(synonyms)
    if concepts:
        # Provider-friendly OR query covering equivalent language.
        groups = ["(" + " OR ".join('"%s"' % s for s in syns[:6]) + ")" for syns in concepts]
        variants.append(" ".join(groups))
        # Natural-language broadening catches pages whose snippets omit exact phrases.
        broad_terms = []
        for syns in concepts:
            broad_terms.extend(syns[:3])
        variants.append(" ".join(dict.fromkeys(broad_terms)))
    return list(dict.fromkeys(v for v in variants if v))[:3]


def _web_discovery(query, location):
    all_results, sources, messages = [], [], []
    for variant in _semantic_queries(query):
        try:
            payload = _search_public_records(variant, location)
        except Exception as exc:
            app.logger.exception("SMART_SEARCH_WEB_PROVIDER_ERROR query=%r location=%r", variant, location)
            messages.append(type(exc).__name__)
            continue
        all_results.extend(payload.get("results") or [])
        source = _clean(payload.get("source"), 300)
        if source and source not in sources:
            sources.append(source)
        if payload.get("message"):
            messages.append(_clean(payload.get("message"), 500))
    return {
        "configured": True,
        "source": " + ".join(sources) or "Web Search",
        "message": messages[0] if messages and not all_results else "",
        "results": _dedupe_results(all_results),
    }


def _job_payload(query, location):
    with app.test_request_context("/api/local-jobs", method="POST", json={"query": query, "location": location}):
        response = local_jobs.local_jobs()
    if isinstance(response, tuple):
        response = response[0]
    return response.get_json() if hasattr(response, "get_json") else {"configured": True, "results": []}


def _permit_lead_payload(query, location):
    with app.test_request_context("/api/permit-leads", method="POST", json={"query": query, "location": location}):
        response = permit_leads.permit_leads()
    if isinstance(response, tuple):
        response = response[0]
    return response.get_json() if hasattr(response, "get_json") else {"configured": True, "results": []}


def _permit_host_is_authoritative(url):
    try:
        host = (urlparse(_clean(url, 1600)).hostname or "").lower()
    except ValueError:
        return False
    return host.endswith(".gov") or any(t in host for t in ("accela.com", "energov", "tylerhost", "mygovernmentonline", "permittrax", "citygovapp", "cityof", "countyof"))


def _permit_record_payload(query, location):
    payload = _web_discovery(query, location)
    kept = []
    for item in payload.get("results") or []:
        url = _clean(item.get("url"), 1600)
        haystack = f"{item.get('title','')} {item.get('subtitle','')} {url}".lower()
        if _permit_host_is_authoritative(url) and any(x in haystack for x in ("permit", "inspection", "record", "accela", "energov")):
            kept.append(item)
    result = dict(payload)
    result["results"] = kept
    return result


def _specialized_payload(intent, query, location):
    if intent == "permit_leads":
        return _permit_lead_payload(query, location)
    if intent == "contractors":
        return contractor_intent._contractor_intent_search(query, location)
    if intent == "jobs":
        return _job_payload(query, location)
    if intent == "businesses":
        return search_overrides._search_google_places(query, location)
    if intent == "permits":
        return _permit_record_payload(query, location)
    return {"configured": True, "results": [], "source": ""}


def _smart_search(query, location):
    """Broad discovery first, specialized verification second, for any query/location."""
    intent, intent_scores = _detect_intent(query)
    payloads = []

    # Always search the public web semantically. This prevents specialized filters from
    # becoming the discovery engine and allows arbitrary topics and locations.
    payloads.append(("web_discovery", _web_discovery(query, location)))

    # Specialized engines add high-confidence structured results when applicable.
    if intent != "web":
        try:
            payloads.append((intent, _specialized_payload(intent, query, location)))
        except Exception as exc:
            app.logger.exception("SMART_SEARCH_SPECIALIZED_ERROR intent=%r query=%r location=%r", intent, query, location)

    results = _dedupe_results([item for _, payload in payloads for item in (payload.get("results") or [])])
    sources = []
    for _, payload in payloads:
        source = _clean(payload.get("source"), 300)
        if source and source not in sources:
            sources.append(source)

    return {
        "configured": True,
        "intent": "web_research" if intent == "web" else intent,
        "intent_scores": intent_scores,
        "query": query,
        "location": location,
        "semantic_queries": _semantic_queries(query),
        "source": " + ".join(sources) or "Smart Search",
        "message": f"Found {len(results)} source-backed result(s) using broad semantic web discovery" + (f" plus {intent} verification." if intent != "web" else "."),
        "count": len(results),
        "results": results,
        "search_details": "Natural-language, location-agnostic semantic discovery first; specialized verification augments discovery instead of blocking it.",
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
    app.logger.warning("SMART_SEARCH_DIAGNOSTIC intent=%r count=%s query=%r location=%r source=%r", payload.get("intent"), payload.get("count", 0), query, location, _clean(payload.get("source"), 300))
    return jsonify(payload)
