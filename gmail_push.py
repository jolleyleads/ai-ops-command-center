"""Deliver Gmail push notifications to the existing reply and booking router."""
import base64
import binascii
import json
import os
from datetime import datetime, timedelta, timezone

import requests
from flask import request
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2 import id_token

from app import app, db
from gmail_connect import gmail_access_token

GMAIL = "https://gmail.googleapis.com/gmail/v1/users/me"


class GmailPushCursor(db.Model):
    __tablename__ = "gmail_push_cursor"
    mailbox = db.Column(db.String(254), primary_key=True)
    history_id = db.Column(db.String(32), nullable=False)
    renew_at = db.Column(db.DateTime, nullable=False)


def _gmail(method, resource, **kwargs):
    return requests.request(
        method, f"{GMAIL}/{resource}",
        headers={"Authorization": f"Bearer {gmail_access_token()}"},
        timeout=10, **kwargs,
    )


def renew_gmail_watch():
    """Called under the outreach scheduler lease. Preserve the replay cursor."""
    topic = os.getenv("GMAIL_PUSH_TOPIC", "").strip()
    mailbox = os.getenv("GMAIL_FROM_EMAIL", "").strip().lower()
    if not topic or not mailbox:
        return
    now = datetime.utcnow()
    cursor = db.session.get(GmailPushCursor, mailbox)
    if cursor and cursor.renew_at > now:
        return
    profile = _gmail("GET", "profile")
    profile.raise_for_status()
    if profile.json()["emailAddress"].lower() != mailbox:
        raise ValueError("Gmail push mailbox does not match Google authorization")
    result = _gmail("POST", "watch", json={"topicName": topic, "labelIds": ["INBOX"]})
    result.raise_for_status()
    data = result.json()
    expiration = datetime.fromtimestamp(int(data["expiration"]) / 1000, tz=timezone.utc).replace(tzinfo=None)
    renew_at = min(now + timedelta(days=1), expiration - timedelta(hours=1))
    if cursor:
        cursor.renew_at = renew_at
    else:
        db.session.add(GmailPushCursor(
            mailbox=mailbox, history_id=str(int(data["historyId"])), renew_at=renew_at,
        ))
    db.session.commit()


def _verified_push():
    audience = os.getenv("GMAIL_PUSH_AUDIENCE", "").strip()
    service_account = os.getenv("GMAIL_PUSH_SERVICE_ACCOUNT", "").strip()
    subscription = os.getenv("GMAIL_PUSH_SUBSCRIPTION", "").strip()
    if not all((audience, service_account, subscription)):
        return False
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        return False
    claims = id_token.verify_oauth2_token(token, GoogleRequest(), audience=audience)
    return claims.get("email_verified") is True and claims.get("email") == service_account


def _read_history(cursor):
    params = {
        "startHistoryId": cursor.history_id, "historyTypes": "messageAdded",
        "labelId": "INBOX", "maxResults": 500,
    }
    threads = set()
    while True:
        response = _gmail("GET", "history", params=params)
        if response.status_code == 404:
            return None, None
        response.raise_for_status()
        data = response.json()
        for record in data.get("history", []):
            for entry in record.get("messagesAdded", []):
                thread_id = entry["message"].get("threadId")
                if thread_id:
                    threads.add(thread_id)
        page = data.get("nextPageToken")
        if not page:
            return threads, str(int(data["historyId"]))
        params["pageToken"] = page


@app.post("/api/outreach/gmail-push")
def gmail_push():
    from outreach_scheduler import _claim_cycle, _release_cycle
    from v1_orchestration import scan_real_inbound_replies

    try:
        if not _verified_push():
            return "", 401
    except ValueError:
        return "", 401
    body = request.get_json(silent=True)
    if not isinstance(body, dict) or body.get("subscription") != os.getenv("GMAIL_PUSH_SUBSCRIPTION", "").strip():
        return "", 400
    try:
        encoded = body["message"]["data"]
        data = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        mailbox = data["emailAddress"].lower()
        notification_id = int(data["historyId"])
    except (AttributeError, KeyError, ValueError, TypeError, binascii.Error):
        return "", 400
    if mailbox != os.getenv("GMAIL_FROM_EMAIL", "").strip().lower():
        return "", 204

    lease = _claim_cycle()
    if not lease:
        return "", 503
    try:
        cursor = db.session.get(GmailPushCursor, mailbox)
        if not cursor:
            return "", 503
        if notification_id <= int(cursor.history_id):
            return "", 204
        threads, history_id = _read_history(cursor)
        if threads is None:
            # Snapshot before recovery so arrivals during the scan can still replay.
            profile = _gmail("GET", "profile")
            profile.raise_for_status()
            history_id = str(int(profile.json()["historyId"]))
            result = scan_real_inbound_replies(gmail_read_interval=1.25)
        else:
            result = scan_real_inbound_replies(thread_ids=threads)
        if not result["ok"] or int(history_id) < notification_id:
            return "", 503
        cursor.history_id = history_id
        db.session.commit()
        return "", 204
    except (requests.RequestException, ValueError, KeyError, RuntimeError) as exc:
        app.logger.warning("Gmail push retry required: %s", type(exc).__name__)
        return "", 503
    finally:
        _release_cycle(lease)
