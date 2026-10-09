import hmac
import os

from flask import jsonify, request

from app import app


@app.before_request
def protect_outreach_followup_processor():
    if request.path != "/api/outreach/process-followups":
        return None
    expected = os.getenv("OUTREACH_CRON_TOKEN", "").strip()
    provided = request.headers.get("X-Outreach-Cron-Token", "")
    if not expected or not provided or not hmac.compare_digest(expected, provided):
        return jsonify({"error": "unauthorized"}), 401
    return None
