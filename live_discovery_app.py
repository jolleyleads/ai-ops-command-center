"""Database-independent, read-only discovery service.

Run separately from commercial_app: gunicorn live_discovery_app:app.
No PostgreSQL imports, persistence, contact enrichment, or outreach.
"""
import json
import os
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from flask import Flask, jsonify, request

app = Flask(__name__)

def discover(prompt, location="United States", limit=10):
    """Return source-backed research references, NOT verified businesses or leads."""
    prompt = str(prompt or "").strip()[:500]
    location = str(location or "United States").strip()[:120]
    limit = max(1, min(int(limit), 20))
    if not prompt:
        return {"error": "Enter a research request.", "results": []}, 400
    key = os.environ.get("EXA_API_KEY")
    if not key:
        return {"error": "Live discovery provider unavailable.", "results": [], "provider_status": "not_configured"}, 503
    body = json.dumps({"query": f"{prompt} {location}", "numResults": limit, "type": "auto"}).encode()
    req = Request("https://api.exa.ai/search", data=body, headers={"x-api-key": key, "Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(req, timeout=18) as response:
            payload = json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError):
        return {"error": "Live discovery provider request failed.", "results": [], "provider_status": "failed"}, 502
    rows = []
    seen = set()
    for item in payload.get("results", []):
        url = str(item.get("url") or "").strip()
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.netloc or url in seen:
            continue
        seen.add(url)
        rows.append({"title": str(item.get("title") or parsed.netloc)[:250],
                     "url": url, "source": "Exa", "classification": "Research source · unverified",
                     "reason": "Source found for this search; business identity and automation need have not been verified."})
    return {"query": prompt, "location": location, "results": rows, "count": len(rows),
            "verified_count": 0, "provider_status": "ok",
            "message": "These are research sources, not qualified leads. No information has been saved."}, 200

@app.post("/api/live-discovery")
def live_discovery():
    data = request.get_json(silent=True) or {}
    try:
        result, status = discover(data.get("prompt"), data.get("location"), data.get("target_count", 10))
    except (ValueError, TypeError):
        return jsonify({"error": "Invalid result count.", "results": []}), 400
    return jsonify(result), status

@app.get("/api/live-discovery/health")
def health():
    return jsonify({"service": "live-discovery", "database_required": False, "provider_configured": bool(os.environ.get("EXA_API_KEY"))})
