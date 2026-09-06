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


def _google_error_message(response):
    try:
        payload = response.json()
    except ValueError:
        return ""

    error = payload.get("error")
    if isinstance(error, dict):
        message = error.get("message")
        if message:
            return _clean(message, 500)

        details = error.get("errors")
        if isinstance(details, list) and details:
            first = details[0] if isinstance(details[0], dict) else {}
            message = first.get("message")
            if message:
                return _clean(message, 500)
    return ""


def _request_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        candidate = forwarded.split(",", 1)[0].strip()
        if candidate:
            return candidate
    return request.remote_addr or ""


def _normalize_custom_search_results(payload):
    results = []
    for item in payload.get("items", []):
        results.append(
            {
                "type": "public_record",
                "title": item.get("title") or "Search result",
                "subtitle": item.get("snippet") or "",
                "url": item.get("link") or "",
                "source": item.get("displayLink") or "Google Programmable Search",
            }
        )
    return results


def _normalize_web_search_results(payload):
    results = []
    for item in payload.get("searchResults", []):
        url = item.get("displayUrl") or ""
        results.append(
            {
                "type": "public_record",
                "title": item.get("title") or "Search result",
                "subtitle": item.get("snippet") or "",
                "url": url,
                "source": item.get("shortenedDisplayUrl") or "Google Web Search Service",
            }
        )
    return results


def _search_public_records(query, location=""):
    custom_api_key = os.environ.get("GOOGLE_SEARCH_API_KEY") or ""
    search_engine_id = os.environ.get("GOOGLE_SEARCH_CX") or ""

    web_api_key = (
        os.environ.get("GOOGLE_WEB_SEARCH_API_KEY")
        or os.environ.get("GOOGLE_SEARCH_API_KEY")
        or ""
    )
    web_client_id = os.environ.get("GOOGLE_WEB_SEARCH_CLIENT_ID") or ""

    custom_configured = bool(custom_api_key and search_engine_id)
    web_configured = bool(web_api_key and web_client_id)

    if not custom_configured and not web_configured:
        return {
            "configured": False,
            "source": "Google Search",
            "message": (
                "Permit/public-record search is not configured. "
                "Set GOOGLE_SEARCH_API_KEY and GOOGLE_SEARCH_CX for Programmable Search, "
                "or GOOGLE_WEB_SEARCH_API_KEY and GOOGLE_WEB_SEARCH_CLIENT_ID for Google's Web Search Service."
            ),
            "results": [],
        }

    text_query = " ".join(part for part in [query, location] if part).strip()
    if not text_query:
        return {
            "configured": True,
            "source": "Google Search",
            "message": "Enter a permit or public-record search.",
            "results": [],
        }

    if web_configured:
        user_ip = _request_ip()
        if not user_ip:
            return {
                "configured": True,
                "source": "Google Web Search Service",
                "message": "Web Search Service requires an end-user IP address, but none was available.",
                "results": [],
            }

        response = requests.get(
            "https://websearchservice.googleapis.com/v1:search",
            headers={"X-Goog-Api-Key": web_api_key},
            params={
                "clientContext.clientId": web_client_id,
                "userContext.ipAddress": user_ip,
                "userContext.regionCode": "US",
                "searchQuery.query": text_query,
                "searchQuery.languageCode": "en",
                "searchQuery.safeSearch": "ON",
                "pageSize": 10,
                "webSearch": "",
            },
            timeout=20,
        )

        if response.ok:
            return {
                "configured": True,
                "source": "Google Web Search Service",
                "message": "",
                "results": _normalize_web_search_results(response.json()),
            }

        error_detail = _google_error_message(response)
        message = f"Google Web Search Service returned HTTP {response.status_code}."
        if error_detail:
            message += f" {error_detail}"
        return {
            "configured": True,
            "source": "Google Web Search Service",
            "message": message,
            "results": [],
        }

    response = requests.get(
        "https://www.googleapis.com/customsearch/v1",
        params={
            "key": custom_api_key,
            "cx": search_engine_id,
            "q": text_query,
            "num": 10,
        },
        timeout=20,
    )

    if not response.ok:
        error_detail = _google_error_message(response)
        message = f"Google Programmable Search returned HTTP {response.status_code}."
        if error_detail:
            message += f" {error_detail}"
        if response.status_code == 403:
            message += (
                " The app is configured, but Google denied this request. "
                "Check the API key's Custom Search API restriction, project/API enablement, billing/quota, "
                "or migrate this search to Google's Web Search Service with GOOGLE_WEB_SEARCH_CLIENT_ID."
            )
        return {
            "configured": True,
            "source": "Google Programmable Search",
            "message": message,
            "results": [],
        }

    return {
        "configured": True,
        "source": "Google Programmable Search",
        "message": "",
        "results": _normalize_custom_search_results(response.json()),
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
    custom_search = bool(
        os.environ.get("GOOGLE_SEARCH_API_KEY")
        and os.environ.get("GOOGLE_SEARCH_CX")
    )
    web_search = bool(
        (os.environ.get("GOOGLE_WEB_SEARCH_API_KEY") or os.environ.get("GOOGLE_SEARCH_API_KEY"))
        and os.environ.get("GOOGLE_WEB_SEARCH_CLIENT_ID")
    )

    return jsonify(
        {
            "jobs": {"configured": True, "source": "Remotive"},
            "businesses": {
                "configured": bool(_places_key()),
                "source": "Google Places",
            },
            "public_records": {
                "configured": custom_search or web_search,
                "source": (
                    "Google Web Search Service"
                    if web_search
                    else "Google Programmable Search"
                ),
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
        event_status = "success"
        if not payload.get("configured"):
            event_status = "not_configured"
        elif payload.get("message") and not payload.get("results"):
            event_status = "error"

        db.session.add(
            AutomationEvent(
                event_type=event_type,
                source=payload.get("source") or "Universal Search",
                status=event_status,
                details=f"mode={mode}; query={query}; location={location}",
            )
        )
        db.session.commit()
    except Exception:
        db.session.rollback()

    return jsonify(payload)
