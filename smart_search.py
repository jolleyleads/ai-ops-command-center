from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, re, time, requests
from flask import jsonify, request
from app import app
import contractor_intent, search_overrides
from universal_app import _search_public_records, _search_businesses
from research_agent import plan_research, evaluate_research


def _clean(v,limit=500): return str(v or "").strip()[:limit]

def _dedupe(items):
    out=[]; seen=set()
    for x in items:
        if not isinstance(x,dict): continue
        k=_clean(x.get("url"),1600).lower() or (_clean(x.get("title"),500).lower()+"|"+_clean(x.get("subtitle"),800).lower())
        if k and k not in seen: seen.add(k); out.append(x)
    return out

def _search(q,loc):
    try: return _search_public_records(q,loc)
    except Exception:
        app.logger.exception("RESEARCH_SEARCH_ERROR query=%r",q); return {"source":"web","results":[]}

def _batch(queries,loc):
    results=[]; sources=[]
    with ThreadPoolExecutor(max_workers=min(3,max(1,len(queries)))) as pool:
        fs=[pool.submit(_search,q,loc) for q in queries]
        for f in as_completed(fs):
            x=f.result(); results.extend(x.get("results") or [])
            s=_clean(x.get("source"),200)
            if s and s not in sources: sources.append(s)
    return _dedupe(results),sources

def _page(url):
    try:
        p=urlparse(_clean(url,1600)); host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"): return ""
        r=requests.get(url,timeout=2.5,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/2.0"},allow_redirects=True)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower(): return ""
        raw=r.text[:100000]; raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>"," ",raw)
        return re.sub(r"\s+"," ",re.sub(r"(?s)<[^>]+>"," ",raw)).strip()[:6000]
    except Exception: return ""

def _inspect(items,limit=4):
    targets=[x for x in items if x.get("url")][:limit]
    if not targets: return
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        fs={pool.submit(_page,x["url"]):x for x in targets}
        for f in as_completed(fs):
            text=f.result()
            if text: fs[f]["page_text"]=text

def _tool_results(plan,q,loc,started):
    """Specialized modules are optional evidence tools; they never decide acceptance."""
    if time.monotonic()-started > 19: return []
    intent=_clean(plan.get("intent"),100).lower()
    out=[]
    try:
        if any(x in intent for x in ("business","contractor","company")):
            out.extend((_search_businesses(q,loc).get("results") or [])[:10])
        if "contractor" in intent and time.monotonic()-started < 22:
            out.extend((contractor_intent._contractor_intent_search(q,loc).get("results") or [])[:10])
    except Exception:
        app.logger.exception("RESEARCH_TOOL_ERROR intent=%r",intent)
    return out

def _promote(evidence,evaluation):
    """Promotion is evidence based. Nothing is fabricated and zero is allowed only after discovery."""
    ranked=[_clean(x,1600) for x in (evaluation.get("ranked_urls") or []) if _clean(x,1600)]
    rank={u:i for i,u in enumerate(ranked)}
    evidence.sort(key=lambda x:(rank.get(_clean(x.get("url"),1600),999), 0 if x.get("page_text") else 1))
    promoted=[]
    for item in evidence:
        x=dict(item); text=_clean(x.pop("page_text",None),6000)
        x["promotion_status"]="verified_page" if text else "discovered"
        x["evidence_basis"]="page content inspected" if text else "search-provider title/snippet"
        promoted.append(x)
    return promoted

def _fallback(q,loc):
    results,sources=_batch([q],loc)
    return {"configured":True,"agent_mode":False,"query":q,"location":loc,"source":" + ".join(sources) or "Web Search","count":len(results),"results":results,"message":f"Found {len(results)} provider result(s) without LLM planning."}

def _smart_search(q,loc):
    if not os.getenv("OPENAI_API_KEY"): return _fallback(q,loc)
    started=time.monotonic(); tried=[]; sources=[]
    try:
        # DISCOVER: LLM decides the goal, intent and semantic searches.
        plan=plan_research(q,loc) or {}
        queries=[_clean(x,500) for x in (plan.get("queries") or []) if _clean(x,500)][:3]
        direct=" ".join(x for x in (q,loc) if x).strip()
        # Always include the user's literal inquiry so a bad planner can never suppress discovery.
        if direct and direct not in queries: queries=[direct]+queries
        queries=queries[:3] or [direct or q]
        evidence,src=_batch(queries,loc); tried.extend(queries); sources.extend(src)

        # OBSERVE: inspect actual pages before judging candidates.
        if time.monotonic()-started < 16: _inspect(evidence,4)

        # EVALUATE: LLM evaluates evidence, not rigid keyword filters.
        evaluation={}
        if time.monotonic()-started < 20:
            evaluation=evaluate_research(q,loc,evidence) or {}

        # RESEARCH AGAIN: LLM may reformulate based on evidence gaps.
        follow=[_clean(x,500) for x in (evaluation.get("followup_queries") or []) if _clean(x,500) and _clean(x,500) not in tried][:2]
        if follow and time.monotonic()-started < 22:
            more,src2=_batch(follow,loc); tried.extend(follow); evidence=_dedupe(evidence+more)
            sources.extend(x for x in src2 if x not in sources)

        # TOOLS: Places/contractor modules can add evidence, never veto it.
        evidence=_dedupe(evidence+_tool_results(plan,q,loc,started))

        # PROMOTE: rank what was actually discovered; never invent a lead.
        promoted=_promote(evidence,evaluation)
        sufficient=bool(evaluation.get("sufficient"))
        return {
            "configured":True,"agent_mode":True,"framework":"discover-observe-evaluate-promote",
            "intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,
            "query":q,"location":loc,"queries_tried":tried,
            "verification_criteria":plan.get("verification_criteria") or [],
            "source":" + ".join(sources) or "Research Agent","count":len(promoted),"results":promoted,
            "answer_summary":evaluation.get("answer_summary") or "",
            "search_exhausted":not sufficient,"stop_reason":"evidence sufficient" if sufficient else "request research budget reached",
            "runtime_ms":int((time.monotonic()-started)*1000),
            "message":f"LLM research agent discovered and evaluated {len(promoted)} source-backed candidate(s) across {len(tried)} search(es)."
        }
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR")
        p=_fallback(q,loc); p["agent_error"]=type(exc).__name__; p["runtime_ms"]=int((time.monotonic()-started)*1000); return p

@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args
    q=_clean(d.get("query") or d.get("keyword"),500); loc=_clean(d.get("location"),200)
    if not q: return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(q,loc))

@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500); loc=_clean(request.args.get("location") or "Portsmouth, VA",200)
    p=_smart_search(q,loc)
    app.logger.warning("SMART_SEARCH_DIAGNOSTIC agent=%r framework=%r intent=%r count=%s runtime_ms=%s query=%r",p.get("agent_mode"),p.get("framework"),p.get("intent"),p.get("count",0),p.get("runtime_ms"),q)
    return jsonify(p)
