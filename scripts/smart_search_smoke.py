"""Live API contract smoke. Empty verified-result sets are reported, never fabricated."""
import json
import os
import time
import urllib.parse
import urllib.request
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

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
    # Campaign polling reuses HTTP helpers without importing application deps.
    from src.job_evidence import receipt_is_current, is_hiring_query, alternative_claim_allowed
    from src.record_evidence import record_receipt_is_current
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
        company=row.get("candidate_name") or row.get("company") or row.get("title")
        needs_job=expected_intent=="jobs" or row.get("classification")=="Verified Lead" and is_hiring_query(query) and not alternative_claim_allowed(query,row.get("verified_channels"))
        if needs_job and not receipt_is_current(row.get("job_validation"),query,location,company=company):
            errors.append(f"result {i} lacks current job evidence matching role, city and employer")
        if (expected_intent in {"permits","permit_leads"} or "permit_license" in row.get("verified_channels",[])) and not record_receipt_is_current(row.get("record_validation"),query,location):
            errors.append(f"result {i} lacks current record evidence matching city")
        if row.get("classification") == "Verified Lead":
            verified += 1
            urls = [row.get(k) for k in ("url","website","direct_url","source_url")]+list(row.get("supporting_urls") or [])
            if not any(isinstance(u,str) and u.startswith(("https://","http://")) for u in urls):
                errors.append(f"verified result {i} has no source URL")
    if payload.get("verified_count") != verified:
        errors.append("verified_count differs from verified result length")
    return errors


def validate_frontend(html, dashboard_script=""):
    from html.parser import HTMLParser
    class Controls(HTMLParser):
        def __init__(self):
            super().__init__();self.ids=set();self.scripts=[];self.views=set()
        def handle_starttag(self, tag, attrs):
            attrs=dict(attrs)
            if attrs.get('id'):self.ids.add(attrs['id'])
            if tag=='script' and attrs.get('src'):self.scripts.append(attrs['src'])
            if attrs.get('data-view'):self.views.add(attrs['data-view'])
    controls=Controls();controls.feed(html)
    errors=[]
    if '<title>AutoMake AI</title>' not in html:errors.append('AutoMake AI page title missing')
    for name in ('prompt','territory','task-mode','send','prepare','workspace-menu','workspace-panel'):
        if name not in controls.ids:errors.append('Missing customer control: '+name)
    for route in ('/api/research/jobs','/activate-outreach','/api/chat/campaigns/prepare'):
        if route not in html:errors.append('Missing customer workflow: '+route)
    if not {'chat','leads','campaigns','conversations','appointments','settings'} <= controls.views:
        errors.append('Customer workspace navigation incomplete')
    if not any(x.split('?')[0]=='/chat-operator/dashboard.js' for x in controls.scripts):
        errors.append('Customer dashboard script missing')
    if dashboard_script and '/api/chat/dashboard' not in dashboard_script:
        errors.append('Dashboard script is not connected to persisted workspace')
    return errors


def main():
    wait_for_commit(os.environ.get("GITHUB_SHA"))
    with urllib.request.urlopen(ORIGIN+"/", timeout=60) as response:
        html = response.read().decode()
    with urllib.request.urlopen(ORIGIN+"/chat-operator/dashboard.js", timeout=60) as response:
        dashboard_script=response.read().decode()
    errors=validate_frontend(html,dashboard_script)
    if errors:
        raise RuntimeError("Customer interface contract: "+"; ".join(errors))
    print("PASS: deployed AutoMake AI customer interface and workflow controls",flush=True)
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
