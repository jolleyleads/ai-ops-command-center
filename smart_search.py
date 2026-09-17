from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, re, time, random, requests
from flask import jsonify, request
from app import app
from universal_app import _search_businesses, _normalize_custom_search_results
from research_agent import plan_research, evaluate_research
from rag_research import retrieve_context, remember_evidence, annotate_evidence

_GOOGLE_BLOCKED_UNTIL=0.0

def _clean(v,limit=500): return str(v or "").strip()[:limit]
def _dedupe(items):
    out=[];seen=set()
    for x in items:
        if not isinstance(x,dict):continue
        k=_clean(x.get("url"),1600).lower() or (_clean(x.get("title"),500).lower()+"|"+_clean(x.get("subtitle"),800).lower())
        if k and k not in seen:seen.add(k);out.append(x)
    return out

def _google(q,loc=""):
    global _GOOGLE_BLOCKED_UNTIL
    key=os.getenv("GOOGLE_SEARCH_API_KEY") or "";cx=os.getenv("GOOGLE_SEARCH_CX") or ""
    if not (key and cx):return {"source":"Google Programmable Search","results":[],"status":0,"message":"Google search credentials are not configured."}
    if time.monotonic()<_GOOGLE_BLOCKED_UNTIL:return {"source":"Google Programmable Search","results":[],"status":429,"message":"Google search is temporarily in quota cooldown."}
    text=" ".join(x for x in (q,loc) if x).strip()[:600]
    for attempt in range(3):
        try:
            r=requests.get("https://www.googleapis.com/customsearch/v1",params={"key":key,"cx":cx,"q":text,"num":10},timeout=8)
            rows=_normalize_custom_search_results(r.json()) if r.ok else []
            app.logger.warning("SMART_SEARCH_GOOGLE status=%s results=%s query=%r",r.status_code,len(rows),text)
            if r.ok:return {"source":"Google Programmable Search","results":rows,"status":200,"message":""}
            if r.status_code==429:
                if attempt<2:
                    time.sleep(min(8,(2**attempt)+random.random()))
                    continue
                _GOOGLE_BLOCKED_UNTIL=time.monotonic()+300
                return {"source":"Google Programmable Search","results":[],"status":429,"message":"Google search quota is temporarily exhausted."}
            return {"source":"Google Programmable Search","results":[],"status":r.status_code,"message":f"Google search returned HTTP {r.status_code}."}
        except Exception:
            app.logger.exception("SMART_SEARCH_GOOGLE_ERROR")
            if attempt<2:time.sleep(min(8,(2**attempt)+random.random()))
    return {"source":"Google Programmable Search","results":[],"status":0,"message":"Google search request failed."}

def _search(q,loc):
    g=_google(q,loc);return {"source":g["source"],"results":_dedupe(g.get("results") or []),"status":g.get("status"),"message":g.get("message") or ""}
def _batch(queries,loc):
    results=[];sources=[];messages=[]
    for q in queries:
        x=_search(q,loc);results.extend(x.get("results") or []);s=_clean(x.get("source"),300);m=_clean(x.get("message"),500)
        if s and s not in sources:sources.append(s)
        if m and m not in messages:messages.append(m)
        if x.get("status")==429:break
    return _dedupe(results),sources,messages

def _page(url):
    try:
        p=urlparse(_clean(url,1600));host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"):return ""
        r=requests.get(url,timeout=4,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/6.0"},allow_redirects=True)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower():return ""
        raw=r.text[:140000];raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>"," ",raw);return re.sub(r"\s+"," ",re.sub(r"(?s)<[^>]+>"," ",raw)).strip()[:12000]
    except Exception:return ""
def _inspect(items,limit=10):
    targets=[x for x in items if x.get("url") and not x.get("page_text")][:limit]
    if not targets:return
    with ThreadPoolExecutor(max_workers=min(6,len(targets))) as pool:
        fs={pool.submit(_page,x["url"]):x for x in targets}
        for f in as_completed(fs):
            text=f.result()
            if text:fs[f]["page_text"]=text

def _memory_items(q,loc):return [{"title":x["title"],"url":x["url"],"subtitle":x["text"],"source":"RAG memory","last_seen":x["last_seen"],"rag_retrieved":True} for x in retrieve_context(q,loc)]
def _infer_location(q,loc,plan):
    if _clean(loc,200):return _clean(loc,200)
    cities="Richmond|Norfolk|Portsmouth|Chesapeake|Suffolk|Virginia Beach|Hampton|Newport News"
    m=re.search(r"\b("+cities+r")\s*,?\s*(Virginia|VA)?\b",q,re.I)
    if m:return _clean(m.group(1)+((', '+m.group(2)) if m.group(2) else ', Virginia'),200)
    for key in ("location","place","region"):
        v=_clean(plan.get(key),200)
        if v:return v
    return ""
def _is_contractor_query(q):return any(x in q.lower() for x in ("contractor","electrical","electrician","permit","qualifying agent","master electrician"))
def _discovery_queries(q,loc):
    if not _is_contractor_query(q):return [q]
    return [f'"master electrician" hiring {loc}',f'"qualifying agent" electrical {loc}',f'"pull permits" electrician {loc}',f'electrical contractors {loc}']
def _candidate_names(items):
    bad=("indeed","linkedin","ziprecruiter","glassdoor","permit","jobs","hiring","search results","city of","top 10","best ","directory","yellow pages","yelp","angi","homeadvisor")
    out=[]
    for x in items:
        name=_clean(x.get("company") or x.get("business_name") or x.get("title"),160);name=re.sub(r"\s+[|–—:].*$","",name).strip();name=re.sub(r"\s+-\s+.*$","",name).strip()
        if 2<len(name)<100 and not any(b in name.lower() for b in bad) and name.lower() not in {n.lower() for n in out}:out.append(name)
    return out[:8]
def _candidate_verify(names,loc):
    return _batch([f'"{n}" {loc} ("master electrician" OR "qualifying agent" OR "pull permits" OR hiring)' for n in names[:5]],"") if names else ([],[],[])
def _promote(evidence,evaluation,q):
    ranked=[_clean(x,1600) for x in (evaluation.get("ranked_urls") or []) if _clean(x,1600)];rank={u:i for i,u in enumerate(ranked)};annotate_evidence(evidence,q);evidence.sort(key=lambda x:(rank.get(_clean(x.get("url"),1600),999),-float(x.get("evidence_score") or 0)));out=[]
    for item in evidence:
        x=dict(item);inspected=bool(x.pop("page_text",None));score=float(x.get("evidence_score") or 0);x["promotion_status"]="promoted" if inspected and score>=.45 else ("verified_page" if inspected else "discovered");x["evidence_basis"]="page content inspected" if inspected else ("persistent RAG evidence" if x.get("rag_retrieved") else "Google search title/snippet");out.append(x)
    return out
def _smart_search(q,loc):
    started=time.monotonic();sources=[];messages=[]
    try:
        plan=plan_research(q,loc,prior_evidence=[]) or {};loc=_infer_location(q,loc,plan);memory=_memory_items(q,loc);app.logger.warning("SMART_SEARCH_STAGE inferred_location=%r query=%r",loc,q)
        live,src,msg=_batch(_discovery_queries(q,loc),"");sources+=src;messages+=msg;evidence=_dedupe(memory+live);names=_candidate_names(live);verified=[]
        if names:
            verified,src2,msg2=_candidate_verify(names,loc);sources+=src2;messages+=msg2;evidence=_dedupe(evidence+verified)
        _inspect(verified+evidence,10);evaluation=evaluate_research(q,loc,evidence) or {}
        try:remember_evidence([x for x in evidence if x.get("page_text") or (x.get("subtitle") and not x.get("rag_retrieved"))])
        except Exception:app.logger.exception("RAG_PERSIST_ERROR")
        promoted=_promote(evidence,evaluation,q);provider_ok=bool(live or verified);provider_message=" ".join(dict.fromkeys(messages))
        app.logger.warning("SMART_SEARCH_STAGE final_evidence=%s promoted=%s provider_ok=%s runtime_ms=%s",len(evidence),sum(1 for x in promoted if x.get("promotion_status")=="promoted"),provider_ok,int((time.monotonic()-started)*1000))
        return {"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"multi_provider":False,"search_provider":"Google Programmable Search","framework":"google-discovery-verification-contact-enrichment-rag","intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,"query":q,"location":loc,"source":"Google Programmable Search + RAG","count":len(promoted),"promoted_count":sum(1 for x in promoted if x.get("promotion_status")=="promoted"),"business_candidate_count":len(live),"verification_hit_count":len(verified),"results":promoted,"answer_summary":evaluation.get("answer_summary") or "","provider_available":provider_ok,"provider_message":provider_message,"search_exhausted":not bool(promoted),"stop_reason":"evidence returned" if promoted else (provider_message or "no verified evidence returned"),"runtime_ms":int((time.monotonic()-started)*1000),"message":f"Agent returned {len(promoted)} evidence result(s) from {len(live)} discovered candidate result(s), with {len(verified)} verification hit(s)."}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR");return {"configured":True,"agent_mode":False,"query":q,"location":loc,"source":"Google Programmable Search + RAG","count":0,"results":[],"agent_error":type(exc).__name__,"message":"Search agent failed safely without fabricating results."}
@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args;q=_clean(d.get("prompt") or d.get("query") or d.get("keyword"),500);loc=_clean(d.get("location"),200)
    if not q:return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(q,loc))
@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500);loc=_clean(request.args.get("location") or "",200);return jsonify(_smart_search(q,loc))
