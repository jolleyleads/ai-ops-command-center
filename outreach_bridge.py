import json
import os
import re
import time
from urllib.parse import urljoin,urlparse
import requests
from app import db
from outreach_automation import OutreachLead, _draft_email
from src.enrichment import enrich_lead, validated_payload
from src.qualification import qualify_lead, qualification_payload

EMAIL_RE=re.compile(r"(?i)(?<![\w.+-])([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})(?![\w.-])")
QUEUE_MIN_SCORE=int(os.getenv("OUTREACH_REVIEW_MIN_SCORE","60"))
AUTOSEND_ENABLED=os.getenv("OUTREACH_AUTOSEND_ENABLED","false").lower() in {"1","true","yes","on"}
CONTACT_MAX_URLS=max(1,min(int(os.getenv("CONTACT_ENRICH_MAX_URLS","5")),8))
CONTACT_BUDGET_SECONDS=max(2.0,min(float(os.getenv("CONTACT_ENRICH_BUDGET_SECONDS","12")),20.0))
CONTACT_CONNECT_TIMEOUT=max(0.5,min(float(os.getenv("CONTACT_CONNECT_TIMEOUT","1.5")),3.0))
CONTACT_READ_TIMEOUT=max(1.0,min(float(os.getenv("CONTACT_READ_TIMEOUT","2.5")),5.0))

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
    for k in ("website","direct_url","source_url","url","verification_source_url"):
        u=_clean(result.get(k),1800)
        if u.startswith(("http://","https://")):vals.append(u)
    for u in result.get("supporting_urls") or []:
        u=_clean(u,1800)
        if u.startswith(("http://","https://")):vals.append(u)
    for e in result.get("evidence") or []:
        if isinstance(e,dict):
            u=_clean(e.get("url"),1800)
            if u.startswith(("http://","https://")):vals.append(u)
    return list(dict.fromkeys(vals))[:8]
def _public_contact_evidence(result):
    """Fetch bounded candidate-owned pages and retain exact public contact evidence."""
    started=time.monotonic();urls=_candidate_urls(result);rows=[];attempted=0
    headers={"User-Agent":"Mozilla/5.0 AI-Ops-Contact-Verification/2.3"}
    blocked_hosts=("indeed.","ziprecruiter.","glassdoor.","linkedin.","facebook.","google.","yelp.")
    roots=[]
    for u in urls:
        h=_host(u)
        if h and not any(x in h for x in blocked_hosts):
            root=f"{urlparse(u).scheme}://{h}/"
            if root not in roots:roots.append(root)
    # Search more than one candidate-owned domain when discovery provides them,
    # but remain tightly bounded and never follow third-party/aggregator hosts.
    roots=roots[:2]
    fetch_urls=[]
    for root in roots:
        fetch_urls.extend([root,urljoin(root,"contact"),urljoin(root,"contact-us"),urljoin(root,"about"),urljoin(root,"about-us"),urljoin(root,"team"),urljoin(root,"careers")])
    fetch_urls=list(dict.fromkeys(fetch_urls))
    budget_exhausted=False
    seen=set()
    while fetch_urls and attempted<CONTACT_MAX_URLS:
        elapsed=time.monotonic()-started
        remaining=CONTACT_BUDGET_SECONDS-elapsed
        if remaining<=0.5:
            budget_exhausted=True;break
        url=fetch_urls.pop(0)
        if url in seen:continue
        seen.add(url);attempted+=1
        connect_timeout=min(CONTACT_CONNECT_TIMEOUT,max(0.5,remaining/2))
        read_timeout=min(CONTACT_READ_TIMEOUT,max(0.5,remaining-connect_timeout))
        try:r=requests.get(url,headers=headers,timeout=(connect_timeout,read_timeout),allow_redirects=True)
        except requests.RequestException:continue
        if not r.ok:continue
        ct=(r.headers.get("content-type") or "").lower()
        if "text/html" not in ct and "text/plain" not in ct:continue
        final=r.url;final_host=_host(final)
        owning_root=next((root for root in roots if final_host and (final_host==_host(root) or final_host.endswith("."+_host(root)) or _host(root).endswith("."+final_host))),"")
        if not owning_root:continue
        text=r.text[:500000]
        emails=[_valid_email(x) for x in EMAIL_RE.findall(text)]
        emails=list(dict.fromkeys(e for e in emails if e and _same_company_domain(e,[final])))
        phone=re.search(r"(?<!\d)(?:\+?1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]?\d{3}[ .-]?\d{4}(?!\d)",text)
        if emails or phone:
            rows.append({"candidate_name":_clean(result.get("company") or result.get("name") or result.get("business_name") or result.get("title"),300),"title":"Public company contact page","subtitle":" ".join(emails[:3])+(" "+phone.group(0) if phone else ""),"text":text[:120000],"url":final,"source":"public_company_contact_page"})
            # Email is the outreach requirement; stop once exact same-domain proof exists.
            if emails:break
        # Discover explicit contact/about/team/careers links advertised by the
        # company's own page. Only same-company-domain URLs may enter the queue.
        for href,label in re.findall(r'(?is)<a[^>]+href=["\\']([^"\\']+)["\\'][^>]*>(.*?)</a>',text):
            href=_clean(href,1800)
            if not href or href.startswith(("mailto:","tel:","#","javascript:")):continue
            absolute=urljoin(final,href)
            ah=_host(absolute)
            if not ah or not (ah==_host(owning_root) or ah.endswith("."+_host(owning_root)) or _host(owning_root).endswith("."+ah)):continue
            path=(urlparse(absolute).path or "").lower()
            label_text=re.sub(r"<[^>]+>"," ",label).lower()
            contactish=("contact","about","team","staff","career","location","reach","get in touch","connect")
            if any(token in path or token in label_text for token in contactish) and absolute not in seen and absolute not in fetch_urls:
                fetch_urls.insert(0,absolute)
    return rows,{"attempted":attempted,"max_urls":CONTACT_MAX_URLS,"budget_seconds":CONTACT_BUDGET_SECONDS,"elapsed_seconds":round(time.monotonic()-started,3),"budget_exhausted":budget_exhausted,"candidate_owned_roots":len(roots)}

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
def _outreach_search(payload):
    """Allow any evidence-backed B2B prospecting search with an explicit target intent."""
    text=" ".join([_clean(payload.get("intent"),500),_clean(payload.get("goal"),500),_clean(payload.get("query"),500)]).strip()
    return bool(text and isinstance(payload.get("results"),list))

# Backward-compatible name for callers/tests; semantics are now universal.
def _contractor_search(payload):
    return _outreach_search(payload)
def _evidence_for_storage(result):
    evidence=result.get("evidence") if isinstance(result.get("evidence"),list) else []
    if evidence:return evidence
    return [{"title":_clean(result.get("title"),500),"snippet":_clean(result.get("subtitle"),1500),"url":_clean(result.get("url"),1800),"source":_clean(result.get("source"),300),"promotion_status":_clean(result.get("promotion_status"),50),"evidence_basis":_clean(result.get("evidence_basis"),300)}]

def ingest_verified_results(search_payload):
    summary={"enabled":True,"autosend_enabled":AUTOSEND_ENABLED,"mode":"queue_only" if not AUTOSEND_ENABLED else "autosend","eligible":0,"saved":0,"drafted":0,"sent":0,"skipped":[]}
    if not _outreach_search(search_payload):summary["enabled"]=False;summary["paused_reason"]="not_b2b_outreach_search";return summary
    for result in search_payload.get("results") or []:
        if not isinstance(result,dict):continue
        company=_clean(result.get("company") or result.get("name") or result.get("business_name") or result.get("title"),300);score=_evidence_score(result)
        if not company or score<QUEUE_MIN_SCORE or not _verified(result):continue
        summary["eligible"]+=1;urls=_candidate_urls(result);source_url=urls[0] if urls else ""
        base_evidence=result.get("evidence") or [result]
        enrichment=enrich_lead({"company_name":company,"website":result.get("website"),"url":result.get("url"),"phone":result.get("phone"),"email":result.get("email"),"discovery_urls":urls},base_evidence)
        validated=validated_payload(enrichment);contact_probe=None
        if not validated.get("email") and not validated.get("phone"):
            contact_rows,contact_probe=_public_contact_evidence(result)
            if contact_rows:
                enrichment=enrich_lead({"company_name":company,"website":result.get("website"),"url":result.get("url"),"phone":result.get("phone"),"email":result.get("email"),"discovery_urls":urls},list(base_evidence)+contact_rows)
                validated=validated_payload(enrichment)
            if not validated.get("email") and not validated.get("phone"):
                summary["skipped"].append({"company":company,"reason":"contact_enrichment_exhausted","contact_probe":contact_probe})
        existing=OutreachLead.query.filter_by(company=company,source_url=source_url).first()
        qctx={"target_location":_clean(search_payload.get("location"),300),"candidate_location":_clean(result.get("location"),300),"business_type":_clean(search_payload.get("business_type") or search_payload.get("category"),300),"candidate_type":_clean(result.get("category") or result.get("type"),300),"query":_clean(search_payload.get("query") or search_payload.get("goal") or search_payload.get("intent"),1000),"intent_signal":_clean(search_payload.get("intent_signal") or search_payload.get("query") or search_payload.get("goal"),1000),"evidence":result.get("evidence") or [],"duplicate":bool(existing),"excluded":bool(result.get("excluded")),"exclusion_terms":search_payload.get("exclusion_terms") or [],"max_evidence_age_days":search_payload.get("max_evidence_age_days") or 180}
        qualification=qualify_lead(validated,verification_ok=_verified(result),context=qctx);qualified=qualification_payload(validated,qualification)
        if not qualified:summary["skipped"].append({"company":company,"reason":"qualification_failed","qualification_status":qualification.get("status"),"qualification_reason_codes":qualification.get("reason_codes") or [],"validated_contact_fields":[k for k in ("email","phone","decision_maker") if validated.get(k)]});continue
        email=_clean(qualified.get("email"),500);email_source=_clean(qualified.get("email_source_url"),1800);contact_name=_clean(qualified.get("decision_maker"),300)
        if existing:summary["skipped"].append({"company":company,"reason":"already_queued","lead_id":existing.id});continue
        lead=OutreachLead(company=company,contact_email=email,contact_name=contact_name,location=_clean(result.get("location") or search_payload.get("location"),300),source_url=source_url,evidence_json=json.dumps({"verification":_evidence_for_storage(result),"enrichment":enrichment,"validated":validated,"qualification":qualification,"qualified":qualified,"contact_probe":contact_probe}),score=score,verification=_clean(result.get("verification"),100) or "SOURCE_VERIFIED",status="review")
        db.session.add(lead);db.session.commit();summary["saved"]+=1
        if email:
            drafted=_draft_email(lead)
            if drafted.get("ok"):lead.subject=drafted["subject"];lead.body=drafted["body"];lead.status="drafted";lead.last_error="";db.session.commit();summary["drafted"]+=1
            else:lead.last_error=_clean(drafted.get("error"),2000);db.session.commit();summary["skipped"].append({"company":company,"reason":"draft_failed"})
        else:summary["skipped"].append({"company":company,"reason":"no_verified_public_email"})
        summary["skipped"].append({"company":company,"email_source":email_source,"status":lead.status,"lead_id":lead.id})
    return summary
