"""One-shot production provider acceptance runner."""
import json
import os
import sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app import app, db
from outreach_automation import OutreachLead, _safe_send
from outreach_scheduler import run_scheduled_outreach_cycle

def fail(reason, **extra):
    print("PROVIDER_ACCEPTANCE_RESULT " + json.dumps({"ok": False, "reason": reason, **extra}, default=str, sort_keys=True))
    raise SystemExit(1)

def snapshot(lead):
    return {"id": lead.id, "company": lead.company, "contact_email": lead.contact_email, "status": lead.status, "gmail_message_id": lead.gmail_message_id, "gmail_thread_id": lead.gmail_thread_id, "sent_at": lead.sent_at, "replied_at": lead.replied_at, "last_error": lead.last_error}

def main():
    recipient = (os.getenv("ACCEPTANCE_RECIPIENT") or "").strip().lower()
    sender = (os.getenv("GMAIL_FROM_EMAIL") or "").strip().lower()
    if not recipient or "@" not in recipient: fail("ACCEPTANCE_RECIPIENT_REQUIRED")
    if not sender: fail("GMAIL_FROM_EMAIL_REQUIRED")
    if recipient == sender: fail("RECIPIENT_MUST_DIFFER_FROM_SENDER")
    with app.app_context():
        marker = "Provider Acceptance E2E"
        lead = OutreachLead.query.filter_by(contact_email=recipient, company=marker).order_by(OutreachLead.id.desc()).first()
        created = False
        if lead is None:
            lead = OutreachLead(company=marker, contact_email=recipient, contact_name="Acceptance Test", location="Production Acceptance", source_url="provider-acceptance", evidence_json="[]", score=100, verification="SOURCE_VERIFIED", status="qualified", subject="AI Ops provider acceptance test", body="Production acceptance test. Please reply that you are interested and include a specific meeting time.")
            db.session.add(lead)
            db.session.commit()
            created = True
        before = snapshot(lead)
        send_result = None
        if not (lead.gmail_message_id and lead.gmail_thread_id and lead.sent_at):
            send_result = _safe_send(lead, kind="initial", sequence=0, subject=lead.subject, body=lead.body)
            db.session.expire_all()
            lead = db.session.get(OutreachLead, lead.id)
        if not (lead.gmail_message_id and lead.gmail_thread_id and lead.sent_at):
            fail("PROVIDER_BACKED_GMAIL_SEND_REQUIRED", lead_id=lead.id, send_result=send_result, after=snapshot(lead))
        cycle = run_scheduled_outreach_cycle()
        db.session.expire_all()
        lead = db.session.get(OutreachLead, lead.id)
        result = {"ok": bool(cycle.get("ok")) and bool(lead.gmail_message_id) and bool(lead.gmail_thread_id), "recipient": recipient, "lead_id": lead.id, "created": created, "before": before, "send_result": send_result, "after": snapshot(lead), "cycle": cycle, "timestamp": datetime.now(timezone.utc).isoformat()}
        print("PROVIDER_ACCEPTANCE_RESULT " + json.dumps(result, default=str, sort_keys=True))
        if not result["ok"]: raise SystemExit(1)

if __name__ == "__main__":
    main()
