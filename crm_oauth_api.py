"""Opt-in, session-scoped OAuth CRM connections. Requires provider app credentials."""
import base64
import hashlib
import os
import secrets
import time
from urllib.parse import urlencode

import requests
from cryptography.fernet import Fernet, InvalidToken
from flask import jsonify, redirect, request, session
from app import app
from outreach_automation import _operator_session_authorized

CONFIG = {
    "hubspot": ("https://app.hubspot.com/oauth/authorize", "https://api.hubapi.com/oauth/v1/token", "crm.objects.contacts.read"),
    "salesforce": ("https://login.salesforce.com/services/oauth2/authorize", "https://login.salesforce.com/services/oauth2/token", "api refresh_token"),
    "pipedrive": ("https://oauth.pipedrive.com/oauth/authorize", "https://oauth.pipedrive.com/oauth/token", ""),
    "jobber": ("https://api.getjobber.com/api/oauth/authorize", "https://api.getjobber.com/api/oauth/token", ""),
    "clio": ("https://app.clio.com/oauth/authorize", "https://app.clio.com/oauth/token", ""),
}

def _cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(str(app.secret_key).encode()).digest()))

def _config(provider):
    prefix = "CRM_" + provider.upper()
    return os.getenv(prefix + "_CLIENT_ID", ""), os.getenv(prefix + "_CLIENT_SECRET", "")

def _redirect_uri(provider):
    return os.getenv("CRM_" + provider.upper() + "_REDIRECT_URI", "https://automakeai.live/oauth/crm/" + provider + "/callback")

def _status(provider):
    if provider not in CONFIG:
        return {"configured": False, "connected": False, "status": "provider_setup_required"}
    configured = all(_config(provider))
    encrypted = session.get("crm_" + provider + "_token")
    connected = bool(encrypted and time.time() < session.get("crm_" + provider + "_expires", 0))
    return {"configured": configured, "connected": connected, "status": "connected" if connected else ("ready_to_connect" if configured else "setup_required")}

@app.get("/api/crm/status/<provider>")
def crm_connection_status(provider):
    if not _operator_session_authorized():
        return jsonify(error="Sign in first"), 401
    if provider not in CONFIG and provider != "servicetitan":
        return jsonify(error="Unknown CRM"), 404
    return jsonify(provider=provider, **_status(provider))

@app.get("/connect/crm/<provider>")
def crm_connect(provider):
    if not _operator_session_authorized():
        return redirect("/login", 303)
    if provider not in CONFIG:
        return jsonify(error="Provider-specific authorization setup required"), 503
    client, secret = _config(provider)
    if not client or not secret:
        return jsonify(error="CRM app credentials have not been configured"), 503
    auth, _, scope = CONFIG[provider]
    state = secrets.token_urlsafe(32)
    session["crm_" + provider + "_state"] = state
    session["crm_" + provider + "_started"] = time.time()
    params = dict(client_id=client, redirect_uri=_redirect_uri(provider), response_type="code", state=state)
    if scope:
        params["scope"] = scope
    return redirect(auth + "?" + urlencode(params), 303)

@app.get("/oauth/crm/<provider>/callback")
def crm_callback(provider):
    if not _operator_session_authorized():
        return redirect("/login", 303)
    if provider not in CONFIG:
        return jsonify(error="Unknown CRM"), 404
    expected = session.pop("crm_" + provider + "_state", None)
    started = session.pop("crm_" + provider + "_started", 0)
    if not expected or not secrets.compare_digest(expected, request.args.get("state", "")) or not 0 <= time.time() - started < 600:
        return jsonify(error="Authorization expired. Please try again."), 400
    if request.args.get("error") or not request.args.get("code"):
        return redirect("/chat-operator?crm=" + provider + "&status=cancelled", 303)
    client, secret = _config(provider)
    _, token_url, _ = CONFIG[provider]
    try:
        response = requests.post(token_url, data=dict(grant_type="authorization_code", client_id=client,
            client_secret=secret, code=request.args["code"], redirect_uri=_redirect_uri(provider)), timeout=15)
        response.raise_for_status()
        data = response.json()
        token = data["access_token"]
        session["crm_" + provider + "_token"] = _cipher().encrypt(token.encode()).decode()
        session["crm_" + provider + "_expires"] = time.time() + max(0, min(int(data.get("expires_in", 3600)), 86400) - 60)
    except (requests.RequestException, KeyError, TypeError, ValueError):
        return jsonify(error="CRM authorization failed. Please retry."), 502
    return redirect("/chat-operator?crm=" + provider + "&status=connected", 303)

@app.get("/api/crm/test/<provider>")
def crm_test_connection(provider):
    if not _operator_session_authorized():
        return jsonify(error="Sign in first"), 401
    if provider not in CONFIG:
        return jsonify(error="Provider API test not configured"), 503
    if not _status(provider)["connected"]:
        return jsonify(connected=False, error="Connect the CRM first"), 401
    try:
        token = _cipher().decrypt(session["crm_" + provider + "_token"].encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return jsonify(connected=False, error="Reconnect required"), 401
    # Token presence alone does not establish API access; provider-specific API
    # validation must be added before reporting a successful live test.
    return jsonify(connected=True, verified=False, message="Authorization token received; provider API verification pending")

@app.post("/api/crm/disconnect/<provider>")
def crm_disconnect(provider):
    if not _operator_session_authorized():
        return jsonify(error="Sign in first"), 401
    if provider not in CONFIG:
        return jsonify(error="Unknown CRM"), 404
    from outreach_automation import _csrf_ok
    if not _csrf_ok():
        return jsonify(error="Please refresh and try again"), 403
    session.pop("crm_" + provider + "_token", None)
    session.pop("crm_" + provider + "_expires", None)
    return jsonify(connected=False)
