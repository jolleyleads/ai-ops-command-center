"""Durable outreach suppression and duplicate-send protection."""
from __future__ import annotations
import hashlib
import re
from typing import Any

EMAIL_RE=re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

def normalize_email(value:Any)->str:
    return str(value or "").strip().lower()

def valid_email(value:Any)->bool:
    return bool(EMAIL_RE.match(normalize_email(value)))

def send_key(*,lead_id:int,kind:str,sequence:int=0,recipient:str="")->str:
    raw=f"{int(lead_id)}|{str(kind).strip().lower()}|{int(sequence)}|{normalize_email(recipient)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def suppression_gate(email:Any,suppressed:bool)->dict:
    address=normalize_email(email)
    reasons=[]
    if not valid_email(address):reasons.append("INVALID_RECIPIENT")
    if suppressed:reasons.append("RECIPIENT_SUPPRESSED")
    return {"ok":not reasons,"validated":not reasons,"recipient":address,"reasons":reasons}

def send_attempt_gate(existing_status:Any)->dict:
    status=str(existing_status or "").strip().lower()
    if status=="sent":
        return {"ok":False,"allowed":False,"reason":"DUPLICATE_ALREADY_SENT"}
    if status in {"pending","uncertain"}:
        return {"ok":False,"allowed":False,"reason":"PRIOR_SEND_UNCERTAIN"}
    return {"ok":True,"allowed":True,"reason":"NEW_SEND"}
