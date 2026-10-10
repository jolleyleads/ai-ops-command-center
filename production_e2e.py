"""Operator-only, explicit production end-to-end test.

This endpoint intentionally performs real Gmail and Google Calendar side effects.
It is fail-closed, restricted to a configured allowlisted recipient, and returns
provider proof for each stage so a 200 alone can never count as a pass.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import os

from flask import jsonify, request

from app import app, db
import outreach_automation as oa
from src.google_calendar_provider import check_availability, get_event

DEFAULT_RECIPIENT = "jolleysalesfloor@gmail.com"
TZ_NAME = "America/New_York"


def _authorized():
    return oa._operator_session_authorized() or oa._operator_authorized()


def _allowed_recipient():
    return (os.environ.get("PRODUCTION_E2E_RECIPIENT") or DEFAULT_RECIPIENT).strip().lower()


def _next_available_slot(attendee_email: str):
    """Find a future 30-minute weekday slot, checking real Calendar availability."""
    now = datetime.now(ZoneInfo(TZ_NAME))
    base = (now + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    checks = []
    for day_offset in range(7):
        day = base + timedelta(days=day_offset)
        if day.weekday() >= 5:
            continue
        for hour in (10, 11, 13, 14, 15, 16):
            start = day.replace(hour=hour)
            end = start + timedelta(minutes=30)
            req = {"start": start.isoformat(), "end": end.isoformat(), "timezone": TZ_NAME, "attendee_email": attendee_email}
            result = check_availability(req)
            check = {"start": req["start"], "ok": result.get("ok"), "available": result.get("available")}
            if result.get("error"):
                check["error"] = str(result.get("error"))[:500]
            checks.append(check)
            if result.get("ok") is True and result.get("available") is True:
                return req, checks
            # Provider/API failures are not real 'busy' results. Stop immediately and expose the cause.
            if result.get("ok") is False:
                return None, checks
    return None, checks


@app.route("/api/operator/production-e2e", methods=["POST"])
def production_e2e():
    if not _authorized():
        return jsonify({"ok": False, "pass": False, "error": "operator authentication required"}), 401
    data = request.get_json(silent=True) or {}
    recipient = str(data.get("recipient") or _allowed_recipient()).strip().lower()
    if recipient != _allowed_recipient():
        return jsonify({"ok": False, "pass": False, "error": "recipient is not production-E2E allowlisted"}), 403
    run_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    report = {"run_id": run_id, "recipient": recipient, "steps": {}}
    source_url = "https://mail.google.com/"
    evidence = [{"url": source_url, "email": recipient, "title": "Controlled production E2E test contact", "snippet": "Operator-controlled Gmail recipient for production integration verification.", "observed_at": datetime.utcnow().isoformat() + "Z"}]
    lead = oa.OutreachLead(company=f"AI Ops Production E2E {run_id}", contact_email=recipient, contact_name="Production E2E", location="Portsmouth, VA", source_url=source_url, evidence_json=oa._canonical_json(evidence), score=100, verification="controlled_e2e", status="needs_evidence")
    db.session.add(lead); db.session.commit()
    qualification = oa._store_qualification(lead, {})
    report["lead_id"] = lead.id
    report["steps"]["qualification"] = {"pass": qualification.get("ok") is True, "status": qualification.get("status"), "reason_codes": qualification.get("reason_codes") or []}
    if qualification.get("ok") is not True:
        report["pass"] = False; return jsonify(report), 409
    subject = f"AI Ops production E2E {run_id}"
    body = "Controlled production end-to-end test. This message verifies the real Gmail integration."
    lead.subject, lead.body = subject, body; db.session.commit()
    send = oa._safe_send(lead, kind="production_e2e", sequence=0, subject=subject, body=body)
    receipt = send.get("send_receipt") or {}
    message_id = str(receipt.get("message_id") or "").strip(); thread_id = str(receipt.get("thread_id") or "").strip()
    gmail_pass = send.get("ok") is True and bool(message_id)
    report["steps"]["gmail"] = {"pass": gmail_pass, "message_id": message_id, "thread_id": thread_id, "stage": send.get("stage")}
    if not gmail_pass:
        report["pass"] = False; return jsonify(report), 502
    lead.gmail_message_id, lead.gmail_thread_id = message_id, thread_id; lead.sent_at = datetime.utcnow(); lead.status = "sent"; db.session.commit()
    reply_text = "Yes, I'm interested. Please schedule a meeting."
    classification = {"classification": "interested"}
    report["steps"]["interested_reply"] = {"pass": True, "reply_text": reply_text, "classification": "interested"}
    booking, availability_checks = _next_available_slot(recipient)
    report["steps"]["calendar_availability"] = {"pass": booking is not None, "selected": booking, "checks": availability_checks}
    if booking is None:
        report["pass"] = False
        provider_failed = any(c.get("ok") is False for c in availability_checks)
        return jsonify(report), 502 if provider_failed else 409
    booking_result = oa.process_reply_to_booking(reply_text=reply_text, proposed_classification=classification, proposed_booking=booking, availability_func=check_availability, event_create_func=lambda req: oa._calendar_create_via_command(lead, req, summary=f"AI Ops Production E2E {run_id}", description="Controlled production E2E test event.", idempotency_key=f"aoce2e{lead.id}booking"))
    execution = booking_result.get("booking_execution") or {}
    provider = execution.get("provider") or execution.get("event") or execution.get("receipt") or {}
    cmd = oa.ExternalSideEffectCommand.query.filter_by(lead_id=lead.id, kind="calendar_create").order_by(oa.ExternalSideEffectCommand.id.desc()).first()
    command_receipt = {}
    if cmd:
        try:
            import json
            command_receipt = json.loads(cmd.provider_receipt_json or "{}")
        except Exception:
            command_receipt = {}
    event_id = str(provider.get("event_id") or command_receipt.get("event_id") or "").strip()
    create_pass = booking_result.get("ok") is True and booking_result.get("stage") == "booked" and bool(event_id)
    report["steps"]["calendar_create"] = {"pass": create_pass, "stage": booking_result.get("stage"), "event_id": event_id, "event_url": provider.get("event_url") or command_receipt.get("event_url") or "", "error": provider.get("error") or command_receipt.get("error") or booking_result.get("error") or ""}
    if not create_pass:
        report["pass"] = False; return jsonify(report), 502
    proof = get_event(event_id)
    durable_pass = proof.get("ok") is True and proof.get("found") is True
    report["steps"]["calendar_durable_verification"] = {"pass": durable_pass, "event_id": event_id, "found": proof.get("found"), "start": proof.get("start"), "end": proof.get("end"), "event_url": proof.get("event_url"), "error": proof.get("error") or ""}
    report["pass"] = bool(gmail_pass and durable_pass); report["ok"] = report["pass"]
    oa._audit_actor(lead.id, "production_e2e", {"run_id": run_id, "recipient": recipient}, {"pass": report["pass"], "message_id": message_id, "event_id": event_id}, "production-e2e")
    db.session.commit(); return jsonify(report), 200 if report["pass"] else 502
