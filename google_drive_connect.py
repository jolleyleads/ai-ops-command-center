"""Optional per-session Google Drive integration for the customer workspace."""
import os
import base64
import hashlib
from cryptography.fernet import Fernet, InvalidToken
import secrets
import time
from urllib.parse import urlencode

import requests
from flask import jsonify, redirect, request, session
from app import app
from outreach_automation import _operator_session_authorized

DRIVE_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"

def _credentials():
    return (os.getenv("GOOGLE_LOGIN_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID", ""),
            os.getenv("GOOGLE_LOGIN_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET", ""))

def _redirect():
    return os.getenv("GOOGLE_DRIVE_REDIRECT_URI", "https://automakeai.live/oauth/drive/callback")

def _cipher():
    key = hashlib.sha256(str(app.secret_key).encode()).digest()
    return Fernet(base64.urlsafe_b64encode(key))

def _access_token():
    try:
        return _cipher().decrypt(session.get("drive_access_token", "").encode()).decode()
    except (InvalidToken, ValueError, TypeError):
        return ""

def _authorized():
    return _operator_session_authorized()

@app.get("/api/drive/status")
def drive_status():
    if not _authorized():
        return jsonify(error="Sign in first"), 401
    return jsonify(connected=bool(session.get("drive_access_token") and time.time() < session.get("drive_expires", 0)),
                   configured=all(_credentials()))

@app.get("/connect/drive")
def connect_drive():
    if not _authorized():
        return redirect("/login", 303)
    client, secret = _credentials()
    if not client or not secret:
        return jsonify(error="Google Drive authorization is not configured"), 503
    state = secrets.token_urlsafe(32)
    session["drive_oauth_state"] = state
    session["drive_oauth_started"] = time.time()
    return redirect(GOOGLE_AUTH + "?" + urlencode(dict(client_id=client, redirect_uri=_redirect(),
        response_type="code", scope=DRIVE_SCOPE, state=state, access_type="online",
        prompt="select_account consent")), 303)

@app.get("/oauth/drive/callback")
def drive_callback():
    if not _authorized():
        return redirect("/login", 303)
    state = session.pop("drive_oauth_state", None)
    started = session.pop("drive_oauth_started", 0)
    if not state or not secrets.compare_digest(state, request.args.get("state", "")) or time.time() - started > 600:
        return jsonify(error="Google Drive sign-in expired. Try again."), 400
    if request.args.get("error") or not request.args.get("code"):
        return redirect("/chat-operator?drive=cancelled", 303)
    client, secret = _credentials()
    try:
        response = requests.post(GOOGLE_TOKEN, data=dict(client_id=client, client_secret=secret,
            code=request.args["code"], grant_type="authorization_code", redirect_uri=_redirect()), timeout=15)
        response.raise_for_status()
        payload = response.json()
        token = payload["access_token"]
        if DRIVE_SCOPE not in payload.get("scope", DRIVE_SCOPE).split():
            return jsonify(error="Drive permission was not granted"), 403
        session["drive_access_token"] = _cipher().encrypt(token.encode()).decode()
        session["drive_expires"] = time.time() + min(int(payload.get("expires_in", 3600)), 3600) - 60
    except (requests.RequestException, KeyError, ValueError, TypeError):
        return jsonify(error="Could not connect Google Drive"), 502
    return redirect("/chat-operator?drive=connected", 303)

@app.get("/api/drive/files")
def drive_files():
    if not _authorized():
        return jsonify(error="Sign in first"), 401
    token = _access_token()
    if not token or time.time() >= session.get("drive_expires", 0):
        return jsonify(error="Connect Google Drive to browse files", connected=False), 401
    try:
        response = requests.get("https://www.googleapis.com/drive/v3/files",
            headers={"Authorization": "Bearer " + token},
            params={"pageSize": 50, "fields": "nextPageToken,files(id,name,mimeType,webViewLink,modifiedTime)",
                    "q": "trashed = false", "orderBy": "modifiedTime desc"}, timeout=15)
        if response.status_code == 401:
            session.pop("drive_access_token", None)
            session.pop("drive_expires", None)
            return jsonify(error="Drive connection expired. Reconnect to continue."), 401
        response.raise_for_status()
        return jsonify(response.json())
    except (requests.RequestException, ValueError):
        return jsonify(error="Could not load Drive files"), 502

@app.post("/api/drive/disconnect")
def drive_disconnect():
    if not _authorized():
        return jsonify(error="Sign in first"), 401
    from outreach_automation import _csrf_ok
    if not _csrf_ok():
        return jsonify(error="Please refresh and try again"), 403
    session.pop("drive_access_token", None)
    session.pop("drive_expires", None)
    return jsonify(connected=False)
