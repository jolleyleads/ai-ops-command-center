import json
import os
import re
from urllib.parse import urlparse
import requests
from app import db
from outreach_automation import OutreachLead, _draft_email
from src.enrichment import enrich_lead, validated_payload

EMAIL_RE=re.compile(r"(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])")
QUEUE_MIN_SCORE=int(os.getenv("OUTREACH_REVIEW_MIN_SCORE","60"))
AUTOSEND_ENABLED=os.getenv("OUTREACH_AUTOSEND_ENABLED","false").lower() in {"1","true","yes","on"}

def _clean(v,limit=2000):return str(v or "").strip()[:limit]
def _valid_email(v):
    v=_clean(v,500).lower()
    return v if EMAIL_RE.fullmatch(v) and not v.endswith((".png",".jpg",".jpeg",".gif",".webp",".svg")) else ""
def _host(url):
    try:return (urlparse(url).hostname or "").lower().removeprefix("www.")
    except Exception:return ""
def _same_company_domain(email,urls):
    d=email.rsplit("@",1)[-1].lower()
    return any(d==_host(u) or d.endswith("."+_host(u)) or _host(u).endswith("."+d) for u in urls if _host(u))
def _candidate_urls(result):
    vals=[]
    for k in ("website","direct_url","source_url","url"):
        u=_clean(result.get(k),1800)
        if u.startswith(("http://","https://")):vals.append(u)
    for e in result.get("evidence") or []:
        if isinstance(e,dict):
            u=_clean(e.get("url"),1800)
            if u.startswith(("http://","https://")):vals.append(u)
    return list(dict.fromkeys(vals))[:6]
def _verified_public_email(result):
    urls=_candidate_urls(result)
    for k in ("contact_email","email","recruiterEmail"):
        e=_valid_email(result.get(k))
        if e and urls and _same_company_domain(e,urls):return e,"search_result"
    for evidence in result.get("evidence") or []:
        if isinstance(evidence,dict):
            for value in evidence.values():
                if isinstance(value,str):
                    for candidate in EMAIL_RE.findall(value):
                        e=_valid_email(candidate)
                        if e and urls and _same_company_domain(e,urls):return e,"evidence"
    headers={"User-Agent":"Mozilla/5.0 AI-Ops-Contact-Verification/2.0"}
    for url in urls:
        try:r=requests.get(url,headers=headers,timeout=8,allow_redirects=True)
        except requests.RequestException:continue
        if not r.ok:continue
        ct=(r.headers.get("content-type") or "").lower()
        if "text/html" not in ct and "text/plain" not in ct:continue
        for candidate in EMAIL_RE.findall(r.text[:500000]):
            e=_valid_email(candidate)
            if e and _same_company_domain(e,[r.url,url]):return e,r.url
    return "",""
def _evidence_score(result):
    raw=result.get("intent_score")
    if raw is None:raw=result.get("prospect_score")
    if raw is None:raw=result.get("quality_score")
    if raw is not None:
        try:return max(0,min(int(raw),100))
        except (TypeError,ValueError):pass
    status=_clean(result.get("promotion_status"),50).lower()
    try:base=float(result.get("evidence_score") or 0)
    except (TypeError,ValueError):base=0
    if status=="promoted":return max(75,min(100,int(base*100)))
    if status=="verified_page":return max(60,min(89,int(base*100)))
    return min(59,max(0,int(base*100)))
def _verified(result):
    label=_clean(result.get("verification"),100).upper()
    if label in {"VERIFIED_INTENT","CROSS_CHECKED_VERIFIED_INTENT","LIKELY_VERIFIED_INTENT","VERIFIED"}:return True
    return _clean(result.get("promotion_status"),50).lower() in {"promoted","verified_page"} and bool(_candidate_urls(result))
def _contractor_search(payload):
    text=" ".join([_clean(payload.get("intent"),100),_clean(payload.get("goal"),500),_clean(payload.get("query"),500)]).lower()
    return any(x in text for x in ("contractor","electrician","electrical","master electrician","qualifying agent","permit"))
def _evidence_for_storage(result):
    evidence=result.get("evidence") if isinstance(result.get("evidence"),list) else []
    if evidence:return evidence
    return [{"title":_clean(result.get("title"),500),"snippet":_clean(result.get("subtitle"),1500),"url":_clean(result.get("url"),1800),"source":_clean(result.get("source"),300),"promotion_status":_clean(result.get("promotion_status"),50),"evidence_basis":_clean(result.get("evidence_basis"),300)}]

def ingest_verified_results(search_payload):
    summary={"enabled":True,"autosend_enabled":AUTOSEND_ENABLED,"mode":"queue_only" if not AUTOSEND_ENABLED else "autosend","eligible":0,"saved":0,"drafted":0,"sent":0,"skipped":[]}
    if not _contractor_search(search_payload):
        summary["enabled"]=False;summary["paused_reason"]="not_contractor_or_permit_search";return summary
    for result in search_payload.get("results") or []:
        if not isinstance(result,dict):continue
        company=_clean(result.get("company") or result.get("name") or result.get("business_name") or result.get("title"),300)
        score=_evidence_score(result)
        if not company or score<QUEUE_MIN_SCORE or not _verified(result):continue
        summary["eligible"]+=1
        urls=_candidate_urls(result);source_url=urls[0] if urls else ""
        enrichment=enrich_lead({"company_name":company,"website":result.get("website"),"url":result.get("url"),"phone":result.get("phone"),"email":result.get("email"),"discovery_urls":urls}, result.get("evidence") or [result])
        validated=validated_payload(enrichment)
        email=_clean(validated.get("email"),500)
        email_source=_clean(validated.get("email_source_url"),1800)
        contact_name=_clean(validated.get("decision_maker"),300)
        existing=OutreachLead.query.filter_by(company=company,source_url=source_url).first()
        if existing:
            summary["skipped"].append({"company":company,"reason":"already_queued","lead_id":existing.id});continue
        lead=OutreachLead(company=company,contact_email=email,contact_name=contact_name,location=_clean(result.get("location") or search_payload.get("location"),300),source_url=source_url,evidence_json=json.dumps({"verification":_evidence_for_storage(result),"enrichment":enrichment,"validated":validated}),score=score,verification=_clean(result.get("verification"),100) or "SOURCE_VERIFIED",status="review")
        db.session.add(lead);db.session.commit();summary["saved"]+=1
        if email:
            drafted=_draft_email(lead)
            if drafted.get("ok"):
                lead.subject=drafted["subject"];lead.body=drafted["body"];lead.status="drafted";lead.last_error="";db.session.commit();summary["drafted"]+=1
            else:
                lead.last_error=_clean(drafted.get("error"),2000);db.session.commit();summary["skipped"].append({"company":company,"reason":"draft_failed"})
        else:summary["skipped"].append({"company":company,"reason":"no_verified_public_email"})
        summary["skipped"].append({"company":company,"email_source":email_source,"status":lead.status,"lead_id":lead.id})
    return summary
