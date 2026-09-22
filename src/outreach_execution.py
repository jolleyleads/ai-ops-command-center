"""Deterministic outreach validation and execution gates.

The LLM may draft copy. This module decides whether that draft is safe to send,
and whether a send receipt is strong enough to advance workflow state.
"""
from __future__ import annotations
import re
from typing import Any, Dict
from urllib.parse import urlparse

EMAIL_RE=re.compile(r"(?i)^[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}$")
URL_RE=re.compile(r"https?://[^\s)>]+",re.I)
UNSUB_RE=re.compile(r"(?i)\b(unsubscribe|opt[ -]?out|remove me|do not contact|don't contact|stop emailing)\b")

def _clean(v:Any,limit:int=8000)->str:return str(v or "").strip()[:limit]
def _url(v:Any)->bool:
    try:
        p=urlparse(_clean(v,1800))
        return p.scheme in {"http","https"} and bool(p.hostname)
    except Exception:return False

def validate_outreach_message(lead:Dict[str,Any],subject:Any,body:Any)->Dict[str,Any]:
    """Fail closed before any send side effect."""
    reasons=[]
    subject=_clean(subject,500);body=_clean(body,6000)
    email=_clean(lead.get("contact_email") or lead.get("email"),500).lower()
    if not EMAIL_RE.fullmatch(email):reasons.append("INVALID_OR_MISSING_RECIPIENT")
    if not subject:reasons.append("MISSING_SUBJECT")
    if not body:reasons.append("MISSING_BODY")
    if len(subject)>160:reasons.append("SUBJECT_TOO_LONG")
    if len(body)>5000:reasons.append("BODY_TOO_LONG")

    evidence=lead.get("evidence") or {}
    if isinstance(evidence,str):
        evidence_text=evidence
    else:
        evidence_text=str(evidence)
    # URLs in generated copy must already exist in source-backed workflow data.
    for u in URL_RE.findall(body):
        if u not in evidence_text and u!=_clean(lead.get("source_url"),1800):
            reasons.append("UNSUPPORTED_URL_IN_MESSAGE");break

    # Never execute an outreach send for a record carrying an opt-out signal.
    combined=" ".join([_clean(lead.get("last_reply"),2000),_clean(lead.get("last_error"),2000),_clean(lead.get("status"),100)])
    if UNSUB_RE.search(combined):reasons.append("OPT_OUT_SIGNAL_PRESENT")

    return {"ok":not reasons,"validated":not reasons,"reasons":reasons,"subject":subject,"body":body,"recipient":email}

def validate_send_receipt(receipt:Dict[str,Any])->Dict[str,Any]:
    """A provider call is not success unless it returns durable message/thread proof."""
    receipt=receipt if isinstance(receipt,dict) else {}
    reasons=[]
    if receipt.get("ok") is not True:reasons.append("PROVIDER_SEND_FAILED")
    message_id=_clean(receipt.get("message_id"),255)
    thread_id=_clean(receipt.get("thread_id"),255)
    if not message_id:reasons.append("MISSING_MESSAGE_ID")
    if not thread_id:reasons.append("MISSING_THREAD_ID")
    return {"ok":not reasons,"validated":not reasons,"reasons":reasons,"message_id":message_id,"thread_id":thread_id}

def execute_outreach_send(lead:Dict[str,Any],send_func)->Dict[str,Any]:
    """Validate -> send once -> validate receipt. Caller persists state only on success."""
    gate=validate_outreach_message(lead,lead.get("subject"),lead.get("body"))
    if not gate["ok"]:return {"ok":False,"stage":"blocked","gate":gate,"send_receipt":{}}
    raw=send_func(gate["recipient"],gate["subject"],gate["body"],_clean(lead.get("gmail_thread_id"),255))
    receipt=validate_send_receipt(raw)
    if not receipt["ok"]:return {"ok":False,"stage":"send_failed","gate":gate,"send_receipt":receipt}
    return {"ok":True,"stage":"contacted","gate":gate,"send_receipt":receipt}
