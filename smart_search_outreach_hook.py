import hmac
import os

from flask import jsonify, request

from app import app
from outreach_bridge import ingest_verified_results


@app.before_request
def protect_outreach_followup_processor():
    if request.path != "/api/outreach/process-followups":
        return None
    expected = os.getenv("OUTREACH_CRON_TOKEN", "").strip()
    provided = request.headers.get("X-Outreach-Cron-Token", "")
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        return jsonify({"error": "unauthorized"}), 401
    return None


@app.after_request
def smart_search_outreach_hook(response):
    if request.path != "/api/smart-search" or request.method not in {"GET", "POST"}:
        return response
    if response.status_code != 200 or not response.is_json:
        return response

    try:
        payload = response.get_json(silent=True) or {}
        automation = ingest_verified_results(payload)
        if isinstance(payload, dict):
            payload["outreach_automation"] = automation
            response.set_data(app.json.dumps(payload))
            response.headers["Content-Type"] = "application/json"
            response.headers["Content-Length"] = str(len(response.get_data()))
    except Exception as exc:
        app.logger.exception("SMART_SEARCH_OUTREACH_ERROR %s", type(exc).__name__)

    return response
