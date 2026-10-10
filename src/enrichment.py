"""Deterministic, source-bound lead enrichment.

Retrieval may be performed by search providers. This module owns validation:
unsupported fields are omitted and only validated values may flow downstream.
"""
from __future__ import annotations
import re
from typing import Any, Dict, Iterable
from urllib.parse import urlparse
from src.company_identity import identity_proof, host, owned_host, email_on_domain, contact_context_matches

EMAIL_RE=re.compile(r"(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])")
PHONE_RE=re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?([2-9]\d{2})\)?[ .-]?(\d{3})[ .-]?(\d{4})(?!\d)")
TITLE_RE=re.compile(r"(?i)\b(owner|founder|president|ceo|chief executive officer|general manager|operations manager|hiring manager|recruiter|director|principal|partner)\b")

def _clean(v:Any,limit:int=4000)->str:return " ".join(str(v or "").strip().split())[:limit]
def _url(v:Any)->str:
    u=_clean(v,1800)
    try:
        p=urlparse(u)
        return u if p.scheme in {"http","https"} and bool(p.hostname) else ""
    except Exception:return ""
def _host(u:str)->str:
    try:return (urlparse(u).hostname or "").lower().removeprefix("www.")
    except Exception:return ""
def _company_key(v:Any)->str:return re.sub(r"[^a-z0-9]","",_clean(v,300).lower())
def _same_domain(a:str,b:str)->bool:
    ha,hb=_host(a),_host(b)
    return bool(ha and hb and (ha==hb or ha.endswith("."+hb) or hb.endswith("."+ha)))
def _phone(v:Any)->str:
    m=PHONE_RE.search(_clean(v,500))
    return f"({m.group(1)}) {m.group(2)}-{m.group(3)}" if m else ""
def _email(v:Any)->str:
    m=EMAIL_RE.search(_clean(v,1000))
    if not m:return ""
    e=m.group(1).lower()
    return "" if e.endswith((".png",".jpg",".jpeg",".gif",".webp",".svg")) else e

def _evidence_rows(rows:Iterable[Dict[str,Any]],company:str):
    key=_company_key(company)
    for row in rows or []:
        if not isinstance(row,dict):continue
        candidate=_clean(row.get("candidate_name") or row.get("company_name") or row.get("company"),300)
        if candidate and _company_key(candidate)!=key:continue
        u=_url(row.get("url") or row.get("source_url"))
        if not u:continue
        text=" ".join(_clean(row.get(k),8000) for k in ("title","subtitle","page_text","snippet","text"))
        yield row,u,text

def enrich_lead(lead:Dict[str,Any],evidence_rows:Iterable[Dict[str,Any]])->Dict[str,Any]:
    """Validate source-backed enrichment. No LLM-generated field is accepted as proof."""
    company=_clean(lead.get("company_name") or lead.get("company") or lead.get("name") or lead.get("title"),300)
    out={"company_name":company,"fields":{},"evidence":[],"validated":False}
    if not company:return out
    rows=list(_evidence_rows(evidence_rows,company))
    # A candidate label or arbitrary discovery URL cannot establish ownership.
    explicit=_url(lead.get("website"))
    if not explicit and re.fullmatch(r"[A-Z0-9]{2,4}",company):
        out["identity_status"]="unproven"
        return out
    proofs=[(row,u,text,identity_proof(company,row,explicit)) for row,u,text in rows]
    proofs=[x for x in proofs if x[3]]
    domains={host(explicit)} if explicit and proofs else {x[3]["official_host"] for x in proofs}
    if len(domains)!=1:
        out["identity_status"]="ambiguous" if domains else "unproven"
        return out
    website=explicit or "https://"+next(iter(domains))
    rows=[(row,u,text) for row,u,text,proof in proofs if owned_host(proof["source_url"],website)]
    out["identity_status"]="source_bound"
    location=_clean(lead.get("location") or lead.get("target_location"),300)
    if website:
        out["fields"]["website"]={"value":website,"source_url":website,"validated":True}

    # Contacts are accepted only when found in candidate-specific source text.
    for row,u,text in rows:
        if "email" not in out["fields"]:
            for e in EMAIL_RE.findall(text):
                email=_email(e)
                if email and email_on_domain(email,website) and contact_context_matches(text,email,location):
                    out["fields"]["email"]={"value":email,"source_url":u,"validated":True};break
        if "phone" not in out["fields"]:
            for match in PHONE_RE.finditer(text):
                if contact_context_matches(text,match.group(0),location):
                    out["fields"]["phone"]={"value":_phone(match.group(0)),"source_url":u,"validated":True};break
        if "decision_maker" not in out["fields"]:
            # Require a title plus a nearby human-looking two-word name in the same source.
            tm=TITLE_RE.search(text)
            if tm:
                window=text[max(0,tm.start()-100):min(len(text),tm.end()+100)]
                names=re.findall(r"\b([A-Z][a-z]{1,30}\s+[A-Z][a-z]{1,30})\b",window)
                names=[n for n in names if n.lower() not in {"Virginia Beach","United States"}]
                if names:
                    out["fields"]["decision_maker"]={"value":names[0],"title":tm.group(1),"source_url":u,"validated":True}
        out["evidence"].append({"url":u,"title":_clean(row.get("title"),500),"snippet":_clean(row.get("subtitle") or row.get("snippet"),1500)})

    # Existing phone/email may pass only when evidence text actually contains the value.
    existing_phone=_phone(lead.get("phone"))
    if existing_phone and "phone" not in out["fields"]:
        digits=re.sub(r"\D","",existing_phone)[-10:]
        for row,u,text in rows:
            if digits and digits in re.sub(r"\D","",text) and not location:
                out["fields"]["phone"]={"value":existing_phone,"source_url":u,"validated":True};break
    existing_email=_email(lead.get("email") or lead.get("contact_email"))
    if existing_email and "email" not in out["fields"]:
        for row,u,text in rows:
            if existing_email.lower() in text.lower() and email_on_domain(existing_email,website) and contact_context_matches(text,existing_email,location):
                out["fields"]["email"]={"value":existing_email,"source_url":u,"validated":True};break

    out["evidence"]=list({x["url"]:x for x in out["evidence"]}.values())
    out["validated"]=bool(out["fields"]) and all(v.get("validated") and _url(v.get("source_url")) for v in out["fields"].values())
    return out

def validated_payload(enrichment:Dict[str,Any])->Dict[str,Any]:
    """The only enrichment shape qualification/outreach should consume."""
    if not enrichment.get("validated"):return {}
    payload={"company_name":_clean(enrichment.get("company_name"),300),"evidence":enrichment.get("evidence") or []}
    for key,record in (enrichment.get("fields") or {}).items():
        if isinstance(record,dict) and record.get("validated") and _url(record.get("source_url")):
            payload[key]=record.get("value")
            payload[f"{key}_source_url"]=record.get("source_url")
            if key=="decision_maker" and record.get("title"):payload["decision_maker_title"]=record.get("title")
    return payload
