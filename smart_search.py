from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os,re,time,requests
from flask import jsonify,request
from app import app
from research_agent import plan_research,recover_tool_plan,evaluate_research,extract_candidates
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
    text=" ".join(x for x in (query,location) if x).strip()[:1400];body={"model":os.getenv("OPENAI_SEARCH_MODEL") or "gpt-4.1-mini","tools":[{"type":"web_search"}],"tool_choice":"required","include":["web_search_call.action.sources"],"instructions":"Search the live public web for the user's actual request. Prefer current primary and authoritative sources. Return grounded citations. Never invent facts or URLs.","input":text}
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
    return [x for x in evidence if _clean(x.get("url"),1600) in relevant] if relevant else []

def _verified_results(evidence,evaluation,q):
    by_url={_clean(x.get("url"),1600):x for x in evidence if _clean(x.get("url"),1600)}
    out=[];seen=set()
    for verdict in evaluation.get("verified_results") or []:
        if not isinstance(verdict,dict):continue
        url=_clean(verdict.get("url"),1600);item=by_url.get(url)
        if not item or url in seen:continue
        entity=_clean(verdict.get("entity_name"),300);claim=_clean(verdict.get("claim"),1200)
        supporting=[_clean(u,1600) for u in (verdict.get("supporting_urls") or []) if _clean(u,1600) in by_url]
        if not entity or not claim or not supporting:continue
        x=dict(item);x.pop("page_text",None);x["title"]=entity;x["verified_claim"]=claim;x["supporting_urls"]=supporting;x["confidence"]=_clean(verdict.get("confidence"),20) or "medium";x["promotion_status"]="verified";x["evidence_basis"]="target entity and requested claim semantically verified from supplied evidence";seen.add(url);out.append(x)
    annotate_evidence(out,q)
    return out

def _candidate_followups(q,loc,candidates,deadline,max_candidates=3):
    evidence=[];messages=[];tools=[]
    for cand in (candidates or [])[:max_candidates]:
        if time.monotonic()>=deadline-6:break
        name=_clean(cand.get("name"),300)
        if not name:continue
        calls=[{"tool":"web_search","query":f'"{name}" {q}',"location":loc},{"tool":"business_search","query":name,"location":loc}]
        rows,msg,used=_run_calls(calls,deadline,2);messages+=msg;tools+=used
        for x in rows:
            x["candidate_name"]=name;x["candidate_discovery_urls"]=cand.get("discovery_urls") or []
        evidence.extend(rows)
    return _dedupe(evidence),messages,tools

def _smart_search(q,loc):
    started=time.monotonic();deadline=started+25;messages=[];tools=[]
    try:
        plan=plan_research(q,loc,[]) or {}
        if plan.get("planning_degraded") or not plan.get("tool_calls"):
            plan=recover_tool_plan(q,loc) or plan
        calls=plan.get("tool_calls") or []
        if not calls:
            # Grounded web discovery is the universal safe baseline when the semantic planner is unavailable.
            # Evidence evaluation can still request specialized public-record/business/job follow-ups.
            calls=[{"tool":"web_search","query":q,"location":loc},{"tool":"public_records","query":q,"location":loc},{"tool":"business_search","query":q,"location":loc}]
            plan=dict(plan)
            plan["planning_degraded"]=True
            plan["planning_recovered"]=False
            plan["fallback_route"]="grounded_web_discovery"
        live,msg,used=_run_calls(calls,deadline,3);messages+=msg;tools+=used
        discovery=_dedupe(live+_memory(q,loc))
        if time.monotonic()<deadline-9:_inspect(discovery,6)
        candidates=extract_candidates(q,loc,discovery) if discovery and time.monotonic()<deadline-9 else []
        joined,msgc,usedc=_candidate_followups(q,loc,candidates,deadline,3) if candidates else ([],[],[])
        messages+=msgc;tools+=usedc
        evidence=_dedupe(discovery+joined)
        if time.monotonic()<deadline-5:_inspect(evidence,8)
        evaluation=evaluate_research(q,loc,evidence) if evidence and time.monotonic()<deadline-5 else {}
        follow=evaluation.get("followup_tool_calls") or []
        if not evaluation.get("sufficient") and follow and time.monotonic()<deadline-7:
            extra,msg2,used2=_run_calls(follow,deadline,1);messages+=msg2;tools+=used2;_inspect(extra,3)
            evidence=_dedupe(evidence+extra)
            evaluation=evaluate_research(q,loc,evidence) if time.monotonic()<deadline-4 else evaluation
        if evaluation:
            evidence=_semantic_keep(evidence,evaluation)
        else:
            # Preserve source-backed discovery as candidates; never mislabel it verified.
            for x in evidence:
                x["promotion_status"]="candidate"
                x["evidence_basis"]="source-backed candidate; semantic verification unavailable"
        try:remember_evidence([x for x in evidence if not x.get("rag_retrieved") and (x.get("page_text") or x.get("subtitle"))])
        except Exception:app.logger.exception("RAG_PERSIST_ERROR")
        promoted=_verified_results(evidence,evaluation,q) if evaluation else []\n        visible=promoted if promoted else ([dict(x, promotion_status=x.get("promotion_status") or "candidate") for x in evidence[:10]] if not evaluation else [])\n        runtime=int((time.monotonic()-started)*1000);unique_tools=list(dict.fromkeys(t for t in tools if t))
        return {"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"dynamic_tool_selection":True,"planning_degraded":bool(plan.get("planning_degraded")),"planning_recovered":bool(plan.get("planning_recovered")),"planning_error":plan.get("planning_error") or "","semantic_relevance":True,"framework":"discover-extract-candidates-verify-identity-join-evidence-promote-rag","intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,"query":q,"location":loc,"source":" + ".join(unique_tools+["semantic RAG"]),"tools_used":unique_tools,"live_source_count":len(live),"candidate_count":len(candidates),"joined_evidence_count":len(joined),"count":len(visible),"promoted_count":len(promoted),"results":visible,"answer_summary":evaluation.get("answer_summary") or "","provider_message":" ".join(dict.fromkeys(messages)),"runtime_ms":runtime,"message":(f"Agent returned {len(promoted)} target entities with the requested claim verified from supplied evidence." if evaluation else f"Agent returned {len(visible)} source-backed candidates; semantic verification is temporarily unavailable.")}
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
