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

MASTER_ROLE_SIGNALS = (
    "master electrician",
    "licensed master electrician",
    "master electrical",
)

PERMIT_RESPONSIBILITY_SIGNALS = (
    "pull permits",
    "pull electrical permits",
    "permit pulling",
    "pulling permits",
    "permit responsibility",
    "electrical qualifier",
    "qualifying agent",
    "qualifying individual",
    "qualifying party",
    "qualifying electrician",
    "license qualifier",
    "license holder",
)

NEGATIVE_SIGNALS = (
    "staffing agency",
    "recruiting agency",
    "confidential employer",
    "company confidential",
    "school",
    "university",
    "college",
    "education",
    "training program",
    "apprenticeship program",
    "exam prep",
    "course",
    "certification class",
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
    return terms[0] in haystack


def _signals(title, snippet):
    text = f"{title} {snippet}".lower()
    role = [signal for signal in MASTER_ROLE_SIGNALS if signal in text]
    permit = [signal for signal in PERMIT_RESPONSIBILITY_SIGNALS if signal in text]
    return role, permit


def _has_negative_signal(title, snippet):
    text = f"{title} {snippet}".lower()
    return any(signal in text for signal in NEGATIVE_SIGNALS)


def _extract_company_from_title(title):
    raw = _clean(title, 300)
    if not raw:
        return ""
    cleaned = re.sub(r"\s*\|\s*(Indeed|ZipRecruiter|LinkedIn).*$", "", raw, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+-\s+(Indeed|ZipRecruiter|LinkedIn).*$", "", cleaned, flags=re.IGNORECASE)
    for separator in (" - ", " | ", " at "):
        if separator in cleaned:
            pieces = [piece.strip() for piece in cleaned.split(separator) if piece.strip()]
            if len(pieces) < 2:
                continue
            for candidate in pieces[1:]:
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
    for pattern in (
        r"(?:company|employer)\s*[:\-]\s*([^|;,\n]{3,120})",
        r"(?:at|with)\s+([A-Z][A-Za-z0-9&' .\-]{2,100})(?:\s+in\s+|\s+-\s+|\.|,)",
    ):
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

    matches = [
        business for business in payload.get("results") or []
        if _company_names_match(company_name, business.get("title"))
    ]
    if len(matches) != 1:
        return ({}, "company_not_verified") if not matches else ({}, "company_match_ambiguous")

    business = matches[0]
    address = _clean(business.get("subtitle"), 500).lower()
    primary = (_location_terms(location) or [""])[0]
    if primary and primary not in address:
        return {}, "verified_company_location_mismatch"
    return business, "verified"


def _job_query_variants(location):
    year = datetime.now(timezone.utc).year
    loc = _clean(location, 160)
    intent = '("master electrician" OR "licensed master electrician") ("pull permits" OR "pull electrical permits" OR "permit pulling" OR "qualifying agent" OR "electrical qualifier" OR "license holder")'
    exclusions = '-school -college -university -course -education -training -exam'
    return [
        ("Indeed", f'site:indeed.com {intent} "{loc}" contractor {year} {exclusions}'),
        ("ZipRecruiter", f'site:ziprecruiter.com {intent} "{loc}" contractor {year} {exclusions}'),
        ("LinkedIn", f'site:linkedin.com/jobs {intent} "{loc}" contractor {year} {exclusions}'),
        ("Web", f'{intent} "{loc}" electrical contractor hiring {year} {exclusions}'),
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
        rejection = "education_staffing_or_noncontractor_content"

    role_signals, permit_signals = _signals(title, snippet)
    if not rejection and not role_signals:
        rejection = "no_master_electrician_signal"
    if not rejection and not permit_signals:
        rejection = "no_permit_pulling_or_qualifier_signal"

    company_name = _extract_company(title, snippet) if not rejection else ""
    verification = {}
    verification_status = "not_attempted"
    if not rejection:
        verification, verification_status = _verify_company(company_name, location)
        if verification_status != "verified":
            rejection = verification_status

    if rejection:
        return {"accepted": False, "reason": rejection, "source": source, "title": title, "url": url}

    score = 80
    score += min(10, 5 * len(role_signals))
    score += min(10, 5 * len(permit_signals))
    if verification.get("website"):
        score += 3
    if verification.get("phone"):
        score += 3
    if verification.get("status") == "OPERATIONAL":
        score += 4
    score = min(score, 100)

    return {
        "accepted": True,
        "verification_status": "VERIFIED",
        "confidence": "high",
        "prospect_score": score,
        "source": source,
        "source_url": url,
        "source_title": title,
        "source_snippet": snippet,
        "company": verification.get("title") or company_name,
        "location": location,
        "master_electrician_signals": role_signals,
        "permit_pulling_signals": permit_signals,
        "phone": verification.get("phone") or "",
        "website": verification.get("website") or "",
        "business_address": verification.get("subtitle") or "",
        "evidence": {
            "job_listing": {"title": title, "snippet": snippet, "url": url, "source": source},
            "company_verification": {
                "name": verification.get("title") or "",
                "address": verification.get("subtitle") or "",
                "website": verification.get("website") or "",
                "phone": verification.get("phone") or "",
                "business_status": verification.get("status") or "",
                "google_maps_url": verification.get("url") or "",
            },
        },
        "lead_signal": "Verified contractor with explicit Master Electrician AND permit-pulling/qualifier need in the indexed source.",
    }


@app.route("/api/verified-job-signals", methods=["POST"])
def verified_job_signals():
    data = request.get_json(silent=True) or {}
    location = _clean(data.get("location"), 200)
    if not location:
        return jsonify({"configured": True, "message": "Enter a city/state location, for example: Portsmouth, VA.", "results": []}), 400

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
        "precision_mode": "master_electrician_permit_pulling_only",
        "verification_policy": (
            "A lead is accepted only when the indexed source explicitly mentions a Master Electrician and also explicitly mentions permit-pulling or electrical-license qualifier responsibility. "
            "Education, schools, courses, staffing agencies, generic electrician jobs, and results without a uniquely verified local business are rejected."
        ),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "count": len(accepted),
        "message": f"Found {len(accepted)} verified contractor lead" + ("" if len(accepted) == 1 else "s") + " explicitly seeking a Master Electrician for permit/qualifier responsibility.",
        "results": accepted,
        "rejections": rejected[:50],
        "sources_run": sources_run,
    })
