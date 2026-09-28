"""Controlled provider-integration acceptance harness.

This intentionally does NOT alter or bypass production lead qualification.
It exercises provider plumbing with an explicitly configured controlled recipient.
"""
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, gmail_access_token, send_gmail
from src.google_calendar_provider import check_availability


def emit(ok, stage, **extra):
    result = {"ok": bool(ok), "stage": stage, "timestamp": datetime.now(timezone.utc).isoformat(), **extra}
    print("PROVIDER_INTEGRATION_RESULT " + json.dumps(result, default=str, sort_keys=True))
    if not ok:
        raise SystemExit(1)
    return result


def main():
    recipient = (os.getenv("ACCEPTANCE_RECIPIENT") or "").strip().lower()
    sender = (os.getenv("GMAIL_FROM_EMAIL") or "").strip().lower()
    if not recipient or "@" not in recipient:
        emit(False, "configuration", reason="ACCEPTANCE_RECIPIENT_REQUIRED")
    if not sender:
        emit(False, "configuration", reason="GMAIL_FROM_EMAIL_REQUIRED")
    if recipient == sender:
        emit(False, "configuration", reason="RECIPIENT_MUST_DIFFER_FROM_SENDER")

    with app.app_context():
        token = gmail_access_token()
        if not token:
            emit(False, "gmail_auth", reason="GMAIL_ACCESS_TOKEN_REQUIRED")

        subject = "AI Ops Provider Integration Acceptance"
        body = "Controlled provider integration acceptance message. Reply to this thread to continue reply-ingestion acceptance."
        sent = send_gmail(token, recipient, subject, body)
        if not isinstance(sent, dict):
            emit(False, "gmail_send", reason="INVALID_GMAIL_PROVIDER_RESPONSE", provider=sent)
        message_id = str(sent.get("id") or sent.get("message_id") or "").strip()
        thread_id = str(sent.get("threadId") or sent.get("thread_id") or "").strip()
        if not message_id or not thread_id:
            emit(False, "gmail_send", reason="REAL_GMAIL_RECEIPT_REQUIRED", provider=sent)

        # Availability is read-only and safe to verify immediately. Event creation is
        # deliberately left to the real reply->booking production path after a real reply.
        availability = check_availability({})
        if not isinstance(availability, dict) or availability.get("ok") is not True:
            emit(False, "calendar_availability", reason="CALENDAR_AVAILABILITY_RECEIPT_REQUIRED", gmail_message_id=message_id, gmail_thread_id=thread_id, calendar=availability)

        emit(True, "awaiting_real_reply", recipient=recipient, gmail_message_id=message_id, gmail_thread_id=thread_id, calendar_availability=availability, next_required="Reply to the Gmail thread; production reply ingestion/classification/booking must then produce durable reply evidence and a real calendar event receipt.")


if __name__ == "__main__":
    main()
