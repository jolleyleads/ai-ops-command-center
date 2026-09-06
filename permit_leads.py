from datetime import datetime, timezone

from flask import jsonify, request

from app import app
from universal_app import _search_public_records


def _clean(value, limit=300):
    return str(value or "").strip()[:limit]


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


@app.route("/api/permit-leads", methods=["POST"])
def permit_leads():
    data = request.get_json(silent=True) or {}
    location = _clean(data.get("location") or "Portsmouth, VA", 200)
    user_query = _clean(data.get("query") or "electrical permits", 200)
    year = datetime.now(timezone.utc).year

    targeted_queries = [
        f'"electrical permit" contractor applicant submitted pending issued {year}',
        f'"electrical permits" contractor "master electrician" application issued {year}',
    ]

    seen = set()
    results = []
    source_name = "Public Record Search"

    for targeted_query in targeted_queries:
        payload = _search_public_records(targeted_query, location)
        source_name = payload.get("source") or source_name

        if not payload.get("configured"):
            return jsonify(
                {
                    "configured": False,
                    "message": payload.get("message") or "Public-record search is not configured.",
                    "results": [],
                }
            )

        if payload.get("message") and not payload.get("results"):
            return jsonify(
                {
                    "configured": True,
                    "message": payload.get("message"),
                    "source": source_name,
                    "results": [],
                }
            )

        for item in payload.get("results", []):
            title = item.get("title") or "Permit activity"
            snippet = item.get("subtitle") or ""
            url = item.get("url") or ""

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
                    "source": item.get("source") or source_name,
                    "prospect_score": score,
                    "fit": "High" if score >= 75 else "Medium" if score >= 55 else "Low",
                    "lead_signal": "Direct public evidence of electrical-permit activity",
                    "analysis": (
                        "Kept because the public result mentions electrical permitting plus "
                        "contractor/applicant/license or active permit-status language."
                    ),
                }
            )

    results.sort(key=lambda item: item.get("prospect_score", 0), reverse=True)

    return jsonify(
        {
            "configured": True,
            "query": user_query,
            "location": location,
            "source": source_name,
            "count": len(results),
            "message": (
                f"Found {len(results)} evidence-backed electrical permit lead"
                + ("." if len(results) == 1 else "s.")
            ),
            "results": results,
        }
    )
