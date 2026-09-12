import os
import re
from urllib.parse import urlparse

import requests
from flask import jsonify, request

from app import app


JOB_SOURCES = {
    "indeed.com": "Indeed",
    "www.indeed.com": "Indeed",
    "ziprecruiter.com": "ZipRecruiter",
    "www.ziprecruiter.com": "ZipRecruiter",
    "linkedin.com": "LinkedIn",
    "www.linkedin.com": "LinkedIn",
}


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _tokens(value):
    return [t for t in re.findall(r"[a-z0-9]+", _clean(value, 250).lower()) if len(t) > 1]


def _location_parts(location):
    parts = [part.strip().lower() for part in _clean(location, 200).split(",") if part.strip()]
    return parts


def _location_matches(text, location):
    parts = _location_parts(location)
    if not parts:
        return False
    haystack = text.lower()
    city = parts[0]
    if city not in haystack:
        return False
    if len(parts) > 1:
        state = parts[1]
        state_map = {
            "virginia": "va", "va": "virginia",
            "north carolina": "nc", "nc": "north carolina",
            "maryland": "md", "md": "maryland",
        }
        if state not in haystack and state_map.get(state, "") not in haystack:
            return False
    return True


def _role_matches(title, snippet, query):
    role_tokens = _tokens(query)
    if not role_tokens:
        return False
    text = f"{title} {snippet}".lower()
    # Require every meaningful requested term to appear somewhere in the result.
    return all(token in text for token in role_tokens)


def _source_name(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return "Web"
    if host.startswith("m."):
        host = host[2:]
    return JOB_SOURCES.get(host, host or "Web")


def _company_from_title(title):
    raw = _clean(title, 300)
    raw = re.sub(r"\s*[|\-]\s*(Indeed|ZipRecruiter|LinkedIn).*$", "", raw, flags=re.IGNORECASE)
    for separator in (" - ", " | ", " at "):
        if separator in raw:
            parts = [p.strip() for p in raw.split(separator) if p.strip()]
            if len(parts) >= 2:
                return parts[1][:180]
    return ""


def _search_brave_jobs(query, location):
    api_key = os.environ.get("BRAVE_SEARCH_API_KEY") or ""
    if not api_key:
        return {"configured": False, "message": "BRAVE_SEARCH_API_KEY is missing.", "results": []}

    search_queries = [
        f'site:indeed.com/viewjob "{query}" "{location}"',
        f'site:ziprecruiter.com/jobs "{query}" "{location}"',
        f'site:linkedin.com/jobs/view "{query}" "{location}"',
        f'"{query}" "{location}" ("apply" OR "careers") -course -school -training',
    ]

    seen = set()
    results = []

    for search_query in search_queries:
        try:
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                params={
                    "q": search_query,
                    "country": "US",
                    "search_lang": "en",
                    "count": 20,
                    "freshness": "pm",
                },
                timeout=20,
            )
        except requests.RequestException:
            continue

        if not response.ok:
            continue

        try:
            rows = (response.json().get("web") or {}).get("results") or []
        except ValueError:
            rows = []

        for item in rows:
            title = _clean(item.get("title"), 300)
            snippet = _clean(item.get("description"), 1200)
            url = _clean(item.get("url"), 1200)
            if not url or url in seen:
                continue

            evidence_text = f"{title} {snippet}"
            if not _location_matches(evidence_text, location):
                continue
            if not _role_matches(title, snippet, query):
                continue

            seen.add(url)
            company = _company_from_title(title)
            results.append({
                "type": "job",
                "title": title,
                "subtitle": " | ".join(part for part in [company, location] if part),
                "company": company,
                "location": location,
                "url": url,
                "source": _source_name(url),
                "status": "Current indexed result",
                "analysis": "Matched the requested job terms and exact city/state in a result indexed within the past month. Open the source to confirm the posting is still accepting applications.",
            })

    return {
        "configured": True,
        "source": "Brave Search",
        "message": (
            f"Found {len(results)} current indexed job"
            + ("" if len(results) == 1 else "s")
            + f" matching '{query}' in {location}. Results outside the requested city/state or missing the requested role terms were rejected."
        ),
        "count": len(results),
        "results": results[:30],
    }


@app.route("/api/local-jobs", methods=["POST"])
def local_jobs():
    data = request.get_json(silent=True) or {}
    query = _clean(data.get("query") or "", 200)
    location = _clean(data.get("location") or "", 200)

    if not query:
        return jsonify({"configured": True, "message": "Enter a job title or job type.", "results": [], "count": 0}), 400
    if not location:
        return jsonify({"configured": True, "message": "Enter a city and state, for example Portsmouth, VA.", "results": [], "count": 0}), 400

    return jsonify(_search_brave_jobs(query, location))
