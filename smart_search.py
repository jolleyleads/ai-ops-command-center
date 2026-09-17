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
        if not isinstance(x,dict):continue
        k=_clean(x.get("url"),1600).lower() or (_clean(x.get("title"),500).lower()+"|"+_clean(x.get("subtitle"),800).lower())
        if k and k not in seen:seen.add(k);out.append(x)
    return out

def _extract_web_rows(payload):
    rows=[]
    def walk(node):
        if isinstance(node,dict):
            url=_clean(node.get("url"),1600)
            if url.startswith(("http://","https://")):rows.append({"title":_clean(node.get("title") or node.get("name"),500) or urlparse(url).netloc,"url":url,"subtitle":_clean(node.get("snippet") or node.get("text") or node.get("description"),1800),"source":"OpenAI Web Search"})
            for v in node.values():walk(v)
        elif isinstance(node,list):
            for v in node:walk(v)
    walk(payload);return _dedupe(rows)

def _search(query,location=""):
    key=os.getenv("OPENAI_API_KEY") or ""
    if not key:return {"results":[],"status":0,"message":"OPENAI_API_KEY is not configured."}
    text=" ".join(x for x in (query,location) if x).strip()[:1400]
    body={"model":os.getenv("OPENAI_SEARCH_MODEL") or "chat-latest","tools":[{"type":"web_search"}],"tool_choice":"required","include":["web_search_call.action.sources","web_search_call.results"],"instructions":"Act as a general-purpose live web search engine. Search for the user's actual meaning, not just literal keywords. Prefer current primary and authoritative sources. Never invent facts, entities, jobs, permits, contacts or URLs.","input":text}
    try:
        r=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=body,timeout=8)
        if not r.ok:return {"results":[],"status":r.status_code,"message":f"OpenAI Web Search returned HTTP {r.status_code}."}
        return {"results":_extract_web_rows(r.json()),"status":200,"message":""}
    except requests.RequestException as exc:return {"results":[],"status":0,"message":f"OpenAI Web Search request failed: {type(exc).__name__}."}

def _batch(queries,loc,deadline,max_queries=2):
    results=[];messages=[]
    for q in (queries or [])[:max_queries]:
        if time.monotonic()>=deadline:break
        x=_search(_clean(q,700),loc);results.extend(x.get("results") or [])
        if x.get("message"):messages.append(x["message"])
        if x.get("status") in (401,403,429):break
    return _dedupe(results),messages

def _page(url):
    try:
        p=urlparse(_clean(url,1600));host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"):return ""
        r=requests.get(url,timeout=2,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/9.0"},allow_redirects=True)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower():return ""
        raw=r.text[:100000];raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>"," ",raw);return re.sub(r"\s+"," ",re.sub(r"(?s)<[^>]+>"," ",raw)).strip()[:8000]
    except Exception:return ""
def _inspect(items,limit=5):
    targets=[x for x in items if x.get("url") and not x.get("page_text")][:limit]
    if not targets:return
    with ThreadPoolExecutor(max_workers=min(5,len(targets))) as pool:
        fs={pool.submit(_page,x["url"]):x for x in targets}
        for f in as_completed(fs):
            try:text=f.result()
            except Exception:text=""
            if text:fs[f]["page_text"]=text

def _memory(q,loc):
    try:return [{"title":x["title"],"url":x["url"],"subtitle":x["text"],"source":"RAG memory","last_seen":x["last_seen"],"rag_retrieved":True} for x in retrieve_context(q,loc,limit=5)]
    except Exception:return []
def _semantic_keep(evidence,evaluation):
    relevant={_clean(u,1600) for u in (evaluation.get("relevant_urls") or []) if _clean(u,1600)}
    if not relevant:return [x for x in evidence if not x.get("rag_retrieved")]
    return [x for x in evidence if _clean(x.get("url"),1600) in relevant]
def _promote(evidence,evaluation,q):
    ranked=[_clean(x,1600) for x in (evaluation.get("ranked_urls") or []) if _clean(x,1600)];rank={u:i for i,u in enumerate(ranked)};annotate_evidence(evidence,q);evidence.sort(key=lambda x:(rank.get(_clean(x.get("url"),1600),999),-float(x.get("evidence_score") or 0)));out=[]
    for item in evidence:
        x=dict(item);inspected=bool(x.pop("page_text",None));score=float(x.get("evidence_score") or 0);x["promotion_status"]="promoted" if inspected and score>=.40 else ("verified_page" if inspected else "discovered");x["evidence_basis"]="page content inspected" if inspected else ("semantically relevant RAG evidence" if x.get("rag_retrieved") else "live web source");out.append(x)
    return out

def _smart_search(q,loc):
    started=time.monotonic();deadline=started+24;messages=[]
    try:
        plan=plan_research(q,loc,[]) or {};queries=plan.get("queries") or [q]
        live,msg=_batch(queries,loc,deadline,2);messages+=msg;memory=_memory(q,loc);evidence=_dedupe(live+memory)
        if time.monotonic()<deadline-5:_inspect(evidence,5)
        evaluation=evaluate_research(q,loc,evidence) if evidence and time.monotonic()<deadline-5 else {}
        evidence=_semantic_keep(evidence,evaluation)
        follow=evaluation.get("followup_queries") or []
        if not evaluation.get("sufficient") and follow and time.monotonic()<deadline-9:
            extra,msg2=_batch(follow,loc,deadline,1);messages+=msg2;_inspect(extra,3);combined=_dedupe(evidence+extra);evaluation=evaluate_research(q,loc,combined) if time.monotonic()<deadline-5 else evaluation;evidence=_semantic_keep(combined,evaluation)
        try:remember_evidence([x for x in evidence if not x.get("rag_retrieved") and (x.get("page_text") or x.get("subtitle"))])
        except Exception:app.logger.exception("RAG_PERSIST_ERROR")
        promoted=_promote(evidence,evaluation,q);runtime=int((time.monotonic()-started)*1000)
        return {"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"semantic_relevance":True,"search_provider":"OpenAI Web Search","framework":"semantic-plan-search-read-reason-research-verify-rag","intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,"query":q,"location":loc,"source":"OpenAI Web Search + semantic RAG","count":len(promoted),"promoted_count":sum(1 for x in promoted if x.get("promotion_status")=="promoted"),"results":promoted,"answer_summary":evaluation.get("answer_summary") or "","provider_message":" ".join(dict.fromkeys(messages)),"runtime_ms":runtime,"message":f"Agent returned {len(promoted)} semantically relevant evidence result(s)."}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR");return {"configured":True,"agent_mode":False,"query":q,"location":loc,"source":"OpenAI Web Search + semantic RAG","count":0,"results":[],"agent_error":type(exc).__name__,"message":"Search agent failed safely without fabricating results."}

@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args;q=_clean(d.get("prompt") or d.get("query") or d.get("keyword"),500);loc=_clean(d.get("location"),200)
    if not q:return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(q,loc))
@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500);loc=_clean(request.args.get("location") or "",200);return jsonify(_smart_search(q,loc))
