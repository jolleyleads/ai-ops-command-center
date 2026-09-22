"""Reply qualification and booking readiness gates.

The LLM may interpret a reply, but deterministic code validates the interpretation
against reply text and decides whether booking is allowed.
"""
from __future__ import annotations
import re
from typing import Any, Dict

OPT_OUT=re.compile(r"(?i)\b(unsubscribe|opt[ -]?out|remove me|do not contact|don't contact|stop emailing|stop contacting|take me off)\b")
NEGATIVE=re.compile(r"(?i)\b(not interested|no thanks|no thank you|not now|don't need|do not need|we're good|we are good)\b")
QUESTION=re.compile(r"\?|\b(how much|price|pricing|cost|what do you|how does|can you|could you|do you|where|when|who)\b", re.I)
INTEREST=re.compile(r"(?i)\b(interested|sounds good|let's talk|lets talk|call me|schedule|book|meeting|available|tell me more|yes|sure)\b")
TIME_SIGNAL=re.compile(r"(?i)\b(today|tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|am|pm|morning|afternoon|evening|noon|\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm))\b")

ALLOWED={"interested","not_interested","question","unclear"}

def _clean(v:Any,limit:int=8000)->str:return " ".join(str(v or "").strip().split())[:limit]

def deterministic_signals(reply_text:Any)->Dict[str,bool]:
    text=_clean(reply_text)
    return {
        "opt_out":bool(OPT_OUT.search(text)),
        "negative":bool(NEGATIVE.search(text)),
        "question":bool(QUESTION.search(text)),
        "interest":bool(INTEREST.search(text)),
        "time_signal":bool(TIME_SIGNAL.search(text)),
    }

def validate_reply_classification(reply_text:Any, proposed:Dict[str,Any])->Dict[str,Any]:
    text=_clean(reply_text)
    signals=deterministic_signals(text)
    reasons=[]
    label=_clean((proposed or {}).get("classification"),100).lower()
    if not text:reasons.append("MISSING_REPLY_TEXT")
    if label not in ALLOWED:reasons.append("INVALID_CLASSIFICATION")
    # Deterministic precedence prevents an LLM from overriding explicit stop/negative text.
    if signals["opt_out"]:
        final="not_interested"
    elif signals["negative"]:
        final="not_interested"
    elif signals["question"]:
        final="question"
    elif signals["interest"]:
        final="interested"
    elif label in ALLOWED:
        final=label
    else:
        final="unclear"
    if signals["opt_out"] and label=="interested":reasons.append("CLASSIFICATION_CONFLICTS_WITH_OPT_OUT")
    if signals["negative"] and label=="interested":reasons.append("CLASSIFICATION_CONFLICTS_WITH_NEGATIVE")
    return {"ok":bool(text) and not reasons,"validated":bool(text) and not reasons,"classification":final,"signals":signals,"reasons":reasons}

def booking_readiness(classification:Dict[str,Any], proposed:Dict[str,Any])->Dict[str,Any]:
    reasons=[]
    if classification.get("validated") is not True:reasons.append("UNVALIDATED_REPLY_CLASSIFICATION")
    if classification.get("classification")!="interested":reasons.append("NOT_INTERESTED_FOR_BOOKING")
    if classification.get("signals",{}).get("opt_out"):reasons.append("OPT_OUT")
    start=_clean((proposed or {}).get("start"),100)
    end=_clean((proposed or {}).get("end"),100)
    timezone=_clean((proposed or {}).get("timezone"),100)
    attendee=_clean((proposed or {}).get("attendee_email"),500)
    if not start:reasons.append("MISSING_START")
    if not end:reasons.append("MISSING_END")
    if not timezone:reasons.append("MISSING_TIMEZONE")
    if not attendee or "@" not in attendee:reasons.append("MISSING_ATTENDEE_EMAIL")
    ready=not reasons
    return {"ok":ready,"validated":ready,"booking_ready":ready,"reasons":reasons,"start":start,"end":end,"timezone":timezone,"attendee_email":attendee}

def validate_booking_receipt(receipt:Dict[str,Any])->Dict[str,Any]:
    receipt=receipt if isinstance(receipt,dict) else {}
    reasons=[]
    if receipt.get("ok") is not True:reasons.append("BOOKING_PROVIDER_FAILED")
    event_id=_clean(receipt.get("event_id"),255)
    if not event_id:reasons.append("MISSING_EVENT_ID")
    return {"ok":not reasons,"validated":not reasons,"event_id":event_id,"event_url":_clean(receipt.get("event_url"),1800),"reasons":reasons}
