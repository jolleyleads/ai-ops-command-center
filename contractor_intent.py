import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse

import requests
from flask import jsonify, request

from app import app
import search_overrides
from universal_app import _google_error_message, _normalize_brave_search_results, _normalize_custom_search_results

INTENT_TERMS = {"master electrician":35,"master electrical":30,"qualifying electrician":35,"electrical qualifier":35,"qualifying agent":35,"license holder":30,"license qualifier":35,"permit puller":35,"pull permits":30,"pulling permits":30,"permit pulling":30,"electrical permits":15,"master license":20}
HIRING_TERMS = {"hiring":20,"needed":20,"need a":20,"seeking":20,"looking for":20,"wanted":20,"apply":10,"job":10,"position":10,"opening":15}
NEGATIVE_TERMS = ("training","salary guide","how to become","exam prep","course")

def _clean(value, limit=1000): return str(value or "").strip()[:limit]
def _domain(url):
    try: return urlparse(url or "").netloc.lower().replace("www.","")
    except Exception: return ""
def _canonical_url(url):
    value=_clean(url,1500)
    if not value: return ""
    try:
        parsed=urlparse(value); return f"{parsed.netloc.lower().replace('www.','')}{parsed.path.rstrip('/')}".lower()
    except Exception: return value.lower().rstrip("/")

def _score_evidence(item, company):
    title=_clean(item.get("title"),500); snippet=_clean(item.get("subtitle"),1500); url=_clean(item.get("url"),1500)
    text=f"{title} {snippet}".lower(); company_text=company.lower()
    if any(term in text for term in NEGATIVE_TERMS): return 0,[]
    intent_hits=[term for term in INTENT_TERMS if term in text]; hiring_hits=[term for term in HIRING_TERMS if term in text]
    if not intent_hits: return 0,[]
    score=max(INTENT_TERMS[t] for t in intent_hits)
    if hiring_hits: score+=max(HIRING_TERMS[t] for t in hiring_hits)
    if company_text and company_text in text: score+=20
    host=_domain(url)
    if any(host.endswith(x) for x in ("indeed.com","ziprecruiter.com","linkedin.com","glassdoor.com")): score+=10
    if ".gov" in host: score+=10
    return min(score,100), intent_hits+hiring_hits

def _brave_evidence_search(text_query):
    key=os.environ.get("BRAVE_SEARCH_API_KEY") or ""
    if not key: return {"configured":False,"source":"Brave Search","results":[],"message":"Brave Search is not configured."}
    try:
        r=requests.get("https://api.search.brave.com/res/v1/web/search",headers={"Accept":"application/json","X-Subscription-Token":key},params={"q":text_query,"country":"US","search_lang":"en","count":20},timeout=20)
        if r.ok: return {"configured":True,"source":"Brave Search","results":_normalize_brave_search_results(r.json()),"message":""}
        return {"configured":True,"source":"Brave Search","results":[],"message":f"Brave Search returned HTTP {r.status_code}."}
    except requests.RequestException as exc: return {"configured":True,"source":"Brave Search","results":[],"message":f"Brave Search request failed: {type(exc).__name__}."}

def _google_evidence_search(text_query):
    key=os.environ.get("GOOGLE_SEARCH_API_KEY") or ""; cx=os.environ.get("GOOGLE_SEARCH_CX") or ""
    if not (key and cx): return {"configured":False,"source":"Google Programmable Search","results":[],"message":"Google Programmable Search is not configured."}
    try:
        r=requests.get("https://www.googleapis.com/customsearch/v1",params={"key":key,"cx":cx,"q":text_query,"num":10},timeout=20)
        if r.ok: return {"configured":True,"source":"Google Programmable Search","results":_normalize_custom_search_results(r.json()),"message":""}
        detail=_google_error_message(r); message=f"Google Programmable Search returned HTTP {r.status_code}."
        if detail: message+=f" {detail}"
        return {"configured":True,"source":"Google Programmable Search","results":[],"message":message}
    except requests.RequestException as exc: return {"configured":True,"source":"Google Programmable Search","results":[],"message":f"Google Programmable Search request failed: {type(exc).__name__}."}

def _cross_checked_evidence_search(query, location):
    text_query=" ".join(part for part in [query,location] if part).strip()
    with ThreadPoolExecutor(max_workers=2) as pool:
        bf=pool.submit(_brave_evidence_search,text_query); gf=pool.submit(_google_evidence_search,text_query); brave=bf.result(); google=gf.result()
    merged=[]; by_key={}
    for provider,payload in (("brave",brave),("google",google)):
        for item in payload.get("results") or []:
            key=_canonical_url(item.get("url")) or f"{_clean(item.get('title'),500).lower()}|{_domain(item.get('url'))}"
            if not key: continue
            row=by_key.get(key)
            if row is None:
                row=dict(item); row["providers"]=[]; row["provider_sources"]=[]; by_key[key]=row; merged.append(row)
            if provider not in row["providers"]: row["providers"].append(provider)
            source=_clean(item.get("source"),300)
            if source and source not in row["provider_sources"]: row["provider_sources"].append(source)
            if len(_clean(item.get("subtitle"),1500))>len(_clean(row.get("subtitle"),1500)): row["subtitle"]=item.get("subtitle")
    return {"configured":bool(brave.get("configured") or google.get("configured")),"source":"Brave Search + Google Programmable Search","results":merged,"provider_status":{"brave":{"configured":bool(brave.get("configured")),"result_count":len(brave.get("results") or []),"message":brave.get("message") or ""},"google":{"configured":bool(google.get("configured")),"result_count":len(google.get("results") or []),"message":google.get("message") or ""}}}

def _verify_one_business(business, location):
    company=_clean(business.get("title"),300)
    if not company: return {"result":None,"provider_status":{},"company":""}
    q=f'"{company}" ("master electrician" OR "qualifying electrician" OR "electrical qualifier" OR "qualifying agent" OR "license holder" OR "pull permits" OR "permit pulling") (hiring OR needed OR seeking OR "looking for")'
    payload=_cross_checked_evidence_search(q,location); status=payload.get("provider_status") or {}
    if not payload.get("configured") or not payload.get("results"): return {"result":None,"provider_status":status,"company":company}
    evidence=[]; best=0; cross=False
    for item in payload.get("results") or []:
        score,hits=_score_evidence(item,company)
        if score<60: continue
        providers=item.get("providers") or []; count=len(providers); adjusted=min(score+(10 if count>=2 else 0),100)
        evidence.append({"title":_clean(item.get("title"),500),"snippet":_clean(item.get("subtitle"),1000),"url":_clean(item.get("url"),1500),"source":_clean(item.get("source"),300),"score":adjusted,"base_score":score,"matched_terms":hits,"providers":providers,"provider_count":count,"cross_checked":count>=2})
        cross=cross or count>=2; best=max(best,adjusted)
    if not evidence: return {"result":None,"provider_status":status,"company":company}
    evidence.sort(key=lambda row:(row["provider_count"],row["score"]),reverse=True); result=dict(business)
    result.update({"type":"contractor_opportunity","intent_score":best,"verification":"CROSS_CHECKED_VERIFIED_INTENT" if cross and best>=75 else ("VERIFIED_INTENT" if best>=75 else "LIKELY_VERIFIED_INTENT"),"cross_checked":cross,"evidence":evidence[:3],"evidence_count":len(evidence),"provider_status":status,"reason":"Public web evidence matched contractor intent terms. Brave and Google were queried independently; cross_checked is true only when both providers returned the same evidence URL."})
    return {"result":result,"provider_status":status,"company":company}

def _contractor_intent_search(query, location):
    places=search_overrides._search_google_places(query or "electrical contractors",location)
    if not places.get("configured"): return places
    candidates=(places.get("results") or [])[:12]
    if not candidates: return {"configured":True,"source":"Google Places + Brave + Google Evidence","message":"No Google Places contractor candidates found.","results":[],"provider_diagnostics":[]}
    verified=[]; diagnostics=[]
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures=[pool.submit(_verify_one_business,b,location) for b in candidates]
        for future in as_completed(futures):
            try: outcome=future.result()
            except Exception as exc: outcome={"result":None,"provider_status":{},"company":"","error":type(exc).__name__}
            diagnostics.append({"company":outcome.get("company") or "","provider_status":outcome.get("provider_status") or {},"error":outcome.get("error") or ""})
            if outcome.get("result"): verified.append(outcome["result"])
    verified.sort(key=lambda row:(bool(row.get("cross_checked")),row.get("intent_score",0),row.get("rating") or 0),reverse=True)
    return {"configured":True,"source":"Google Places + Brave + Google Evidence","message":f"Found {len(verified)} contractor opportunities with supporting public evidence." if verified else "No verified contractor opportunities found. Google Places candidates without supporting need evidence were rejected.","results":verified,"candidates_checked":len(candidates),"verification_threshold":60,"provider_diagnostics":diagnostics}

def universal_search_with_contractor_intent():
    data=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args; mode=_clean(data.get("mode") or "jobs",40).lower(); query=_clean(data.get("query") or data.get("keyword") or "",300); location=_clean(data.get("location") or "",200)
    if mode not in ("contractor","contractors"): return search_overrides.universal_search_override()
    payload=_contractor_intent_search(query,location); payload.update({"mode":mode,"query":query,"location":location,"count":len(payload.get("results") or [])}); search_overrides._record_event("verified_contractor_intent_search",payload.get("source") or "Google Places + Brave + Google Evidence","success" if payload.get("results") else "no_verified_results",mode,query,location); return jsonify(payload)

@app.route("/api/test-contractor-intent",methods=["GET"])
def test_contractor_intent():
    query=_clean(request.args.get("query") or "electrical contractors",300); location=_clean(request.args.get("location") or "Virginia Beach, VA",200); payload=_contractor_intent_search(query,location); results=payload.get("results") or []; diagnostics=payload.get("provider_diagnostics") or []
    summary={"diagnostic":True,"configured":bool(payload.get("configured")),"source":payload.get("source"),"query":query,"location":location,"candidates_checked":payload.get("candidates_checked",0),"verified_count":len(results),"verification_threshold":payload.get("verification_threshold",60),"message":payload.get("message"),"provider_diagnostics":diagnostics,"results":results}
    app.logger.warning("CONTRACTOR_INTENT_DIAGNOSTIC configured=%s candidates=%s verified=%s query=%r location=%r message=%r",summary["configured"],summary["candidates_checked"],summary["verified_count"],query,location,_clean(summary.get("message"),700).replace("\n"," ").replace("\r"," "))
    for row in diagnostics:
        b=(row.get("provider_status") or {}).get("brave") or {}; g=(row.get("provider_status") or {}).get("google") or {}
        app.logger.warning("CONTRACTOR_PROVIDER_STATUS company=%r brave_configured=%s brave_results=%s brave_message=%r google_configured=%s google_results=%s google_message=%r error=%r",_clean(row.get("company"),300),bool(b.get("configured")),b.get("result_count",0),_clean(b.get("message"),500),bool(g.get("configured")),g.get("result_count",0),_clean(g.get("message"),500),_clean(row.get("error"),100))
    for result in results[:5]:
        evidence=(result.get("evidence") or [{}])[0]; app.logger.warning("CONTRACTOR_INTENT_RESULT company=%r intent_score=%s verification=%r cross_checked=%s evidence_score=%s evidence_source=%r evidence_providers=%r evidence_title=%r evidence_url=%r matched_terms=%r",_clean(result.get("title"),300),result.get("intent_score",0),_clean(result.get("verification"),80),bool(result.get("cross_checked")),evidence.get("score",0),_clean(evidence.get("source"),200),evidence.get("providers") or [],_clean(evidence.get("title"),500).replace("\n"," ").replace("\r"," "),_clean(evidence.get("url"),1000),evidence.get("matched_terms") or [])
    return jsonify(summary)

app.view_functions["universal_search"]=universal_search_with_contractor_intent
