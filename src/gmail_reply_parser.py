"""Deterministic Gmail MIME body extraction for reply evidence."""
from __future__ import annotations
import base64, html, re
from email.utils import parseaddr
from typing import Any, Dict, List

TAG_RE=re.compile(r"<[^>]+>")
SPACE_RE=re.compile(r"\s+")

def _decode(data:Any)->str:
    raw=str(data or "")
    if not raw:return ""
    try:
        raw += "=" * (-len(raw) % 4)
        return base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8","replace")
    except Exception:
        return ""

def _plain_html(value:str)->str:
    text=re.sub(r"(?is)<(script|style).*?>.*?</\1>"," ",value or "")
    text=re.sub(r"(?i)<br\s*/?>","\n",text)
    text=re.sub(r"(?i)</p\s*>","\n",text)
    return html.unescape(TAG_RE.sub(" ",text))

def extract_body(payload:Dict[str,Any],limit:int=20000)->Dict[str,Any]:
    plain:List[str]=[];html_parts:List[str]=[]
    def walk(part:Dict[str,Any]):
        if not isinstance(part,dict):return
        mime=str(part.get("mimeType") or "").lower()
        data=((part.get("body") or {}).get("data"))
        decoded=_decode(data)
        if decoded:
            if mime=="text/plain":plain.append(decoded)
            elif mime=="text/html":html_parts.append(decoded)
        for child in part.get("parts") or []:walk(child)
    walk(payload or {})
    source="text/plain" if plain else ("text/html" if html_parts else "none")
    text="\n".join(plain) if plain else _plain_html("\n".join(html_parts))
    text=SPACE_RE.sub(" ",text).strip()[:limit]
    return {"ok":bool(text),"text":text,"source":source}

def message_to_evidence(message:Dict[str,Any])->Dict[str,Any]:
    payload=message.get("payload") or {}
    headers={str(h.get("name") or "").lower():str(h.get("value") or "") for h in payload.get("headers") or []}
    body=extract_body(payload)
    from_raw=headers.get("from","")
    _,from_email=parseaddr(from_raw)
    return {
        "message_id":str(message.get("id") or "")[:255],
        "thread_id":str(message.get("threadId") or "")[:255],
        "from":from_raw[:1000],
        "from_email":from_email.strip().lower()[:500],
        "text":body["text"],
        "body_source":body["source"],
        "internal_date":str(message.get("internalDate") or "")[:50],
    }
