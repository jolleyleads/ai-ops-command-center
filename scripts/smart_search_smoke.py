"""Live API contract smoke. Empty verified-result sets are reported, never fabricated."""
import json
import os
import time
import urllib.parse
import urllib.request
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.job_evidence import receipt_is_current, is_hiring_query, alternative_claim_allowed
from src.record_evidence import record_receipt_is_current

ORIGIN = "https://ai-ops-command-center.onrender.com"
CASES = [
    ("jobs", "machine learning engineer jobs", "Portsmouth, VA"),
    ("contractors", "contractors looking for a master electrician to pull permits", "Virginia Beach, VA"),
    ("businesses", "find HVAC companies", "Norfolk, VA"),
    ("permits", "recent electrical permits issued", "Chesapeake, VA"),
    ("permit_leads", "master electrician permit pulling leads", "Portsmouth, VA"),
]


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent":"AutoMake-Contract-Smoke/2.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        return json.load(response)


def wait_for_commit(expected, timeout=300):
    if not expected:
        raise RuntimeError("Expected deployment commit is required")
    deadline = time.monotonic()+timeout
    while time.monotonic() < deadline:
        try:
            if get_json(ORIGIN+"/api/health").get("git_commit") == expected:
                return
        except Exception as exc:
            print("Readiness:", type(exc).__name__, flush=True)
        time.sleep(5)
    raise RuntimeError("Exact deployed commit was not ready")


def validate_payload(payload, expected_intent, query="", location=""):
    errors = []
    if not isinstance(payload, dict):
        return ["response is not an object"]
    query=query or payload.get("query") or ""
    location=location or payload.get("location") or ""
    for field, expected in (("intent",expected_intent),("configured",True),("agent_mode",True),("verification_gate",True)):
        if payload.get(field) != expected:
            errors.append(f"{field}: expected {expected!r}, got {payload.get(field)!r}")
    if payload.get("agent_error"):
        errors.append("research agent failed")
    if not payload.get("source"):
        errors.append("no source provider reported")
    rows = payload.get("results")
    if not isinstance(rows, list):
        return errors+["results is not a list"]
    if payload.get("count") != len(rows):
        errors.append("count differs from result length")
    verified = 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            errors.append(f"result {i} is not an object")
            continue
        if not (row.get("title") or row.get("name") or row.get("company")):
            errors.append(f"result {i} has no display name")
        company=row.get("candidate_name") or row.get("title") or row.get("company")
        needs_job=expected_intent=="jobs" or row.get("classification")=="Verified Lead" and is_hiring_query(query) and not alternative_claim_allowed(query,row.get("verified_channels"))
        if needs_job and not receipt_is_current(row.get("job_validation"),query,location,company=company):
            errors.append(f"result {i} lacks current job evidence matching role, city and employer")
        if (expected_intent=="permits" or "permit_license" in row.get("verified_channels",[])) and not record_receipt_is_current(row.get("record_validation"),query,location):
            errors.append(f"result {i} lacks current record evidence matching city")
        if row.get("classification") == "Verified Lead":
            verified += 1
            urls = [row.get(k) for k in ("url","website","direct_url","source_url")]+list(row.get("supporting_urls") or [])
            if not any(isinstance(u,str) and u.startswith(("https://","http://")) for u in urls):
                errors.append(f"verified result {i} has no source URL")
    if payload.get("verified_count") != verified:
        errors.append("verified_count differs from verified result length")
    return errors


def main():
    wait_for_commit(os.environ.get("GITHUB_SHA"))
    with urllib.request.urlopen(ORIGIN+"/", timeout=60) as response:
        html = response.read().decode()
    for marker in ('Smart Search','/api/smart-search','id="searchQuery"','id="searchLocation"'):
        if marker not in html:
            raise RuntimeError("Missing frontend marker: "+marker)
    if 'id="searchMode"' in html:
        raise RuntimeError("Old mode selector remains")
    failed = False
    for intent, query, location in CASES:
        try:
            payload = get_json(ORIGIN+"/api/test-smart-search?"+urllib.parse.urlencode({"query":query,"location":location}))
            errors = validate_payload(payload, intent, query, location)
            print(json.dumps({"expected_intent":intent,"intent":payload.get("intent"),"count":payload.get("count"),"verified_count":payload.get("verified_count"),"provider_message":payload.get("provider_message"),"errors":errors}),flush=True)
            failed |= bool(errors)
        except Exception as exc:
            print("FAIL",intent,str(exc),flush=True)
            failed = True
    if failed:
        raise SystemExit(1)
    print("PASS: deployed search API contract. Lead availability and relevance require separate acceptance evidence.")


if __name__ == "__main__":
    main()
