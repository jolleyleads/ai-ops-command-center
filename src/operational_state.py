"""Operational state projection and attention rules."""
from __future__ import annotations
from typing import Any,Dict

OPERATIONAL_STAGES=("discovered","verified","qualified","outreach_ready","contacted","followup","responded","interested","question","not_interested","booking_ready","booked","closed","needs_attention")

def project_stage(status:Any)->str:
    s=str(status or "").strip().lower()
    mapping={
        "needs_evidence":"discovered","review":"discovered","qualified":"qualified",
        "drafted":"outreach_ready","sent":"contacted","followup_sent":"followup",
        "responded":"responded","interested":"interested","question":"question",
        "not_interested":"not_interested","opted_out":"closed","booking_ready":"booking_ready",
        "booked":"booked","rejected":"closed","closed":"closed",
    }
    return mapping.get(s,"needs_attention")

def attention_reason(*,status:Any,last_error:Any="",send_status:Any="",booking_status:Any="")->str:
    if str(send_status or "").lower() in {"pending","uncertain"}:return "SEND_RECONCILIATION_REQUIRED"
    if str(booking_status or "").lower() in {"pending","uncertain"}:return "BOOKING_RECONCILIATION_REQUIRED"
    if str(last_error or "").strip():return str(last_error).strip()[:500]
    if project_stage(status)=="needs_attention":return "UNKNOWN_OPERATIONAL_STATE"
    return ""

def state_snapshot(*,status:Any,last_error:Any="",send_status:Any="",booking_status:Any="")->Dict[str,Any]:
    reason=attention_reason(status=status,last_error=last_error,send_status=send_status,booking_status=booking_status)
    return {"stage":"needs_attention" if reason else project_stage(status),"needs_attention":bool(reason),"attention_reason":reason}
