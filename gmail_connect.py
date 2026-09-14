import hashlib
import hmac
import os
import time
from urllib.parse import urlencode

import requests
from flask import jsonify, redirect, request

import app as app_module
from app import app, db

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]
DEFAULT_REDIRECT_URI = "https://ai-ops-command-center.onrender.com/oauth/google/callback"


class GmailOAuthConnection(db.Model):
    __tablename__ = "gmail_oauth_connection"

    id = db.Column(db.Integer, primary_key=True)
    refresh_token = db.Column(db.Text, nullable=False)
    email = db.Column(db.String(500), default="")
    updated_at = db.Column(db.DateTime, server_default=db.func.now(), onupdate=db.func.now())


with app.app_context():
    db.create_all()


def _secret():
    return (os.getenv("SECRET_KEY") or app.secret_key or "dev-secret-key").encode("utf-8")


def _state_value():
    stamp = str(int(time.time()))
    digest = hmac.new(_secret(), stamp.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{stamp}.{digest}"


def _valid_state(value):
    try:
        stamp, digest = str(value or "").split(".", 1)
        age = int(time.time()) - int(stamp)
        if age < 0 or age > 900:
            return False
        expected = hmac.new(_secret(), stamp.encode("utf-8"), hashlib.sha256).hexdigest()
        return hmac.compare_digest(digest, expected)
    except Exception:
        return False


def _redirect_uri():
    return os.getenv("GOOGLE_OAUTH_REDIRECT_URI", DEFAULT_REDIRECT_URI).strip()


def _client_credentials():
    return (
        os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
    )


def _stored_refresh_token():
    try:
        row = GmailOAuthConnection.query.order_by(GmailOAuthConnection.id.desc()).first()
        return (row.refresh_token or "").strip() if row else ""
    except Exception:
        return ""


def _refresh_access_token(refresh_token):
    client_id, client_secret = _client_credentials()
    if not all([client_id, client_secret, refresh_token]):
        raise RuntimeError("Gmail OAuth is not configured.")

    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
        timeout=20,
    )
    if not response.ok:
        raise RuntimeError(f"Google token error {response.status_code}: {response.text[:500]}")
    token = (response.json().get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Google returned no access token.")
    return token


def gmail_access_token():
    direct = os.getenv("GMAIL_ACCESS_TOKEN", "").strip()
    if direct:
        return direct

    stored = _stored_refresh_token()
    if stored:
        try:
            return _refresh_access_token(stored)
        except Exception:
            pass

    legacy = os.getenv("GOOGLE_REFRESH_TOKEN", "").strip()
    if legacy:
        return _refresh_access_token(legacy)

    raise RuntimeError("Gmail is not connected. Open /gmail and click Connect Gmail.")


# Patch the shared app helper before outreach modules import it.
app_module.gmail_access_token = gmail_access_token


@app.route("/gmail", methods=["GET"])
def gmail_connect_page():
    status = "Not connected"
    email = ""
    try:
        token = gmail_access_token()
        profile = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if profile.ok:
            email = (profile.json().get("emailAddress") or "").strip()
            status = f"Connected to {email}" if email else "Connected"
    except Exception:
        pass

    return f"""<!doctype html>
<html><head><meta name='viewport' content='width=device-width,initial-scale=1'><title>Connect Gmail</title>
<style>body{{font-family:Arial,sans-serif;background:#0d1321;color:#fff;margin:0;padding:30px}}.card{{max-width:650px;margin:40px auto;background:#18233a;padding:28px;border-radius:16px}}a.btn{{display:inline-block;background:#fff;color:#111;padding:14px 20px;border-radius:10px;text-decoration:none;font-weight:700}}.status{{padding:12px 0 20px;color:#d7e3ff}}small{{color:#9fb2d0}}</style></head>
<body><div class='card'><h1>Gmail Connection</h1><div class='status'>{status}</div><p>Click once, sign into Google, and press Allow. AI Ops will save the authorization automatically.</p><a class='btn' href='/connect/gmail'>Connect Gmail</a><p><small>Requested access: read message/thread metadata needed for reply checks and send outreach emails.</small></p><p><a href='/' style='color:#d7e3ff'>Back to AI Ops</a></p></div></body></html>"""


@app.route("/connect/gmail", methods=["GET"])
def connect_gmail():
    client_id, client_secret = _client_credentials()
    if not client_id or not client_secret:
        return "Google OAuth client ID/secret are not configured on Render.", 503

    params = {
        "client_id": client_id,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": " ".join(GMAIL_SCOPES),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": _state_value(),
    }
    return redirect(f"{GOOGLE_AUTH_URL}?{urlencode(params)}")


@app.route("/oauth/google/callback", methods=["GET"])
def gmail_oauth_callback():
    if request.args.get("error"):
        return redirect("/gmail?error=google_denied")
    if not _valid_state(request.args.get("state")):
        return "Invalid or expired OAuth state. Start again from /gmail.", 400

    code = (request.args.get("code") or "").strip()
    if not code:
        return "Google did not return an authorization code.", 400

    client_id, client_secret = _client_credentials()
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": _redirect_uri(),
        },
        timeout=20,
    )
    if not response.ok:
        app.logger.warning("GMAIL_OAUTH_EXCHANGE_FAILED status=%s", response.status_code)
        return "Google authorization could not be completed. Start again from /gmail.", 502

    data = response.json()
    refresh_token = (data.get("refresh_token") or "").strip()
    access_token = (data.get("access_token") or "").strip()
    if not refresh_token:
        return "Google did not issue a refresh token. Start again and approve access.", 502

    email = ""
    if access_token:
        profile = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=20,
        )
        if profile.ok:
            email = (profile.json().get("emailAddress") or "").strip()

    try:
        GmailOAuthConnection.query.delete()
        db.session.add(GmailOAuthConnection(refresh_token=refresh_token, email=email))
        db.session.commit()
    except Exception:
        db.session.rollback()
        app.logger.exception("GMAIL_OAUTH_SAVE_FAILED")
        return "Gmail authorized, but AI Ops could not save the connection.", 500

    app.logger.info("GMAIL_OAUTH_CONNECTED email=%s", email or "unknown")
    return redirect("/gmail?connected=1")


@app.route("/api/gmail/status", methods=["GET"])
def gmail_status():
    try:
        token = gmail_access_token()
        profile = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers={"Authorization": f"Bearer {token}"},
            timeout=20,
        )
        if not profile.ok:
            return jsonify({"connected": False, "reason": f"gmail_profile_{profile.status_code}"}), 200
        email = (profile.json().get("emailAddress") or "").strip()
        return jsonify({"connected": True, "email": email, "redirect_uri": _redirect_uri()}), 200
    except Exception as exc:
        text = str(exc).lower()
        reason = "authorization_expired" if ("invalid_grant" in text or "expired or revoked" in text) else "not_connected"
        return jsonify({"connected": False, "reason": reason, "redirect_uri": _redirect_uri()}), 200
