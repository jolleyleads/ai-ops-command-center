"""Deterministic follow-up and reply stop rules.

Any verified inbound reply stops automation. Opt-out language is a stronger terminal
stop. The LLM is never used to decide whether another message may be sent.
"""
from __future__ import annotations
import re
from email.utils import parseaddr
from typing import Any, Dict, Iterable

OPT_OUT_RE=re.compile(
    r"(?i)\b(unsubscribe|opt[ -]?out|remove me|remove us|do not contact|don't contact|"
    r"stop emailing|stop email|stop contacting|no more emails|take me off|take us off)\b"
)

def _clean(v:Any,limit:int=8000)->str:return " ".join(str(v or "").strip().split())[:limit]

def classify_inbound(messages:Iterable[Dict[str,Any]],sender_email:str="")->Dict[str,Any]:
    """Classify only messages not sent by our configured sender."""
    sender=_clean(sender_email,500).lower()
    inbound=[]
    for msg in messages or []:
        if not isinstance(msg,dict):continue
        from_value=_clean(msg.get("from"),1000).lower()
        parsed_from=_clean(msg.get("from_email"),500).lower() or parseaddr(from_value)[1].lower().strip()
        if sender and parsed_from==sender:continue
        # Without a configured sender, require the caller to explicitly mark inbound.
        if not sender and msg.get("inbound") is not True:continue
        text=_clean(msg.get("text") or msg.get("snippet") or msg.get("body"),8000)
        inbound.append({"message_id":_clean(msg.get("message_id") or msg.get("id"),255),"from":from_value,"from_email":parsed_from,"text":text,"thread_id":_clean(msg.get("thread_id"),255),"body_source":_clean(msg.get("body_source"),50),"internal_date":_clean(msg.get("internal_date"),50)})
    if not inbound:
        return {"ok":True,"replied":False,"opted_out":False,"stop":False,"reason":"NO_INBOUND_REPLY","reply_evidence":[]}
    opted=any(OPT_OUT_RE.search(x["text"] or "") for x in inbound)
    return {
        "ok":True,"replied":True,"opted_out":opted,"stop":True,
        "reason":"OPT_OUT" if opted else "INBOUND_REPLY",
        "reply_evidence":inbound,
    }

def followup_permission(*,reply_state:Dict[str,Any],follow_up_count:int,max_followups:int,thread_id:str,contact_email:str)->Dict[str,Any]:
    reasons=[]
    if reply_state.get("ok") is not True:reasons.append("REPLY_CHECK_FAILED")
    if reply_state.get("stop") is True:reasons.append("HARD_STOP_"+str(reply_state.get("reason") or "REPLY"))
    if not _clean(thread_id,255):reasons.append("MISSING_THREAD_ID")
    if not _clean(contact_email,500):reasons.append("MISSING_CONTACT_EMAIL")
    if int(follow_up_count or 0)>=int(max_followups):reasons.append("MAX_FOLLOWUPS_REACHED")
    return {"ok":not reasons,"allowed":not reasons,"reasons":reasons}
