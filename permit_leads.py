import re
from datetime import datetime, timezone

from flask import jsonify, request

from app import app
from universal_app import _search_businesses, _search_public_records


def _clean(value, limit=300):
    return str(value or "").strip()[:limit]


def _location_parts(location):
    parts = [part.strip().lower() for part in str(location or "").split(",") if part.strip()]
    city = parts[0] if parts else ""
    state = parts[1] if len(parts) > 1 else ""
    return city, state


def _strict_location_matches(title, snippet, location):
    city, _state = _location_parts(location)
    if not city:
        return True
    text = f"{title} {snippet}".lower()
    return city in text


def _extract_contractor_name(title, snippet):
    text = f"{title}\n{snippet}"
    patterns = [
        r"(?:electrical\s+)?contractor\s*(?:name)?\s*[:\-]\s*([^\n|;,]{3,100})",
        r"applicant\s*(?:name)?\s*[:\-]\s*([^\n|;,]{3,100})",
        r"trade\s+name\s*[:\-]\s*([^\n|;,]{3,100})",
        r"company\s*(?:name)?\s*[:\-]\s*([^\n|;,]{3,100})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            name = _clean(match.group(1), 100).strip(" .:-")
            if len(name) >= 3:
                return name
    return ""


def _has_active_permit_signal(title, snippet):
    text = f"{title} {snippet}".lower()
    return (
        "electrical" in text
        and "permit" in text
        and any(
            term in text
            for term in (
                "applied",
                "application",
                "submitted",
                "pending",
                "in progress",
                "issued",
                "permit #",
                "permit no",
                "applicant",
                "contractor",
                "trade name",
            )
        )
    )


def _score_result(title, snippet, location, year, contractor_name, enriched):
    text = f"{title} {snippet}".lower()
    score = 0
    if "electrical" in text and "permit" in text:
        score += 30
    if any(term in text for term in ("applied", "application", "submitted", "pending", "in progress", "issued")):
        score += 20
    if contractor_name:
        score += 25
    if str(year) in text:
        score += 10
    if _strict_location_matches(title, snippet, location):
        score += 10
    if enriched:
        score += 5
    return min(score, 100)


def _enrich_contractor(contractor_name, location):
    if not contractor_name:
        return {}

    payload = _search_businesses(contractor_name, location)
    if not payload.get("configured") or not payload.get("results"):
        return {}

    target = contractor_name.lower()
    for business in payload.get("results", []):
        business_name = str(business.get("title") or "").lower()
        if target == business_name or target in business_name or business_name in target:
            return business
    return {}


@app.route("/api/permit-leads", methods=["POST"])
def permit_leads():
    data = request.get_json(silent=True) or {}
    location = _clean(data.get("location") or "Portsmouth, VA", 200)
    user_query = _clean(data.get("query") or "electrical permit activity", 200)
    year = datetime.now(timezone.utc).year

    city, state = _location_parts(location)
    location_phrase = ", ".join(part for part in [city.title(), state.upper()] if part)

    targeted_queries = [
        f'"{location_phrase}" "electrical permit" contractor applicant submitted pending issued {year}',
        f'"{city.title()}" "electrical permits" contractor applicant application issued {year}',
    ]

    seen = set()
    results = []
    source_name = "Public Record Search"

    for targeted_query in targeted_queries:
        payload = _search_public_records(targeted_query, "")
        source_name = payload.get("source") or source_name

        if not payload.get("configured"):
            return jsonify({
                "configured": False,
                "message": payload.get("message") or "Public-record search is not configured.",
                "results": [],
            })

        if payload.get("message") and not payload.get("results"):
            return jsonify({
                "configured": True,
                "message": payload.get("message"),
                "source": source_name,
                "results": [],
            })

        for item in payload.get("results", []):
            title = item.get("title") or "Permit activity"
            snippet = item.get("subtitle") or ""
            url = item.get("url") or ""

            if not url or url in seen:
                continue
            if not _strict_location_matches(title, snippet, location):
                continue
            if not _has_active_permit_signal(title, snippet):
                continue

            contractor_name = _extract_contractor_name(title, snippet)
            if not contractor_name:
                continue

            enrichment = _enrich_contractor(contractor_name, location)
            seen.add(url)

            score = _score_result(
                title,
                snippet,
                location,
                year,
                contractor_name,
                bool(enrichment),
            )

            results.append({
                "type": "permit_lead",
                "title": contractor_name,
                "subtitle": snippet,
                "url": url,
                "source": item.get("source") or source_name,
                "prospect_score": score,
                "fit": "High" if score >= 80 else "Medium" if score >= 65 else "Low",
                "lead_signal": "Named contractor/applicant in Portsmouth electrical-permit activity",
                "analysis": "Qualified only because the public search result names a contractor/applicant and explicitly matches Portsmouth electrical-permit activity.",
                "phone": enrichment.get("phone") or "",
                "website": enrichment.get("website") or "",
                "rating": enrichment.get("rating"),
                "review_count": enrichment.get("review_count"),
                "business_address": enrichment.get("subtitle") or "",
                "verified_business": bool(enrichment),
            })

    results.sort(key=lambda item: item.get("prospect_score", 0), reverse=True)

    return jsonify({
        "configured": True,
        "query": user_query,
        "location": location,
        "source": source_name,
        "count": len(results),
        "message": (
            f"Found {len(results)} named Portsmouth electrical permit contractor lead"
            + ("." if len(results) == 1 else "s.")
        ),
        "results": results,
    })
