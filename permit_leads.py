import os
from datetime import datetime, timezone

import requests
from flask import jsonify, request

from app import app


def _clean(value, limit=300):
    return str(value or "").strip()[:limit]


def _google_error_message(response):
    try:
        payload = response.json()
    except ValueError:
        return ""
    error = payload.get("error")
    if isinstance(error, dict):
        return _clean(error.get("message"), 500)
    return ""


def _location_terms(location):
    raw = location.lower().replace(",", " ").split()
    terms = {part for part in raw if len(part) > 2}
    if "va" in raw:
        terms.add("virginia")
    return terms


def _score_result(title, snippet, location, year):
    text = f"{title} {snippet}".lower()
    score = 0

    if "electrical" in text and "permit" in text:
        score += 35
    if any(term in text for term in ("contractor", "applicant", "trade name", "master electrician", "license")):
        score += 25
    if any(term in text for term in ("applied", "application", "submitted", "pending", "in progress", "issued")):
        score += 15
    if str(year) in text:
        score += 10

    location_terms = _location_terms(location)
    if location_terms and any(term in text for term in location_terms):
        score += 15

    return min(score, 100)


def _has_direct_permit_signal(title, snippet):
    text = f"{title} {snippet}".lower()
    has_permit = "electrical" in text and "permit" in text
    has_activity = any(
        term in text
        for term in (
            "contractor",
            "applicant",
            "trade name",
            "master electrician",
            "license",
            "applied",
            "application",
            "submitted",
            "pending",
            "in progress",
            "issued",
            "permit #",
            "permit no",
        )
    )
    return has_permit and has_activity


def _location_matches(title, snippet, location):
    terms = _location_terms(location)
    if not terms:
        return True
    text = f"{title} {snippet}".lower()
    return any(term in text for term in terms)


def _search_google(query, api_key, cx, num=10):
    response = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={"key": api_key, "cx": cx, "q": query, "num": num},
        timeout=20,
    )
    if not response.ok:
        return None, response
    return response.json(), response


@app.route("/api/permit-leads", methods=["POST"])
def permit_leads():
    data = request.get_json(silent=True) or {}
    location = _clean(data.get("location") or "Portsmouth, VA", 200)
    user_query = _clean(data.get("query") or "electrical permits", 200)

    api_key = os.environ.get("GOOGLE_SEARCH_API_KEY") or ""
    cx = os.environ.get("GOOGLE_SEARCH_CX") or ""
    if not api_key or not cx:
        return jsonify(
            {
                "configured": False,
                "message": "Permit Lead Finder needs GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX.",
                "results": [],
            }
        )

    year = datetime.now(timezone.utc).year
    targeted_queries = [
        f'"{location}" "electrical permit" (contractor OR applicant OR "trade name") (applied OR application OR submitted OR pending OR issued) {year}',
        f'"{location}" "electrical permits" (contractor OR "master electrician" OR license) ("in progress" OR issued OR application) {year}',
    ]

    seen = set()
    results = []

    for targeted_query in targeted_queries:
        payload, response = _search_google(targeted_query, api_key, cx)
        if payload is None:
            detail = _google_error_message(response)
            message = f"Google Programmable Search returned HTTP {response.status_code}."
            if detail:
                message += f" {detail}"
            return jsonify({"configured": True, "message": message, "results": []})

        for item in payload.get("items", []):
            title = item.get("title") or "Permit activity"
            snippet = item.get("snippet") or ""
            url = item.get("link") or ""
            if not url or url in seen:
                continue
            if not _has_direct_permit_signal(title, snippet):
                continue
            if not _location_matches(title, snippet, location):
                continue

            seen.add(url)
            score = _score_result(title, snippet, location, year)
            results.append(
                {
                    "type": "permit_lead",
                    "title": title,
                    "subtitle": snippet,
                    "url": url,
                    "source": item.get("displayLink") or "Google Programmable Search",
                    "prospect_score": score,
                    "fit": "High" if score >= 75 else "Medium" if score >= 55 else "Low",
                    "lead_signal": "Direct public evidence of electrical-permit activity",
                    "analysis": (
                        "This result was kept because the public record mentions electrical permitting "
                        "plus contractor/applicant/license or active permit-status language."
                    ),
                }
            )

    results.sort(key=lambda item: item.get("prospect_score", 0), reverse=True)

    return jsonify(
        {
            "configured": True,
            "query": user_query,
            "location": location,
            "source": "Google Programmable Search",
            "count": len(results),
            "message": (
                f"Found {len(results)} evidence-backed electrical permit lead"
                + ("." if len(results) == 1 else "s.")
            ),
            "results": results,
        }
    )
