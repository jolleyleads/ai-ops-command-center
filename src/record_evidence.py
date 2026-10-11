"""Source-bound locality checks for permit and license evidence."""
import hashlib
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from src.company_identity import location_matches, STATES
from src.job_evidence import requested_location, _stamp, MAX_CHECK_AGE

VERSION = "record-page-v1"
RECORD = re.compile(r"\b(?:permits?|inspections?|licenses?|licensing)\b", re.I)


def check_record_evidence(row, query, location="", now=None):
    now = now or datetime.now(timezone.utc)
    url = str(row.get("resolved_url") or row.get("url") or "")
    target = requested_location(query, location)
    targets = list(dict.fromkeys(v for v in (target, requested_location(query)) if v))
    base = {"version": VERSION, "ok": False, "source_url": url, "requested_location": target}
    if row.get("rag_retrieved") or not row.get("directly_fetched") or row.get("http_status") != 200:
        return {**base, "reasons": ["live_record_page_required"]}
    checked = _stamp(row.get("job_page_fetched_at") or row.get("observed_at"))
    if not checked or checked > now + timedelta(minutes=5) or now - checked > MAX_CHECK_AGE:
        return {**base, "reasons": ["record_check_stale_or_missing"]}
    detail = str(row.get("job_detail_text") or "")
    heading = str(row.get("source_heading") or "")
    if not RECORD.search(detail) or not RECORD.search(heading):
        return {**base, "reasons": ["record_detail_heading_required"]}
    record_ids=set(re.findall(r"(?i)\b(?:permit|record|inspection|license)\s*(?:number|id|#)?\s*[:#\-]?\s*([a-z]*\d+[a-z0-9\-]*)\b",detail))
    if len(record_ids)>1:
        return {**base, "reasons": ["ambiguous_multiple_records_on_page"]}
    if "master electrician" in query.lower() and not re.search(r"\bmaster electrician\b",detail,re.I):
        return {**base, "reasons": ["requested_master_electrician_role_unproven"]}
    state_pattern = "|".join(re.escape(s) for s in sorted(STATES, key=len, reverse=True)) + "|" + "|".join(STATES.values())
    addresses = re.findall(r"(?i)\b(?:project location|site address|property address|job address|worksite|record location|jurisdiction)\s*[:\-]\s*([^;\n]{2,100}?,\s*(?:" + state_pattern + r"))\b", detail)
    # A heading explicitly naming the record and locality is supported; a city
    # in an unrelated footer, company HQ, or nearby record is not.
    locations = addresses or ([heading] if location_matches(heading, target) else [])
    if not locations or any(not all(location_matches(v, p) for v in locations) for p in targets):
        return {**base, "reasons": ["requested_city_not_in_record_location"]}
    dated = re.search(r"(?i)\b(?:issued date|issue date|date issued|permit date|record date)\s*[:\-]\s*(\d{4}-\d{2}-\d{2})\b", detail)
    date = dated.group(1) if dated else None
    posted = _stamp(date)
    if date and (not posted or posted > now + timedelta(minutes=5)):
        return {**base, "reasons": ["record_date_invalid_or_future"]}
    if re.search(r"\b(?:recent|new|latest|current)\b", query, re.I) and (not posted or now - posted > timedelta(days=90)):
        return {**base, "reasons": ["recent_record_date_unproven"]}
    return {**base, "ok": True, "reasons": [], "checked_at": checked.isoformat(), "record_locations": locations, "record_date": date, "master_electrician_observed":bool(re.search(r"\bmaster electrician\b",detail,re.I)), "content_sha256": hashlib.sha256((url + heading + detail).encode()).hexdigest()}


def record_receipt_is_current(receipt, query, location="", now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(receipt, dict) or receipt.get("version") != VERSION or receipt.get("ok") is not True:
        return False
    if "master electrician" in query.lower() and receipt.get("master_electrician_observed") is not True:
        return False
    checked = _stamp(receipt.get("checked_at"))
    if not checked or checked > now + timedelta(minutes=5) or now - checked > MAX_CHECK_AGE:
        return False
    targets = list(dict.fromkeys(v for v in (requested_location(query, location), requested_location(query)) if v))
    locations=receipt.get("record_locations") or []
    if not locations or any(not all(location_matches(v, p) for v in locations) for p in targets):
        return False
    posted = _stamp(receipt.get("record_date"))
    if receipt.get("record_date") and (not posted or posted > now + timedelta(minutes=5)):
        return False
    if re.search(r"\b(?:recent|new|latest|current)\b", query, re.I) and (not posted or now - posted > timedelta(days=90)):
        return False
    try:
        url=urlparse(str(receipt.get("source_url") or ""))
        valid_url=url.scheme in {"https", "http"} and bool(url.hostname)
    except ValueError:
        valid_url=False
    return bool(valid_url and re.fullmatch(r"[a-f0-9]{64}", str(receipt.get("content_sha256") or "")))
