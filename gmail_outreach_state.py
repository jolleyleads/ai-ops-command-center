import base64
import json
import os
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import getaddresses, parseaddr

import requests

from app import gmail_access_token
from src.services import run_ai

TRACK_HEADER = "X-AI-Ops-Outreach"
COMPANY_HEADER = "X-AI-Ops-Company"
STEP_HEADER = "X-AI-Ops-Step"
TRACK_VALUE = "v1"
FIRST_FOLLOWUP_DAYS = int(os.getenv("OUTREACH_FIRST_FOLLOWUP_DAYS", "3"))
SECOND_FOLLOWUP_DAYS = int(os.getenv("OUTREACH_SECOND_FOLLOWUP_DAYS", "4"))
MAX_FOLLOWUPS = int(os.getenv("OUTREACH_MAX_FOLLOWUPS", "2"))
LOOKBACK_DAYS = max(7, int(os.getenv("OUTREACH_GMAIL_LOOKBACK_DAYS", "45")))


def _clean(value, limit=4000):
    return str(value or "").strip()[:limit]


def _auth_headers():
    return {"Authorization": f"Bearer {gmail_access_token()}"}


def gmail_ready():
    try:
        headers = _auth_headers()
        response = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/profile",
            headers=headers,
            timeout=20,
        )
        if not response.ok:
            return {"ok": False, "reason": f"gmail_profile_{response.status_code}"}
        email = (response.json().get("emailAddress") or "").lower().strip()
        if not email:
            return {"ok": False, "reason": "gmail_profile_missing_email"}
        return {"ok": True, "email": email}
    except Exception as exc:
        text = _clean(exc, 1000).lower()
        if "invalid_grant" in text or "expired or revoked" in text:
            return {"ok": False, "reason": "gmail_authorization_expired"}
        return {"ok": False, "reason": f"gmail_auth_{type(exc).__name__}"}


def _header_map(message):
    return {
        str(item.get("name") or "").lower(): str(item.get("value") or "")
        for item in ((message.get("payload") or {}).get("headers") or [])
    }


def _email_from_header(value):
    return (parseaddr(value or "")[1] or "").lower().strip()


def _recipient_from_header(value):
    addresses = getaddresses([value or ""])
    for _, address in addresses:
        address = (address or "").lower().strip()
        if address:
            return address
    return ""


def _account_email():
    configured = (os.getenv("GMAIL_FROM_EMAIL") or "").lower().strip()
    if configured:
        return configured
    status = gmail_ready()
    return status.get("email", "") if status.get("ok") else ""


def send_tracked_email(to_email, subject, body, company, thread_id="", step="initial"):
    status = gmail_ready()
    if not status.get("ok"):
        return {"ok": False, "error": status.get("reason") or "gmail_not_ready"}
    try:
        msg = EmailMessage()
        msg["To"] = _clean(to_email, 500)
        msg["Subject"] = _clean(subject, 500)
        from_email = os.getenv("GMAIL_FROM_EMAIL", "").strip()
        if from_email:
            msg["From"] = from_email
        msg[TRACK_HEADER] = TRACK_VALUE
        msg[COMPANY_HEADER] = _clean(company, 240)
        msg[STEP_HEADER] = _clean(step, 80)
        msg.set_content(_clean(body, 10000))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
        payload = {"raw": raw}
        if thread_id:
            payload["threadId"] = thread_id

        response = requests.post(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            headers={**_auth_headers(), "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if not response.ok:
            return {"ok": False, "error": f"Gmail error {response.status_code}: {response.text[:500]}"}
        data = response.json()
        return {
            "ok": True,
            "message_id": data.get("id") or "",
            "thread_id": data.get("threadId") or thread_id,
        }
    except Exception as exc:
        return {"ok": False, "error": _clean(exc, 1000)}


def _get_message_metadata(message_id):
    response = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",
        headers=_auth_headers(),
        params={
            "format": "metadata",
            "metadataHeaders": ["From", "To", "Subject", TRACK_HEADER, COMPANY_HEADER, STEP_HEADER],
        },
        timeout=30,
    )
    if not response.ok:
        return None
    return response.json()


def already_contacted(to_email):
    to_email = (to_email or "").lower().strip()
    if not to_email:
        return False
    if not gmail_ready().get("ok"):
        return False
    try:
        response = requests.get(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages",
            headers=_auth_headers(),
            params={"q": f"in:sent to:{to_email} newer_than:{LOOKBACK_DAYS}d", "maxResults": 25},
            timeout=30,
        )
        if not response.ok:
            return False
        for item in response.json().get("messages") or []:
            message = _get_message_metadata(item.get("id"))
            if not message:
                continue
            headers = _header_map(message)
            if headers.get(TRACK_HEADER.lower()) == TRACK_VALUE:
                recipient = _recipient_from_header(headers.get("to", ""))
                if recipient == to_email:
                    return True
        return False
    except Exception:
        return False


def _tracked_sent_messages():
    response = requests.get(
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        headers=_auth_headers(),
        params={"q": f"in:sent newer_than:{LOOKBACK_DAYS}d", "maxResults": 100},
        timeout=30,
    )
    if not response.ok:
        return []

    tracked = []
    for item in response.json().get("messages") or []:
        message = _get_message_metadata(item.get("id"))
        if not message:
            continue
        headers = _header_map(message)
        if headers.get(TRACK_HEADER.lower()) != TRACK_VALUE:
            continue
        tracked.append(message)
    return tracked


def _get_thread(thread_id):
    response = requests.get(
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}",
        headers=_auth_headers(),
        params={
            "format": "metadata",
            "metadataHeaders": ["From", "To", "Subject", TRACK_HEADER, COMPANY_HEADER, STEP_HEADER],
        },
        timeout=30,
    )
    if not response.ok:
        return None
    return response.json()


def _millis_to_dt(value):
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except Exception:
        return None


def _draft_followup(company, recipient, subject, original_snippet, followup_number):
    instructions = (
        "Write a concise professional B2B follow-up email. Use only the supplied facts. "
        "Do not invent names, needs, credentials, dates, projects, or claims. Return strict JSON with one key: body."
    )
    workflow = {
        "company": company,
        "recipient": recipient,
        "original_subject": subject,
        "original_message_snippet": original_snippet,
        "followup_number": followup_number,
    }
    prompt = (
        "Draft a short follow-up to prior outreach. Reference the earlier message naturally, "
        "do not claim the company still needs help unless the supplied text says so, and ask for a simple reply or brief call.\n\n"
        f"WORKFLOW DATA:\n{json.dumps(workflow, indent=2)}"
    )
    result = run_ai(prompt=prompt, instructions=instructions)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "OpenAI follow-up drafting failed."}
    raw = _clean(result.get("output"), 8000)
    try:
        parsed = json.loads(raw)
    except Exception:
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return {"ok": False, "error": "OpenAI did not return valid JSON."}
        try:
            parsed = json.loads(raw[start:end + 1])
        except Exception:
            return {"ok": False, "error": "OpenAI did not return valid JSON."}
    body = _clean(parsed.get("body"), 6000)
    if not body:
        return {"ok": False, "error": "OpenAI response was missing follow-up body."}
    return {"ok": True, "body": body}


def process_durable_followups():
    status = gmail_ready()
    if not status.get("ok"):
        return {"ok": False, "processed": [], "error": status.get("reason") or "gmail_not_ready"}

    now = datetime.now(timezone.utc)
    sender = _account_email()
    if not sender:
        return {"ok": False, "processed": [], "error": "Unable to determine Gmail sender address."}

    tracked = _tracked_sent_messages()
    thread_ids = []
    seen = set()
    for message in tracked:
        thread_id = message.get("threadId") or ""
        if thread_id and thread_id not in seen:
            seen.add(thread_id)
            thread_ids.append(thread_id)

    processed = []
    for thread_id in thread_ids:
        thread = _get_thread(thread_id)
        if not thread:
            processed.append({"thread_id": thread_id, "status": "error", "reason": "thread_lookup_failed"})
            continue

        messages = sorted(thread.get("messages") or [], key=lambda item: int(item.get("internalDate") or 0))
        tracked_messages = []
        replied = False
        for message in messages:
            headers = _header_map(message)
            from_email = _email_from_header(headers.get("from", ""))
            is_tracked = headers.get(TRACK_HEADER.lower()) == TRACK_VALUE
            if is_tracked and from_email == sender:
                tracked_messages.append(message)
            elif from_email and from_email != sender:
                replied = True

        if not tracked_messages:
            continue
        if replied:
            processed.append({"thread_id": thread_id, "status": "responded"})
            continue

        sent_count = len(tracked_messages)
        followups_sent = max(0, sent_count - 1)
        if followups_sent >= MAX_FOLLOWUPS:
            processed.append({"thread_id": thread_id, "status": "completed_no_reply"})
            continue

        latest = tracked_messages[-1]
        latest_at = _millis_to_dt(latest.get("internalDate"))
        if not latest_at:
            processed.append({"thread_id": thread_id, "status": "error", "reason": "missing_internal_date"})
            continue

        wait_days = FIRST_FOLLOWUP_DAYS if followups_sent == 0 else SECOND_FOLLOWUP_DAYS
        if now < latest_at + timedelta(days=wait_days):
            continue

        first_headers = _header_map(tracked_messages[0])
        company = _clean(first_headers.get(COMPANY_HEADER.lower()), 240)
        recipient = _recipient_from_header(first_headers.get("to", ""))
        subject = _clean(first_headers.get("subject"), 500)
        snippet = _clean(tracked_messages[0].get("snippet"), 1500)
        if not company or not recipient or not subject:
            processed.append({"thread_id": thread_id, "status": "error", "reason": "missing_tracked_metadata"})
            continue

        next_number = followups_sent + 1
        drafted = _draft_followup(company, recipient, subject, snippet, next_number)
        if not drafted.get("ok"):
            processed.append({"thread_id": thread_id, "status": "error", "reason": "draft_failed"})
            continue

        sent = send_tracked_email(
            recipient,
            subject,
            drafted["body"],
            company,
            thread_id=thread_id,
            step=f"followup{next_number}",
        )
        if not sent.get("ok"):
            processed.append({"thread_id": thread_id, "status": "error", "reason": "gmail_send_failed"})
            continue

        processed.append({"thread_id": thread_id, "status": "followup_sent", "followup_number": next_number})

    return {"ok": True, "processed": processed, "tracked_threads": len(thread_ids)}
