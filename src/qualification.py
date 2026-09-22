"""Deterministic qualification gate.

Qualification is evidence-driven and fail-closed. The LLM may interpret or
write downstream content, but cannot waive qualification requirements.
"""
from __future__ import annotations
from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable
from urllib.parse import urlparse

QUALIFIED="Qualified"
NOT_QUALIFIED="Not Qualified"
NEEDS_EVIDENCE="Needs More Evidence"

def _clean(v:Any,limit:int=1000)->str:return " ".join(str(v or "").strip().split())[:limit]
def _norm(v:Any)->str:return re.sub(r"[^a-z0-9]+"," ",_clean(v,2000).lower()).strip()
def _source_url(v:Any)->bool:
    try:
        p=urlparse(_clean(v,1800));return p.scheme in {"http","https"} and bool(p.hostname)
    except Exception:return False
def _terms(v:Any)->set[str]:
    stop={"find","with","that","are","the","and","for","from","current","currently","recent","evidence","company","companies","business","businesses","in","of","a","an"}
    return {x for x in _norm(v).split() if len(x)>2 and x not in stop}
def _contains(hay:Any,needle:Any)->bool:
    n=_norm(needle);h=_norm(hay)
    return bool(n and (n in h or all(x in h for x in n.split())))
def _parse_date(v:Any):
    s=_clean(v,80)
    if not s:return None
    try:
        if s.endswith("Z"):s=s[:-1]+"+00:00"
        d=datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:return None
def _evidence(validated:Dict[str,Any],context:Dict[str,Any])->list[Dict[str,Any]]:
    rows=[]
    for x in list(validated.get("evidence") or [])+list(context.get("evidence") or []):
        if isinstance(x,dict) and _source_url(x.get("url") or x.get("source_url")):rows.append(x)
    seen=set();out=[]
    for x in rows:
        u=_clean(x.get("url") or x.get("source_url"),1800)
        if u not in seen:seen.add(u);out.append(x)
    return out
def _row_text(row:Dict[str,Any])->str:
    return " ".join(_clean(row.get(k),5000) for k in ("title","subtitle","snippet","page_text","text","verified_claim","evidence_basis","verification_query"))
def _fresh(row:Dict[str,Any],now:datetime,max_age_days:int)->bool|None:
    d=None
    for k in ("published_at","publishedAt","date","observed_at","observedAt","fetched_at","fetchedAt"):
        d=_parse_date(row.get(k))
        if d:break
    if not d:return None
    return 0 <= (now-d.astimezone(timezone.utc)).total_seconds()/86400 <= max_age_days

def qualify_lead(validated:Dict[str,Any], *, verification_ok:bool=True, context:Dict[str,Any]|None=None, now:datetime|None=None)->Dict[str,Any]:
    """Return an explicit three-state deterministic qualification receipt."""
    context=context or {};now=now or datetime.now(timezone.utc)
    hard=[];missing=[];passed=[]
    company=_clean(validated.get("company_name"),300)
    if verification_ok:passed.append("verified_identity")
    else:hard.append("IDENTITY_NOT_VERIFIED")
    if not company:hard.append("MISSING_COMPANY_IDENTITY")

    website=_clean(validated.get("website"),1800)
    if website and _source_url(validated.get("website_source_url")):passed.append("validated_website")
    else:missing.append("MISSING_VALIDATED_WEBSITE")
    email_ok=bool(_clean(validated.get("email"),500) and _source_url(validated.get("email_source_url")))
    phone_ok=bool(_clean(validated.get("phone"),100) and _source_url(validated.get("phone_source_url")))
    if email_ok or phone_ok:passed.append("validated_contact")
    else:missing.append("MISSING_VALIDATED_CONTACT")

    rows=_evidence(validated,context)
    if rows:passed.append("source_evidence")
    else:missing.append("MISSING_SOURCE_EVIDENCE")

    target_location=_clean(context.get("target_location") or context.get("location"),300)
    actual_location=_clean(context.get("candidate_location") or context.get("lead_location") or context.get("result_location"),300)
    if target_location:
        if actual_location and (_contains(actual_location,target_location) or _contains(target_location,actual_location)):passed.append("geographic_fit")
        elif actual_location:hard.append("GEOGRAPHIC_MISMATCH")
        else:missing.append("GEOGRAPHIC_FIT_UNPROVEN")

    target_type=_clean(context.get("business_type") or context.get("target_business_type"),300)
    actual_type=" ".join([_clean(context.get("candidate_type"),500),_clean(context.get("category"),500),_clean(context.get("query"),1000)]+[_row_text(x) for x in rows])
    if target_type:
        if _terms(target_type) & _terms(actual_type):passed.append("business_type_fit")
        else:missing.append("BUSINESS_TYPE_FIT_UNPROVEN")

    intent=_clean(context.get("intent_signal") or context.get("search_intent") or context.get("query"),1000)
    intent_terms=_terms(intent)
    evidence_text=" ".join(_row_text(x) for x in rows)
    if intent_terms:
        matched=intent_terms & _terms(evidence_text)
        threshold=1 if len(intent_terms)<=2 else 2
        if len(matched)>=threshold:passed.append("intent_signal_fit")
        else:missing.append("INTENT_SIGNAL_UNPROVEN")

    max_age=int(context.get("max_evidence_age_days") or 180)
    if rows:
        freshness=[_fresh(x,now,max_age) for x in rows]
        if any(x is True for x in freshness):passed.append("evidence_recency")
        elif all(x is False for x in freshness if x is not None) and any(x is False for x in freshness):hard.append("EVIDENCE_STALE")
        else:missing.append("EVIDENCE_RECENCY_UNPROVEN")

    if context.get("duplicate"):hard.append("DUPLICATE_LEAD")
    if context.get("excluded"):hard.append("EXCLUDED_LEAD")
    exclusion_terms=[_norm(x) for x in context.get("exclusion_terms") or [] if _norm(x)]
    combined=_norm(" ".join([company,actual_location,actual_type,evidence_text]))
    if any(x in combined for x in exclusion_terms):hard.append("EXCLUSION_RULE_MATCHED")

    if hard:status=NOT_QUALIFIED
    elif missing:status=NEEDS_EVIDENCE
    else:status=QUALIFIED
    ok=status==QUALIFIED
    return {
        "ok":ok,"qualified":ok,"status":status,
        "reason_codes":hard+missing,
        "passed_checks":passed,
        "company_name":company,
        "contact_channel":"email" if email_ok else ("phone" if phone_ok else ""),
        "evidence_urls":[_clean(x.get("url") or x.get("source_url"),1800) for x in rows],
        "validated_input":validated if ok else {},
    }

def qualification_payload(validated:Dict[str,Any],qualification:Dict[str,Any])->Dict[str,Any]:
    """Only an explicit successful Qualified receipt may flow to outreach."""
    if qualification.get("status")!=QUALIFIED or qualification.get("qualified") is not True or qualification.get("ok") is not True:return {}
    allowed=("company_name","website","website_source_url","decision_maker","decision_maker_title","decision_maker_source_url","phone","phone_source_url","email","email_source_url","evidence")
    return {k:validated[k] for k in allowed if k in validated}
