import html
import os
import re
from urllib.parse import urljoin, urlparse

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

EMAIL_RE = re.compile(
    r"(?i)(?<![A-Z0-9._%+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9._%+-])"
)
CONTACT_PATHS = ("/contact", "/contact-us", "/about", "/about-us")
PREFERRED_LOCAL_PARTS = (
    "info",
    "contact",
    "office",
    "hello",
    "sales",
    "service",
    "support",
    "admin",
)
REJECTED_EMAIL_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
)


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
    prospects = []
    for place in payload.get("places", []):
        prospect = normalize_google_place(place, industry)
        if prospect.get("website"):
            enrichment = discover_public_email(prospect["website"])
            if enrichment.get("email"):
                prospect["email"] = enrichment["email"]
                prospect["email_source_url"] = enrichment["source_url"]
                prospect["evidence"].append(
                    f"Public email listed on official website: {enrichment['source_url']}"
                )
        prospects.append(prospect)
    return prospects


def discover_public_email(website):
    """Find a public email on the official website without generating or guessing one."""
    website = str(website or "").strip()
    if not website:
        return {"email": "", "source_url": ""}

    root = _root_url(website)
    if not root:
        return {"email": "", "source_url": ""}

    root_host = _normalized_host(root)
    urls = [website]
    for path in CONTACT_PATHS:
        urls.append(urljoin(root + "/", path.lstrip("/")))

    seen = set()
    candidates = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        if _normalized_host(url) != root_host:
            continue

        text = _fetch_public_page(url)
        if not text:
            continue

        for email in _extract_emails(text):
            candidates.append((email, url))

    if not candidates:
        return {"email": "", "source_url": ""}

    candidates.sort(key=lambda item: _email_rank(item[0], root_host))
    email, source_url = candidates[0]
    return {"email": email, "source_url": source_url}


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


def _fetch_public_page(url):
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AI-Ops-Prospect-Enrichment/1.0)"
            },
            timeout=10,
            allow_redirects=True,
        )
    except requests.RequestException:
        return ""

    if not response.ok:
        return ""
    content_type = str(response.headers.get("Content-Type") or "").lower()
    if "html" not in content_type and "text" not in content_type:
        return ""
    return html.unescape(response.text[:750000])


def _extract_emails(text):
    found = []
    seen = set()
    for match in EMAIL_RE.findall(text or ""):
        email = match.strip().lower().rstrip(".,;:)")
        if email in seen:
            continue
        if any(email.endswith(suffix) for suffix in REJECTED_EMAIL_SUFFIXES):
            continue
        if "example.com" in email or "example.org" in email or "example.net" in email:
            continue
        seen.add(email)
        found.append(email)
    return found


def _email_rank(email, root_host):
    local, _, domain = email.partition("@")
    domain_host = domain.lower().removeprefix("www.")
    same_domain = domain_host == root_host or domain_host.endswith("." + root_host)
    preferred = local.lower() in PREFERRED_LOCAL_PARTS
    role_prefix = any(local.lower().startswith(prefix) for prefix in PREFERRED_LOCAL_PARTS)
    return (
        0 if same_domain else 1,
        0 if preferred else 1,
        0 if role_prefix else 1,
        len(email),
        email,
    )


def _root_url(url):
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return ""
        return f"{parsed.scheme}://{parsed.netloc}"
    except Exception:
        return ""


def _normalized_host(url):
    try:
        return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:
        return ""


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
