"""Deterministic, source-bound lead enrichment.

Retrieval may be performed by search providers. This module owns validation:
unsupported fields are omitted and only validated values may flow downstream.
"""
from __future__ import annotations
import re
from typing import Any, Dict, Iterable
from urllib.parse import urlparse
from src.company_identity import identity_proof, host, owned_host, email_on_domain, contact_context_matches
from src.company_identity import current_contact_source
from src.contact_assessment import assess_people, is_shared_email, current_email_context

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
        if not current_contact_source(row):continue
        candidate=_clean(row.get("candidate_name") or row.get("company_name") or row.get("company"),300)
        if candidate and _company_key(candidate)!=key:continue
        u=_url(row.get("url") or row.get("source_url"))
        if not u:continue
        text=str(row.get("page_text") or row.get("text") or "")[:120000]
        yield row,u,text

def enrich_lead(lead:Dict[str,Any],evidence_rows:Iterable[Dict[str,Any]], *, email_allowed=None)->Dict[str,Any]:
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

    # Keep all source-local addresses so a known wrong person cannot become
    # the fallback simply because their email occurred first on the page.
    email_candidates=[]
    for row,u,text in rows:
        for e in EMAIL_RE.findall(text):
            email=_email(e)
            if email and email_on_domain(email,website) and contact_context_matches(text,email,location) and current_email_context(text,email) and (email_allowed is None or email_allowed(email)):
                email_candidates.append({"value":email,"source_url":u,"validated":True,"observed_at":row.get("observed_at")})
                out["fields"].setdefault("email",email_candidates[-1])
        if "phone" not in out["fields"]:
            for match in PHONE_RE.finditer(text):
                if contact_context_matches(text,match.group(0),location):
                    out["fields"]["phone"]={"value":_phone(match.group(0)),"source_url":u,"validated":True,"observed_at":row.get("observed_at")};break
        out["evidence"].append({"url":u,"title":_clean(row.get("title"),500),"snippet":_clean(row.get("subtitle") or row.get("snippet"),1500),"observed_at":row.get("observed_at"),"directly_fetched":True,"http_status":200})

    query=_clean(lead.get("query") or lead.get("business_need") or lead.get("intent_signal"),1000)
    candidates,person,person_status=assess_people(rows,company,website,location,query)
    out["decision_maker_candidates"]=candidates
    assessment={"version":"contact-evidence-v2","company_status":"source_bound","target_location":location,"decision_maker_status":person_status,"email_person_status":"unconfirmed","mailbox_status":"unconfirmed","reason_codes":[]}
    if not location:assessment["reason_codes"].append("CONTACT_LOCALITY_NOT_REQUESTED")
    if person:
        out["fields"]["decision_maker"]={"value":person["name"],"title":person["title"],"source_url":person["source_url"],"validated":True,"responsibility_status":person["responsibility_status"],"observed_at":person["observed_at"]}
        if person["email"] and person["status"]=="source_supported" and (email_allowed is None or email_allowed(person["email"])):
            out["fields"]["email"]={"value":person["email"],"source_url":person["source_url"],"validated":True,"observed_at":person["observed_at"]}
            assessment.update(email_person_status="same_source_card",person_name=person["name"],person_email=person["email"])
    elif candidates:assessment["reason_codes"].append("DECISION_MAKER_NOT_UNIQUELY_SUPPORTED")
    if query and candidates and assessment["email_person_status"]!="same_source_card":
        generic=next((c for c in email_candidates if is_shared_email(c["value"])),None)
        if generic:out["fields"]["email"]=generic
        else:out["fields"].pop("email",None)
        assessment["reason_codes"].append("PERSONAL_EMAIL_RESPONSIBILITY_NOT_PROVEN")
    email=out["fields"].get("email")
    if email:
        email.update(observation_status="source_observed",mailbox_status="unconfirmed",deliverability_status="unconfirmed",address_kind="shared_inbox" if is_shared_email(email["value"]) else "individual_or_unknown")
        if is_shared_email(email["value"]):assessment["reason_codes"].append("SHARED_INBOX_NOT_PERSONAL_EMAIL")
    out["contact_assessment"]=assessment

    out["evidence"]=list({x["url"]:x for x in out["evidence"]}.values())
    out["validated"]=bool(out["fields"]) and all(v.get("validated") and _url(v.get("source_url")) for v in out["fields"].values())
    return out

def validated_payload(enrichment:Dict[str,Any])->Dict[str,Any]:
    """The only enrichment shape qualification/outreach should consume."""
    if not enrichment.get("validated"):return {}
    payload={"company_name":_clean(enrichment.get("company_name"),300),"evidence":enrichment.get("evidence") or []}
    if enrichment.get("contact_assessment"):payload["contact_assessment"]=enrichment["contact_assessment"]
    for key,record in (enrichment.get("fields") or {}).items():
        if isinstance(record,dict) and record.get("validated") and _url(record.get("source_url")):
            payload[key]=record.get("value")
            payload[f"{key}_source_url"]=record.get("source_url")
            if key=="decision_maker" and record.get("title"):payload["decision_maker_title"]=record.get("title")
    return payload
