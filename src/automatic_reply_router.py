"""Automatic grounded routing for durable inbound reply evidence.

Deterministic text rules own hard stops and clear intents. Ambiguous text may be
proposed by an LLM, but the existing validator owns the final classification.
Scheduling details are never invented here; automatic booking requires explicit
full dates and times in the reply.
"""
from __future__ import annotations
import json,re,os
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from typing import Any,Callable,Dict
from src.reply_booking import deterministic_signals,validate_reply_classification

ISO=re.compile(r"\b(20\d\d-\d\d-\d\dT\d\d:\d\d(?::\d\d)?(?:Z|[+-]\d\d:\d\d))\b")
TZ=re.compile(r"\b(America/[A-Za-z_]+(?:/[A-Za-z_]+)?)\b")

def deterministic_proposal(text:Any)->Dict[str,Any]:
    signals=deterministic_signals(text)
    if signals["opt_out"] or signals["negative"]:label="not_interested"
    elif signals["question"]:label="question"
    elif signals["interest"]:label="interested"
    else:label="unclear"
    return {"classification":label}

def extract_explicit_booking(text:Any)->Dict[str,str]:
    from src.scheduling_dates import interpret_booking
    result=interpret_booking(text)
    return {key:result[key] for key in ("start","end","timezone")}

def current_reply_text(text):
    # Quoted outbound questions must not become the customer's intent.
    return re.split(r"\s+On\s+.{0,500}?wrote:\s*",str(text or ""),maxsplit=1,flags=re.I|re.S)[0].strip()

def classify_reply(text:Any,llm_func:Callable|None=None)->Dict[str,Any]:
    proposal=deterministic_proposal(text)
    # Only unclear text may ask the LLM for interpretation. Deterministic validation
    # still owns the result and explicit opt-out/negative/question rules.
    if proposal["classification"]=="unclear" and llm_func:
        try:
            raw=llm_func(str(text or ""))
            if isinstance(raw,dict) and raw.get("classification"):
                proposal={"classification":str(raw["classification"]).strip().lower()}
        except Exception:
            proposal={"classification":"unclear"}
    return validate_reply_classification(text,proposal)
