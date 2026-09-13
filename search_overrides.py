import os

import requests
from flask import jsonify, request

from app import AutomationEvent, app, db
import local_jobs
from universal_app import _search_public_records


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _places_key():
    return (
        os.environ.get("GOOGLE_PLACES_API_KEY")
        or os.environ.get("GOOGLE_MAPS_API_KEY")
        or ""
    )


def _google_error_message(response):
    try:
        payload = response.json()
    except ValueError:
        return ""
    error = payload.get("error") if isinstance(payload, dict) else None
    if not isinstance(error, dict):
        return ""
    return _clean(error.get("message"), 700)


def _search_google_places(query, location=""):
    api_key = _places_key()
    if not api_key:
        return {
            "configured": False,
            "source": "Google Places",
            "message": "Google Places is not configured on this service. Set GOOGLE_PLACES_API_KEY or GOOGLE_MAPS_API_KEY.",
            "results": [],
        }

    text_query = " ".join(part for part in [_clean(query, 300), _clean(location, 200)] if part).strip()
    if not text_query:
        return {
            "configured": True,
            "source": "Google Places",
            "message": "Enter a business or contractor search and location.",
            "results": [],
        }

    try:
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
            json={
                "textQuery": text_query,
                "maxResultCount": 20,
                "includePureServiceAreaBusinesses": True,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return {
            "configured": True,
            "source": "Google Places",
            "message": f"Google Places connection failed: {_clean(exc, 300)}",
            "results": [],
        }

    if not response.ok:
        detail = _google_error_message(response)
        message = f"Google Places returned HTTP {response.status_code}."
        if detail:
            message += f" {detail}"
        return {
            "configured": True,
            "source": "Google Places",
            "message": message,
            "results": [],
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "configured": True,
            "source": "Google Places",
            "message": "Google Places returned an unreadable response.",
            "results": [],
        }

    results = []
    seen_ids = set()
    for place in payload.get("places") or []:
        place_id = _clean(place.get("id"), 300)
        if place_id and place_id in seen_ids:
            continue
        if place_id:
            seen_ids.add(place_id)

        display_name = place.get("displayName") or {}
        name = _clean(display_name.get("text"), 300) if isinstance(display_name, dict) else ""
        if not name:
            continue

        status = _clean(place.get("businessStatus"), 80)
        if status and status not in {"OPERATIONAL", "CLOSED_TEMPORARILY"}:
            continue

        results.append({
            "type": "business",
            "id": place_id,
            "title": name,
            "subtitle": _clean(place.get("formattedAddress"), 500),
            "phone": _clean(place.get("nationalPhoneNumber"), 100),
            "rating": place.get("rating"),
            "review_count": place.get("userRatingCount"),
            "status": status,
            "website": _clean(place.get("websiteUri"), 1200),
            "url": _clean(place.get("googleMapsUri") or place.get("websiteUri"), 1200),
            "types": place.get("types") or [],
            "source": "Google Places",
            "verification": "VERIFIED_GOOGLE_PLACES",
        })

    return {
        "configured": True,
        "source": "Google Places",
        "message": f"Found {len(results)} Google Places business result" + ("." if len(results) == 1 else "s."),
        "results": results,
    }


def _record_event(event_type, source, status, mode, query, location):
    try:
        db.session.add(AutomationEvent(
            event_type=event_type,
            source=source or "Universal Search",
            status=status,
            details=f"mode={mode}; query={query}; location={location}",
        ))
        db.session.commit()
    except Exception:
        db.session.rollback()


def universal_search_override():
    data = (request.get_json(silent=True) or {}) if request.method == "POST" else request.args
    mode = _clean(data.get("mode") or "jobs", 40).lower()
    query = _clean(data.get("query") or data.get("keyword") or "", 300)
    location = _clean(data.get("location") or "", 200)

    if mode in ("job", "jobs"):
        return local_jobs.local_jobs()

    if mode in ("business", "businesses", "contractor", "contractors"):
        payload = _search_google_places(query, location)
        event_type = "universal_business_search"
    elif mode in ("permit", "permits", "public_record", "public_records", "records"):
        payload = _search_public_records(query, location)
        event_type = "universal_public_record_search"
    else:
        return jsonify({"error": "Unsupported search mode"}), 400

    payload.update({
        "mode": mode,
        "query": query,
        "location": location,
        "count": len(payload.get("results") or []),
    })

    if not payload.get("configured"):
        event_status = "not_configured"
    elif payload.get("message") and not payload.get("results"):
        event_status = "error"
    else:
        event_status = "success"

    _record_event(event_type, payload.get("source") or "Universal Search", event_status, mode, query, location)
    return jsonify(payload)


def universal_search_capabilities_override():
    brave_search = bool(os.environ.get("BRAVE_SEARCH_API_KEY"))
    google_api_key_present = bool(os.environ.get("GOOGLE_SEARCH_API_KEY"))
    google_cx_present = bool(os.environ.get("GOOGLE_SEARCH_CX"))
    custom_search = google_api_key_present and google_cx_present
    web_search = bool(
        (os.environ.get("GOOGLE_WEB_SEARCH_API_KEY") or os.environ.get("GOOGLE_SEARCH_API_KEY"))
        and os.environ.get("GOOGLE_WEB_SEARCH_CLIENT_ID")
    )

    if brave_search:
        public_source = "Brave Search"
    elif web_search:
        public_source = "Google Web Search Service"
    elif custom_search:
        public_source = "Google Programmable Search"
    else:
        public_source = "Public Record Search"

    return jsonify({
        "jobs": {"configured": brave_search or custom_search or web_search, "source": "Verified Local Job Search"},
        "businesses": {"configured": bool(_places_key()), "source": "Google Places"},
        "public_records": {
            "configured": brave_search or custom_search or web_search,
            "source": public_source,
            "google_search_api_key_present": google_api_key_present,
            "google_search_cx_present": google_cx_present,
        },
    })


app.view_functions["universal_search"] = universal_search_override
app.view_functions["universal_search_capabilities"] = universal_search_capabilities_override
