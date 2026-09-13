import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from flask import jsonify, request

from app import app
from universal_app import _search_public_records


MASTER_SEARCH_POLICY = """
AI Ops Command Center must return real, current, source-backed opportunities only.
Never invent companies, job openings, URLs, salaries, dates, locations, contacts, or evidence.
Prefer original employer career pages, then Indeed, ZipRecruiter, LinkedIn Jobs, Glassdoor,
and other established job sources. Prefer today/24h/3d/7d/14d results and normally reject
stale results over 30 days when age is known. Respect the requested location. Do not add
remote jobs unless the user explicitly requests remote work. Remove duplicates, retain the
source URL, and return fewer verified results rather than filler. If a field cannot be verified,
leave it blank or label it Not publicly listed. Search in stages: discover, filter, verify from
indexed evidence, deduplicate, score, rank, return. Search behavior stays universal and does
not alter the workflow builder, staging center, pipeline, or automation architecture.
""".strip()

TRUSTED_JOB_HOSTS = {
    "indeed.com": "Indeed",
    "www.indeed.com": "Indeed",
    "ziprecruiter.com": "ZipRecruiter",
    "www.ziprecruiter.com": "ZipRecruiter",
    "linkedin.com": "LinkedIn Jobs",
    "www.linkedin.com": "LinkedIn Jobs",
    "glassdoor.com": "Glassdoor",
    "www.glassdoor.com": "Glassdoor",
    "jobs.lever.co": "Lever",
    "boards.greenhouse.io": "Greenhouse",
    "job-boards.greenhouse.io": "Greenhouse",
}

REMOTE_SIGNALS = (
    "remote",
    "work from home",
    "work-from-home",
    "anywhere in the us",
    "anywhere in the u.s.",
    "united states - remote",
    "us remote",
    "u.s. remote",
)

NON_JOB_SIGNALS = (
    "salary guide",
    "career guide",
    "what does",
    "how to become",
    "training",
    "course",
    "degree",
    "bootcamp",
    "certification",
    "resume example",
    "interview questions",
)

ROLE_EXPANSIONS = {
    "automation engineer": [
        "automation engineer",
        "ai automation engineer",
        "workflow automation engineer",
        "ai engineer",
        "machine learning engineer",
        "applied ai engineer",
    ],
    "machine learning engineer": [
        "machine learning engineer",
        "ml engineer",
        "ai engineer",
        "applied ai engineer",
        "generative ai engineer",
        "llm engineer",
    ],
    "ai engineer": [
        "ai engineer",
        "artificial intelligence engineer",
        "machine learning engineer",
        "applied ai engineer",
        "generative ai engineer",
        "llm engineer",
    ],
}


def _clean(value, limit=1200):
    return str(value or "").strip()[:limit]


def _host(url):
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    if host.startswith("m."):
        host = host[2:]
    return host


def _source_name(url, fallback=""):
    host = _host(url)
    if host in TRUSTED_JOB_HOSTS:
        return TRUSTED_JOB_HOSTS[host]
    if host.endswith(".myworkdayjobs.com"):
        return "Workday"
    return _clean(fallback, 120) or host or "Web Search"


def _role_variants(query):
    q = _clean(query, 200).lower()
    for key, values in ROLE_EXPANSIONS.items():
        if key in q or q in key:
            return values
    return [_clean(query, 200)] if query else ["automation engineer"]


def _location_parts(location):
    raw = re.sub(r"\s+", " ", _clean(location, 200).lower()).strip()
    if "," in raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    words = raw.split()
    if len(words) >= 2 and words[-1] in {"va", "virginia", "nc", "maryland", "md"}:
        return [" ".join(words[:-1]), words[-1]]
    return [raw] if raw else []


def _location_matches(title, snippet, location):
    parts = _location_parts(location)
    if not parts:
        return True
    haystack = f"{title} {snippet}".lower()
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


def _is_remote(title, snippet):
    text = f"{title} {snippet}".lower()
    return any(signal in text for signal in REMOTE_SIGNALS)


def _looks_like_non_job(title, snippet):
    text = f"{title} {snippet}".lower()
    return any(signal in text for signal in NON_JOB_SIGNALS)


def _role_signals(title, snippet, query):
    text = f"{title} {snippet}".lower()
    variants = _role_variants(query)
    exact = [role for role in variants if role.lower() in text]
    if exact:
        return exact

    requested = set(re.findall(r"[a-z0-9]+", _clean(query, 200).lower()))
    title_tokens = set(re.findall(r"[a-z0-9]+", _clean(title, 400).lower()))
    useful = {t for t in requested if len(t) >= 3 and t not in {"job", "jobs"}}
    if useful and useful.issubset(title_tokens.union(set(re.findall(r"[a-z0-9]+", text)))):
        return [query]
    return []


def _extract_age_days(text):
    lower = _clean(text, 1400).lower()
    if any(x in lower for x in ("today", "just posted", "hours ago", "hour ago")):
        return 0
    match = re.search(r"(\d+)\s+day[s]?\s+ago", lower)
    if match:
        return int(match.group(1))
    match = re.search(r"(\d+)\s+week[s]?\s+ago", lower)
    if match:
        return int(match.group(1)) * 7
    match = re.search(r"(\d+)\s+month[s]?\s+ago", lower)
    if match:
        return int(match.group(1)) * 30
    return None


def _freshness_score(age_days):
    if age_days is None:
        return 8
    if age_days <= 1:
        return 25
    if age_days <= 3:
        return 23
    if age_days <= 7:
        return 20
    if age_days <= 14:
        return 16
    if age_days <= 30:
        return 10
    return 0


def _canonical_url(url):
    value = _clean(url, 1600)
    try:
        parsed = urlparse(value)
    except ValueError:
        return value
    return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/')}"


def _query_variants(query, location):
    roles = _role_variants(query)[:4]
    loc = _clean(location, 180)
    queries = []
    for role in roles:
        queries.extend([
            f'"{role}" "{loc}" Indeed',
            f'"{role}" "{loc}" ZipRecruiter',
            f'"{role}" "{loc}" LinkedIn jobs',
            f'"{role}" "{loc}" careers hiring',
        ])
    return queries[:12]


def _evaluate(item, query, location, allow_remote=False):
    title = _clean(item.get("title"), 400)
    snippet = _clean(item.get("subtitle"), 1400)
    url = _clean(item.get("url"), 1600)
    source = _source_name(url, item.get("source"))

    if not title or not url:
        return None, "missing_title_or_url"
    if _looks_like_non_job(title, snippet):
        return None, "non_job_content"
    if not allow_remote and _is_remote(title, snippet):
        return None, "remote_excluded"
    if not _location_matches(title, snippet, location):
        return None, "location_not_explicit"

    role_signals = _role_signals(title, snippet, query)
    if not role_signals:
        return None, "role_not_relevant"

    age_days = _extract_age_days(f"{title} {snippet}")
    if age_days is not None and age_days > 30:
        return None, "stale_over_30_days"

    host = _host(url)
    trusted = host in TRUSTED_JOB_HOSTS or host.endswith(".myworkdayjobs.com")
    source_score = 20 if trusted else 14
    quality_score = min(
        100,
        30 + _freshness_score(age_days) + source_score + 15 + 10,
    )

    return {
        "type": "job",
        "title": title,
        "subtitle": snippet,
        "company": "Not publicly listed",
        "location": location,
        "posted": "Not publicly listed" if age_days is None else ("Today" if age_days == 0 else f"About {age_days} day(s) ago"),
        "salary": "Not publicly listed",
        "employment_type": "Not publicly listed",
        "url": url,
        "direct_url": url,
        "source": source,
        "verification": "LIKELY VERIFIED" if trusted else "UNVERIFIED",
        "quality_score": quality_score,
        "intent_score": 100,
        "why_it_matches": "Indexed job result matches the requested role family and requested city/state.",
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "remote": _is_remote(title, snippet),
        "role_signals": role_signals,
    }, "accepted"


@app.route("/api/local-jobs", methods=["GET", "POST"])
def local_jobs():
    data = request.get_json(silent=True) or {} if request.method == "POST" else request.args
    query = _clean(data.get("query") or data.get("keyword") or "automation engineer", 240)
    location = _clean(data.get("location") or "", 200)
    allow_remote = str(data.get("allow_remote") or "").lower() in {"1", "true", "yes", "on"}

    if not query:
        return jsonify({"configured": True, "message": "Enter a job title or job type.", "results": [], "count": 0}), 400
    if not location:
        return jsonify({
            "configured": True,
            "message": "Enter a city and state, for example Portsmouth, VA.",
            "results": [],
            "count": 0,
            "policy": MASTER_SEARCH_POLICY,
        }), 400

    accepted = []
    rejected = []
    seen_urls = set()
    seen_titles = set()
    sources_run = []

    for search_query in _query_variants(query, location):
        payload = _search_public_records(search_query, "")
        sources_run.append({
            "query": search_query,
            "source": payload.get("source") or "",
            "configured": bool(payload.get("configured")),
            "message": payload.get("message") or "",
        })

        if not payload.get("configured"):
            return jsonify({
                "configured": False,
                "source": payload.get("source") or "Web Search",
                "message": payload.get("message") or "Web search is not configured.",
                "results": [],
                "count": 0,
                "sources_run": sources_run,
                "policy": MASTER_SEARCH_POLICY,
            }), 503

        for item in payload.get("results") or []:
            raw_url = _clean(item.get("url"), 1600)
            raw_title = _clean(item.get("title"), 400)
            canonical = _canonical_url(raw_url)
            title_key = re.sub(r"[^a-z0-9]+", " ", raw_title.lower()).strip()
            if not raw_url or canonical in seen_urls or (title_key and title_key in seen_titles):
                continue

            row, reason = _evaluate(item, query, location, allow_remote=allow_remote)
            seen_urls.add(canonical)
            if title_key:
                seen_titles.add(title_key)

            if row:
                accepted.append(row)
            else:
                rejected.append({"title": raw_title, "url": raw_url, "reason": reason})

    accepted.sort(key=lambda row: row.get("quality_score", 0), reverse=True)
    accepted = accepted[:30]

    return jsonify({
        "configured": True,
        "source": "Verified Local Job Search",
        "query": query,
        "location": location,
        "allow_remote": allow_remote,
        "count": len(accepted),
        "message": (
            f"Found {len(accepted)} source-backed local job result"
            + ("" if len(accepted) == 1 else "s")
            + ". Remote-only, stale, unrelated, and duplicate results were filtered out."
        ),
        "results": accepted,
        "rejected_count": len(rejected),
        "rejections": rejected[:30],
        "sources_run": sources_run,
        "policy": MASTER_SEARCH_POLICY,
    })
