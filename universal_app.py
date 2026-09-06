import os
import requests
from flask import jsonify, request

from app import app, db, AutomationEvent, search_remote_jobs


def _clean(value, limit=300):
    return str(value or "").strip()[:limit]


def _places_key():
    return (
        os.environ.get("GOOGLE_PLACES_API_KEY")
        or os.environ.get("GOOGLE_MAPS_API_KEY")
        or ""
    )


def _search_businesses(query, location=""):
    api_key = _places_key()
    if not api_key:
        return {
            "configured": False,
            "source": "Google Places",
            "message": (
                "Business/contractor search is ready, but a Google Places key is not configured. "
                "Set GOOGLE_PLACES_API_KEY or GOOGLE_MAPS_API_KEY on Render."
            ),
            "results": [],
        }

    text_query = " ".join(part for part in [query, location] if part).strip()
    if not text_query:
        return {
            "configured": True,
            "source": "Google Places",
            "message": "Enter a business or contractor search.",
            "results": [],
        }

    response = requests.post(
        "https://places.googleapis.com/v1/places:searchText",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": (
                "places.id,places.displayName,places.formattedAddress,"
                "places.websiteUri,places.googleMapsUri,places.nationalPhoneNumber,"
                "places.rating,places.userRatingCount,places.businessStatus,places.types"
            ),
        },
        json={"textQuery": text_query, "maxResultCount": 20},
        timeout=20,
    )

    if not response.ok:
        return {
            "configured": True,
            "source": "Google Places",
            "message": f"Google Places returned HTTP {response.status_code}.",
            "results": [],
        }

    results = []
    for place in response.json().get("places", []):
        name = (place.get("displayName") or {}).get("text") or "Unknown business"
        results.append(
            {
                "type": "business",
                "id": place.get("id") or "",
                "title": name,
                "subtitle": place.get("formattedAddress") or "",
                "phone": place.get("nationalPhoneNumber") or "",
                "rating": place.get("rating"),
                "review_count": place.get("userRatingCount"),
                "status": place.get("businessStatus") or "",
                "website": place.get("websiteUri") or "",
                "url": place.get("googleMapsUri") or place.get("websiteUri") or "",
                "source": "Google Places",
            }
        )

    return {
        "configured": True,
        "source": "Google Places",
        "message": "",
        "results": results,
    }


def _search_public_records(query, location=""):
    api_key = os.environ.get("GOOGLE_SEARCH_API_KEY") or ""
    search_engine_id = os.environ.get("GOOGLE_SEARCH_CX") or ""

    if not api_key or not search_engine_id:
        return {
            "configured": False,
            "source": "Google Programmable Search",
            "message": (
                "Permit/public-record search is wired safely but its web-search source is not configured. "
                "Set GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX on Render to activate it."
            ),
            "results": [],
        }

    text_query = " ".join(part for part in [query, location] if part).strip()
    if not text_query:
        return {
            "configured": True,
            "source": "Google Programmable Search",
            "message": "Enter a permit or public-record search.",
            "results": [],
        }

    response = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": api_key,
            "cx": search_engine_id,
            "q": text_query,
            "num": 10,
        },
        timeout=20,
    )

    if not response.ok:
        return {
            "configured": True,
            "source": "Google Programmable Search",
            "message": f"Public-record search returned HTTP {response.status_code}.",
            "results": [],
        }

    results = []
    for item in response.json().get("items", []):
        results.append(
            {
                "type": "public_record",
                "title": item.get("title") or "Search result",
                "subtitle": item.get("snippet") or "",
                "url": item.get("link") or "",
                "source": item.get("displayLink") or "Google Programmable Search",
            }
        )

    return {
        "configured": True,
        "source": "Google Programmable Search",
        "message": "",
        "results": results,
    }


def _normalize_jobs(keyword):
    rows = []
    for job in search_remote_jobs(keyword):
        rows.append(
            {
                "type": "job",
                "id": job.get("id") or "",
                "title": job.get("title") or "Unknown title",
                "subtitle": " | ".join(
                    part
                    for part in [job.get("company"), job.get("location")]
                    if part
                ),
                "url": job.get("url") or "",
                "source": job.get("source") or "",
                "status": job.get("status") or "",
                "error": job.get("error") or "",
            }
        )
    return rows


@app.route("/api/universal-search/capabilities")
def universal_search_capabilities():
    return jsonify(
        {
            "jobs": {"configured": True, "source": "Remotive"},
            "businesses": {
                "configured": bool(_places_key()),
                "source": "Google Places",
            },
            "public_records": {
                "configured": bool(
                    os.environ.get("GOOGLE_SEARCH_API_KEY")
                    and os.environ.get("GOOGLE_SEARCH_CX")
                ),
                "source": "Google Programmable Search",
            },
        }
    )


@app.route("/api/universal-search", methods=["GET", "POST"])
def universal_search():
    data = request.get_json(silent=True) or {} if request.method == "POST" else request.args

    mode = _clean(data.get("mode") or "jobs", 40).lower()
    query = _clean(data.get("query") or data.get("keyword") or "", 300)
    location = _clean(data.get("location") or "", 200)

    if mode in ("job", "jobs"):
        keyword = query or "machine learning"
        payload = {
            "configured": True,
            "source": "Remotive",
            "message": "",
            "results": _normalize_jobs(keyword),
        }
        event_type = "universal_job_search"
    elif mode in ("business", "businesses", "contractor", "contractors"):
        payload = _search_businesses(query, location)
        event_type = "universal_business_search"
    elif mode in ("permit", "permits", "public_record", "public_records", "records"):
        payload = _search_public_records(query, location)
        event_type = "universal_public_record_search"
    else:
        return jsonify({"error": "Unsupported search mode"}), 400

    payload.update(
        {
            "mode": mode,
            "query": query,
            "location": location,
            "count": len(payload.get("results") or []),
        }
    )

    try:
        db.session.add(
            AutomationEvent(
                event_type=event_type,
                source=payload.get("source") or "Universal Search",
                status="success" if payload.get("configured") else "not_configured",
                details=f"mode={mode}; query={query}; location={location}",
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(payload)
