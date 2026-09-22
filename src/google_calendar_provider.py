"""Google Calendar provider for deterministic booking execution."""
from __future__ import annotations
import os
from typing import Any, Dict
import requests
from app import gmail_access_token

BASE="https://www.googleapis.com/calendar/v3"

def _headers()->Dict[str,str]:
    return {"Authorization":f"Bearer {gmail_access_token()}","Content-Type":"application/json"}

def check_availability(req:Dict[str,Any])->Dict[str,Any]:
    calendar_id=os.environ.get("GOOGLE_CALENDAR_ID","primary").strip() or "primary"
    payload={"timeMin":req["start"],"timeMax":req["end"],"timeZone":req["timezone"],"items":[{"id":calendar_id}]}
    try:
        r=requests.post(f"{BASE}/freeBusy",headers=_headers(),json=payload,timeout=30)
        if not r.ok:return {"ok":False,"available":False,"error":f"Google Calendar freeBusy {r.status_code}: {r.text[:500]}"}
        busy=((r.json().get("calendars") or {}).get(calendar_id) or {}).get("busy") or []
        return {"ok":True,"available":len(busy)==0,"checked_start":req["start"],"checked_end":req["end"],"busy":busy}
    except Exception as exc:
        return {"ok":False,"available":False,"error":str(exc)[:500]}

def create_event(req:Dict[str,Any],*,summary:str,description:str="",idempotency_key:str="")->Dict[str,Any]:
    calendar_id=os.environ.get("GOOGLE_CALENDAR_ID","primary").strip() or "primary"
    body={
        "summary":str(summary or "Appointment")[:500],
        "description":str(description or "")[:4000],
        "start":{"dateTime":req["start"],"timeZone":req["timezone"]},
        "end":{"dateTime":req["end"],"timeZone":req["timezone"]},
        "attendees":[{"email":req["attendee_email"]}],
    }
    params={"sendUpdates":"all"}
    # Google Calendar event IDs provide idempotency. Only use a normalized key supplied by caller.
    if idempotency_key:
        body["id"]=idempotency_key.lower()[:1024]
    try:
        r=requests.post(f"{BASE}/calendars/{requests.utils.quote(calendar_id,safe='')}/events",headers=_headers(),params=params,json=body,timeout=30)
        if not r.ok:return {"ok":False,"error":f"Google Calendar create {r.status_code}: {r.text[:500]}"}
        data=r.json()
        return {"ok":True,"event_id":data.get("id") or "","event_url":data.get("htmlLink") or "","start":((data.get("start") or {}).get("dateTime") or ""),"end":((data.get("end") or {}).get("dateTime") or "")}
    except Exception as exc:
        return {"ok":False,"error":str(exc)[:500]}
