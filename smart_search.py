from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, re, time, requests
from flask import jsonify, request
from app import app
import contractor_intent, local_jobs, permit_leads, search_overrides
from universal_app import _search_public_records
from research_agent import plan_research, evaluate_research


def _clean(v,limit=500): return str(v or "").strip()[:limit]
def _dedupe_results(items):
    out=[]; seen=set()
    for x in items:
        if not isinstance(x,dict): continue
        k=_clean(x.get("url"),1600).lower() or (_clean(x.get("title"),500).lower()+"|"+_clean(x.get("subtitle"),800).lower())
        if k and k not in seen: seen.add(k); out.append(x)
    return out

def _detect_intent(q):
    t=_clean(q,1000).lower(); s={"permit_leads":0,"contractors":0,"permits":0,"jobs":0,"businesses":0}
    if any(x in t for x in ("job","jobs","hiring","career","position","opening","employment","vacancy")): s["jobs"]+=4
    if any(x in t for x in ("permit record","permit records","issued permit","public record","inspection record")): s["permits"]+=5
    if any(x in t for x in ("contractor","electrician","plumber","hvac","roofer","builder")): s["contractors"]+=2
    if any(x in t for x in ("qualifying agent","qualified agent","qualifier","master electrician","license holder","pull permits","permit pulling")): s["permit_leads"]+=4; s["contractors"]+=2
    if any(x in t for x in ("looking for","seeking","needed","needs","hiring","wanted")) and s["permit_leads"]: s["permit_leads"]+=3
    if any(x in t for x in ("business","businesses","company","companies","shop","provider")): s["businesses"]+=2
    b=max(s,key=s.get); return (b if s[b] else "web"),s

def _web_one(q,loc):
    try: return _search_public_records(q,loc)
    except Exception: app.logger.exception("RESEARCH_SEARCH_ERROR query=%r",q); return {"results":[]}
def _web_batch(qs,loc):
    results=[]; sources=[]
    with ThreadPoolExecutor(max_workers=min(3,max(1,len(qs)))) as p:
        fs=[p.submit(_web_one,q,loc) for q in qs]
        for f in as_completed(fs):
            x=f.result(); results.extend(x.get("results") or []); s=_clean(x.get("source"),300)
            if s and s not in sources: sources.append(s)
    return _dedupe_results(results),sources

def _page(url):
    try:
        p=urlparse(_clean(url,1600)); host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"): return ""
        r=requests.get(url,timeout=2.5,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/1.0"},allow_redirects=True)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower(): return ""
        raw=r.text[:100000]; raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\\1>"," ",raw)
        return re.sub(r"\\s+"," ",re.sub(r"(?s)<[^>]+>"," ",raw)).strip()[:6000]
    except Exception: return ""
def _inspect(items,limit=3):
    targets=[x for x in items if x.get("url")][:limit]
    with ThreadPoolExecutor(max_workers=max(1,len(targets))) as p:
        fs={p.submit(_page,x["url"]):x for x in targets}
        for f in as_completed(fs):
            t=f.result()
            if t: fs[f]["page_text"]=t

def _specialized(intent,q,loc):
    if intent=="contractors": return contractor_intent._contractor_intent_search(q,loc)
    if intent=="businesses": return search_overrides._search_google_places(q,loc)
    # Job and permit-lead engines can fan out into many provider calls. They remain tools,
    # but are intentionally excluded from this latency-bounded synchronous endpoint.
    return {"results":[]}
def _fallback(q,loc):
    intent,scores=_detect_intent(q); results,sources=_web_batch([q],loc)
    return {"configured":True,"agent_mode":False,"intent":intent,"intent_scores":scores,"query":q,"location":loc,"source":" + ".join(sources) or "Smart Search","count":len(results),"results":results,"message":f"Found {len(results)} discovery result(s); fallback mode used."}

def _smart_search(q,loc):
    if not os.getenv("OPENAI_API_KEY"): return _fallback(q,loc)
    started=time.monotonic(); evidence=[]; sources=[]; tried=[]; evaluation={}
    try:
        plan=plan_research(q,loc) or {}; intent=plan.get("intent") or "web_research"
        queries=[_clean(x,500) for x in (plan.get("queries") or [q]) if _clean(x,500)][:3]
        found,src=_web_batch(queries,loc); tried.extend(queries); evidence=_dedupe_results(found); sources.extend(src)
        if time.monotonic()-started < 18:
            _inspect(evidence,3)
            if time.monotonic()-started < 22: evaluation=evaluate_research(q,loc,evidence) or {}
        # One optional follow-up search pass, but no second LLM call and no slow specialized fan-out.
        follow=[_clean(x,500) for x in (evaluation.get("followup_queries") or []) if _clean(x,500) and _clean(x,500) not in tried][:2]
        if follow and time.monotonic()-started < 23:
            more,src2=_web_batch(follow,loc); tried.extend(follow); evidence=_dedupe_results(evidence+more)
            sources.extend(x for x in src2 if x not in sources)
        static,_=_detect_intent(q)
        if static in ("contractors","businesses") and time.monotonic()-started < 24:
            try: evidence=_dedupe_results(evidence+(_specialized(static,q,loc).get("results") or []))
            except Exception: app.logger.exception("RESEARCH_SPECIALIZED_ERROR")
        ranked=evaluation.get("ranked_urls") or []; rank={u:i for i,u in enumerate(ranked)}; evidence.sort(key=lambda x:rank.get(x.get("url"),999))
        for x in evidence: x.pop("page_text",None)
        sufficient=bool(evaluation.get("sufficient"))
        return {"configured":True,"agent_mode":True,"intent":intent,"goal":plan.get("goal") or q,"query":q,"location":loc,"queries_tried":tried,"verification_criteria":plan.get("verification_criteria") or [],"source":" + ".join(sources) or "Research Agent","count":len(evidence),"results":evidence,"answer_summary":evaluation.get("answer_summary") or "","search_exhausted":not sufficient,"stop_reason":"evidence sufficient" if sufficient else "synchronous research budget reached","runtime_ms":int((time.monotonic()-started)*1000),"message":f"Research agent found {len(evidence)} result(s) after {len(tried)} targeted search(es)."}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR"); p=_fallback(q,loc); p["agent_error"]=type(exc).__name__; p["runtime_ms"]=int((time.monotonic()-started)*1000); return p

@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args; q=_clean(d.get("query") or d.get("keyword"),500); loc=_clean(d.get("location"),200)
    if not q: return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(q,loc))
@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500); loc=_clean(request.args.get("location") or "Portsmouth, VA",200); p=_smart_search(q,loc)
    app.logger.warning("SMART_SEARCH_DIAGNOSTIC agent=%r intent=%r count=%s runtime_ms=%s query=%r",p.get("agent_mode"),p.get("intent"),p.get("count",0),p.get("runtime_ms"),q); return jsonify(p)
