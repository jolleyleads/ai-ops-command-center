"""Authenticated one-shot surface for controlled provider acceptance."""
from flask import jsonify, request
from app import app
import outreach_automation as oa
from scripts.provider_integration_acceptance import run_provider_integration_acceptance

CONTROLLED_RECIPIENT = "neyolabs@gmail.com"


@app.route("/api/operator/provider-acceptance-once", methods=["POST"])
def provider_acceptance_once():
    if not oa._operator_session_authorized():
        return jsonify({"ok": False, "error": "unauthorized"}), 401
    if not oa._csrf_ok():
        return jsonify({"ok": False, "error": "csrf_failed"}), 403
    data = request.get_json(silent=True) or {}
    recipient = str(data.get("recipient") or CONTROLLED_RECIPIENT).strip().lower()
    if recipient != CONTROLLED_RECIPIENT:
        return jsonify({"ok": False, "error": "controlled_recipient_required"}), 400
    result = run_provider_integration_acceptance(recipient)
    return jsonify(result), 200 if result.get("ok") else 502
