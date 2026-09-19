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
    text=" ".join(x for x in (query,location) if x).strip()[:1400];body={"model":os.getenv("OPENAI_SEARCH_MODEL") or "gpt-5.6-luna","tools":[{"type":"web_search"}],"tool_choice":"required","include":["web_search_call.action.sources"],"instructions":"Search the live public web for the user's actual request. Prefer current primary and authoritative sources. Return grounded citations. Never invent facts or URLs.","input":text}
    try:
        r=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=body,timeout=15)
        if not r.ok:
            try: detail=_clean((r.json().get("error") or {}).get("message"),700)
            except Exception: detail=_clean(r.text,700)
            return {"results":[],"message":f"OpenAI Web Search returned HTTP {r.status_code}: {detail}"}
        payload=r.json();rows=_extract_web_rows(payload)
        if rows:return {"results":rows,"message":""}
        types=[_clean(x.get("type"),80) for x in (payload.get("output") or []) if isinstance(x,dict)]
        err=payload.get("error") or {};incomplete=payload.get("incomplete_details") or {}
        detail=_clean(err.get("message") or incomplete.get("reason"),500)
        return {"results":[],"message":f"OpenAI Web Search returned no source URLs. status={_clean(payload.get('status'),40)} output_types={types} detail={detail}"}
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
    return [x for x in evidence if _clean(x.get("url"),1600) in relevant] if relevant else evidence

def _deterministic_need_verification(evidence,q):
    """Fail-closed verifier for explicit hiring/permit-capability need claims in source text."""
    ql=_clean(q,1200).lower()
    electrician_intent=("electric" in ql and ("master" in ql or "permit" in ql))
    if not electrician_intent:return []
    need_patterns=[
        r"\b(?:seeking|hiring|looking for|need(?:s|ed)?|wanted)\b.{0,90}\bmaster electrician\b",
        r"\bmaster electrician\b.{0,90}\b(?:required|needed|wanted|opening|position|job)\b",
        r"\b(?:need(?:s|ed)?|seeking|looking for)\b.{0,100}\b(?:pull|pulling|obtain)\b.{0,40}\bpermits?\b",
        r"\bpermit[- ]pulling\b.{0,80}\b(?:needed|required|help|service)\b",
    ]
    out=[];seen=set()
    for item in evidence:
        url=_clean(item.get("url"),1600)
        text=" ".join(_clean(item.get(k),8000) for k in ("title","subtitle","page_text")).lower()
        if not url or url in seen or not any(re.search(p,text,re.I|re.S) for p in need_patterns):continue
        x=dict(item);x.pop("page_text",None);x["classification"]="Verified Lead";x["promotion_status"]="verified";x["verification_gate"]="passed"
        x["verified_claim"]="Source explicitly indicates a current need for a master electrician or permit-pulling capability."
        x["supporting_urls"]=[url];x["confidence"]="high";x["evidence_basis"]="deterministic explicit-need phrase matched in source evidence";out.append(x);seen.add(url)
    return out

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

def _verification_gate(items, promoted, evaluation):
    """Deterministic three-state gate: Verified Lead, Candidate, or Rejected."""
    verified_by_url={_clean(x.get("url"),1600):x for x in promoted if _clean(x.get("url"),1600)}
    rejected_urls={_clean(x.get("url"),1600) for x in (evaluation.get("rejected_results") or []) if isinstance(x,dict) and _clean(x.get("url"),1600)}
    relevant_urls={_clean(u,1600) for u in (evaluation.get("relevant_urls") or []) if _clean(u,1600)}
    out=[]
    for item in items:
        x=dict(item);x.pop("page_text",None);url=_clean(x.get("url"),1600)
        if url in verified_by_url:
            y=dict(verified_by_url[url]);y["classification"]="Verified Lead";y["verification_gate"]="passed";out.append(y);continue
        if url in rejected_urls or (relevant_urls and url not in relevant_urls):
            x["classification"]="Rejected";x["promotion_status"]="rejected";x["verification_gate"]="failed";x["evidence_basis"]="rejected: evidence does not support the requested lead claim";out.append(x);continue
        x["classification"]="Candidate";x["promotion_status"]="candidate";x["verification_gate"]="pending";x["evidence_basis"]="discovery evidence only; requested claim still requires direct supporting source evidence";out.append(x)
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
        promoted=_verified_results(evidence,evaluation,q) if evaluation else []\n        deterministic_promoted=_deterministic_need_verification(evidence,q)\n        if deterministic_promoted:\n            promoted=_dedupe(promoted+deterministic_promoted)
        # Never discard grounded discovery just because semantic promotion found zero verified claims.
        # Verified entities stay first-class; otherwise expose source-backed candidates explicitly as unverified.
        visible=_verification_gate(evidence[:10],promoted,evaluation)
        verified_count=sum(1 for x in visible if x.get("classification")=="Verified Lead")
        candidate_count_visible=sum(1 for x in visible if x.get("classification")=="Candidate")
        rejected_count=sum(1 for x in visible if x.get("classification")=="Rejected")
        runtime=int((time.monotonic()-started)*1000);unique_tools=list(dict.fromkeys(t for t in tools if t))
        provider_message=" ".join(dict.fromkeys(messages))
        if provider_message: app.logger.warning("SMART_SEARCH_PROVIDER_DIAGNOSTIC query=%r location=%r tools=%r live_source_count=%d message=%s",q,loc,unique_tools,len(live),provider_message)
        return {"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"dynamic_tool_selection":True,"planning_degraded":bool(plan.get("planning_degraded")),"planning_recovered":bool(plan.get("planning_recovered")),"planning_error":plan.get("planning_error") or "","semantic_relevance":True,"framework":"discover-extract-candidates-verify-identity-join-evidence-promote-rag","intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,"query":q,"location":loc,"source":" + ".join(unique_tools+["semantic RAG"]),"tools_used":unique_tools,"live_source_count":len(live),"candidate_count":len(candidates),"joined_evidence_count":len(joined),"count":len(visible),"promoted_count":len(promoted),"verified_count":verified_count,"unverified_candidate_count":candidate_count_visible,"rejected_count":rejected_count,"verification_gate":True,"results":visible,"answer_summary":evaluation.get("answer_summary") or "","provider_message":provider_message,"runtime_ms":runtime,"message":(f"Verification gate: {verified_count} Verified Leads, {candidate_count_visible} Candidates, {rejected_count} Rejected. Verified Lead requires direct source evidence for the requested claim.")}
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
