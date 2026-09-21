"""Deterministic qualification gate.

Only source-validated enrichment may qualify a lead. The LLM may explain or
personalize later; it cannot waive these requirements or manufacture fields.
"""
from __future__ import annotations
from typing import Any, Dict
from urllib.parse import urlparse

def _clean(v:Any,limit:int=1000)->str:return " ".join(str(v or "").strip().split())[:limit]

def _source_url(v:Any)->bool:
    try:
        p=urlparse(_clean(v,1800))
        return p.scheme in {"http","https"} and bool(p.hostname)
    except Exception:return False

def qualify_lead(validated:Dict[str,Any], *, verification_ok:bool=True)->Dict[str,Any]:
    """Apply hard qualification rules to the validated enrichment view only."""
    reasons=[]
    company=_clean(validated.get("company_name"),300)
    if not verification_ok:reasons.append("lead_not_verified")
    if not company:reasons.append("missing_company")
    website=_clean(validated.get("website"),1800)
    if not website or not _source_url(validated.get("website_source_url")):
        reasons.append("missing_validated_website")

    email=_clean(validated.get("email"),500)
    phone=_clean(validated.get("phone"),100)
    email_ok=bool(email and _source_url(validated.get("email_source_url")))
    phone_ok=bool(phone and _source_url(validated.get("phone_source_url")))
    if not (email_ok or phone_ok):reasons.append("missing_validated_contact_channel")

    dm=_clean(validated.get("decision_maker"),300)
    dm_ok=bool(dm and _source_url(validated.get("decision_maker_source_url")))
    evidence=[x for x in (validated.get("evidence") or []) if isinstance(x,dict) and _source_url(x.get("url"))]
    if not evidence:reasons.append("missing_source_evidence")

    qualified=not reasons
    return {
        "ok":qualified,
        "qualified":qualified,
        "reasons":reasons,
        "company_name":company,
        "contact_channel":"email" if email_ok else ("phone" if phone_ok else ""),
        "decision_maker_validated":dm_ok,
        "evidence_urls":[x["url"] for x in evidence],
        "validated_input":validated if qualified else {},
    }

def qualification_payload(validated:Dict[str,Any], qualification:Dict[str,Any])->Dict[str,Any]:
    """Fail closed: downstream outreach receives no lead fields unless qualified."""
    if not qualification.get("qualified") or not qualification.get("ok"):return {}
    allowed=(
        "company_name","website","website_source_url","decision_maker",
        "decision_maker_title","decision_maker_source_url","phone","phone_source_url",
        "email","email_source_url","evidence",
    )
    return {k:validated[k] for k in allowed if k in validated}
