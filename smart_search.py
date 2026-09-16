from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, re, time, requests
from flask import jsonify, request
from app import app
import contractor_intent
from universal_app import _search_public_records, _search_businesses
from research_agent import plan_research, evaluate_research
from rag_research import retrieve_context, remember_evidence, annotate_evidence


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
    except Exception: app.logger.exception("RESEARCH_SEARCH_ERROR query=%r",q); return {"source":"web","results":[]}
def _batch(queries,loc):
    results=[]; sources=[]
    with ThreadPoolExecutor(max_workers=min(3,max(1,len(queries)))) as pool:
        fs=[pool.submit(_search,q,loc) for q in queries]
        for f in as_completed(fs):
            x=f.result(); results.extend(x.get("results") or []); s=_clean(x.get("source"),200)
            if s and s not in sources: sources.append(s)
    return _dedupe(results),sources

def _page(url):
    try:
        p=urlparse(_clean(url,1600)); host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"): return ""
        r=requests.get(url,timeout=2.5,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/4.0"},allow_redirects=True)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower(): return ""
        raw=r.text[:120000]; raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>"," ",raw)
        return re.sub(r"\s+"," ",re.sub(r"(?s)<[^>]+>"," ",raw)).strip()[:10000]
    except Exception: return ""
def _inspect(items,limit=5):
    targets=[x for x in items if x.get("url") and not x.get("page_text")][:limit]
    if not targets:return
    with ThreadPoolExecutor(max_workers=len(targets)) as pool:
        fs={pool.submit(_page,x["url"]):x for x in targets}
        for f in as_completed(fs):
            text=f.result()
            if text: fs[f]["page_text"]=text

def _memory_items(q,loc):
    return [{"title":x["title"],"url":x["url"],"subtitle":x["text"],"source":"RAG memory","last_seen":x["last_seen"],"rag_retrieved":True} for x in retrieve_context(q,loc)]
def _tools(plan,q,loc,started):
    if time.monotonic()-started>24:return []
    intent=_clean(plan.get("intent"),200).lower(); out=[]
    try:
        if any(x in intent for x in ("business","contractor","company","local","provider")):
            out.extend((_search_businesses(q,loc).get("results") or [])[:10])
        if "contractor" in intent and time.monotonic()-started<27:
            out.extend((contractor_intent._contractor_intent_search(q,loc).get("results") or [])[:10])
    except Exception: app.logger.exception("RESEARCH_TOOL_ERROR intent=%r",intent)
    return out

def _promote(evidence,evaluation,q):
    ranked=[_clean(x,1600) for x in (evaluation.get("ranked_urls") or []) if _clean(x,1600)]; rank={u:i for i,u in enumerate(ranked)}
    annotate_evidence(evidence,q); evidence.sort(key=lambda x:(rank.get(_clean(x.get("url"),1600),999),-float(x.get("evidence_score") or 0)))
    out=[]
    for item in evidence:
        x=dict(item); inspected=bool(x.pop("page_text",None)); score=float(x.get("evidence_score") or 0)
        x["promotion_status"]="promoted" if inspected and score>=.45 else ("verified_page" if inspected else "discovered")
        x["evidence_basis"]="page content inspected" if inspected else ("persistent RAG evidence" if x.get("rag_retrieved") else "search-provider title/snippet")
        out.append(x)
    return out

def _expansion_queries(q,plan,tried):
    intent=_clean(plan.get("intent"),200).lower()
    goal=_clean(plan.get("goal") or q,500)
    concepts=" ".join(_clean(x,100) for x in (plan.get("concepts") or []) if _clean(x,100))
    candidates=[
        goal,
        f'{q} current recent evidence',
        f'{q} company contractor applicant hiring request need',
        f'{q} permit application filing license public records',
        f'{q} site:gov permit contractor applicant',
        f'{q} job posting hiring qualifying agent master electrician',
    ]
    if concepts: candidates.insert(1,f'{q} {concepts}')
    if "job" in intent or "hiring" in q.lower(): candidates.insert(1,f'{q} careers jobs hiring')
    if any(x in intent for x in ("business","contractor","company","provider")): candidates.insert(1,f'{q} contractor company business')
    out=[]
    seen={_clean(x,500).lower() for x in tried}
    for x in candidates:
        x=_clean(x,500)
        if x and x.lower() not in seen:
            seen.add(x.lower()); out.append(x)
    return out[:4]

def _fallback(q,loc):
    live,sources=_batch([q],loc); results=_dedupe(live+_memory_items(q,loc)); annotate_evidence(results,q)
    return {"configured":True,"agent_mode":False,"rag_enabled":True,"query":q,"location":loc,"source":" + ".join(sources) or "Web Search + RAG","count":len(results),"results":results,"message":f"Found {len(results)} live or remembered evidence result(s)."}

def _smart_search(q,loc):
    if not os.getenv("OPENAI_API_KEY"): return _fallback(q,loc)
    started=time.monotonic(); tried=[]; sources=[]; expanded=False
    try:
        memory=_memory_items(q,loc)
        plan=plan_research(q,loc,prior_evidence=memory) or {}
        queries=[_clean(x,500) for x in (plan.get("queries") or []) if _clean(x,500)][:3]; direct=" ".join(x for x in (q,loc) if x).strip()
        if direct and direct not in queries: queries=[direct]+queries
        queries=queries[:3] or [direct or q]
        live,src=_batch(queries,loc); tried.extend(queries); sources.extend(src)
        evidence=_dedupe(live+memory)
        if time.monotonic()-started<15:_inspect(evidence,5)
        try: remember_evidence([x for x in evidence if x.get("page_text") or (x.get("subtitle") and not x.get("rag_retrieved"))])
        except Exception: app.logger.exception("RAG_PERSIST_ERROR")
        evaluation=evaluate_research(q,loc,evidence) if time.monotonic()-started<19 else {}
        evaluation=evaluation or {}
        follow=[_clean(x,500) for x in (evaluation.get("followup_queries") or []) if _clean(x,500) and _clean(x,500) not in tried][:2]
        weak=(not evidence) or (not evaluation.get("sufficient")) or len(evidence)<3
        if weak and time.monotonic()-started<24:
            expansion=[]
            for x in follow+_expansion_queries(q,plan,tried):
                if x and x not in tried and x not in expansion: expansion.append(x)
            expansion=expansion[:4]
            if expansion:
                expanded=True
                more,src2=_batch(expansion,loc); tried.extend(expansion); evidence=_dedupe(evidence+more); sources.extend(x for x in src2 if x not in sources)
                if time.monotonic()-started<29:_inspect(evidence,5)
                try: remember_evidence([x for x in more if x.get("page_text") or x.get("subtitle")])
                except Exception: app.logger.exception("RAG_EXPANSION_PERSIST_ERROR")
                if time.monotonic()-started<31:
                    evaluation=evaluate_research(q,loc,evidence) or evaluation
        evidence=_dedupe(evidence+_tools(plan,q,loc,started))
        promoted=_promote(evidence,evaluation,q); sufficient=bool(evaluation.get("sufficient"))
        return {"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"search_expanded":expanded,"framework":"understand-plan-search-evaluate-expand-crawl-rag-enrich-score-verify-promote","intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,"query":q,"location":loc,"queries_tried":tried,"verification_criteria":plan.get("verification_criteria") or [],"source":" + ".join(sources) or "Research Agent + RAG","count":len(promoted),"promoted_count":sum(1 for x in promoted if x.get("promotion_status")=="promoted"),"results":promoted,"answer_summary":evaluation.get("answer_summary") or "","search_exhausted":not sufficient,"stop_reason":"evidence sufficient" if sufficient else "adaptive research budget reached","runtime_ms":int((time.monotonic()-started)*1000),"message":f"Agent researched {len(promoted)} source-backed candidate(s)"+(" after automatically expanding the search strategy" if expanded else "")+", using live discovery plus persistent RAG memory."}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR"); p=_fallback(q,loc); p["agent_error"]=type(exc).__name__; p["runtime_ms"]=int((time.monotonic()-started)*1000); return p

@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args; q=_clean(d.get("prompt") or d.get("query") or d.get("keyword"),500); loc=_clean(d.get("location"),200)
    if not q:return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(q,loc))
@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500); loc=_clean(request.args.get("location") or "",200); p=_smart_search(q,loc)
    app.logger.warning("SMART_SEARCH_DIAGNOSTIC agent=%r rag=%r expanded=%r framework=%r intent=%r count=%s promoted=%s runtime_ms=%s query=%r",p.get("agent_mode"),p.get("rag_enabled"),p.get("search_expanded"),p.get("framework"),p.get("intent"),p.get("count",0),p.get("promoted_count",0),p.get("runtime_ms"),q); return jsonify(p)
