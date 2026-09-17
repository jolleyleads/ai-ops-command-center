from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, re, time, requests
from flask import jsonify, request
from app import app
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

def _extract_web_rows(payload):
    rows=[]
    def walk(node):
        if isinstance(node,dict):
            url=_clean(node.get("url"),1600)
            if url.startswith(("http://","https://")):
                rows.append({"title":_clean(node.get("title") or node.get("name"),500) or urlparse(url).netloc,"url":url,"subtitle":_clean(node.get("snippet") or node.get("text") or node.get("description"),1500),"source":"OpenAI Web Search"})
            for value in node.values(): walk(value)
        elif isinstance(node,list):
            for value in node: walk(value)
    walk(payload); return _dedupe(rows)

def _openai_web_search(query,location=""):
    key=os.getenv("OPENAI_API_KEY") or ""
    if not key:return {"source":"OpenAI Web Search","results":[],"status":0,"message":"OPENAI_API_KEY is not configured."}
    text=" ".join(x for x in (query,location) if x).strip()[:1200]
    body={"model":os.getenv("OPENAI_SEARCH_MODEL") or "chat-latest","tools":[{"type":"web_search"}],"tool_choice":"required","include":["web_search_call.action.sources","web_search_call.results"],"instructions":"Search the live public web. Prefer primary, official and current sources. Do not invent entities, jobs, permits, contacts or URLs.","input":text}
    try:
        r=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=body,timeout=8)
        if not r.ok:return {"source":"OpenAI Web Search","results":[],"status":r.status_code,"message":f"OpenAI Web Search returned HTTP {r.status_code}."}
        rows=_extract_web_rows(r.json()); return {"source":"OpenAI Web Search","results":rows,"status":200,"message":""}
    except requests.RequestException as exc:
        return {"source":"OpenAI Web Search","results":[],"status":0,"message":f"OpenAI Web Search request failed: {type(exc).__name__}."}

def _search(q,loc): return _openai_web_search(q,loc)
def _batch(queries,loc,deadline=None,max_queries=2):
    results=[]; sources=[]; messages=[]
    for q in queries[:max_queries]:
        if deadline and time.monotonic()>deadline: break
        x=_search(q,loc); results.extend(x.get("results") or []); s=_clean(x.get("source"),300); m=_clean(x.get("message"),500)
        if s and s not in sources:sources.append(s)
        if m and m not in messages:messages.append(m)
        if x.get("status") in (401,403,429):break
    return _dedupe(results),sources,messages

def _page(url):
    try:
        p=urlparse(_clean(url,1600)); host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"):return ""
        r=requests.get(url,timeout=2,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/8.0"},allow_redirects=True)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower():return ""
        raw=r.text[:100000]; raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>"," ",raw); return re.sub(r"\s+"," ",re.sub(r"(?s)<[^>]+>"," ",raw)).strip()[:8000]
    except Exception:return ""
def _inspect(items,limit=5):
    targets=[x for x in items if x.get("url") and not x.get("page_text")][:limit]
    if not targets:return
    with ThreadPoolExecutor(max_workers=min(5,len(targets))) as pool:
        fs={pool.submit(_page,x["url"]):x for x in targets}
        for f in as_completed(fs):
            text=f.result()
            if text:fs[f]["page_text"]=text

def _memory_items(q,loc):
    try:return [{"title":x["title"],"url":x["url"],"subtitle":x["text"],"source":"RAG memory","last_seen":x["last_seen"],"rag_retrieved":True} for x in retrieve_context(q,loc)]
    except Exception:return []
def _infer_location(q,loc,plan):
    if _clean(loc,200):return _clean(loc,200)
    m=re.search(r"\b(Richmond|Norfolk|Portsmouth|Chesapeake|Suffolk|Virginia Beach|Hampton|Newport News)\s*,?\s*(Virginia|VA)?\b",q,re.I)
    if m:return _clean(m.group(1)+((', '+m.group(2)) if m.group(2) else ', Virginia'),200)
    return _clean(plan.get("location") or plan.get("place") or plan.get("region"),200)
def _is_contractor_query(q):return any(x in q.lower() for x in ("contractor","electrical","electrician","permit","qualifying agent","master electrician"))
def _discovery_queries(q,loc):
    if not _is_contractor_query(q):return [q]
    return [f'"master electrician" hiring {loc}',f'"qualifying agent" electrical {loc}']
def _candidate_names(items):
    bad=("indeed","linkedin","ziprecruiter","glassdoor","permit","jobs","hiring","search results","city of","top 10","best ","directory","yellow pages","yelp","angi","homeadvisor"); out=[]
    for x in items:
        name=_clean(x.get("company") or x.get("business_name") or x.get("title"),160); name=re.sub(r"\s+[|–—:].*$","",name).strip(); name=re.sub(r"\s+-\s+.*$","",name).strip()
        if 2<len(name)<100 and not any(b in name.lower() for b in bad) and name.lower() not in {n.lower() for n in out}:out.append(name)
    return out[:5]
def _candidate_verify(names,loc,deadline):
    if not names or time.monotonic()>deadline:return [],[],[]
    return _batch([f'"{n}" {loc} "master electrician" "qualifying agent" "pull permits" hiring' for n in names[:2]],"",deadline,1)
def _promote(evidence,evaluation,q):
    ranked=[_clean(x,1600) for x in (evaluation.get("ranked_urls") or []) if _clean(x,1600)]; rank={u:i for i,u in enumerate(ranked)}; annotate_evidence(evidence,q); evidence.sort(key=lambda x:(rank.get(_clean(x.get("url"),1600),999),-float(x.get("evidence_score") or 0))); out=[]
    for item in evidence:
        x=dict(item); inspected=bool(x.pop("page_text",None)); score=float(x.get("evidence_score") or 0); x["promotion_status"]="promoted" if inspected and score>=.45 else ("verified_page" if inspected else "discovered"); x["evidence_basis"]="page content inspected" if inspected else ("persistent RAG evidence" if x.get("rag_retrieved") else "OpenAI Web Search source"); out.append(x)
    return out

def _smart_search(q,loc):
    started=time.monotonic(); deadline=started+24; sources=[]; messages=[]
    try:
        plan=plan_research(q,loc,prior_evidence=[]) or {}; loc=_infer_location(q,loc,plan); memory=_memory_items(q,loc)
        live,src,msg=_batch(_discovery_queries(q,loc),"",deadline,2); sources+=src; messages+=msg; evidence=_dedupe(memory+live); names=_candidate_names(live); verified=[]
        if names and time.monotonic()<deadline-8:
            verified,src2,msg2=_candidate_verify(names,loc,deadline); sources+=src2; messages+=msg2; evidence=_dedupe(evidence+verified)
        if time.monotonic()<deadline-4:_inspect(verified+evidence,5)
        evaluation={}
        if time.monotonic()<deadline-7:
            try:evaluation=evaluate_research(q,loc,evidence) or {}
            except Exception:app.logger.exception("RESEARCH_EVALUATION_ERROR")
        try:remember_evidence([x for x in evidence if x.get("page_text") or (x.get("subtitle") and not x.get("rag_retrieved"))])
        except Exception:app.logger.exception("RAG_PERSIST_ERROR")
        promoted=_promote(evidence,evaluation,q); provider_message=" ".join(dict.fromkeys(messages)); runtime=int((time.monotonic()-started)*1000)
        return {"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"search_provider":"OpenAI Web Search","framework":"bounded-agentic-web-rag-verification","intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,"query":q,"location":loc,"source":"OpenAI Web Search + RAG","count":len(promoted),"promoted_count":sum(1 for x in promoted if x.get("promotion_status")=="promoted"),"business_candidate_count":len(names),"verification_hit_count":len(verified),"results":promoted,"answer_summary":evaluation.get("answer_summary") or "","provider_message":provider_message,"runtime_ms":runtime,"message":f"Agent returned {len(promoted)} evidence result(s) without exceeding the request budget."}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR"); return {"configured":True,"agent_mode":False,"query":q,"location":loc,"source":"OpenAI Web Search + RAG","count":0,"results":[],"agent_error":type(exc).__name__,"message":"Search agent failed safely without fabricating results."}

@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args; q=_clean(d.get("prompt") or d.get("query") or d.get("keyword"),500); loc=_clean(d.get("location"),200)
    if not q:return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(q,loc))
@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500); loc=_clean(request.args.get("location") or "",200); return jsonify(_smart_search(q,loc))
