"""V1.1 evidence upgrade layered above the frozen V1 engine.

This verifier is deliberately bounded: Smart Search already performs live-source
retrieval, so this layer deterministically evaluates the evidence attached to
those discovered candidates instead of starting another serial network crawl.
It never fabricates a company, contact, claim, or URL and never bypasses V1.
"""
import re
from urllib.parse import urlparse


def _s(v,n=3000): return str(v or "").strip()[:n]
def _key(v): return re.sub(r"[^a-z0-9]+","",_s(v,300).lower())


def _candidate_name(row):
    return _s(row.get("company") or row.get("name") or row.get("business_name") or row.get("title"),300)


def _intent_patterns(query):
    q=_s(query,1200).lower(); patterns=[]
    if any(x in q for x in ("hiring","hire ","jobs","technician","open role")):
        patterns += [
            r"\b(?:hiring|seeking|careers?|job opening|open position|openings?|join our team)\b.{0,220}\b(?:hvac\s+)?(?:service\s+)?(?:technician|technicians|installer|installers|employee|employees|team member|team members)\b",
            r"\b(?:hvac\s+)?(?:service\s+)?(?:technician|technicians|installer|installers)\b.{0,220}\b(?:hiring|job|position|opening|apply|needed|required)\b",
        ]
    return patterns


def _urls(row):
    vals=[]
    for key in ("url","source_url","verification_source_url"):
        if _s(row.get(key)).startswith(("http://","https://")): vals.append(_s(row.get(key),1200))
    for key in ("supporting_urls","urls"):
        for value in row.get(key) or []:
            if _s(value).startswith(("http://","https://")): vals.append(_s(value,1200))
    evidence=row.get("evidence") or row.get("sources") or []
    if isinstance(evidence,dict): evidence=[evidence]
    for item in evidence:
        if isinstance(item,dict):
            value=_s(item.get("url") or item.get("source_url"),1200)
            if value.startswith(("http://","https://")): vals.append(value)
    return list(dict.fromkeys(vals))[:5]


def _evidence_text(row):
    parts=[]
    for key in ("title","snippet","description","text","content","verified_claim","evidence_basis","why","reason"):
        value=row.get(key)
        if value: parts.append(_s(value,5000))
    evidence=row.get("evidence") or row.get("sources") or []
    if isinstance(evidence,dict): evidence=[evidence]
    for item in evidence[:10]:
        if isinstance(item,dict):
            for key in ("title","snippet","description","text","content","quote","claim"):
                if item.get(key): parts.append(_s(item.get(key),3000))
    return " ".join(parts).lower()[:20000]


def _identity_supported(name,row,urls,text):
    nk=_key(name)
    if not nk:return False
    hay=_key(" ".join([_s(row.get("title"),1000),text[:8000]]))
    hosts=_key(" ".join((urlparse(u).hostname or "") for u in urls))
    if nk in hay or nk in hosts:return True
    tokens=[_key(t) for t in re.findall(r"[A-Za-z0-9]+",name) if len(t)>=6 and t.lower() not in {"company","services","service","heating","cooling"}]
    return any(t and (t in hay or t in hosts) for t in tokens)


def enhance_discovery(discovery,query,territory,max_candidates=10):
    """Promote only candidates proven by evidence already returned by discovery."""
    if not isinstance(discovery,dict):return discovery
    rows=[dict(x) for x in (discovery.get("results") or []) if isinstance(x,dict)]
    patterns=_intent_patterns(query)
    if not patterns:return dict(discovery)
    verified=0
    for row in rows[:max_candidates]:
        if row.get("classification")=="Verified Lead": verified+=1; continue
        name=_candidate_name(row)
        urls=_urls(row); text=_evidence_text(row)
        if not name or not urls or not text:continue
        if not _identity_supported(name,row,urls,text):continue
        if not any(re.search(p,text,re.I|re.S) for p in patterns):continue
        row.update({
            "classification":"Verified Lead","promotion_status":"verified","verification_gate":"passed",
            "verified_claim":"Candidate-specific discovery evidence explicitly supports the requested current hiring signal.",
            "supporting_urls":urls,"evidence_basis":"V1.1 deterministic identity + requested-intent evidence gate passed using Smart Search source evidence",
            "verification_source":"Smart Search live-source evidence","verification_source_url":urls[0],"confidence":"high"})
        verified+=1
    out=dict(discovery);out["results"]=rows
    out["verified_count"]=verified
    out["unverified_candidate_count"]=sum(1 for x in rows if x.get("classification")=="Candidate")
    out["rejected_count"]=sum(1 for x in rows if x.get("classification")=="Rejected")
    out["v11_evidence_upgrade"]=True
    out["v11_evidence_mode"]="bounded_existing_source_evidence"
    return out
