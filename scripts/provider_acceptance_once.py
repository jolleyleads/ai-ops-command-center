"""One-shot production provider acceptance runner.

This runner intentionally does not simulate provider receipts.  It creates a
controlled test lead through the application's existing persistence model and
uses the existing production outreach/reply/booking machinery.  It is designed
for an operator-controlled acceptance test where the recipient sends a real
reply before the second invocation.

Usage:
  ACCEPTANCE_RECIPIENT=jolleysalesfloor@gmail.com \
    python scripts/provider_acceptance_once.py

Run it once to seed/send the controlled outreach. After the recipient replies
with an interested response, run it again (or let the production scheduler
process the reply) and inspect the durable lead/audit/provider state.
"""

import json
import os
import sys
from datetime import datetime, timezone

# Keep repo-root imports deterministic when invoked as scripts/foo.py.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db, Lead
from outreach_scheduler import run_scheduled_outreach_cycle


def _fail(reason, **extra):
    result = {"ok": False, "reason": reason, **extra}
    print("PROVIDER_ACCEPTANCE_RESULT " + json.dumps(result, default=str, sort_keys=True))
    raise SystemExit(1)


def _lead_snapshot(lead):
    # Only expose non-secret, acceptance-relevant durable fields that actually
    # exist on the production model. This avoids inventing provider proof.
    wanted = (
        "id", "company_name", "email", "status", "outreach_status",
        "gmail_message_id", "gmail_thread_id", "reply_message_id",
        "reply_classification", "calendar_event_id", "calendar_event_link",
        "last_error", "next_action", "updated_at",
    )
    return {name: getattr(lead, name) for name in wanted if hasattr(lead, name)}


def main():
    recipient = (os.getenv("ACCEPTANCE_RECIPIENT") or "").strip().lower()
    if not recipient or "@" not in recipient:
        _fail("ACCEPTANCE_RECIPIENT_REQUIRED")

    sender = (os.getenv("GMAIL_FROM_EMAIL") or "").strip().lower()
    if not sender:
        _fail("GMAIL_FROM_EMAIL_REQUIRED")
    if recipient == sender:
        _fail("RECIPIENT_MUST_DIFFER_FROM_SENDER")

    with app.app_context():
        # Reuse one durable acceptance lead so repeated invocations cannot
        # accidentally create/send duplicate test threads.
        marker = "Provider Acceptance E2E"
        lead = Lead.query.filter_by(email=recipient).filter(Lead.company_name == marker).order_by(Lead.id.desc()).first()

        created = False
        if lead is None:
            # Set only fields known to exist. The production scheduler remains
            # responsible for deciding whether the lead is eligible to send.
            lead = Lead(company_name=marker, email=recipient)
            if hasattr(lead, "contact_name"):
                lead.contact_name = "Acceptance Test"
            if hasattr(lead, "status"):
                lead.status = "qualified"
            if hasattr(lead, "qualification_status"):
                lead.qualification_status = "Qualified"
            if hasattr(lead, "verified"):
                lead.verified = True
            if hasattr(lead, "next_action"):
                lead.next_action = "provider_acceptance"
            db.session.add(lead)
            db.session.commit()
            created = True

        before = _lead_snapshot(lead)
        cycle = run_scheduled_outreach_cycle()
        db.session.expire_all()
        lead = db.session.get(Lead, lead.id)
        after = _lead_snapshot(lead)

        result = {
            "ok": bool(cycle.get("ok")),
            "acceptance": True,
            "recipient": recipient,
            "sender": sender,
            "lead_id": lead.id,
            "created": created,
            "before": before,
            "after": after,
            "cycle": cycle,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        print("PROVIDER_ACCEPTANCE_RESULT " + json.dumps(result, default=str, sort_keys=True))

        if not result["ok"]:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
