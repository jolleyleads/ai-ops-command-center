"""Controlled provider-integration acceptance harness.

Does not alter or bypass production lead qualification. It exercises Gmail send
and read-only Calendar availability against an explicitly controlled recipient.
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, gmail_access_token, send_gmail
from src.google_calendar_provider import check_availability


def _result(ok, stage, **extra):
    return {"ok": bool(ok), "stage": stage, "timestamp": datetime.now(timezone.utc).isoformat(), **extra}


def run_provider_integration_acceptance(recipient=None):
    recipient = (recipient or os.getenv("ACCEPTANCE_RECIPIENT") or "").strip().lower()
    sender = (os.getenv("GMAIL_FROM_EMAIL") or "").strip().lower()
    if not recipient or "@" not in recipient:
        return _result(False, "configuration", reason="ACCEPTANCE_RECIPIENT_REQUIRED")
    if not sender:
        return _result(False, "configuration", reason="GMAIL_FROM_EMAIL_REQUIRED")
    if recipient == sender:
        return _result(False, "configuration", reason="RECIPIENT_MUST_DIFFER_FROM_SENDER")

    with app.app_context():
        try:
            token = gmail_access_token()
        except Exception as exc:
            return _result(False, "gmail_auth", reason=str(exc)[:500])
        if not token:
            return _result(False, "gmail_auth", reason="GMAIL_ACCESS_TOKEN_REQUIRED")

        subject = "AI Ops Provider Integration Acceptance"
        body = "Controlled provider integration acceptance message. Reply to this thread to continue reply-ingestion acceptance."
        try:
            sent = send_gmail(recipient, subject, body)
        except Exception as exc:
            return _result(False, "gmail_send", reason=str(exc)[:500])
        if not isinstance(sent, dict):
            return _result(False, "gmail_send", reason="INVALID_GMAIL_PROVIDER_RESPONSE")
        message_id = str(sent.get("id") or sent.get("message_id") or "").strip()
        thread_id = str(sent.get("threadId") or sent.get("thread_id") or "").strip()
        if not message_id or not thread_id:
            return _result(False, "gmail_send", reason="REAL_GMAIL_RECEIPT_REQUIRED", provider=sent)

        start = datetime.now(timezone.utc) + timedelta(days=1)
        start = start.replace(hour=14, minute=0, second=0, microsecond=0)
        end = start + timedelta(minutes=30)
        availability = check_availability({"start": start.isoformat(), "end": end.isoformat(), "timezone": "America/New_York"})
        if not isinstance(availability, dict) or availability.get("ok") is not True:
            return _result(False, "calendar_availability", reason="CALENDAR_AVAILABILITY_RECEIPT_REQUIRED", gmail_message_id=message_id, gmail_thread_id=thread_id, calendar=availability)

        return _result(True, "awaiting_real_reply", recipient=recipient, gmail_message_id=message_id, gmail_thread_id=thread_id, calendar_availability=availability, next_required="Reply to this Gmail thread; production inbound processing must then produce durable reply evidence/classification and the booking path must produce a real Calendar event receipt.")


def main():
    result = run_provider_integration_acceptance()
    print("PROVIDER_INTEGRATION_RESULT " + json.dumps(result, default=str, sort_keys=True))
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
