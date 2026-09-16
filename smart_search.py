from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os
import re
import requests

from flask import jsonify, request

from app import app
import contractor_intent
import local_jobs
import permit_leads
import search_overrides
from universal_app import _search_public_records
from research_agent import plan_research, evaluate_research


def _clean(value, limit=500):
    return str(value or "").strip()[:limit]


def _dedupe_results(results):
    kept, seen = [], set()
    for item in results:
        if not isinstance(item, dict): continue
        key = _clean(item.get("url"), 1600).lower() or (_clean(item.get("title"), 500).lower()+"|"+_clean(item.get("subtitle"),800).lower())
        if key and key not in seen:
            seen.add(key); kept.append(item)
    return kept


def _detect_intent(query):
    text=_clean(query,1000).lower(); scores={"permit_leads":0,"contractors":0,"permits":0,"jobs":0,"businesses":0}
    if any(x in text for x in ("job","jobs","hiring","career","position","opening","employment","vacancy")): scores["jobs"]+=4
    if any(x in text for x in ("permit record","permit records","issued permit","issued permits","permit database","public record","inspection record")): scores["permits"]+=5
    if any(x in text for x in ("contractor","electrician","plumber","hvac","roofer","builder")): scores["contractors"]+=2
    if any(x in text for x in ("qualifying agent","qualified agent","qualifier","master electrician","license holder","pull permits","permit pulling")): scores["permit_leads"]+=4; scores["contractors"]+=2
    if any(x in text for x in ("looking for","seeking","needed","needs","hiring","wanted")) and scores["permit_leads"]: scores["permit_leads"]+=3
    if any(x in text for x in ("business","businesses","company","companies","shop","provider")): scores["businesses"]+=2
    best=max(scores,key=scores.get); return (best if scores[best] else "web"),scores


def _web_one(query, location):
    try: return _search_public_records(query, location)
    except Exception:
        app.logger.exception("RESEARCH_SEARCH_ERROR query=%r",query); return {"results":[]}


def _web_batch(queries, location):
    results=[]; sources=[]
    with ThreadPoolExecutor(max_workers=min(4,max(1,len(queries)))) as pool:
        futures=[pool.submit(_web_one,q,location) for q in queries]
        for f in as_completed(futures):
            p=f.result(); results.extend(p.get("results") or [])
            s=_clean(p.get("source"),300)
            if s and s not in sources: sources.append(s)
    return _dedupe_results(results),sources


def _safe_page_text(url):
    try:
        p=urlparse(_clean(url,1600))
        if p.scheme not in ("http","https") or not p.hostname: return ""
        host=p.hostname.lower()
        if host in ("localhost","127.0.0.1","::1") or host.endswith(".local"): return ""
        r=requests.get(url,timeout=5,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/1.0"},stream=True,allow_redirects=True)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower(): return ""
        raw=r.raw.read(180000,decode_content=True).decode(r.encoding or "utf-8",errors="ignore")
        raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\\1>"," ",raw)
        text=re.sub(r"(?s)<[^>]+>"," ",raw); text=re.sub(r"\\s+"," ",text).strip()
        return text[:12000]
    except Exception: return ""


def _inspect_pages(results, limit=5):
    targets=[x for x in results if x.get("url")][:limit]
    with ThreadPoolExecutor(max_workers=min(5,max(1,len(targets)))) as pool:
        fmap={pool.submit(_safe_page_text,x.get("url")):x for x in targets}
        for f in as_completed(fmap):
            text=f.result()
            if text: fmap[f]["page_text"]=text
    return results


def _specialized_payload(intent, query, location):
    if intent=="permit_leads":
        with app.test_request_context("/api/permit-leads",method="POST",json={"query":query,"location":location}): r=permit_leads.permit_leads()
        if isinstance(r,tuple): r=r[0]
        return r.get_json() if hasattr(r,"get_json") else {"results":[]}
    if intent=="contractors": return contractor_intent._contractor_intent_search(query,location)
    if intent=="jobs":
        with app.test_request_context("/api/local-jobs",method="POST",json={"query":query,"location":location}): r=local_jobs.local_jobs()
        if isinstance(r,tuple): r=r[0]
        return r.get_json() if hasattr(r,"get_json") else {"results":[]}
    if intent=="businesses": return search_overrides._search_google_places(query,location)
    if intent=="permits": return _web_one(query,location)
    return {"results":[]}


def _fallback_search(query,location):
    intent,scores=_detect_intent(query); results,sources=_web_batch([query],location)
    try:
        if intent!="web": results=_dedupe_results(results+(_specialized_payload(intent,query,location).get("results") or []))
    except Exception: app.logger.exception("FALLBACK_SPECIALIZED_ERROR")
    return {"configured":True,"agent_mode":False,"intent":intent,"intent_scores":scores,"query":query,"location":location,"source":" + ".join(sources) or "Smart Search","count":len(results),"results":results,"message":f"Found {len(results)} discovery result(s). LLM research planning is unavailable, so fallback search was used."}


def _smart_search(query, location):
    if not os.getenv("OPENAI_API_KEY"): return _fallback_search(query,location)
    try:
        plan=plan_research(query,location) or {}; intent=plan.get("intent") or "web_research"
        queries=[_clean(x,500) for x in (plan.get("queries") or [query]) if _clean(x,500)][:4]
        evidence=[]; sources=[]; tried=[]; evaluation=None
        for iteration in range(2):
            fresh=[q for q in queries if q not in tried][:4]
            if not fresh: break
            tried.extend(fresh); found,src=_web_batch(fresh,location); sources.extend(x for x in src if x not in sources)
            evidence=_dedupe_results(evidence+found); _inspect_pages(evidence,5)
            evaluation=evaluate_research(query,location,evidence) or {}
            if evaluation.get("sufficient"): break
            queries=[_clean(x,500) for x in (evaluation.get("followup_queries") or []) if _clean(x,500)]
        static_intent,_=_detect_intent(query)
        try:
            if static_intent!="web": evidence=_dedupe_results(evidence+(_specialized_payload(static_intent,query,location).get("results") or []))
        except Exception: app.logger.exception("RESEARCH_SPECIALIZED_ERROR")
        ranked=(evaluation or {}).get("ranked_urls") or []
        rank={u:i for i,u in enumerate(ranked)}; evidence.sort(key=lambda x:rank.get(x.get("url"),999))
        for x in evidence: x.pop("page_text",None)
        exhausted=not bool((evaluation or {}).get("sufficient"))
        return {"configured":True,"agent_mode":True,"intent":intent,"goal":plan.get("goal") or query,"query":query,"location":location,"queries_tried":tried,"verification_criteria":plan.get("verification_criteria") or [],"source":" + ".join(sources) or "Research Agent","count":len(evidence),"results":evidence,"answer_summary":(evaluation or {}).get("answer_summary") or "","search_exhausted":exhausted,"stop_reason":"evidence sufficient" if not exhausted else "bounded research budget exhausted","message":f"Research agent found {len(evidence)} result(s) after {len(tried)} targeted search(es)."}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR")
        payload=_fallback_search(query,location); payload["agent_error"]=type(exc).__name__; return payload


@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    data=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args
    query=_clean(data.get("query") or data.get("keyword"),500); location=_clean(data.get("location"),200)
    if not query: return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(query,location))


@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    query=_clean(request.args.get("query") or "machine learning engineer jobs",500); location=_clean(request.args.get("location") or "Portsmouth, VA",200)
    payload=_smart_search(query,location); app.logger.warning("SMART_SEARCH_DIAGNOSTIC agent=%r intent=%r count=%s query=%r",payload.get("agent_mode"),payload.get("intent"),payload.get("count",0),query)
    return jsonify(payload)
