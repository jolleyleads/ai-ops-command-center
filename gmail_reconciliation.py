"""Deterministic Gmail send identity, reconciliation, and safe retry.

Loaded after outreach_automation so production outreach sends use a durable RFC
Message-ID bound to the external command. Provider injection remains supported for
deterministic integration/failure tests. Uncertain sends remain fail-closed.
"""
import base64
import json
import os
from datetime import datetime
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Dict

import requests
from flask import jsonify

import outreach_automation as oa
from app import app, db, gmail_access_token
from src.outreach_execution import execute_outreach_send
from src.outreach_safety import normalize_email, send_key, suppression_gate, send_attempt_gate

NEGATIVE_GRACE_SECONDS = max(60, int(os.getenv("GMAIL_RECONCILIATION_GRACE_SECONDS", "180")))
# Keep the provider that existed before this hardening module loaded. Tests and
# integration harnesses intentionally replace oa._gmail_send; production does not.
_BASE_GMAIL_SEND = oa._gmail_send


def _message_identity(command_key: str) -> str:
    safe="".join(ch for ch in str(command_key or "").lower() if ch in "0123456789abcdef")
    if len(safe) < 16: raise ValueError("valid durable command key required for Gmail identity")
    return f"<aiops-{safe}@mail.aiops.local>"


def _gmail_send_identified(to_email: str, subject: str, body: str, *, command_key: str, thread_id: str="") -> Dict[str,Any]:
    try:
        token=gmail_access_token();identity=_message_identity(command_key);msg=EmailMessage()
        msg["To"]=to_email;msg["Subject"]=subject;msg["Message-ID"]=identity;msg["X-AI-Ops-Command-ID"]=command_key
        from_email=os.environ.get("GMAIL_FROM_EMAIL","")
        if from_email: msg["From"]=from_email
        msg.set_content(body);raw=base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=");payload={"raw":raw}
        if thread_id: payload["threadId"]=thread_id
        response=requests.post("https://gmail.googleapis.com/gmail/v1/users/me/messages/send",headers={"Authorization":f"Bearer {token}","Content-Type":"application/json"},json=payload,timeout=30)
        if not response.ok:return {"ok":False,"error":f"Gmail error {response.status_code}: {response.text[:500]}","message_identity":identity}
        data=response.json();return {"ok":True,"message_id":data.get("id"),"thread_id":data.get("threadId") or thread_id,"message_identity":identity,"raw":data}
    except Exception as exc:return {"ok":False,"error":oa._clean(exc,1000),"message_identity":_message_identity(command_key)}


def _provider_for_command(command_key: str):
    """Use injected provider in tests; deterministic identified provider in production."""
    current=oa._gmail_send
    if current is not _BASE_GMAIL_SEND:
        return current
    return lambda to,sub,text,thread_id="": _gmail_send_identified(to,sub,text,command_key=command_key,thread_id=thread_id)


def _headers(message):
    out={}
    for row in ((message.get("payload") or {}).get("headers") or []):
        name=str(row.get("name") or "").lower();value=str(row.get("value") or "")
        if name:out[name]=value
    return out


def gmail_reconciliation_proof(cmd):
    if not cmd or cmd.kind!="gmail_send":return {"ok":False,"outcome":"inconclusive","error":"GMAIL_SEND_COMMAND_REQUIRED"}
    try:payload=json.loads(cmd.payload_json or "{}")
    except Exception:return {"ok":False,"outcome":"inconclusive","error":"INVALID_COMMAND_PAYLOAD"}
    recipient=normalize_email(payload.get("recipient"));subject=str(payload.get("subject") or "");identity=_message_identity(cmd.idempotency_key)
    try:
        token=gmail_access_token();headers={"Authorization":f"Bearer {token}"};q=f'in:sent rfc822msgid:{identity}'
        response=requests.get("https://gmail.googleapis.com/gmail/v1/users/me/messages",headers=headers,params={"q":q,"maxResults":10},timeout=30)
        if not response.ok:return {"ok":False,"outcome":"inconclusive","source":"gmail_messages_list","query":q,"http_status":response.status_code,"error":response.text[:500]}
        rows=response.json().get("messages") or []
        if len(rows)>1:return {"ok":False,"outcome":"inconclusive","source":"gmail_messages_list","query":q,"match_count":len(rows),"error":"MULTIPLE_IDENTITY_MATCHES"}
        if len(rows)==1:
            message_id=str(rows[0].get("id") or "");detail=requests.get(f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{message_id}",headers=headers,params={"format":"metadata","metadataHeaders":["Message-ID","To","Subject","X-AI-Ops-Command-ID"]},timeout=30)
            if not detail.ok:return {"ok":False,"outcome":"inconclusive","source":"gmail_message_get","message_id":message_id,"http_status":detail.status_code,"error":detail.text[:500]}
            data=detail.json();h=_headers(data);exact_identity=h.get("message-id","").strip().lower()==identity.lower();exact_recipient=normalize_email(parseaddr(h.get("to","") )[1])==recipient;exact_command=h.get("x-ai-ops-command-id","").strip()==cmd.idempotency_key
            if not (exact_identity and exact_recipient and exact_command):return {"ok":False,"outcome":"inconclusive","source":"gmail_message_get","message_id":message_id,"identity_match":exact_identity,"recipient_match":exact_recipient,"command_match":exact_command,"error":"GMAIL_IDENTITY_MISMATCH"}
            return {"ok":True,"outcome":"found","source":"gmail_sent_rfc822msgid","query":q,"message_identity":identity,"message_id":message_id,"thread_id":str(data.get("threadId") or ""),"recipient":recipient,"subject":h.get("subject","")}
        age=(datetime.utcnow()-(cmd.updated_at or cmd.created_at or datetime.utcnow())).total_seconds()
        if age<NEGATIVE_GRACE_SECONDS:return {"ok":False,"outcome":"inconclusive","source":"gmail_sent_rfc822msgid","query":q,"message_identity":identity,"match_count":0,"age_seconds":int(age),"error":"NEGATIVE_SEARCH_GRACE_PERIOD"}
        return {"ok":True,"outcome":"not_found","source":"gmail_sent_rfc822msgid","query":q,"message_identity":identity,"match_count":0,"age_seconds":int(age),"recipient":recipient,"subject":subject}
    except Exception as exc:return {"ok":False,"outcome":"inconclusive","source":"gmail_reconciliation","message_identity":identity,"error":oa._clean(exc,1000)}


def reconcile_gmail_command(cmd):
    if not cmd or cmd.kind!="gmail_send":return {"ok":False,"status":"blocked","error":"GMAIL_SEND_COMMAND_REQUIRED"}
    if cmd.status!="uncertain":return {"ok":False,"status":cmd.status,"error":"UNCERTAIN_COMMAND_REQUIRED"}
    proof=gmail_reconciliation_proof(cmd);outcome=proof.get("outcome")
    if outcome=="inconclusive":
        oa._audit_actor(cmd.lead_id,"gmail_reconciliation_inconclusive",{"command_key":cmd.idempotency_key},{"status":"uncertain","proof":proof},"system");db.session.commit();return {"ok":False,"status":"uncertain","proof":proof}
    result=oa._reconcile_external_command(cmd,outcome=="found",proof);attempt=oa.OutreachSendAttempt.query.filter_by(idempotency_key=json.loads(cmd.payload_json or "{}").get("send_key","")).first();lead=db.session.get(oa.OutreachLead,cmd.lead_id)
    if outcome=="found":
        if attempt:attempt.status="sent";attempt.message_id=proof.get("message_id","");attempt.thread_id=proof.get("thread_id","");attempt.error="";attempt.updated_at=datetime.utcnow()
        if lead:lead.status="sent";lead.gmail_message_id=proof.get("message_id","");lead.gmail_thread_id=proof.get("thread_id","");lead.sent_at=lead.sent_at or datetime.utcnow();lead.last_error=""
    else:
        if attempt:attempt.status="failed";attempt.error="RECONCILIATION_PROVED_NO_SIDE_EFFECT";attempt.updated_at=datetime.utcnow()
        if lead:lead.last_error="RECONCILIATION_PROVED_NO_SIDE_EFFECT"
    oa._audit_actor(cmd.lead_id,"gmail_reconciliation_applied",{"command_key":cmd.idempotency_key},{"outcome":outcome,"command_status":result.get("status"),"proof":proof},"system");db.session.commit();return {"ok":True,"outcome":outcome,"command_status":result.get("status"),"proof":proof}


def hardened_safe_send(lead,*,kind,sequence,subject,body):
    qualification=oa._qualification_gate(lead)
    if not qualification.get("ok"):return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":["QUALIFICATION_REQUIRED"],"qualification":qualification}}
    address=normalize_email(lead.contact_email);sg=suppression_gate(address,oa._is_suppressed(address))
    if not sg.get("ok"):return {"ok":False,"stage":"blocked","gate":sg}
    key=send_key(lead_id=lead.id,kind=kind,sequence=sequence,recipient=address);attempt=oa.OutreachSendAttempt.query.filter_by(idempotency_key=key).first();ag=send_attempt_gate(attempt.status if attempt else "")
    if attempt is not None and attempt.status=="failed":return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":["FAILED_ATTEMPT_REQUIRES_OPERATOR_REVIEW"]},"attempt_status":"failed"}
    if not ag.get("allowed"):return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":[ag["reason"]]},"attempt_status":attempt.status if attempt else ""}
    if attempt is None:
        attempt=oa.OutreachSendAttempt(lead_id=lead.id,kind=kind,sequence=sequence,recipient=address,idempotency_key=key,status="pending");db.session.add(attempt);existing=oa._commit_unique_or_existing(oa.OutreachSendAttempt,{"idempotency_key":key})
        if existing is not None:return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":["CONCURRENT_SEND_ATTEMPT_EXISTS"]},"attempt_status":existing.status}
    payload={**oa._serialize(lead),"contact_email":address,"subject":subject,"body":body};command_payload={"recipient":address,"kind":kind,"sequence":sequence,"subject":subject,"body":body,"send_key":key};cmd=oa._enqueue_external_command(lead,"gmail_send",command_payload)
    if cmd.status!="pending":return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":["EXTERNAL_COMMAND_NOT_PENDING"]},"command_status":cmd.status}
    token=oa._claim_external_command(cmd)
    if not token:return {"ok":False,"stage":"blocked","gate":{"ok":False,"reasons":["EXTERNAL_COMMAND_ALREADY_CLAIMED"]}}
    try:
        execution=execute_outreach_send(payload,_provider_for_command(cmd.idempotency_key));completion=oa._finish_external_command(cmd.id,token,execution)
    except BaseException as exc:
        oa._finish_external_command(cmd.id,token,None,exc);attempt.status="uncertain";attempt.error="PROVIDER_EXCEPTION";attempt.updated_at=datetime.utcnow();db.session.commit();raise
    if completion.get("status")!="succeeded":
        attempt.status="uncertain" if completion.get("status")=="uncertain" else "failed";attempt.error=oa._clean(execution,2000);attempt.updated_at=datetime.utcnow();db.session.commit();return execution
    receipt=execution["send_receipt"];attempt.status="sent";attempt.message_id=oa._clean(receipt.get("message_id"),255);attempt.thread_id=oa._clean(receipt.get("thread_id"),255);attempt.error="";attempt.updated_at=datetime.utcnow();db.session.commit();return execution


def retry_after_negative_reconciliation(lead,failed_attempt):
    if not failed_attempt or failed_attempt.status!="failed" or failed_attempt.error!="RECONCILIATION_PROVED_NO_SIDE_EFFECT":return {"ok":False,"stage":"blocked","error":"NEGATIVE_GMAIL_RECONCILIATION_REQUIRED"}
    return hardened_safe_send(lead,kind="reconciled_retry",sequence=failed_attempt.id,subject=lead.subject,body=lead.body)

@app.route("/api/operator/gmail-recovery/<int:command_id>/reconcile",methods=["POST"])
def operator_gmail_reconcile(command_id):
    if not oa._operator_session_authorized():return jsonify({"ok":False,"error":"operator session required"}),401
    if not oa._csrf_ok():return jsonify({"ok":False,"error":"CSRF validation failed"}),403
    result=reconcile_gmail_command(db.session.get(oa.ExternalSideEffectCommand,command_id));return jsonify(result),200 if result.get("ok") else 409

@app.route("/api/operator/gmail-recovery/<int:command_id>/retry",methods=["POST"])
def operator_gmail_retry(command_id):
    if not oa._operator_session_authorized():return jsonify({"ok":False,"error":"operator session required"}),401
    if not oa._csrf_ok():return jsonify({"ok":False,"error":"CSRF validation failed"}),403
    cmd=db.session.get(oa.ExternalSideEffectCommand,command_id)
    if not cmd or cmd.kind!="gmail_send" or cmd.status!="failed" or cmd.error!="RECONCILIATION_PROVED_NO_SIDE_EFFECT":return jsonify({"ok":False,"error":"negative Gmail reconciliation proof required"}),409
    payload=json.loads(cmd.payload_json or "{}");attempt=oa.OutreachSendAttempt.query.filter_by(idempotency_key=payload.get("send_key","")).first();lead=db.session.get(oa.OutreachLead,cmd.lead_id);result=retry_after_negative_reconciliation(lead,attempt);oa._audit_actor(cmd.lead_id,"gmail_reconciled_retry",{"predecessor_command":cmd.id,"predecessor_key":cmd.idempotency_key},{"ok":result.get("ok") is True,"result":result},"operator");db.session.commit();return jsonify(result),200 if result.get("ok") else 409

oa._safe_send=hardened_safe_send
