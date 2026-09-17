import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse
import requests
from flask import jsonify, request
from app import app
import search_overrides

INTENT_TERMS={"master electrician":35,"master electrical":30,"qualifying electrician":35,"electrical qualifier":35,"qualifying agent":35,"license holder":30,"license qualifier":35,"permit puller":35,"pull permits":30,"pulling permits":30,"permit pulling":30,"electrical permits":15,"master license":20}
HIRING_TERMS={"hiring":20,"needed":20,"need a":20,"seeking":20,"looking for":20,"wanted":20,"apply":10,"job":10,"position":10,"opening":15}
NEGATIVE_TERMS=("training","salary guide","how to become","exam prep","course")

def _clean(v,limit=1000): return str(v or "").strip()[:limit]
def _domain(url):
    try:return urlparse(url or "").netloc.lower().replace("www.","")
    except Exception:return ""
def _score_evidence(item,company):
    text=f"{_clean(item.get('title'),500)} {_clean(item.get('subtitle'),1500)}".lower(); company_text=company.lower()
    if any(t in text for t in NEGATIVE_TERMS):return 0,[]
    ih=[t for t in INTENT_TERMS if t in text]; hh=[t for t in HIRING_TERMS if t in text]
    if not ih:return 0,[]
    score=max(INTENT_TERMS[t] for t in ih)+(max(HIRING_TERMS[t] for t in hh) if hh else 0)+(20 if company_text and company_text in text else 0)
    host=_domain(item.get("url")); score+=10 if any(host.endswith(x) for x in ("indeed.com","ziprecruiter.com","linkedin.com","glassdoor.com")) or ".gov" in host else 0
    return min(score,100),ih+hh

def _extract_rows(payload):
    out=[];seen=set()
    def walk(node):
        if isinstance(node,dict):
            url=_clean(node.get("url"),1500)
            if url.startswith(("http://","https://")) and url.lower() not in seen:
                seen.add(url.lower()); out.append({"title":_clean(node.get("title") or node.get("name"),500) or _domain(url),"subtitle":_clean(node.get("snippet") or node.get("text") or node.get("description"),1500),"url":url,"source":"OpenAI Web Search","providers":["openai_web_search"]})
            for v in node.values():walk(v)
        elif isinstance(node,list):
            for v in node:walk(v)
    walk(payload);return out

def _openai_evidence_search(text_query):
    key=os.getenv("OPENAI_API_KEY") or ""
    if not key:return {"configured":False,"source":"OpenAI Web Search","results":[],"message":"OPENAI_API_KEY is not configured."}
    body={"model":os.getenv("OPENAI_SEARCH_MODEL") or "chat-latest","tools":[{"type":"web_search"}],"tool_choice":"required","include":["web_search_call.action.sources","web_search_call.results"],"instructions":"Search the live public web. Return only real source-backed information. Prefer primary sources, official company sites, current job pages, and government records. Never invent companies, jobs, permits, contacts, or URLs.","input":text_query[:1200]}
    try:
        r=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=body,timeout=45)
        if r.ok:return {"configured":True,"source":"OpenAI Web Search","results":_extract_rows(r.json()),"message":""}
        detail=""
        try:detail=_clean((r.json().get("error") or {}).get("message"),500)
        except Exception:pass
        return {"configured":True,"source":"OpenAI Web Search","results":[],"message":f"OpenAI Web Search returned HTTP {r.status_code}."+(f" {detail}" if detail else "")}
    except requests.RequestException as exc:return {"configured":True,"source":"OpenAI Web Search","results":[],"message":f"OpenAI Web Search request failed: {type(exc).__name__}."}

def _verify_one_business(business,location):
    company=_clean(business.get("title"),300)
    if not company:return {"result":None,"provider_status":{},"company":""}
    q=f'"{company}" {location} ("master electrician" OR "qualifying agent" OR "license holder" OR "pull permits") (hiring OR needed OR seeking OR "looking for")'
    payload=_openai_evidence_search(q); status={"openai_web_search":{"configured":bool(payload.get("configured")),"result_count":len(payload.get("results") or []),"message":payload.get("message") or ""}}
    evidence=[];best=0
    for item in payload.get("results") or []:
        score,hits=_score_evidence(item,company)
        if score<60:continue
        evidence.append({"title":_clean(item.get("title"),500),"snippet":_clean(item.get("subtitle"),1000),"url":_clean(item.get("url"),1500),"source":"OpenAI Web Search","score":score,"matched_terms":hits,"providers":["openai_web_search"],"provider_count":1,"cross_checked":False});best=max(best,score)
    if not evidence:return {"result":None,"provider_status":status,"company":company}
    evidence.sort(key=lambda x:x["score"],reverse=True);result=dict(business);result.update({"type":"contractor_opportunity","intent_score":best,"verification":"VERIFIED_INTENT" if best>=75 else "LIKELY_VERIFIED_INTENT","cross_checked":False,"evidence":evidence[:3],"evidence_count":len(evidence),"provider_status":status,"reason":"Public source URLs returned by OpenAI Web Search matched contractor intent terms."});return {"result":result,"provider_status":status,"company":company}

def _contractor_intent_search(query,location):
    discovery=_openai_evidence_search(" ".join(x for x in [query or "electrical contractors",location,"companies"] if x))
    candidates=[];seen=set()
    for item in discovery.get("results") or []:
        title=_clean(item.get("title"),300).split("|")[0].split(" - ")[0].strip()
        if title and title.lower() not in seen:seen.add(title.lower());candidates.append({"title":title,"website":item.get("url"),"source":"OpenAI Web Search"})
    candidates=candidates[:12]
    if not candidates:return {"configured":bool(discovery.get("configured")),"source":"OpenAI Web Search","message":discovery.get("message") or "No contractor candidates found from live web search.","results":[],"provider_diagnostics":[]}
    verified=[];diagnostics=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures=[pool.submit(_verify_one_business,b,location) for b in candidates]
        for future in as_completed(futures):
            try:o=future.result()
            except Exception as exc:o={"result":None,"provider_status":{},"company":"","error":type(exc).__name__}
            diagnostics.append({"company":o.get("company") or "","provider_status":o.get("provider_status") or {},"error":o.get("error") or ""})
            if o.get("result"):verified.append(o["result"])
    verified.sort(key=lambda x:x.get("intent_score",0),reverse=True)
    return {"configured":True,"source":"OpenAI Web Search","message":f"Found {len(verified)} contractor opportunities with supporting public evidence." if verified else "No verified contractor opportunities found; unverified candidates were rejected.","results":verified,"candidates_checked":len(candidates),"verification_threshold":60,"provider_diagnostics":diagnostics}

def universal_search_with_contractor_intent():
    data=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args;mode=_clean(data.get("mode") or "jobs",40).lower();query=_clean(data.get("query") or data.get("keyword") or "",300);location=_clean(data.get("location") or "",200)
    if mode not in ("contractor","contractors"):return search_overrides.universal_search_override()
    payload=_contractor_intent_search(query,location);payload.update({"mode":mode,"query":query,"location":location,"count":len(payload.get("results") or [])});search_overrides._record_event("verified_contractor_intent_search",payload.get("source") or "OpenAI Web Search","success" if payload.get("results") else "no_verified_results",mode,query,location);return jsonify(payload)

@app.route("/api/test-contractor-intent",methods=["GET"])
def test_contractor_intent():
    query=_clean(request.args.get("query") or "electrical contractors",300);location=_clean(request.args.get("location") or "Virginia Beach, VA",200);payload=_contractor_intent_search(query,location);results=payload.get("results") or [];summary={"diagnostic":True,"configured":bool(payload.get("configured")),"source":payload.get("source"),"query":query,"location":location,"candidates_checked":payload.get("candidates_checked",0),"verified_count":len(results),"verification_threshold":payload.get("verification_threshold",60),"message":payload.get("message"),"provider_diagnostics":payload.get("provider_diagnostics") or [],"results":results};app.logger.warning("CONTRACTOR_INTENT_DIAGNOSTIC configured=%s candidates=%s verified=%s source=%r",summary["configured"],summary["candidates_checked"],summary["verified_count"],summary["source"]);return jsonify(summary)

app.view_functions["universal_search"]=universal_search_with_contractor_intent
