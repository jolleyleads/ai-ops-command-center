import os
from urllib.parse import urlparse

import requests


GOOGLE_PLACES_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_FIELDS = ",".join([
    "places.id",
    "places.displayName",
    "places.formattedAddress",
    "places.addressComponents",
    "places.nationalPhoneNumber",
    "places.websiteUri",
    "places.googleMapsUri",
    "places.rating",
    "places.userRatingCount",
    "places.businessStatus",
    "places.types",
])


def google_places_configured():
    return bool(os.getenv("GOOGLE_PLACES_API_KEY", "").strip())


def search_google_places(industry, location, limit=10):
    api_key = os.getenv("GOOGLE_PLACES_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("GOOGLE_PLACES_API_KEY is not configured")

    industry = str(industry or "").strip()
    location = str(location or "").strip()
    if not industry:
        raise ValueError("industry is required")
    if not location:
        raise ValueError("location is required")

    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(1, min(limit, 20))

    response = requests.post(
        GOOGLE_PLACES_SEARCH_URL,
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": GOOGLE_PLACES_FIELDS,
        },
        json={
            "textQuery": f"{industry} in {location}",
            "pageSize": limit,
            "includePureServiceAreaBusinesses": True,
        },
        timeout=20,
    )

    if response.status_code >= 400:
        detail = _google_error_message(response)
        raise RuntimeError(
            f"Google Places request failed ({response.status_code}): {detail}"
        )

    payload = response.json()
    return [normalize_google_place(place, industry) for place in payload.get("places", [])]


def normalize_google_place(place, industry):
    display_name = place.get("displayName") or {}
    company = str(display_name.get("text") or "").strip()
    website = str(place.get("websiteUri") or "").strip()
    phone = str(place.get("nationalPhoneNumber") or "").strip()
    maps_url = str(place.get("googleMapsUri") or "").strip()
    place_id = str(place.get("id") or "").strip()
    rating = place.get("rating")
    review_count = _safe_int(place.get("userRatingCount"), 0)
    city, state = _city_state(place.get("addressComponents") or [])

    evidence = []
    if place_id:
        evidence.append(f"Google Places verified listing: {place_id}")
    if phone:
        evidence.append("Public phone listed on Google Places")
    if website:
        evidence.append(f"Official website linked from Google Places: {_website_host(website)}")
    if review_count:
        if rating is None:
            evidence.append(f"Google Places shows {review_count} public reviews")
        else:
            evidence.append(f"Google Places rating {rating} from {review_count} reviews")

    opportunities = []
    if phone:
        opportunities.append("missed-call text-back and lead capture")
    if website:
        opportunities.append("website lead follow-up automation")
    if review_count >= 50:
        opportunities.append("review-request and reputation follow-up")

    # Review volume can support a lead-volume signal, but we do not infer hiring,
    # growth, CRM pain, or manual follow-up without direct evidence.
    high_lead_volume_signal = review_count >= 150

    return {
        "company": company,
        "website": website,
        "email": "",
        "phone": phone,
        "contact_name": "",
        "contact_title": "",
        "source": "google_places",
        "source_url": maps_url,
        "city": city,
        "state": state,
        "industry": str(industry or "").strip(),
        "hiring_signal": False,
        "hiring_roles": [],
        "review_count": review_count,
        "google_rating": rating,
        "locations_count": 1,
        "high_lead_volume_signal": high_lead_volume_signal,
        "manual_followup_signal": False,
        "crm_need_signal": False,
        "growth_signal": False,
        "automation_opportunities": opportunities,
        "evidence": evidence,
        "status": "new",
        "google_place_id": place_id,
        "business_status": place.get("businessStatus"),
        "types": place.get("types") or [],
        "formatted_address": place.get("formattedAddress") or "",
    }


def _city_state(components):
    city = ""
    state = ""
    for component in components:
        types = component.get("types") or []
        if not city and "locality" in types:
            city = str(component.get("longText") or component.get("shortText") or "").strip()
        if not city and "postal_town" in types:
            city = str(component.get("longText") or component.get("shortText") or "").strip()
        if "administrative_area_level_1" in types:
            state = str(component.get("shortText") or component.get("longText") or "").strip()
    return city, state


def _website_host(url):
    try:
        return urlparse(url).netloc or url
    except Exception:
        return url


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _google_error_message(response):
    try:
        payload = response.json()
        error = payload.get("error") or {}
        return str(error.get("message") or payload)[:500]
    except Exception:
        return response.text[:500]
