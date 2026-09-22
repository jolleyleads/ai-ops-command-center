"""Deterministic booking idempotency helpers."""
from __future__ import annotations
import hashlib
from typing import Any,Dict

def booking_key(*,lead_id:int,reply_message_id:Any,start:Any,end:Any,attendee:Any)->str:
    raw="|".join([str(int(lead_id)),str(reply_message_id or "").strip(),str(start or "").strip(),str(end or "").strip(),str(attendee or "").strip().lower()])
    return hashlib.sha256(raw.encode()).hexdigest()

def google_event_id(key:str)->str:
    # Google event IDs accept lowercase base32hex chars. Hex is a valid subset.
    return ("aocc"+str(key or "").lower())[:64]

def attempt_gate(status:Any)->Dict[str,Any]:
    s=str(status or "").lower().strip()
    if s=="confirmed":return {"allowed":False,"reconcile":True,"reason":"ALREADY_CONFIRMED"}
    if s in {"pending","uncertain"}:return {"allowed":False,"reconcile":True,"reason":"RECONCILE_REQUIRED"}
    return {"allowed":True,"reconcile":False,"reason":"NEW_OR_RETRY"}
