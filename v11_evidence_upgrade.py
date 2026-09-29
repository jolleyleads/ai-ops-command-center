"""V1.1 evidence upgrade layered above the frozen V1 engine.

Only promotes an existing discovered candidate when candidate-specific public
source text explicitly supports the requested intent. It never fabricates a
company, contact, claim, or URL and never bypasses V1 qualification/safe-send.
"""
import os, re, requests
from urllib.parse import urlparse


def _s(v,n=1600): return str(v or "").strip()[:n]
def _key(v): return re.sub(r"[^a-z0-9]+","",_s(v,300).lower())


def _candidate_name(row):
    return _s(row.get("company") or row.get("name") or row.get("business_name") or row.get("title"),300)


def _intent_patterns(query):
    q=_s(query,1200).lower(); patterns=[]
    if any(x in q for x in ("hiring","hire ","jobs","technician","open role")):
        patterns += [
            r"\b(?:hiring|seeking|careers?|job opening|open position|openings?|join our team)\b.{0,180}\b(?:hvac\s+)?(?:service\s+)?(?:technician|technicians|installer|installers|employee|employees|team member|team members)\b",
            r"\b(?:hvac\s+)?(?:service\s+)?(?:technician|technicians|installer|installers)\b.{0,180}\b(?:hiring|job|position|opening|apply|needed|required)\b",
        ]
    return patterns


def _queries(name,query,territory):
    q=_s(query,800).lower(); role="HVAC technician" if "hvac" in q or "technician" in q else "technician"
    return [
        f'"{name}" "{role}" (hiring OR careers OR jobs OR opening) {territory}',
        f'"{name}" ("join our team" OR apply OR hiring) technician {territory}',
    ]


def _exa(query):
    key=os.getenv("EXA_API_KEY") or ""
    if not key:return []
    body={"query":query,"numResults":5,"type":"auto","contents":{"text":{"maxCharacters":9000},"highlights":{"numSentences":6,"highlightsPerUrl":4},"livecrawl":"preferred"}}
    try:
        r=requests.post("https://api.exa.ai/search",headers={"x-api-key":key,"Content-Type":"application/json"},json=body,timeout=15)
        if not r.ok:return []
        return [x for x in (r.json().get("results") or []) if isinstance(x,dict) and _s(x.get("url")).startswith(("http://","https://"))]
    except requests.RequestException:return []


def _identity_supported(name,item):
    """Require the discovered company identity in source title/text/host evidence."""
    nk=_key(name)
    if not nk:return False
    title=_key(item.get("title")); text=_key(_s(item.get("text"),9000)); host=_key(urlparse(_s(item.get("url"))).hostname or "")
    # Full normalized company name, or a meaningful >=6-char company token.
    if nk in title or nk in text or nk in host:return True
    tokens=[_key(t) for t in re.findall(r"[A-Za-z0-9]+",name) if len(t)>=6 and t.lower() not in {"company","services","service","heating","cooling"}]
    return any(t and (t in title or t in host) for t in tokens)


def enhance_discovery(discovery,query,territory,max_candidates=10):
    """Return a copied discovery payload with only source-proven promotions."""
    if not isinstance(discovery,dict):return discovery
    rows=[dict(x) for x in (discovery.get("results") or []) if isinstance(x,dict)]
    patterns=_intent_patterns(query)
    if not patterns:return dict(discovery)
    verified=0
    for row in rows[:max_candidates]:
        if row.get("classification")=="Verified Lead": verified+=1; continue
        name=_candidate_name(row)
        if not name:continue
        proof=None
        for q in _queries(name,query,territory):
            for item in _exa(q):
                text=" ".join([_s(item.get("title"),800),_s(" ".join(item.get("highlights") or []),5000),_s(item.get("text"),9000)]).lower()
                if _identity_supported(name,item) and any(re.search(p,text,re.I|re.S) for p in patterns):
                    proof=item;break
            if proof:break
        if not proof:continue
        url=_s(proof.get("url")); row.update({
            "classification":"Verified Lead","promotion_status":"verified","verification_gate":"passed",
            "verified_claim":"Candidate-specific public source evidence explicitly supports the requested current hiring signal.",
            "supporting_urls":[url],"evidence_basis":"V1.1 deterministic identity + requested-intent evidence gate passed",
            "verification_source":"Exa","verification_source_url":url,"confidence":"high"})
        verified+=1
    out=dict(discovery);out["results"]=rows
    out["verified_count"]=verified
    out["unverified_candidate_count"]=sum(1 for x in rows if x.get("classification")=="Candidate")
    out["rejected_count"]=sum(1 for x in rows if x.get("classification")=="Rejected")
    out["v11_evidence_upgrade"]=True
    return out
