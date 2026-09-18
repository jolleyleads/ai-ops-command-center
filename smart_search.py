from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os,re,time,requests
from flask import jsonify,request
from app import app
from research_agent import plan_research,evaluate_research
from rag_research import retrieve_context,remember_evidence,annotate_evidence
from universal_app import _search_public_records,_search_businesses,_normalize_jobs


def _clean(v,limit=500):return str(v or "").strip()[:limit]
def _dedupe(items):
    out=[];seen=set()
    for x in items:
        if not isinstance(x,dict):continue
        k=_clean(x.get("url"),1600).lower()
        if k and k not in seen:seen.add(k);out.append(x)
    return out

def _extract_web_rows(payload):
    rows=[]
    for output in payload.get("output") or []:
        if not isinstance(output,dict):continue
        if output.get("type")=="web_search_call":
            for src in (output.get("action") or {}).get("sources") or []:
                if isinstance(src,dict):
                    url=_clean(src.get("url"),1600)
                    if url.startswith(("http://","https://")):rows.append({"title":_clean(src.get("title"),500) or urlparse(url).netloc,"url":url,"subtitle":_clean(src.get("snippet") or src.get("description"),1800),"source":"OpenAI Web Search","research_tool":"web_search"})
        if output.get("type")=="message":
            for content in output.get("content") or []:
                if not isinstance(content,dict):continue
                text=_clean(content.get("text"),3000)
                for ann in content.get("annotations") or []:
                    if not isinstance(ann,dict):continue
                    data=ann.get("url_citation") if isinstance(ann.get("url_citation"),dict) else ann;url=_clean(data.get("url"),1600)
                    if url.startswith(("http://","https://")):rows.append({"title":_clean(data.get("title"),500) or urlparse(url).netloc,"url":url,"subtitle":text,"source":"OpenAI Web Search","research_tool":"web_search"})
    return _dedupe(rows)

def _web_search(query,location=""):
    key=os.getenv("OPENAI_API_KEY") or ""
    if not key:return {"results":[],"message":"OPENAI_API_KEY is not configured."}
    text=" ".join(x for x in (query,location) if x).strip()[:1400];body={"model":os.getenv("OPENAI_SEARCH_MODEL") or "chat-latest","tools":[{"type":"web_search"}],"tool_choice":"required","include":["web_search_call.action.sources"],"instructions":"Search the live public web for the user's actual request. Prefer current primary and authoritative sources. Return grounded citations. Never invent facts or URLs.","input":text}
    try:
        r=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=body,timeout=8)
        if not r.ok:return {"results":[],"message":f"OpenAI Web Search returned HTTP {r.status_code}."}
        rows=_extract_web_rows(r.json());return {"results":rows,"message":"" if rows else "OpenAI Web Search exposed no usable source URLs."}
    except requests.RequestException as exc:return {"results":[],"message":f"OpenAI Web Search failed: {type(exc).__name__}."}

def _run_tool(call):
    tool=_clean(call.get("tool"),50);q=_clean(call.get("query"),700);loc=_clean(call.get("location"),200)
    try:
        if tool=="web_search":payload=_web_search(q,loc)
        elif tool=="public_records":payload=_search_public_records(q,loc)
        elif tool=="business_search":payload=_search_businesses(q,loc)
        elif tool=="job_search":payload={"configured":True,"source":"Remotive","message":"","results":_normalize_jobs(q)}
        else:return [],f"Unknown research tool: {tool}"
    except Exception as exc:return [],f"{tool} failed safely: {type(exc).__name__}"
    rows=[]
    for item in payload.get("results") or []:
        if not isinstance(item,dict):continue
        x=dict(item);x["research_tool"]=tool;x.setdefault("source",payload.get("source") or tool);rows.append(x)
    return rows,_clean(payload.get("message"),500)

def _run_calls(calls,deadline,max_calls=3):
    results=[];messages=[];used=[]
    for call in (calls or [])[:max_calls]:
        if time.monotonic()>=deadline:break
        rows,msg=_run_tool(call);results.extend(rows);used.append(_clean(call.get("tool"),50))
        if msg:messages.append(msg)
    return _dedupe(results),messages,used

def _page(url):
    try:
        p=urlparse(_clean(url,1600));host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"):return ""
        r=requests.get(url,timeout=2,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/11.0"},allow_redirects=True)
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
    try:return [{"title":x["title"],"url":x["url"],"subtitle":x["text"],"source":"RAG memory","last_seen":x["last_seen"],"rag_retrieved":True,"research_tool":"rag"} for x in retrieve_context(q,loc,limit=4)]
    except Exception:return []
def _semantic_keep(evidence,evaluation):
    relevant={_clean(u,1600) for u in (evaluation.get("relevant_urls") or []) if _clean(u,1600)}
    if relevant:return [x for x in evidence if _clean(x.get("url"),1600) in relevant]
    return [x for x in evidence if not x.get("rag_retrieved")]
def _promote(evidence,evaluation,q):
    ranked=[_clean(x,1600) for x in (evaluation.get("ranked_urls") or []) if _clean(x,1600)];rank={u:i for i,u in enumerate(ranked)};annotate_evidence(evidence,q);evidence.sort(key=lambda x:(rank.get(_clean(x.get("url"),1600),999),-float(x.get("evidence_score") or 0)));out=[]
    for item in evidence:
        x=dict(item);inspected=bool(x.pop("page_text",None));score=float(x.get("evidence_score") or 0);x["promotion_status"]="promoted" if inspected and score>=.40 else ("verified_page" if inspected else "discovered");x["evidence_basis"]="page content inspected" if inspected else ("semantically relevant RAG evidence" if x.get("rag_retrieved") else f"{x.get('research_tool') or 'live'} source");out.append(x)
    return out

def _smart_search(q,loc):
    started=time.monotonic();deadline=started+25;messages=[];tools=[]
    try:
        plan=plan_research(q,loc,[]) or {};calls=plan.get("tool_calls") or [{"tool":"web_search","query":q,"location":loc}]
        live,msg,used=_run_calls(calls,deadline,3);messages+=msg;tools+=used;evidence=_dedupe(live+_memory(q,loc))
        if time.monotonic()<deadline-5:_inspect(evidence,5)
        evaluation=evaluate_research(q,loc,evidence) if evidence and time.monotonic()<deadline-5 else {};evidence=_semantic_keep(evidence,evaluation)
        follow=evaluation.get("followup_tool_calls") or []
        if not evaluation.get("sufficient") and follow and time.monotonic()<deadline-8:
            extra,msg2,used2=_run_calls(follow,deadline,1);messages+=msg2;tools+=used2;_inspect(extra,3);combined=_dedupe(evidence+extra);evaluation=evaluate_research(q,loc,combined) if time.monotonic()<deadline-5 else evaluation;evidence=_semantic_keep(combined,evaluation)
        try:remember_evidence([x for x in evidence if not x.get("rag_retrieved") and (x.get("page_text") or x.get("subtitle"))])
        except Exception:app.logger.exception("RAG_PERSIST_ERROR")
        promoted=_promote(evidence,evaluation,q);runtime=int((time.monotonic()-started)*1000);unique_tools=list(dict.fromkeys(t for t in tools if t))
        return {"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"dynamic_tool_selection":True,"planning_degraded":bool(plan.get("planning_degraded")),"planning_error":plan.get("planning_error") or "","semantic_relevance":True,"framework":"plan-select-tools-search-read-reason-verify-rag","intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,"query":q,"location":loc,"source":" + ".join(unique_tools+["semantic RAG"]),"tools_used":unique_tools,"live_source_count":len(live),"count":len(promoted),"promoted_count":sum(1 for x in promoted if x.get("promotion_status")=="promoted"),"results":promoted,"answer_summary":evaluation.get("answer_summary") or "","provider_message":" ".join(dict.fromkeys(messages)),"runtime_ms":runtime,"message":f"Agent returned {len(promoted)} semantically relevant evidence result(s) using dynamically selected research tools."}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR");return {"configured":True,"agent_mode":False,"query":q,"location":loc,"count":0,"results":[],"agent_error":type(exc).__name__,"message":"Search agent failed safely without fabricating results."}

@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args;q=_clean(d.get("prompt") or d.get("query") or d.get("keyword"),500);loc=_clean(d.get("location"),200)
    if not q:return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(q,loc))
@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500);loc=_clean(request.args.get("location") or "",200);return jsonify(_smart_search(q,loc))
