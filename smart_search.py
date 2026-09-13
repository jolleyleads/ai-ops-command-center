from flask import jsonify, request

from app import app
import contractor_intent
import local_jobs
from universal_app import _search_public_records


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _detect_intent(query):
    text = _clean(query, 1000).lower()
    permit_terms = ("permit", "permits", "public record", "inspection", "license record", "building record")
    contractor_terms = ("contractor", "electrician", "qualifier", "qualifying agent", "master electrician", "pull permits", "permit puller")
    job_terms = ("job", "jobs", "hiring", "career", "position", "opening", "engineer", "developer", "employment")

    scores = {
        "permits": sum(1 for term in permit_terms if term in text),
        "contractors": sum(1 for term in contractor_terms if term in text),
        "jobs": sum(1 for term in job_terms if term in text),
    }
    if "master electrician" in text or "qualifying agent" in text or "permit puller" in text or "pull permits" in text:
        scores["contractors"] += 3
    if "permit" in text and any(term in text for term in ("pulled", "issued", "record", "recent", "city", "county")):
        scores["permits"] += 3
    if any(term in text for term in ("machine learning engineer", "ai engineer", "automation engineer", "llm engineer")):
        scores["jobs"] += 3

    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return "web", scores
    return best, scores


def _job_payload(query, location):
    # Reuse the verified local-jobs implementation without changing its scoring/search logic.
    with app.test_request_context("/api/local-jobs", method="POST", json={"query": query, "location": location}):
        response = local_jobs.local_jobs()
    if isinstance(response, tuple):
        response = response[0]
    return response.get_json() if hasattr(response, "get_json") else {"configured": True, "results": [], "message": "Job search returned no readable response."}


def _smart_search(query, location):
    intent, intent_scores = _detect_intent(query)

    if intent == "contractors":
        payload = contractor_intent._contractor_intent_search(query, location)
    elif intent == "jobs":
        payload = _job_payload(query, location)
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
            "contractors": "Google Places discovery plus independent Brave and Google evidence verification.",
            "jobs": "Verified local job search with source, location, freshness, and quality filtering.",
            "permits": "Public-record/web search using configured authoritative search providers.",
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
