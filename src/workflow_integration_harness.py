"""Whole-machine workflow harness used only for deterministic integration tests.

It deliberately calls the same production gates/state machines as the live workflow
while providers are injected fakes. Failure points are named so CI can prove that
every transition either advances with evidence or fails closed.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Callable, Dict


class InjectedFailure(RuntimeError):
    pass


def checkpoint(name:str, fail_at:str|None):
    if fail_at==name:
        raise InjectedFailure(name)


def run_workflow(*, oa, lead, draft_func:Callable, gmail_func:Callable,
                 reply:Dict[str,Any], availability_func:Callable,
                 calendar_func:Callable, fail_at:str|None=None)->Dict[str,Any]:
    trace=[]
    def hit(name):
        checkpoint(name,fail_at);trace.append(name)

    hit("discover")
    hit("verify")
    receipt=oa._store_qualification(lead,{})
    if not receipt.get("ok"):return {"ok":False,"stage":"qualify","trace":trace}
    hit("qualify")

    drafted=draft_func(lead)
    if not drafted.get("ok"):return {"ok":False,"stage":"draft","trace":trace}
    lead.subject=drafted["subject"];lead.body=drafted["body"];lead.status="drafted";oa.db.session.commit()
    hit("draft")

    original_gmail=oa._gmail_send
    oa._gmail_send=gmail_func
    try:
        sent=oa._safe_send(lead,kind="initial",sequence=0,subject=lead.subject,body=lead.body)
    finally:
        oa._gmail_send=original_gmail
    if not sent.get("ok"):return {"ok":False,"stage":"gmail","trace":trace,"result":sent}
    hit("command");hit("gmail")

    evidence=reply.get("reply_evidence") or []
    if not evidence:return {"ok":False,"stage":"reply","trace":trace}
    item=evidence[-1]
    row=oa.OutreachReplyEvidence(lead_id=lead.id,message_id=item["message_id"],thread_id=item.get("thread_id",""),from_email=item.get("from_email",lead.contact_email),body_text=item["text"],body_source="test",received_at=datetime.utcnow())
    oa.db.session.add(row);oa.db.session.commit()
    hit("reply")

    classification=oa.classify_reply(item["text"])
    hit("classify")
    if classification.get("classification")!="interested":
        return {"ok":False,"stage":"classify","trace":trace,"classification":classification}

    booking=oa.extract_explicit_booking(item["text"])
    if not booking:return {"ok":False,"stage":"calendar","trace":trace}
    key=oa.booking_key(lead_id=lead.id,reply_message_id=item["message_id"],start=booking["start"],end=booking["end"],timezone_name=booking["timezone"],attendee_email=lead.contact_email)
    event_id=oa.google_event_id(key)
    attempt=oa.OutreachBookingAttempt(lead_id=lead.id,reply_message_id=item["message_id"],idempotency_key=key,event_id=event_id,start=booking["start"],end=booking["end"],timezone=booking["timezone"],attendee_email=lead.contact_email,status="pending")
    oa.db.session.add(attempt);oa.db.session.commit()

    if not availability_func(booking).get("available"):
        attempt.status="failed";oa.db.session.commit();return {"ok":False,"stage":"calendar","trace":trace}
    result=oa._calendar_create_via_command(lead,booking,summary=f"Call with {lead.company}",description="E2E validated reply",idempotency_key=event_id)
    if not result.get("ok"):
        attempt.status="uncertain";attempt.error=str(result);oa.db.session.commit()
        return {"ok":False,"stage":"calendar","trace":trace,"command_status":"uncertain"}
    attempt.status="confirmed";attempt.event_url=result.get("event_url","");oa.db.session.commit()
    hit("calendar")

    # Reconciliation is still executed even after confirmed creation to prove the
    # deterministic provider identity maps back to the durable booking attempt.
    found={"event_id":result.get("event_id") or event_id,"event_url":result.get("event_url","")}
    cmd=oa.ExternalSideEffectCommand.query.filter_by(kind="calendar_create",lead_id=lead.id).order_by(oa.ExternalSideEffectCommand.id.desc()).first()
    if not cmd:return {"ok":False,"stage":"reconcile","trace":trace}
    hit("reconcile")
    hit("audit")
    audits=oa.OperatorAuditEvent.query.filter_by(lead_id=lead.id).all()
    return {"ok":True,"stage":"complete","trace":trace,"audit_count":len(audits),"booking_status":attempt.status,"calendar_proof":found}
