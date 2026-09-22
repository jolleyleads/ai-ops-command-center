"""Deterministic Google Calendar booking execution.

Availability is checked immediately before event creation. A booking is successful
only after Google returns an event id and the receipt validates.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Callable, Dict

def _clean(v:Any,limit:int=2000)->str:return str(v or "").strip()[:limit]

def _iso(v:Any):
    s=_clean(v,100)
    try:return datetime.fromisoformat(s.replace("Z","+00:00"))
    except Exception:return None

def validate_booking_request(req:Dict[str,Any])->Dict[str,Any]:
    req=req if isinstance(req,dict) else {}
    reasons=[]
    if req.get("booking_ready") is not True or req.get("validated") is not True:
        reasons.append("BOOKING_NOT_READY")
    start=_clean(req.get("start"),100);end=_clean(req.get("end"),100)
    if not _iso(start):reasons.append("INVALID_START")
    if not _iso(end):reasons.append("INVALID_END")
    if _iso(start) and _iso(end) and _iso(end)<=_iso(start):reasons.append("END_NOT_AFTER_START")
    tz=_clean(req.get("timezone"),100)
    attendee=_clean(req.get("attendee_email"),500)
    if not tz:reasons.append("MISSING_TIMEZONE")
    if "@" not in attendee:reasons.append("INVALID_ATTENDEE")
    return {"ok":not reasons,"validated":not reasons,"reasons":reasons,"start":start,"end":end,"timezone":tz,"attendee_email":attendee}

def validate_availability_receipt(receipt:Dict[str,Any])->Dict[str,Any]:
    receipt=receipt if isinstance(receipt,dict) else {}
    reasons=[]
    if receipt.get("ok") is not True:reasons.append("AVAILABILITY_PROVIDER_FAILED")
    if receipt.get("available") is not True:reasons.append("TIME_NOT_AVAILABLE")
    checked_start=_clean(receipt.get("checked_start"),100)
    checked_end=_clean(receipt.get("checked_end"),100)
    if not checked_start or not checked_end:reasons.append("MISSING_CHECKED_WINDOW")
    return {"ok":not reasons,"validated":not reasons,"available":not reasons,"reasons":reasons,"checked_start":checked_start,"checked_end":checked_end}

def validate_event_receipt(receipt:Dict[str,Any],request:Dict[str,Any])->Dict[str,Any]:
    receipt=receipt if isinstance(receipt,dict) else {}
    reasons=[]
    if receipt.get("ok") is not True:reasons.append("CALENDAR_CREATE_FAILED")
    event_id=_clean(receipt.get("event_id"),255)
    if not event_id:reasons.append("MISSING_EVENT_ID")
    if _clean(receipt.get("start"),100)!=_clean(request.get("start"),100):reasons.append("START_RECEIPT_MISMATCH")
    if _clean(receipt.get("end"),100)!=_clean(request.get("end"),100):reasons.append("END_RECEIPT_MISMATCH")
    return {"ok":not reasons,"validated":not reasons,"event_id":event_id,"event_url":_clean(receipt.get("event_url"),1800),"reasons":reasons}

def execute_booking(request:Dict[str,Any],availability_func:Callable,event_create_func:Callable)->Dict[str,Any]:
    gate=validate_booking_request(request)
    if not gate["ok"]:return {"ok":False,"stage":"blocked","request_gate":gate}
    raw_avail=availability_func(gate)
    avail=validate_availability_receipt(raw_avail)
    if not avail["ok"]:return {"ok":False,"stage":"unavailable","request_gate":gate,"availability":avail}
    # Creation follows the exact checked window. Provider should use an idempotency key.
    raw_event=event_create_func(gate)
    event=validate_event_receipt(raw_event,gate)
    if not event["ok"]:return {"ok":False,"stage":"create_failed","request_gate":gate,"availability":avail,"booking_receipt":event}
    return {"ok":True,"stage":"booked","request_gate":gate,"availability":avail,"booking_receipt":event}
