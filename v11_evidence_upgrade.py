"""Bounded fail-closed V1.1 evidence verification above the frozen V1 engine."""
import os,re,requests
from concurrent.futures import ThreadPoolExecutor, as_completed
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
    # subtitle is where Smart Search preserves Exa/web snippets and highlights.
    for key in ("title","subtitle","snippet","description","text","content","verified_claim","evidence_basis","why","reason"):
        if row.get(key): parts.append(_s(row.get(key),5000))
    evidence=row.get("evidence") or row.get("sources") or []
    if isinstance(evidence,dict): evidence=[evidence]
    for item in evidence[:10]:
        if isinstance(item,dict):
            for key in ("title","subtitle","snippet","description","text","content","quote","claim"):
                if item.get(key): parts.append(_s(item.get(key),3000))
    return " ".join(parts).lower()[:20000]

def _identity_supported(name,row,urls,text):
    nk=_key(name)
    if not nk:return False
    hay=_key(" ".join([_s(row.get("title"),1000),text[:8000]]));hosts=_key(" ".join((urlparse(u).hostname or "") for u in urls))
    if nk in hay or nk in hosts:return True
    tokens=[_key(t) for t in re.findall(r"[A-Za-z0-9]+",name) if len(t)>=6 and t.lower() not in {"company","services","service","heating","cooling"}]
    return any(t and (t in hay or t in hosts) for t in tokens)

def _bounded_exa(name,query,territory):
    """One candidate-specific query, hard bounded; candidates run concurrently."""
    key=os.getenv("EXA_API_KEY") or ""
    if not key:return []
    role="HVAC technician" if "technician" in query.lower() or "hvac" in query.lower() else "technician"
    q=f'"{name}" "{role}" hiring careers jobs {territory}'
    body={"query":q,"numResults":3,"type":"auto","contents":{"highlights":{"numSentences":5,"highlightsPerUrl":3},"text":{"maxCharacters":3500},"livecrawl":"fallback"}}
    try:
        r=requests.post("https://api.exa.ai/search",headers={"x-api-key":key,"Content-Type":"application/json"},json=body,timeout=(2,5))
        if not r.ok:return []
        out=[]
        for item in r.json().get("results") or []:
            if not isinstance(item,dict):continue
            url=_s(item.get("url"),1200)
            if not url.startswith(("http://","https://")):continue
            out.append({"title":_s(item.get("title"),800),"subtitle":_s(" ".join(item.get("highlights") or []),5000),"text":_s(item.get("text"),3500),"url":url,"source":"Exa bounded candidate verification"})
        return out
    except requests.RequestException:return []

def _proof(name,row,patterns,extra):
    sources=[row]+list(extra or [])
    for src in sources:
        urls=_urls(src);text=_evidence_text(src)
        if urls and text and _identity_supported(name,src,urls,text) and any(re.search(p,text,re.I|re.S) for p in patterns):
            return src,urls
    return None,[]

def enhance_discovery(discovery,query,territory,max_candidates=10):
    if not isinstance(discovery,dict):return discovery
    rows=[dict(x) for x in (discovery.get("results") or []) if isinstance(x,dict)];patterns=_intent_patterns(query)
    if not patterns:return dict(discovery)
    verified=0;needs=[]
    for idx,row in enumerate(rows[:max_candidates]):
        if row.get("classification")=="Verified Lead": verified+=1;continue
        name=_candidate_name(row)
        if not name:continue
        src,urls=_proof(name,row,patterns,[])
        if src:
            row.update({"classification":"Verified Lead","promotion_status":"verified","verification_gate":"passed","verified_claim":"Candidate-specific source evidence explicitly supports the requested current hiring signal.","supporting_urls":urls,"evidence_basis":"V1.1 deterministic identity + requested-intent evidence gate passed","verification_source":src.get("source") or "Smart Search","verification_source_url":urls[0],"confidence":"high"});verified+=1
        else: needs.append((idx,name))
    # Smart Search's business-visible rows can omit its joined snippets. Fill only that gap
    # with one concurrent, hard-bounded candidate query; never serially crawl candidates.
    if needs and os.getenv("EXA_API_KEY"):
        with ThreadPoolExecutor(max_workers=min(5,len(needs))) as pool:
            futures={pool.submit(_bounded_exa,name,query,territory):(idx,name) for idx,name in needs[:5]}
            for future in as_completed(futures):
                idx,name=futures[future]
                try: extra=future.result()
                except Exception: extra=[]
                src,urls=_proof(name,rows[idx],patterns,extra)
                if not src:continue
                rows[idx].update({"classification":"Verified Lead","promotion_status":"verified","verification_gate":"passed","verified_claim":"Candidate-specific bounded source evidence explicitly supports the requested current hiring signal.","supporting_urls":urls,"evidence_basis":"V1.1 deterministic identity + requested-intent evidence gate passed","verification_source":src.get("source") or "Exa","verification_source_url":urls[0],"confidence":"high"});verified+=1
    out=dict(discovery);out["results"]=rows;out["verified_count"]=verified
    out["unverified_candidate_count"]=sum(1 for x in rows if x.get("classification")=="Candidate");out["rejected_count"]=sum(1 for x in rows if x.get("classification")=="Rejected")
    out["v11_evidence_upgrade"]=True;out["v11_evidence_mode"]="existing_evidence_plus_concurrent_bounded_gap_fill"
    return out
