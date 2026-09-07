import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import jsonify, request

from app import app
from universal_app import _search_businesses, _search_public_records


ALLOWED_JOB_DOMAINS = {
    "indeed.com": "Indeed",
    "www.indeed.com": "Indeed",
    "ziprecruiter.com": "ZipRecruiter",
    "www.ziprecruiter.com": "ZipRecruiter",
    "linkedin.com": "LinkedIn",
    "www.linkedin.com": "LinkedIn",
}

DIRECT_NEED_SIGNALS = (
    "master electrician",
    "electrical qualifier",
    "qualifying agent",
    "qualifying individual",
    "qualifying party",
    "qualifying electrician",
    "license qualifier",
    "license holder",
    "licensed electrical contractor",
    "responsible managing employee",
    "responsible managing officer",
    "responsible managing individual",
    "permit pulling",
    "pull permits",
    "pull electrical permits",
    "electrical permit",
    "electrical permits",
)

WEAK_SIGNALS = (
    "journeyman electrician",
    "electrician",
    "electrical technician",
    "electrical helper",
    "apprentice electrician",
)

NEGATIVE_SIGNALS = (
    "staffing agency",
    "recruiting agency",
    "confidential employer",
    "company confidential",
)



def _clean(value, limit=500):
    return str(value or "").strip()[:limit]



def _domain(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("m."):
        host = host[2:]
    return host



def _source_name(url, fallback=""):
    host = _domain(url)
    if host in ALLOWED_JOB_DOMAINS:
        return ALLOWED_JOB_DOMAINS[host]
    return _clean(fallback, 120) or host or "Web Search"



def _normalize_company_name(value):
    text = _clean(value, 200).lower()
    text = re.sub(r"\b(incorporated|corporation|company|limited|llc|l\.l\.c\.|inc\.?|corp\.?|co\.?|ltd\.?)\b", "", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())



def _company_names_match(left, right):
    a = _normalize_company_name(left)
    b = _normalize_company_name(right)
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 6 and a in b:
        return True
    if len(b) >= 6 and b in a:
        return True
    return False



def _location_terms(location):
    raw = _clean(location, 200).lower()
    return [part.strip() for part in raw.split(",") if part.strip()]



def _location_matches(title, snippet, location):
    terms = _location_terms(location)
    if not terms:
        return False
    haystack = f"{title} {snippet}".lower()
    city_or_primary = terms[0]
    if city_or_primary not in haystack:
        return False
    if len(terms) >= 2:
        state = terms[1]
        if len(state) > 2 and state not in haystack:
            # Full state names are useful but not mandatory because many listings use abbreviations.
            pass
    return True



def _direct_signals(title, snippet):
    text = f"{title} {snippet}".lower()
    return [signal for signal in DIRECT_NEED_SIGNALS if signal in text]



def _weak_only(title, snippet):
    text = f"{title} {snippet}".lower()
    return any(signal in text for signal in WEAK_SIGNALS) and not _direct_signals(title, snippet)



def _has_negative_signal(title, snippet):
    text = f"{title} {snippet}".lower()
    return any(signal in text for signal in NEGATIVE_SIGNALS)



def _extract_company_from_title(title):
    raw = _clean(title, 300)
    if not raw:
        return ""

    cleaned = re.sub(r"\s*\|\s*(Indeed|ZipRecruiter|LinkedIn).*$", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+-\s+(Indeed|ZipRecruiter|LinkedIn).*$", "", cleaned, flags=re.IGNORECASE)

    separators = [" - ", " | ", " at "]
    pieces = None
    for separator in separators:
        if separator in cleaned:
            pieces = [piece.strip() for piece in cleaned.split(separator) if piece.strip()]
            break

    if not pieces or len(pieces) < 2:
        return ""

    # Most indexed job-result titles are role - company - location, or role at company.
    # Only accept a middle/last token when it is not obviously a location or job board.
    candidates = pieces[1:]
    for candidate in candidates:
        lower = candidate.lower()
        if lower in {"indeed", "ziprecruiter", "linkedin"}:
            continue
        if re.fullmatch(r"[a-z .'-]+,\s*[a-z]{2}", lower):
            continue
        if len(candidate) >= 3:
            return candidate[:160]
    return ""



def _extract_company_from_snippet(snippet):
    text = _clean(snippet, 800)
    patterns = (
        r"(?:company|employer)\s*[:\-]\s*([^|;,\n]{3,120})",
        r"(?:at|with)\s+([A-Z][A-Za-z0-9&' .\-]{2,100})(?:\s+in\s+|\s+-\s+|\.|,)",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _clean(match.group(1), 160).strip(" .:-")
    return ""



def _extract_company(title, snippet):
    return _extract_company_from_title(title) or _extract_company_from_snippet(snippet)



def _verify_company(company_name, location):
    if not company_name:
        return {}, "company_not_extractable"

    payload = _search_businesses(company_name, location)
    if not payload.get("configured"):
        return {}, "business_verification_not_configured"

    matches = []
    for business in payload.get("results") or []:
        if _company_names_match(company_name, business.get("title")):
            matches.append(business)

    if len(matches) != 1:
        if not matches:
            return {}, "company_not_verified"
        return {}, "company_match_ambiguous"

    business = matches[0]
    address = _clean(business.get("subtitle"), 500).lower()
    primary = (_location_terms(location) or [""])[0]
    if primary and primary not in address:
        return {}, "verified_company_location_mismatch"

    return business, "verified"



def _job_query_variants(location):
    year = datetime.now(timezone.utc).year
    location_phrase = _clean(location, 160)
    direct_terms = '"master electrician" OR "qualifying agent" OR "electrical qualifier" OR "license holder" OR "permit pulling"'
    return [
        ("Indeed", f'site:indeed.com {direct_terms} "{location_phrase}" {year}'),
        ("ZipRecruiter", f'site:ziprecruiter.com {direct_terms} "{location_phrase}" {year}'),
        ("LinkedIn", f'site:linkedin.com/jobs {direct_terms} "{location_phrase}" {year}'),
        ("Web", f'{direct_terms} "{location_phrase}" electrical contractor hiring {year}'),
    ]



def _evaluate_item(item, requested_source, location):
    title = _clean(item.get("title"), 300)
    snippet = _clean(item.get("subtitle"), 1200)
    url = _clean(item.get("url"), 1200)
    source = _source_name(url, item.get("source") or requested_source)

    rejection = None
    if not url:
        rejection = "missing_source_url"
    elif not title:
        rejection = "missing_title"
    elif not _location_matches(title, snippet, location):
        rejection = "location_not_explicit"
    elif _has_negative_signal(title, snippet):
        rejection = "intermediary_or_confidential_employer"
    elif _weak_only(title, snippet):
        rejection = "generic_electrician_hiring_not_direct_license_need"

    signals = _direct_signals(title, snippet)
    if not rejection and not signals:
        rejection = "no_direct_license_or_permit_need_signal"

    company_name = _extract_company(title, snippet) if not rejection else ""
    verification = {}
    verification_status = "not_attempted"

    if not rejection:
        verification, verification_status = _verify_company(company_name, location)
        if verification_status != "verified":
            rejection = verification_status

    if rejection:
        return {
            "accepted": False,
            "reason": rejection,
            "source": source,
            "title": title,
            "url": url,
        }

    score = 70
    score += min(15, 5 * len(signals))
    if verification.get("website"):
        score += 5
    if verification.get("phone"):
        score += 5
    if verification.get("status") == "OPERATIONAL":
        score += 5
    score = min(score, 100)

    return {
        "accepted": True,
        "verification_status": "VERIFIED",
        "confidence": "high" if score >= 90 else "medium",
        "prospect_score": score,
        "source": source,
        "source_url": url,
        "source_title": title,
        "source_snippet": snippet,
        "company": verification.get("title") or company_name,
        "location": location,
        "direct_signals": signals,
        "evidence": {
            "job_listing": {
                "title": title,
                "snippet": snippet,
                "url": url,
                "source": source,
            },
            "company_verification": {
                "name": verification.get("title") or "",
                "address": verification.get("subtitle") or "",
                "website": verification.get("website") or "",
                "phone": verification.get("phone") or "",
                "business_status": verification.get("status") or "",
                "google_maps_url": verification.get("url") or "",
            },
        },
        "lead_signal": "Direct licensed-electrician/qualifier/permit responsibility signal in a current indexed hiring result, cross-checked to one matching business record.",
    }


@app.route("/api/verified-job-signals", methods=["POST"])
def verified_job_signals():
    data = request.get_json(silent=True) or {}
    location = _clean(data.get("location"), 200)

    if not location:
        return jsonify({
            "configured": True,
            "message": "Enter a city/state location, for example: Charlotte, NC.",
            "results": [],
        }), 400

    seen_urls = set()
    accepted = []
    rejected = []
    sources_run = []

    for requested_source, query in _job_query_variants(location):
        payload = _search_public_records(query, "")
        sources_run.append({
            "requested_source": requested_source,
            "search_source": payload.get("source") or "",
            "configured": bool(payload.get("configured")),
            "message": payload.get("message") or "",
        })

        if not payload.get("configured"):
            return jsonify({
                "configured": False,
                "message": payload.get("message") or "Web search is not configured.",
                "results": [],
                "sources_run": sources_run,
            }), 503

        for item in payload.get("results") or []:
            url = _clean(item.get("url"), 1200)
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)

            evaluated = _evaluate_item(item, requested_source, location)
            if evaluated.get("accepted"):
                accepted.append(evaluated)
            else:
                rejected.append(evaluated)

    accepted.sort(key=lambda row: row.get("prospect_score", 0), reverse=True)

    return jsonify({
        "configured": True,
        "location": location,
        "precision_mode": "strict",
        "verification_policy": (
            "No lead is accepted unless the indexed source contains an explicit license/qualifier/permit signal, "
            "the location is explicit, a company name can be deterministically extracted, and exactly one matching "
            "Google Places business is verified in the requested location. Generic electrician hiring is rejected."
        ),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "results": accepted,
        "rejections": rejected[:50],
        "sources_run": sources_run,
    })
