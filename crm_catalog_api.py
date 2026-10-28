"""Read-only CRM catalog endpoint. No provider is represented as connected."""
from flask import jsonify
from app import app
from outreach_automation import _operator_session_authorized
from crm_integrations.registry import catalog

@app.get("/api/crm/providers")
def crm_provider_catalog():
    if not _operator_session_authorized():
        return jsonify(error="Sign in first"), 401
    return jsonify(providers=catalog())
