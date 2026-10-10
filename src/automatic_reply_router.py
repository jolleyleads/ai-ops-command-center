"""Automatic grounded routing for durable inbound reply evidence.

Deterministic text rules own hard stops and clear intents. Ambiguous text may be
proposed by an LLM, but the existing validator owns the final classification.
Scheduling details are never invented here; automatic booking requires explicit
machine-parseable ISO timestamps in the reply.
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
    raw=str(text or "")
    stamps=ISO.findall(raw)
    tz=TZ.search(raw)
    explicit = {
        "start":stamps[0] if len(stamps)>0 else "",
        "end":stamps[1] if len(stamps)>1 else "",
        "timezone":tz.group(1) if tz else "",
    }
    if explicit["start"] or explicit["end"]:
        return explicit
    # Explicit full date + AM/PM only; ambiguous or multiple dates stay pending.
    months="January February March April May June July August September October November December".split()
    pattern=r"\b("+"|".join(months)+r")\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(20\d{2})\s+(?:at\s+)?(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b"
    matches=list(re.finditer(pattern,current_reply_text(raw),re.I))
    if len(matches)!=1:return explicit
    match=matches[0];month,day,year,hour,minute,period=match.groups()
    zone=tz.group(1) if tz else os.getenv("BOOKING_TIMEZONE","America/New_York")
    # Never silently override another explicitly named timezone.
    if not tz and re.search(r"\b(?:UTC|GMT|PST|PDT|Pacific|CST|CDT|Central|MST|MDT|Mountain)\b",raw,re.I):return explicit
    try:
        hour=int(hour)
        if not 1<=hour<=12:return explicit
        length=int(os.getenv("BOOKING_DURATION_MINUTES","30"))
        if not 5<=length<=120:return explicit
        start=datetime(int(year),[m.lower() for m in months].index(month.lower())+1,int(day),hour%12+(12 if period.lower()=="pm" else 0),int(minute or 0),tzinfo=ZoneInfo(zone))
        if start<=datetime.now(ZoneInfo(zone)):return explicit
        return {"start":start.isoformat(),"end":(start+timedelta(minutes=length)).isoformat(),"timezone":zone}
    except (ValueError,KeyError):return explicit

def current_reply_text(text):
    # Quoted outbound questions must not become the customer's intent.
    return re.split(r"\s+On\s+.{0,500}?wrote:\s*",str(text or ""),maxsplit=1,flags=re.I)[0].strip()

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
