import json
import os
import hashlib
import hmac
from datetime import datetime, timedelta
from typing import Any, Dict

import requests
from flask import jsonify, request, Response, session, redirect, url_for
from sqlalchemy.exc import IntegrityError

from app import app, db, gmail_access_token, send_gmail
from src.services import run_ai
from src.outreach_execution import validate_outreach_message, execute_outreach_send
from src.followup_control import classify_inbound, followup_permission
from src.reply_booking_handoff import process_reply_to_booking
from src.google_calendar_provider import check_availability, create_event, get_event
from src.outreach_safety import normalize_email, send_key, suppression_gate, send_attempt_gate
from src.gmail_reply_parser import message_to_evidence
from src.automatic_reply_router import classify_reply, extract_explicit_booking
from src.booking_safety import booking_key, google_event_id, attempt_gate
from src.qualification import qualify_lead, QUALIFIED
from src.operational_state import state_snapshot
from src.side_effect_outbox import command_key, lease_token, provider_outcome

AUTO_SEND_MIN_SCORE = int(os.getenv("OUTREACH_AUTO_SEND_MIN_SCORE", "75"))
REVIEW_MIN_SCORE = int(os.getenv("OUTREACH_REVIEW_MIN_SCORE", "60"))
FIRST_FOLLOWUP_DAYS = int(os.getenv("OUTREACH_FIRST_FOLLOWUP_DAYS", "3"))
SECOND_FOLLOWUP_DAYS = int(os.getenv("OUTREACH_SECOND_FOLLOWUP_DAYS", "4"))
MAX_FOLLOWUPS = int(os.getenv("OUTREACH_MAX_FOLLOWUPS", "2"))


class OutreachLead(db.Model):
    __tablename__ = "outreach_lead"

    id = db.Column(db.Integer, primary_key=True)
    company = db.Column(db.String(300), nullable=False)
    contact_email = db.Column(db.String(500), default="")
    contact_name = db.Column(db.String(300), default="")
    location = db.Column(db.String(300), default="")
    source_url = db.Column(db.Text, default="")
    evidence_json = db.Column(db.Text, default="[]")
    score = db.Column(db.Integer, nullable=False, default=0)
    verification = db.Column(db.String(100), default="")
    status = db.Column(db.String(50), nullable=False, default="review")
    subject = db.Column(db.String(500), default="")
    body = db.Column(db.Text, default="")
    gmail_message_id = db.Column(db.String(255), default="")
    gmail_thread_id = db.Column(db.String(255), default="")
    sent_at = db.Column(db.DateTime)
    follow_up_due_at = db.Column(db.DateTime)
    follow_up_count = db.Column(db.Integer, nullable=False, default=0)
    replied_at = db.Column(db.DateTime)
    last_error = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class OutreachSuppression(db.Model):
    __tablename__ = "outreach_suppression"
    id = db.Column(db.Integer, primary_key=True)
    normalized_email = db.Column(db.String(500), nullable=False, unique=True, index=True)
    reason = db.Column(db.String(100), nullable=False, default="opt_out")
    source_message_id = db.Column(db.String(255), default="")
    source_thread_id = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class OutreachSendAttempt(db.Model):
    __tablename__ = "outreach_send_attempt"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(50), nullable=False)
    sequence = db.Column(db.Integer, nullable=False, default=0)
    recipient = db.Column(db.String(500), nullable=False)
    idempotency_key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    status = db.Column(db.String(30), nullable=False, default="pending")
    message_id = db.Column(db.String(255), default="")
    thread_id = db.Column(db.String(255), default="")
    error = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class OutreachReplyEvidence(db.Model):
    __tablename__ = "outreach_reply_evidence"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, nullable=False, index=True)
    message_id = db.Column(db.String(255), nullable=False, unique=True, index=True)
    thread_id = db.Column(db.String(255), default="")
    from_email = db.Column(db.String(500), default="", index=True)
    body_text = db.Column(db.Text, default="")
    body_source = db.Column(db.String(50), default="")
    opted_out = db.Column(db.Boolean, nullable=False, default=False)
    received_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class OutreachBookingAttempt(db.Model):
    __tablename__ = "outreach_booking_attempt"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, nullable=False, index=True)
    reply_message_id = db.Column(db.String(255), nullable=False, index=True)
    idempotency_key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    event_id = db.Column(db.String(255), nullable=False, unique=True, index=True)
    start = db.Column(db.String(100), nullable=False)
    end = db.Column(db.String(100), nullable=False)
    timezone = db.Column(db.String(100), nullable=False)
    attendee_email = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(30), nullable=False, default="pending")
    event_url = db.Column(db.Text, default="")
    error = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExternalSideEffectCommand(db.Model):
    __tablename__ = "external_side_effect_command"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, nullable=False, index=True)
    kind = db.Column(db.String(50), nullable=False, index=True)
    idempotency_key = db.Column(db.String(64), nullable=False, unique=True, index=True)
    payload_json = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(30), nullable=False, default="pending", index=True)
    lease_token = db.Column(db.String(64), default="")
    lease_expires_at = db.Column(db.DateTime)
    provider_receipt_json = db.Column(db.Text, default="{}")
    error = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class OutreachQualificationReceipt(db.Model):
    __tablename__ = "outreach_qualification_receipt"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, nullable=False, unique=True, index=True)
    status = db.Column(db.String(50), nullable=False)
    qualified = db.Column(db.Boolean, nullable=False, default=False)
    ok = db.Column(db.Boolean, nullable=False, default=False)
    receipt_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class OperatorAuditEvent(db.Model):
    __tablename__ = "operator_audit_event"
    id = db.Column(db.Integer, primary_key=True)
    lead_id = db.Column(db.Integer, nullable=False, index=True)
    action = db.Column(db.String(50), nullable=False)
    actor = db.Column(db.String(200), nullable=False, default="operator")
    request_json = db.Column(db.Text, nullable=False, default="{}")
    result_json = db.Column(db.Text, nullable=False, default="{}")
    previous_hash = db.Column(db.String(64), nullable=False, default="")
    event_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


with app.app_context():
    db.create_all()


def _operator_authorized() -> bool:
    expected=os.environ.get("OPERATOR_CONTROL_TOKEN","")
    supplied=request.headers.get("X-Operator-Token","")
    return bool(expected and supplied and hmac.compare_digest(expected,supplied))

def _audit(lead_id:int, action:str, payload:Dict[str,Any], result:Dict[str,Any]) -> None:
    # Serialize audit writers in PostgreSQL so two operator actions cannot fork the chain.
    if db.engine.dialect.name=="postgresql":
        db.session.execute(db.text("SELECT pg_advisory_xact_lock(:key)"),{"key":90421001})
    prev=OperatorAuditEvent.query.order_by(OperatorAuditEvent.id.desc()).first()
    previous_hash=prev.event_hash if prev else ""
    actor=_clean(request.headers.get("X-Operator-Actor") or "operator",200)
    request_json=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str)
    result_json=json.dumps(result,sort_keys=True,separators=(",",":"),default=str)
    created=datetime.utcnow()
    raw="|".join([previous_hash,str(lead_id),action,actor,request_json,result_json,created.isoformat()])
    event_hash=hashlib.sha256(raw.encode()).hexdigest()
    db.session.add(OperatorAuditEvent(lead_id=lead_id,action=action,actor=actor,request_json=request_json,result_json=result_json,previous_hash=previous_hash,event_hash=event_hash,created_at=created))

def _audit_actor(lead_id:int, action:str, payload:Dict[str,Any], result:Dict[str,Any], actor:str) -> None:
    if db.engine.dialect.name=="postgresql":
        db.session.execute(db.text("SELECT pg_advisory_xact_lock(:key)"),{"key":90421001})
    prev=OperatorAuditEvent.query.order_by(OperatorAuditEvent.id.desc()).first()
    previous_hash=prev.event_hash if prev else ""
    request_json=json.dumps(payload,sort_keys=True,separators=(",",":"),default=str)
    result_json=json.dumps(result,sort_keys=True,separators=(",",":"),default=str)
    created=datetime.utcnow()
    raw="|".join([previous_hash,str(lead_id),action,actor,request_json,result_json,created.isoformat()])
    event_hash=hashlib.sha256(raw.encode()).hexdigest()
    db.session.add(OperatorAuditEvent(lead_id=lead_id,action=action,actor=actor,request_json=request_json,result_json=result_json,previous_hash=previous_hash,event_hash=event_hash,created_at=created))

def _enqueue_external_command(lead:OutreachLead, kind:str, payload:Dict[str,Any]) -> ExternalSideEffectCommand:
    key=command_key(kind,lead.id,payload)
    existing=ExternalSideEffectCommand.query.filter_by(idempotency_key=key).first()
    if existing:return existing
    cmd=ExternalSideEffectCommand(lead_id=lead.id,kind=kind,idempotency_key=key,payload_json=_canonical_json(payload),status="pending")
    db.session.add(cmd)
    _audit_actor(lead.id,"external_command_intent",{"command_key":key,"kind":kind},{"status":"pending"},"system")
    try:db.session.commit()
    except IntegrityError:
        db.session.rollback()
        return ExternalSideEffectCommand.query.filter_by(idempotency_key=key).one()
    return cmd

def _claim_external_command(cmd:ExternalSideEffectCommand, lease_seconds:int=120) -> str:
    if cmd.status!="pending":return ""
    token=lease_token();now=datetime.utcnow()
    updated=ExternalSideEffectCommand.query.filter_by(id=cmd.id,status="pending").update({"status":"executing","lease_token":token,"lease_expires_at":now+timedelta(seconds=lease_seconds),"updated_at":now},synchronize_session=False)
    if updated!=1:
        db.session.rollback();return ""
    db.session.commit();return token

def _finish_external_command(cmd_id:int, token:str, result:Dict[str,Any]|None=None, exc:BaseException|None=None) -> Dict[str,Any]:
    cmd=db.session.get(ExternalSideEffectCommand,cmd_id)
    if not cmd or cmd.status!="executing" or not token or not hmac.compare_digest(cmd.lease_token or "",token):
        return {"ok":False,"stage":"lease_lost"}
    status=provider_outcome(result,exc)
    cmd.status=status;cmd.lease_token="";cmd.lease_expires_at=None;cmd.updated_at=datetime.utcnow()
    cmd.provider_receipt_json=_canonical_json(result or {})
    cmd.error=_clean(str(exc) if exc else ((result or {}).get("error") or ""),2000)
    _audit_actor(cmd.lead_id,"external_command_complete",{"command_key":cmd.idempotency_key,"kind":cmd.kind},{"status":status,"provider":result or {}}, "system")
    db.session.commit()
    return {"ok":status=="succeeded","status":status,"command_id":cmd.id}

def _expire_stale_external_commands(now:datetime|None=None) -> int:
    now=now or datetime.utcnow()
    rows=ExternalSideEffectCommand.query.filter(ExternalSideEffectCommand.status=="executing",ExternalSideEffectCommand.lease_expires_at<=now).all()
    for cmd in rows:
        cmd.status="uncertain";cmd.lease_token="";cmd.lease_expires_at=None;cmd.error="WORKER_LEASE_EXPIRED"
        _audit_actor(cmd.lead_id,"external_command_lease_expired",{"command_key":cmd.idempotency_key},{"status":"uncertain"},"system")
    if rows:db.session.commit()
    return len(rows)

def _control_response(lead:OutreachLead, action:str, payload:Dict[str,Any], result:Dict[str,Any], status:int=200):
    # Business mutation and audit append commit together for database-only actions.
    _audit(lead.id,action,payload,result)
    db.session.commit()
    return jsonify(result),status


def _clean(value: Any, limit: int = 4000) -> str:
    return str(value or "").strip()[:limit]


def _serialize(lead: OutreachLead) -> Dict[str, Any]:
    try:
        evidence = json.loads(lead.evidence_json or "[]")
    except Exception:
        evidence = []

    return {
        "id": lead.id,
        "company": lead.company,
        "contact_email": lead.contact_email,
        "contact_name": lead.contact_name,
        "location": lead.location,
        "source_url": lead.source_url,
        "evidence": evidence,
        "score": lead.score,
        "verification": lead.verification,
        "status": lead.status,
        "subject": lead.subject,
        "body": lead.body,
        "gmail_message_id": lead.gmail_message_id,
        "gmail_thread_id": lead.gmail_thread_id,
        "sent_at": lead.sent_at.isoformat() if lead.sent_at else None,
        "follow_up_due_at": lead.follow_up_due_at.isoformat() if lead.follow_up_due_at else None,
        "follow_up_count": lead.follow_up_count,
        "replied_at": lead.replied_at.isoformat() if lead.replied_at else None,
        "last_error": lead.last_error,
        "created_at": lead.created_at.isoformat() if lead.created_at else None,
        "updated_at": lead.updated_at.isoformat() if lead.updated_at else None,
        "operational": _operational_snapshot(lead),
    }


def _latest_attempt_status(model, lead_id: int) -> str:
    row=model.query.filter_by(lead_id=lead_id).order_by(model.updated_at.desc()).first()
    return row.status if row else ""

def _operational_snapshot(lead: OutreachLead) -> Dict[str, Any]:
    return state_snapshot(
        status=lead.status,last_error=lead.last_error,
        send_status=_latest_attempt_status(OutreachSendAttempt,lead.id),
        booking_status=_latest_attempt_status(OutreachBookingAttempt,lead.id),
    )

def _commit_unique_or_existing(model, lookup: Dict[str, Any]):
    try:
        db.session.commit()
        return None
    except IntegrityError:
        db.session.rollback()
        return model.query.filter_by(**lookup).first()


def _qualification_keyring() -> tuple[str,Dict[str,bytes]]:
    active=_clean(os.environ.get("QUALIFICATION_SIGNING_KEY_VERSION"),64)
    keys:Dict[str,bytes]={}
    raw=os.environ.get("QUALIFICATION_SIGNING_KEYS","")
    # Format: version=secret,version2=secret2. Secrets never enter receipts/logs.
    for item in raw.split(","):
        if "=" not in item:continue
        version,secret=item.split("=",1)
        version=_clean(version,64);secret=secret.strip()
        if version and secret:keys[version]=secret.encode("utf-8")
    return active,keys

def _qualification_signing_key(version: str|None=None) -> tuple[str,bytes]:
    active,keys=_qualification_keyring()
    selected=_clean(version,64) if version else active
    return selected,keys.get(selected,b"")

def _canonical_json(value: Any) -> str:
    return json.dumps(value,sort_keys=True,separators=(",",":"),default=str)

def _server_qualification_inputs(lead: OutreachLead) -> tuple[Dict[str,Any],Dict[str,Any],list[Dict[str,Any]]]:
    # Only persisted server state is authoritative. Request booleans/context are ignored.
    try: raw=json.loads(lead.evidence_json or "[]")
    except Exception: raw=[]
    evidence=[x for x in raw if isinstance(x,dict)]
    validated={
        "company_name":_clean(lead.company,300),
        "email":normalize_email(lead.contact_email),
        "website":_clean(lead.source_url,1800),
        "website_source_url":_clean(lead.source_url,1800),
        "evidence":evidence,
    }
    # Contact provenance must be present in persisted evidence and bind this exact address.
    email=normalize_email(lead.contact_email)
    contact_source=""
    for item in evidence:
        candidate=normalize_email(item.get("email") or item.get("contact_email"))
        url=_clean(item.get("url") or item.get("source_url"),1800)
        if email and candidate==email and url.startswith(("http://","https://")):
            contact_source=url;break
    validated["email_source_url"]=contact_source
    context={"candidate_location":_clean(lead.location,300),"lead_location":_clean(lead.location,300),"evidence":evidence}
    return validated,context,evidence

def _qualification_evidence_digest(lead: OutreachLead, validated: Dict[str,Any], context: Dict[str,Any]) -> str:
    bound={"lead_id":lead.id,"company":_clean(lead.company,300),"email":normalize_email(lead.contact_email),"location":_clean(lead.location,300),"source_url":_clean(lead.source_url,1800),"validated":validated,"context":context}
    return hashlib.sha256(_canonical_json(bound).encode()).hexdigest()

def _sign_qualification(receipt: Dict[str,Any], evidence_digest: str) -> Dict[str,Any]:
    key_version,key=_qualification_signing_key()
    if not key_version or not key:
        return {**receipt,"ok":False,"qualified":False,"status":"Needs More Evidence","reason_codes":["QUALIFICATION_SIGNING_KEY_MISSING"],"evidence_digest":evidence_digest}
    payload={**receipt,"evidence_digest":evidence_digest,"signature_version":"hmac-sha256-v1","key_version":key_version}
    sig=hmac.new(key,_canonical_json(payload).encode(),hashlib.sha256).hexdigest()
    return {**payload,"server_signature":sig}

def _qualification_gate(lead: OutreachLead) -> Dict[str, Any]:
    row=OutreachQualificationReceipt.query.filter_by(lead_id=lead.id).first()
    if row is None:
        return {"ok":False,"qualified":False,"status":"Needs More Evidence","reason_codes":["MISSING_QUALIFICATION_RECEIPT"]}
    try:receipt=json.loads(row.receipt_json or "{}")
    except Exception:receipt={}
    signature=_clean(receipt.get("server_signature"),128)
    unsigned={k:v for k,v in receipt.items() if k!="server_signature"}
    key_version=_clean(receipt.get("key_version"),64)
    resolved_version,key=_qualification_signing_key(key_version)
    expected=hmac.new(key,_canonical_json(unsigned).encode(),hashlib.sha256).hexdigest() if key and resolved_version==key_version else ""
    validated,context,_=_server_qualification_inputs(lead)
    current_digest=_qualification_evidence_digest(lead,validated,context)
    signature_ok=bool(signature and expected and hmac.compare_digest(signature,expected))
    evidence_ok=bool(receipt.get("evidence_digest") and hmac.compare_digest(str(receipt.get("evidence_digest")),current_digest))
    valid=bool(row.ok is True and row.qualified is True and row.status==QUALIFIED and receipt.get("ok") is True and receipt.get("qualified") is True and receipt.get("status")==QUALIFIED and signature_ok and evidence_ok)
    if not valid:
        reasons=list(receipt.get("reason_codes") or [])
        if not signature_ok:reasons.append("QUALIFICATION_SIGNATURE_INVALID")
        if not evidence_ok:reasons.append("QUALIFICATION_EVIDENCE_CHANGED")
        return {"ok":False,"qualified":False,"status":row.status,"reason_codes":list(dict.fromkeys(reasons or ["QUALIFICATION_NOT_VALIDATED"]))}
    return {"ok":True,"qualified":True,"status":QUALIFIED,"receipt":receipt}

def _store_qualification(lead: OutreachLead, data: Dict[str, Any]|None=None) -> Dict[str, Any]:
    # data is intentionally ignored for trust decisions. Qualification is derived
    # entirely from persisted lead/evidence state on the server.
    validated,context,evidence=_server_qualification_inputs(lead)
    verification_ok=bool(_clean(lead.company,300) and evidence)
    receipt=qualify_lead(validated,verification_ok=verification_ok,context=context)
    digest=_qualification_evidence_digest(lead,validated,context)
    receipt=_sign_qualification(receipt,digest)
    row=OutreachQualificationReceipt.query.filter_by(lead_id=lead.id).first()
    if row is None:
        row=OutreachQualificationReceipt(lead_id=lead.id,status=receipt["status"],qualified=receipt["qualified"],ok=receipt["ok"],receipt_json=_canonical_json(receipt))
        db.session.add(row)
    else:
        row.status=receipt["status"];row.qualified=receipt["qualified"];row.ok=receipt["ok"];row.receipt_json=_canonical_json(receipt)
    lead.status="qualified" if receipt.get("ok") else ("rejected" if receipt.get("status")=="Not Qualified" else "needs_evidence")
    lead.last_error="" if receipt.get("ok") else ", ".join(receipt.get("reason_codes") or [])
    db.session.commit()
    return receipt


def _is_suppressed(email: str) -> bool:
    address=normalize_email(email)
    return bool(address and OutreachSuppression.query.filter_by(normalized_email=address).first())


def _suppress(email: str, reason: str="opt_out", message_id: str="", thread_id: str="") -> None:
    address=normalize_email(email)
    if not address:
        return
    row=OutreachSuppression.query.filter_by(normalized_email=address).first()
    if row is None:
        row=OutreachSuppression(normalized_email=address)
        db.session.add(row)
        existing=_commit_unique_or_existing(OutreachSuppression,{"normalized_email":address})
        if existing is not None:row=existing
    row.reason=_clean(reason,100) or "opt_out"
    row.source_message_id=_clean(message_id,255)
    row.source_thread_id=_clean(thread_id,255)


def _safe_send(lead: OutreachLead, *, kind: str, sequence: int, subject: str, body: str) -> Dict[str, Any]:
    qualification=_qualification_gate(lead)
    if not qualification.get("ok"):
        return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":["QUALIFICATION_REQUIRED"],"qualification":qualification}}
    address=normalize_email(lead.contact_email)
    sg=suppression_gate(address,_is_suppressed(address))
    if not sg.get("ok"):
        return {"ok":False,"stage":"blocked","gate":sg}
    key=send_key(lead_id=lead.id,kind=kind,sequence=sequence,recipient=address)
    attempt=OutreachSendAttempt.query.filter_by(idempotency_key=key).first()
    ag=send_attempt_gate(attempt.status if attempt else "")
    if attempt is not None and attempt.status=="failed":
        return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":["FAILED_ATTEMPT_REQUIRES_OPERATOR_REVIEW"]},"attempt_status":"failed"}
    if not ag.get("allowed"):
        return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":[ag["reason"]]},"attempt_status":attempt.status if attempt else ""}
    if attempt is None:
        attempt=OutreachSendAttempt(lead_id=lead.id,kind=kind,sequence=sequence,recipient=address,idempotency_key=key,status="pending")
        db.session.add(attempt)
        existing=_commit_unique_or_existing(OutreachSendAttempt,{"idempotency_key":key})
        if existing is not None:
            return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":["CONCURRENT_SEND_ATTEMPT_EXISTS"]},"attempt_status":existing.status}
    # Pending is committed before provider execution. If the process dies after Gmail
    # accepts the message, the next run fails closed instead of duplicating the send.
    payload={**_serialize(lead),"contact_email":address,"subject":subject,"body":body}
    execution=execute_outreach_send(payload,_gmail_send)
    if not execution.get("ok"):
        attempt.status="uncertain" if execution.get("stage")=="send_failed" else "failed"
        attempt.error=_clean(execution,2000);attempt.updated_at=datetime.utcnow();db.session.commit()
        return execution
    receipt=execution["send_receipt"]
    attempt.status="sent";attempt.message_id=_clean(receipt.get("message_id"),255);attempt.thread_id=_clean(receipt.get("thread_id"),255);attempt.error="";attempt.updated_at=datetime.utcnow()
    db.session.commit()
    return execution


def _route_persisted_reply(lead: OutreachLead, reply: Dict[str, Any], now: datetime) -> Dict[str, Any]:
    """Route newest persisted inbound evidence. No invented scheduling fields."""
    evidence=(reply.get("reply_evidence") or [])
    if not evidence:
        return {"ok":False,"stage":"no_reply_evidence"}
    item=evidence[-1]
    text=_clean(item.get("text"),20000)
    classification=classify_reply(text)
    label=classification.get("classification")
    if label=="not_interested":
        lead.status="opted_out" if classification.get("signals",{}).get("opt_out") else "not_interested"
        lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=""
        if classification.get("signals",{}).get("opt_out"):
            _suppress(lead.contact_email,"opt_out",message_id=_clean(item.get("message_id"),255),thread_id=lead.gmail_thread_id)
        return {"ok":True,"stage":lead.status,"classification":classification}
    if label=="question":
        lead.status="question";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=""
        return {"ok":True,"stage":"question","classification":classification}
    if label!="interested":
        lead.status="responded";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error="REPLY_REQUIRES_REVIEW"
        return {"ok":True,"stage":"unclear","classification":classification}

    qualification=_qualification_gate(lead)
    if not qualification.get("ok"):
        lead.status="interested";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error="QUALIFICATION_REQUIRED_FOR_BOOKING"
        return {"ok":False,"stage":"booking_blocked","classification":classification,"qualification":qualification}
    booking=extract_explicit_booking(text)
    booking["attendee_email"]=lead.contact_email
    # Missing explicit ISO start/end/timezone means interested, not booking-ready.
    if not booking.get("start") or not booking.get("end") or not booking.get("timezone"):
        lead.status="interested";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=""
        return {"ok":True,"stage":"interested","classification":classification,"booking_attempted":False}

    reply_message_id=_clean(item.get("message_id"),255)
    key=booking_key(lead_id=lead.id,reply_message_id=reply_message_id,start=booking["start"],end=booking["end"],attendee=lead.contact_email)
    event_id=google_event_id(key)
    attempt=OutreachBookingAttempt.query.filter_by(idempotency_key=key).first()
    gate=attempt_gate(attempt.status if attempt else "")
    if attempt is None:
        attempt=OutreachBookingAttempt(
            lead_id=lead.id,reply_message_id=reply_message_id,idempotency_key=key,event_id=event_id,
            start=booking["start"],end=booking["end"],timezone=booking["timezone"],attendee_email=normalize_email(lead.contact_email),status="pending",
        )
        db.session.add(attempt)
        existing=_commit_unique_or_existing(OutreachBookingAttempt,{"idempotency_key":key})
        if existing is not None:
            attempt=existing;gate=attempt_gate(attempt.status)
    if gate.get("reconcile"):
        existing=get_event(attempt.event_id)
        if existing.get("ok") and existing.get("found") and existing.get("start")==attempt.start and existing.get("end")==attempt.end:
            attempt.status="confirmed";attempt.event_url=_clean(existing.get("event_url"),1800);attempt.error="";attempt.updated_at=now
            lead.status="booked";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=""
            db.session.commit()
            return {"ok":True,"stage":"booked","reconciled":True,"event_id":attempt.event_id,"classification":classification}
        if existing.get("found") is False and attempt.status in {"pending","uncertain"}:
            attempt.status="failed";attempt.error="RECONCILIATION_EVENT_NOT_FOUND";db.session.commit()
        else:
            attempt.status="uncertain";attempt.error=_clean(existing.get("error") or "RECONCILIATION_MISMATCH",2000);db.session.commit()
            lead.status="interested";lead.last_error=attempt.error
            return {"ok":False,"stage":"reconciliation_blocked","classification":classification}

    summary=f"Call with {_clean(lead.company,300)}"
    result=process_reply_to_booking(
        reply_text=text,proposed_classification={"classification":"interested"},proposed_booking=booking,
        availability_func=check_availability,
        event_create_func=lambda req:create_event(req,summary=summary,description="Booked from validated Gmail reply evidence.",idempotency_key=event_id),
    )
    execution=result.get("booking_execution") or {}
    receipt=execution.get("booking_receipt") or {}
    if result.get("stage")=="booked":
        attempt.status="confirmed";attempt.event_id=_clean(receipt.get("event_id"),255) or event_id;attempt.event_url=_clean(receipt.get("event_url"),1800);attempt.error=""
    elif result.get("stage")=="create_failed":
        # Provider failure is uncertain: reconcile by deterministic event ID next run.
        attempt.status="uncertain";attempt.error=_clean(result,2000)
    else:
        attempt.status="failed";attempt.error=_clean(result,2000)
    attempt.updated_at=now;db.session.commit()
    stage=result.get("stage")
    if stage=="booked":
        lead.status="booked";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=""
        try:stored=json.loads(lead.evidence_json or "[]")
        except Exception:stored=[]
        if not isinstance(stored,dict):stored={"evidence":stored}
        stored["booking"]=result.get("booking_execution") or {};lead.evidence_json=json.dumps(stored)
    elif stage=="unavailable":
        lead.status="booking_ready";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error="TIME_NOT_AVAILABLE"
    else:
        lead.status="interested";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=_clean(result,2000)
    return {"ok":result.get("ok") is True,"stage":stage,"classification":classification,"booking_result":result}


def _rank_status(score: int) -> str:
    if score >= AUTO_SEND_MIN_SCORE:
        return "qualified"
    if score >= REVIEW_MIN_SCORE:
        return "review"
    return "rejected"


def _draft_email(lead: OutreachLead, follow_up_number: int = 0) -> Dict[str, Any]:
    try:
        evidence = json.loads(lead.evidence_json or "[]")
    except Exception:
        evidence = []

    if follow_up_number:
        instructions = (
            "Write a concise B2B follow-up email. Use only facts in the supplied workflow data. "
            "Do not invent names, needs, credentials, dates, or claims. Return strict JSON with keys subject and body."
        )
        prompt = (
            f"Write follow-up #{follow_up_number} to {_clean(lead.company, 300)}. Keep the same subject when appropriate. "
            "Reference the prior outreach naturally, be professional, and ask for a simple reply or brief call. "
            "Do not claim they still need help unless the evidence says so."
        )
        workflow_data = {
            "company": lead.company,
            "location": lead.location,
            "evidence": evidence,
            "previous_subject": lead.subject,
            "previous_body": lead.body,
        }
    else:
        instructions = (
            "Write a concise personalized B2B outreach email for a verified contractor lead. "
            "Use only facts supplied in workflow data. Never invent a contact name, company need, license, project, or claim. "
            "Return strict JSON with keys subject and body."
        )
        prompt = (
            "Draft a short first-touch email offering Master Electrician / qualifying-agent / permit-pulling support only when "
            "the supplied evidence supports that need. Mention one specific verified signal, avoid hype, and end with a low-friction call to action."
        )
        workflow_data = {
            "company": lead.company,
            "location": lead.location,
            "score": lead.score,
            "verification": lead.verification,
            "evidence": evidence,
            "source_url": lead.source_url,
        }

    result = run_ai(
        prompt=f"{prompt}\n\nWORKFLOW DATA:\n{json.dumps(workflow_data, indent=2)}",
        instructions=instructions,
    )
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error") or "OpenAI drafting failed."}

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

    subject = _clean(parsed.get("subject"), 500)
    body = _clean(parsed.get("body"), 6000)
    if not subject or not body:
        return {"ok": False, "error": "OpenAI response was missing subject or body."}
    return {"ok": True, "subject": subject, "body": body, "model": result.get("model")}


def _gmail_send(to_email: str, subject: str, body: str, thread_id: str = "") -> Dict[str, Any]:
    try:
        if thread_id:
            from email.message import EmailMessage
            import base64

            token = gmail_access_token()
            msg = EmailMessage()
            msg["To"] = to_email
            msg["Subject"] = subject
            from_email = os.environ.get("GMAIL_FROM_EMAIL", "")
            if from_email:
                msg["From"] = from_email
            msg.set_content(body)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")
            response = requests.post(
                "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={"raw": raw, "threadId": thread_id},
                timeout=30,
            )
            if not response.ok:
                return {"ok": False, "error": f"Gmail error {response.status_code}: {response.text[:500]}"}
            data = response.json()
        else:
            data = send_gmail(to_email, subject, body)

        return {
            "ok": True,
            "message_id": data.get("id"),
            "thread_id": data.get("threadId") or thread_id,
            "raw": data,
        }
    except Exception as exc:
        return {"ok": False, "error": _clean(exc, 1000)}


def _persist_reply_evidence(lead: OutreachLead, reply: Dict[str, Any]) -> None:
    for item in reply.get("reply_evidence") or []:
        message_id=_clean(item.get("message_id"),255)
        if not message_id:continue
        row=OutreachReplyEvidence.query.filter_by(message_id=message_id).first()
        if row is None:
            received=None
            try:
                received=datetime.utcfromtimestamp(int(item.get("internal_date") or 0)/1000) if item.get("internal_date") else None
            except Exception:
                received=None
            row=OutreachReplyEvidence(
                lead_id=lead.id,message_id=message_id,thread_id=_clean(item.get("thread_id") or lead.gmail_thread_id,255),
                from_email=normalize_email(item.get("from_email")),body_text=_clean(item.get("text"),20000),
                body_source=_clean(item.get("body_source"),50),opted_out=bool(reply.get("opted_out")),received_at=received,
            )
            db.session.add(row)


def _gmail_thread_reply_state(thread_id: str) -> Dict[str, Any]:
    """Read full Gmail MIME bodies and deterministically detect inbound reply/opt-out."""
    try:
        token=gmail_access_token()
        response=requests.get(
            f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{thread_id}",
            headers={"Authorization":f"Bearer {token}"},params={"format":"full"},timeout=30,
        )
        if not response.ok:
            return {"ok":False,"replied":False,"opted_out":False,"stop":True,"reason":"REPLY_CHECK_FAILED","error":f"Gmail thread lookup failed {response.status_code}: {response.text[:500]}"}
        rows=[message_to_evidence(message) for message in (response.json().get("messages") or [])]
        sender=normalize_email(os.environ.get("GMAIL_FROM_EMAIL"))
        if not sender:
            return {"ok":False,"replied":False,"opted_out":False,"stop":True,"reason":"SENDER_IDENTITY_UNCONFIGURED","error":"GMAIL_FROM_EMAIL is required for deterministic reply detection."}
        # Exact parsed From address comparison happens in classify_inbound.
        return classify_inbound(rows,sender_email=sender)
    except Exception as exc:
        return {"ok":False,"replied":False,"opted_out":False,"stop":True,"reason":"REPLY_CHECK_FAILED","error":_clean(exc,1000)}


def _dashboard_record(lead: OutreachLead) -> Dict[str, Any]:
    q=OutreachQualificationReceipt.query.filter_by(lead_id=lead.id).first()
    send=OutreachSendAttempt.query.filter_by(lead_id=lead.id).order_by(OutreachSendAttempt.updated_at.desc()).first()
    reply=OutreachReplyEvidence.query.filter_by(lead_id=lead.id).order_by(OutreachReplyEvidence.created_at.desc()).first()
    booking=OutreachBookingAttempt.query.filter_by(lead_id=lead.id).order_by(OutreachBookingAttempt.updated_at.desc()).first()
    qualification={}
    if q:
        try:qualification=json.loads(q.receipt_json or "{}")
        except Exception:qualification={"status":q.status,"ok":q.ok}
    audits=OperatorAuditEvent.query.filter_by(lead_id=lead.id).order_by(OperatorAuditEvent.id.desc()).limit(20).all()
    return {
        "lead":_serialize(lead),
        "qualification":qualification,
        "send_receipt":{"status":send.status,"message_id":send.message_id,"thread_id":send.thread_id,"error":send.error} if send else None,
        "reply_evidence":{"message_id":reply.message_id,"from_email":reply.from_email,"body_text":reply.body_text,"body_source":reply.body_source,"opted_out":reply.opted_out} if reply else None,
        "booking_receipt":{"status":booking.status,"event_id":booking.event_id,"event_url":booking.event_url,"start":booking.start,"end":booking.end,"timezone":booking.timezone,"error":booking.error} if booking else None,
        "audit":[{"action":a.action,"actor":a.actor,"result":json.loads(a.result_json or "{}"),"event_hash":a.event_hash,"previous_hash":a.previous_hash,"created_at":a.created_at.isoformat()} for a in audits],
    }


@app.route("/api/operator/leads/<int:lead_id>/control", methods=["POST"])
def operator_control(lead_id:int):
    if not _operator_authorized():
        return jsonify({"ok":False,"error":"operator authentication required"}),401
    lead=OutreachLead.query.get_or_404(lead_id)
    payload=request.get_json(silent=True) or {}
    action=_clean(payload.get("action"),50).lower()
    if action=="review":
        result={"ok":True,"action":"review","record":_dashboard_record(lead)}
        return _control_response(lead,action,payload,result)
    if action=="approve":
        gate=_qualification_gate(lead)
        if not gate.get("ok"):
            return _control_response(lead,action,payload,{"ok":False,"error":"qualification gate failed","qualification":gate},409)
        lead.status="qualified";lead.last_error=""
        return _control_response(lead,action,payload,{"ok":True,"action":"approve","lead":_serialize(lead)})
    if action=="reject":
        lead.status="rejected";lead.follow_up_due_at=None;lead.last_error=_clean(payload.get("reason") or "OPERATOR_REJECTED",500)
        return _control_response(lead,action,payload,{"ok":True,"action":"reject","lead":_serialize(lead)})
    if action=="suppress":
        _suppress(lead.contact_email,"operator_suppressed",thread_id=lead.gmail_thread_id)
        lead.status="opted_out";lead.follow_up_due_at=None;lead.last_error=""
        return _control_response(lead,action,payload,{"ok":True,"action":"suppress","lead":_serialize(lead)})
    if action=="close":
        lead.status="closed";lead.follow_up_due_at=None;lead.last_error=""
        return _control_response(lead,action,payload,{"ok":True,"action":"close","lead":_serialize(lead)})
    if action=="reconcile":
        attempt=OutreachBookingAttempt.query.filter_by(lead_id=lead.id).order_by(OutreachBookingAttempt.updated_at.desc()).first()
        if not attempt:
            return _control_response(lead,action,payload,{"ok":False,"error":"no booking attempt to reconcile"},409)
        existing=get_event(attempt.event_id)
        exact=bool(existing.get("ok") and existing.get("found") and existing.get("start")==attempt.start and existing.get("end")==attempt.end)
        if exact:
            attempt.status="confirmed";attempt.event_url=_clean(existing.get("event_url"),1800);attempt.error="";lead.status="booked";lead.last_error="";db.session.flush()
            return _control_response(lead,action,payload,{"ok":True,"action":"reconcile","event_id":attempt.event_id,"lead":_serialize(lead)})
        attempt.status="uncertain";attempt.error=_clean(existing.get("error") or "RECONCILIATION_MISMATCH",2000);lead.last_error=attempt.error;db.session.flush()
        return _control_response(lead,action,payload,{"ok":False,"error":attempt.error},409)
    if action=="retry":
        attempt=OutreachSendAttempt.query.filter_by(lead_id=lead.id).order_by(OutreachSendAttempt.updated_at.desc()).first()
        if not attempt or attempt.status!="failed":
            return _control_response(lead,action,payload,{"ok":False,"error":"only a deterministically failed send may be retried"},409)
        gate=_qualification_gate(lead)
        if not gate.get("ok") or _is_suppressed(lead.contact_email):
            return _control_response(lead,action,payload,{"ok":False,"error":"retry safety gate failed"},409)
        # Explicit operator retry gets a new sequence identity; uncertain/pending sends are never retried.
        result=_safe_send(lead,kind="operator_retry",sequence=attempt.id,subject=lead.subject,body=lead.body)
        if result.get("ok"):
            receipt=result.get("send_receipt") or {};lead.status="sent";lead.gmail_message_id=_clean(receipt.get("message_id"),255);lead.gmail_thread_id=_clean(receipt.get("thread_id"),255);lead.sent_at=datetime.utcnow();lead.last_error="";db.session.flush()
        return _control_response(lead,action,payload,{"ok":result.get("ok") is True,"action":"retry","execution":result,"lead":_serialize(lead)},200 if result.get("ok") else 409)
    return _control_response(lead,action,payload,{"ok":False,"error":"unsupported operator action"},400)


def _operator_session_authorized() -> bool:
    expected=os.environ.get("OPERATOR_CONTROL_TOKEN","").strip()
    supplied=str(session.get("operator_token") or "").strip()
    return bool(expected and supplied and hmac.compare_digest(expected,supplied))


def _operator_login_page(error: str = "") -> Response:
    message=f'<p class="danger">{error}</p>' if error else ''
    return Response(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Ops Operator Login</title><style>body{{font-family:system-ui,-apple-system,sans-serif;background:#0b1020;color:#e8ecf5;margin:0;padding:28px}}.box{{max-width:420px;margin:10vh auto;background:#141b2d;border:1px solid #27304a;border-radius:14px;padding:22px}}input,button{{box-sizing:border-box;width:100%;padding:13px;margin-top:12px;border-radius:9px;border:1px solid #394563}}input{{background:#0b1020;color:#fff}}button{{background:#fff;color:#101526;font-weight:700}}.muted{{color:#9aa7c2}}.danger{{color:#ffb4b4}}</style></head>
<body><div class="box"><h2>AI Ops Command Center</h2><p class="muted">Operator authentication</p>{message}<form method="post" action="/operator/login"><input name="token" type="password" autocomplete="off" autocapitalize="none" spellcheck="false" placeholder="Operator token" required><button type="submit">Sign in</button></form></div></body></html>""",mimetype="text/html")


@app.route("/operator/login",methods=["GET","POST"])
def operator_login():
    if request.method=="GET":
        return _operator_login_page()
    expected=os.environ.get("OPERATOR_CONTROL_TOKEN","").strip()
    supplied=_clean(request.form.get("token"),500)
    if not expected or not supplied or not hmac.compare_digest(expected,supplied):
        session.pop("operator_token",None)
        return _operator_login_page("Invalid operator token."),401
    session["operator_token"]=supplied
    session.permanent=False
    return redirect(url_for("operator_dashboard"),303)


@app.route("/operator/logout",methods=["POST"])
def operator_logout():
    session.pop("operator_token",None)
    return redirect(url_for("operator_login"),303)


@app.route("/api/operator/dashboard", methods=["GET"])
def operator_dashboard_data():
    if not (_operator_session_authorized() or _operator_authorized()):
        return jsonify({"ok":False,"error":"operator authentication required"}),401
    rows=OutreachLead.query.order_by(OutreachLead.updated_at.desc()).limit(500).all()
    records=[_dashboard_record(x) for x in rows]
    counts={}
    for record in records:
        stage=(record["lead"].get("operational") or {}).get("stage") or "unknown"
        counts[stage]=counts.get(stage,0)+1
    attention=[x for x in records if (x["lead"].get("operational") or {}).get("needs_attention")]
    return jsonify({"ok":True,"counts":counts,"attention_count":len(attention),"records":records})


@app.route("/operator", methods=["GET"])
def operator_dashboard():
    if not _operator_session_authorized():
        return redirect(url_for("operator_login"),303)
    rows=OutreachLead.query.order_by(OutreachLead.updated_at.desc()).limit(500).all()
    records=[_dashboard_record(x) for x in rows]
    attention=sum(1 for x in records if (x["lead"].get("operational") or {}).get("needs_attention"))
    def h(v):
        import html
        return html.escape(str(v if v is not None else ""))
    lead_html=[]
    for x in records:
        l=x["lead"];o=l.get("operational") or {}
        details=h(json.dumps({"qualification":x["qualification"],"send":x["send_receipt"],"reply":x["reply_evidence"],"booking":x["booking_receipt"],"evidence":l.get("evidence"),"audit":x["audit"]},indent=2))
        buttons="".join(f'<button name="action" value="{a}">{a.title()}</button>' for a in ("review","approve","reject","retry","reconcile","suppress","close"))
        lead_html.append(f'<article><div class="top"><div><b>{h(l.get("company"))}</b><div class="muted">{h(l.get("contact_email"))} · {h(l.get("location"))}</div></div><span>{h(o.get("stage"))}</span></div><form method="post" action="/operator/leads/{int(l["id"])}/control">{buttons}</form><details><summary>Evidence, receipts & audit</summary><pre>{details}</pre></details></article>')
    body="".join(lead_html) or '<p class="muted">No lead records yet.</p>'
    return Response(f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AI Ops Operator</title><style>body{{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#0b1020;color:#e8ecf5}}header,.wrap{{padding:20px}}header{{border-bottom:1px solid #27304a}}article,.stat{{background:#141b2d;border:1px solid #27304a;border-radius:12px;padding:14px;margin:10px 0}}.stats{{display:flex;gap:10px}}.stat{{flex:1}}.n{{font-size:26px;font-weight:800}}.muted{{color:#9aa7c2;font-size:12px}}.top{{display:flex;justify-content:space-between;gap:10px}}form{{display:flex;gap:7px;flex-wrap:wrap;margin-top:12px}}button{{background:#202a43;color:#fff;border:1px solid #394563;border-radius:8px;padding:10px 12px}}pre{{white-space:pre-wrap;word-break:break-word;background:#0b1020;padding:10px;border-radius:8px;max-height:280px;overflow:auto}}a{{color:#9ec5ff}}</style></head><body><header><b>AI Ops Command Center</b><div class="muted">Server-side authenticated operator controls</div><form method="post" action="/operator/logout"><button type="submit">Sign out</button></form></header><main class="wrap"><div class="stats"><div class="stat"><div class="n">{len(records)}</div><div class="muted">Total leads</div></div><div class="stat"><div class="n">{attention}</div><div class="muted">Needs attention</div></div></div>{body}</main></body></html>""",mimetype="text/html")


@app.route("/operator/leads/<int:lead_id>/control",methods=["POST"])
def operator_control_form(lead_id:int):
    if not _operator_session_authorized():
        return redirect(url_for("operator_login"),303)
    action=_clean(request.form.get("action"),50).lower()
    lead=OutreachLead.query.get_or_404(lead_id)
    # Reuse the same deterministic safety gates as the JSON control path without JavaScript.
    with app.test_request_context(f"/api/operator/leads/{lead_id}/control",method="POST",json={"action":action},headers={"X-Operator-Token":session["operator_token"],"X-Operator-Actor":"dashboard-session"}):
        response=operator_control(lead_id)
    status=response[1] if isinstance(response,tuple) else getattr(response,"status_code",200)
    if status>=400:
        payload=response[0].get_json() if isinstance(response,tuple) else response.get_json()
        import html
        error=html.escape(str((payload or {}).get("error") or "Request failed"))
        return Response(f'<html><meta name="viewport" content="width=device-width,initial-scale=1"><body style="font-family:system-ui;padding:24px"><h3>Action blocked</h3><p>{error}</p><a href="/operator">Back to dashboard</a></body></html>',status=status,mimetype="text/html")
    return redirect(url_for("operator_dashboard"),303)


@app.route("/api/outreach/needs-attention", methods=["GET"])
def outreach_needs_attention():
    rows=OutreachLead.query.order_by(OutreachLead.updated_at.desc()).limit(500).all()
    items=[]
    for lead in rows:
        snap=_operational_snapshot(lead)
        if snap.get("needs_attention"):
            items.append({"lead":_serialize(lead),"reason":snap.get("attention_reason")})
    return jsonify({"ok":True,"count":len(items),"items":items})


@app.route("/api/outreach/leads", methods=["POST"])
def create_outreach_lead():
    data = request.get_json(silent=True) or {}
    company = _clean(data.get("company") or data.get("title") or data.get("name"), 300)
    if not company:
        return jsonify({"error": "company is required"}), 400

    try:
        score = int(data.get("score") if data.get("score") is not None else data.get("intent_score", 0))
    except (TypeError, ValueError):
        return jsonify({"error": "score must be an integer"}), 400

    score = max(0, min(score, 100))
    evidence = data.get("evidence") if isinstance(data.get("evidence"), list) else []

    lead = OutreachLead(
        company=company,
        contact_email=_clean(data.get("contact_email") or data.get("email"), 500),
        contact_name=_clean(data.get("contact_name"), 300),
        location=_clean(data.get("location"), 300),
        source_url=_clean(data.get("source_url") or data.get("url") or data.get("website"), 1500),
        evidence_json=json.dumps(evidence),
        score=score,
        verification=_clean(data.get("verification"), 100),
        status="needs_evidence",
    )
    db.session.add(lead)
    db.session.commit()
    receipt=_store_qualification(lead,data)
    return jsonify({"lead": _serialize(lead), "qualification":receipt, "auto_send_eligible": receipt.get("ok") is True}), 201


@app.route("/api/outreach/leads/<int:lead_id>/draft", methods=["POST"])
def draft_outreach(lead_id: int):
    lead = OutreachLead.query.get_or_404(lead_id)
    qualification=_qualification_gate(lead)
    if not qualification.get("ok"):
        return jsonify({"error":"evidence-validated qualification is required before drafting","qualification":qualification}),409

    drafted = _draft_email(lead)
    if not drafted.get("ok"):
        lead.last_error = drafted.get("error") or "OpenAI drafting failed"
        lead.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(drafted), 502

    message_gate = validate_outreach_message({**_serialize(lead), "subject": drafted["subject"], "body": drafted["body"]}, drafted["subject"], drafted["body"])
    if not message_gate.get("ok"):
        lead.last_error = ", ".join(message_gate.get("reasons") or []) or "Draft validation failed"
        lead.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify({"ok": False, "gate": message_gate}), 409

    lead.subject = drafted["subject"]
    lead.body = drafted["body"]
    lead.status = "drafted"
    lead.last_error = ""
    lead.updated_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "lead": _serialize(lead), "model": drafted.get("model")})


@app.route("/api/outreach/leads/<int:lead_id>/send", methods=["POST"])
def send_outreach(lead_id: int):
    lead = OutreachLead.query.get_or_404(lead_id)
    qualification=_qualification_gate(lead)
    if not qualification.get("ok"):
        return jsonify({"error":"evidence-validated qualification is required before send","qualification":qualification}),409
    if not lead.contact_email:
        return jsonify({"error": "verified contact_email is required before send"}), 409

    if not lead.subject or not lead.body:
        drafted = _draft_email(lead)
        if not drafted.get("ok"):
            lead.last_error = drafted.get("error") or "OpenAI drafting failed"
            db.session.commit()
            return jsonify(drafted), 502
        lead.subject = drafted["subject"]
        lead.body = drafted["body"]

    execution = _safe_send(lead, kind="initial", sequence=0, subject=lead.subject, body=lead.body)
    if not execution.get("ok"):
        reasons = ((execution.get("gate") or {}).get("reasons") or []) + ((execution.get("send_receipt") or {}).get("reasons") or [])
        lead.last_error = ", ".join(reasons) or "Outreach execution failed"
        lead.updated_at = datetime.utcnow()
        db.session.commit()
        return jsonify(execution), 409 if execution.get("stage") == "blocked" else 502

    receipt = execution["send_receipt"]
    sent_at = datetime.utcnow()
    lead.gmail_message_id = _clean(receipt.get("message_id"), 255)
    lead.gmail_thread_id = _clean(receipt.get("thread_id"), 255)
    lead.sent_at = sent_at
    lead.follow_up_due_at = sent_at + timedelta(days=FIRST_FOLLOWUP_DAYS)
    lead.status = "sent"
    lead.last_error = ""
    lead.updated_at = sent_at
    db.session.commit()
    return jsonify({"ok": True, "lead": _serialize(lead)})


@app.route("/api/outreach/process-followups", methods=["POST"])
def process_followups():
    cron_token=os.environ.get("OUTREACH_CRON_TOKEN","").strip()
    supplied=request.headers.get("X-Outreach-Cron-Token","")
    if not cron_token or not supplied or not hmac.compare_digest(cron_token,supplied):
        return jsonify({"ok":False,"error":"unauthorized"}),401

    now = datetime.utcnow()
    leads = OutreachLead.query.filter(
        OutreachLead.status.in_(["sent", "followup_sent"]),
        OutreachLead.follow_up_due_at.isnot(None),
        OutreachLead.follow_up_due_at <= now,
        OutreachLead.replied_at.is_(None),
    ).all()

    processed=[]
    for lead in leads:
        reply=_gmail_thread_reply_state(lead.gmail_thread_id) if lead.gmail_thread_id else {
            "ok":False,"stop":True,"reason":"MISSING_THREAD_ID","error":"missing Gmail thread id"
        }
        if reply.get("stop"):
            if reply.get("replied"):
                _persist_reply_evidence(lead,reply)
                lead.replied_at=now
                routed=_route_persisted_reply(lead,reply,now)
                processed.append({"id":lead.id,"status":lead.status,"hard_stop":True,"reason":reply.get("reason"),"routing_stage":routed.get("stage")})
            else:
                lead.last_error=reply.get("error") or reply.get("reason") or "reply check failed"
                lead.updated_at=now
                processed.append({"id":lead.id,"status":"error","hard_stop":True,"reason":reply.get("reason")})
            continue

        permission=followup_permission(
            reply_state=reply,follow_up_count=lead.follow_up_count,max_followups=MAX_FOLLOWUPS,
            thread_id=lead.gmail_thread_id,contact_email=lead.contact_email,
        )
        if not permission.get("allowed"):
            if "MAX_FOLLOWUPS_REACHED" in permission.get("reasons",[]):
                lead.status="completed_no_reply";lead.follow_up_due_at=None;lead.last_error=""
            else:
                lead.last_error=", ".join(permission.get("reasons") or [])
            lead.updated_at=now
            processed.append({"id":lead.id,"status":lead.status,"hard_stop":True,"reasons":permission.get("reasons")})
            continue

        next_number=lead.follow_up_count+1
        drafted=_draft_email(lead,follow_up_number=next_number)
        if not drafted.get("ok"):
            lead.last_error=drafted.get("error") or "OpenAI follow-up drafting failed"
            lead.updated_at=now
            processed.append({"id":lead.id,"status":"error","error":lead.last_error})
            continue

        final_reply=_gmail_thread_reply_state(lead.gmail_thread_id)
        if final_reply.get("stop"):
            if final_reply.get("replied"):
                _persist_reply_evidence(lead,final_reply)
                lead.replied_at=now
                routed=_route_persisted_reply(lead,final_reply,now)
            else:
                lead.last_error=final_reply.get("error") or final_reply.get("reason") or "final reply check failed"
            lead.updated_at=now
            processed.append({"id":lead.id,"status":lead.status,"hard_stop":True,"reason":final_reply.get("reason")})
            continue

        send_lead={**_serialize(lead),"subject":drafted["subject"],"body":drafted["body"]}
        execution=_safe_send(lead,kind="followup",sequence=next_number,subject=drafted["subject"],body=drafted["body"])
        if not execution.get("ok"):
            reasons=((execution.get("gate") or {}).get("reasons") or [])+((execution.get("send_receipt") or {}).get("reasons") or [])
            lead.last_error=", ".join(reasons) or "Follow-up execution failed"
            lead.updated_at=now
            processed.append({"id":lead.id,"status":"error","error":lead.last_error})
            continue

        receipt=execution["send_receipt"]
        lead.subject=drafted["subject"];lead.body=drafted["body"]
        lead.gmail_message_id=_clean(receipt.get("message_id"),255)
        lead.gmail_thread_id=_clean(receipt.get("thread_id") or lead.gmail_thread_id,255)
        lead.follow_up_count=next_number
        lead.follow_up_due_at=now+timedelta(days=SECOND_FOLLOWUP_DAYS)
        lead.status="followup_sent";lead.last_error="";lead.updated_at=now
        processed.append({"id":lead.id,"status":"followup_sent","follow_up_count":next_number})

    db.session.commit()
    return jsonify({"ok":True,"processed_count":len(processed),"processed":processed})


@app.route("/api/outreach/leads/<int:lead_id>/process-reply-booking", methods=["POST"])
def process_reply_booking(lead_id: int):
    """Explicit production handoff. Authenticated and qualification-gated."""
    if not (_operator_session_authorized() or _operator_authorized()):
        return jsonify({"ok":False,"error":"operator authentication required"}),401
    lead=OutreachLead.query.get_or_404(lead_id)
    qualification=_qualification_gate(lead)
    if not qualification.get("ok"):
        return jsonify({"ok":False,"stage":"blocked","error":"qualification required for booking","qualification":qualification}),409
    data=request.get_json(silent=True) or {}
    reply_text=_clean(data.get("reply_text"),8000)
    proposed_classification=data.get("classification") if isinstance(data.get("classification"),dict) else {"classification":data.get("classification")}
    proposed_booking=data.get("booking") if isinstance(data.get("booking"),dict) else {}
    # Bind attendee to the source-validated outreach contact; callers cannot redirect invites.
    proposed_booking={**proposed_booking,"attendee_email":lead.contact_email}
    summary=f"Call with {_clean(lead.company,300)}"
    idempotency_key=f"aocclead{lead.id}booking".lower()
    result=process_reply_to_booking(
        reply_text=reply_text,
        proposed_classification=proposed_classification,
        proposed_booking=proposed_booking,
        availability_func=check_availability,
        event_create_func=lambda req:create_event(req,summary=summary,description="Booked from validated outreach reply.",idempotency_key=idempotency_key),
    )

    now=datetime.utcnow()
    stage=result.get("stage")
    if stage=="booked":
        lead.status="booked";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=""
        try:
            evidence=json.loads(lead.evidence_json or "[]")
        except Exception:
            evidence=[]
        if not isinstance(evidence,dict):evidence={"evidence":evidence}
        evidence["booking"]=result.get("booking_execution") or {}
        lead.evidence_json=json.dumps(evidence)
    elif stage=="not_interested":
        lead.status="not_interested";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=""
    elif stage=="question":
        lead.status="question";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now;lead.last_error=""
    elif stage in {"interested","unavailable"}:
        lead.status="booking_ready" if stage=="unavailable" else "interested"
        lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now
        lead.last_error=", ".join(((result.get("booking_execution") or {}).get("availability") or {}).get("reasons") or [])
    elif stage=="unclear":
        lead.status="responded";lead.follow_up_due_at=None;lead.replied_at=lead.replied_at or now
    else:
        lead.last_error=str(result)[:2000]
    lead.updated_at=now
    db.session.commit()
    code=200 if result.get("ok") else (409 if stage in {"classification_blocked","unavailable","create_failed","blocked"} else 502)
    return jsonify({"ok":result.get("ok",False),"stage":stage,"lead":_serialize(lead),"result":result}),code


@app.route("/api/outreach/leads", methods=["GET"])
def list_outreach_leads():
    leads = OutreachLead.query.order_by(OutreachLead.id.desc()).limit(200).all()
    return jsonify({"leads": [_serialize(lead) for lead in leads]})
