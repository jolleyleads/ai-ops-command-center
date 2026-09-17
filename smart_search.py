from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import os, re, time, requests, threading
from flask import jsonify, request
from app import app
from universal_app import _search_public_records, _search_businesses, _normalize_custom_search_results, _normalize_brave_search_results
from research_agent import plan_research, evaluate_research
from rag_research import retrieve_context, remember_evidence, annotate_evidence

_BRAVE_LOCK=threading.Lock();_BRAVE_LAST=0.0;_GOOGLE_BLOCKED_UNTIL=0.0

def _clean(v,limit=500): return str(v or "").strip()[:limit]
def _dedupe(items):
    out=[];seen=set()
    for x in items:
        if not isinstance(x,dict):continue
        k=_clean(x.get("url"),1600).lower() or (_clean(x.get("title"),500).lower()+"|"+_clean(x.get("subtitle"),800).lower())
        if k and k not in seen:seen.add(k);out.append(x)
    return out

def _brave(q,loc=""):
    global _BRAVE_LAST
    key=os.getenv("BRAVE_SEARCH_API_KEY") or ""
    if not key:return {"source":"Brave Search","results":[],"status":0}
    text=" ".join(x for x in (q,loc) if x).strip()[:600]
    if not text:return {"source":"Brave Search","results":[],"status":0}
    for attempt in range(2):
        try:
            with _BRAVE_LOCK:
                wait=max(0,1.10-(time.monotonic()-_BRAVE_LAST))
                if wait:time.sleep(wait)
                r=requests.get("https://api.search.brave.com/res/v1/web/search",headers={"Accept":"application/json","X-Subscription-Token":key},params={"q":text,"country":"US","search_lang":"en","count":20},timeout=8)
                _BRAVE_LAST=time.monotonic()
            rows=_normalize_brave_search_results(r.json()) if r.ok else []
            app.logger.warning("SMART_SEARCH_BRAVE status=%s results=%s query=%r",r.status_code,len(rows),text)
            if r.status_code==429 and attempt==0:
                reset=(r.headers.get("X-RateLimit-Reset") or "1").split(",")[0].strip()
                try:time.sleep(min(3,max(1,float(reset))))
                except Exception:time.sleep(1.2)
                continue
            return {"source":"Brave Search","results":rows,"status":r.status_code}
        except Exception:app.logger.exception("SMART_SEARCH_BRAVE_ERROR")
    return {"source":"Brave Search","results":[],"status":0}

def _google(q,loc=""):
    global _GOOGLE_BLOCKED_UNTIL
    if time.monotonic()<_GOOGLE_BLOCKED_UNTIL:return {"source":"Google Programmable Search (cooldown)","results":[],"status":429}
    key=os.getenv("GOOGLE_SEARCH_API_KEY") or "";cx=os.getenv("GOOGLE_SEARCH_CX") or ""
    if not (key and cx):return {"source":"Google Programmable Search","results":[],"status":0}
    try:
        r=requests.get("https://www.googleapis.com/customsearch/v1",params={"key":key,"cx":cx,"q":" ".join(x for x in (q,loc) if x),"num":10},timeout=6)
        rows=_normalize_custom_search_results(r.json()) if r.ok else []
        if r.status_code==429:_GOOGLE_BLOCKED_UNTIL=time.monotonic()+300
        app.logger.warning("SMART_SEARCH_GOOGLE status=%s results=%s query=%r",r.status_code,len(rows),q)
        return {"source":"Google Programmable Search","results":rows,"status":r.status_code}
    except Exception:app.logger.exception("SMART_SEARCH_GOOGLE_ERROR");return {"source":"Google Programmable Search","results":[],"status":0}

def _search(q,loc):
    # Brave is primary. Google is fallback only; never burn Google quota when Brave already returned evidence.
    b=_brave(q,loc)
    if b.get("results"):return {"source":"Brave Search","results":_dedupe(b["results"])}
    g=_google(q,loc)
    return {"source":" + ".join(dict.fromkeys([b.get("source") or "Brave Search",g.get("source") or "Google Programmable Search"])),"results":_dedupe((b.get("results") or [])+(g.get("results") or []))}

def _batch(queries,loc):
    # Brave plans commonly enforce a one-request-per-second window. Keep searches sequential so our own agent does not rate-limit itself.
    results=[];sources=[]
    for q in queries:
        x=_search(q,loc);results.extend(x.get("results") or []);s=_clean(x.get("source"),300)
        if s and s not in sources:sources.append(s)
    return _dedupe(results),sources

def _page(url):
    try:
        p=urlparse(_clean(url,1600));host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"):return ""
        r=requests.get(url,timeout=3,headers={"User-Agent":"Mozilla/5.0 AI-Ops-Research-Agent/5.5"},allow_redirects=True)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower():return ""
        raw=r.text[:140000];raw=re.sub(r"(?is)<(script|style|svg|noscript).*?>.*?</\1>"," ",raw)
        return re.sub(r"\s+"," ",re.sub(r"(?s)<[^>]+>"," ",raw)).strip()[:12000]
    except Exception:return ""
def _inspect(items,limit=8):
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
    m=re.search(r"\b(?:in|near|around)\s+([A-Za-z .'-]+?,?\s*(?:VA|Virginia|NC|Maryland|MD|DC))\b",q,re.I)
    if m:return _clean(m.group(1),200)
    for key in ("location","place","region"):
        v=_clean(plan.get(key),200)
        if v:return v
    return ""
def _is_contractor_query(q):return any(x in q.lower() for x in ("contractor","electrical","electrician","permit","qualifying agent","master electrician"))
def _candidate_discovery_queries(q,loc):
    return [f'electrical contractors {loc}',f'electrician companies {loc}',f'licensed electrical contractor {loc}'] if _is_contractor_query(q) else []
def _business_candidates(q,loc):
    if not _is_contractor_query(q):return []
    rows=[];msg=""
    try:
        p=_search_businesses("electrical contractors",loc);rows=(p.get("results") or [])[:15];msg=p.get("message") or ""
    except Exception:app.logger.exception("SMART_SEARCH_PLACES_ERROR")
    if not rows:
        discovered=[]
        for query in _candidate_discovery_queries(q,loc):
            p=_search(query,"");discovered.extend(p.get("results") or [])
            if len(discovered)>=10:break
        rows=_dedupe(discovered)[:20]
        for x in rows:x["candidate_discovery_source"]="Brave-first web discovery"
    app.logger.warning("SMART_SEARCH_STAGE business_candidates=%s places_message=%r location=%r",len(rows),msg,loc)
    return rows
def _candidate_names(items):
    bad=("indeed","linkedin","ziprecruiter","glassdoor","permit","jobs","hiring","search results","city of","top 10","best ","directory","yellow pages","yelp","angi","homeadvisor")
    out=[]
    for x in items:
        name=_clean(x.get("company") or x.get("business_name") or x.get("title"),160);name=re.sub(r"\s+[|–—:].*$","",name).strip();name=re.sub(r"\s+-\s+.*$","",name).strip()
        if 2<len(name)<100 and not any(b in name.lower() for b in bad) and name.lower() not in {n.lower() for n in out}:out.append(name)
    return out[:8]
def _candidate_verify(names,loc):
    queries=[f'"{n}" {loc} "master electrician" OR "qualifying agent" OR "pull permits" OR hiring' for n in names[:5]]
    return _batch(queries,"") if queries else ([],[])
def _promote(evidence,evaluation,q):
    ranked=[_clean(x,1600) for x in (evaluation.get("ranked_urls") or []) if _clean(x,1600)];rank={u:i for i,u in enumerate(ranked)}
    annotate_evidence(evidence,q);evidence.sort(key=lambda x:(rank.get(_clean(x.get("url"),1600),999),-float(x.get("evidence_score") or 0)))
    out=[]
    for item in evidence:
        x=dict(item);inspected=bool(x.pop("page_text",None));score=float(x.get("evidence_score") or 0);x["promotion_status"]="promoted" if inspected and score>=.45 else ("verified_page" if inspected else "discovered");x["evidence_basis"]="page content inspected" if inspected else ("persistent RAG evidence" if x.get("rag_retrieved") else "search-provider title/snippet");out.append(x)
    return out
def _expansion_queries(q,tried,loc):
    candidates=[f'{loc} electrician "pull permits"',f'{loc} "master electrician" hiring',f'{loc} "qualifying agent" electrical'];seen={_clean(x,500).lower() for x in tried};return [x for x in candidates if x.lower() not in seen][:3]
def _fallback(q,loc):
    live,sources=_batch([q],loc);results=_dedupe(live+_memory_items(q,loc));annotate_evidence(results,q);return {"configured":True,"agent_mode":False,"rag_enabled":True,"query":q,"location":loc,"source":" + ".join(sources) or "Web Search + RAG","count":len(results),"results":results,"message":f"Found {len(results)} live or remembered evidence result(s)."}
def _smart_search(q,loc):
    started=time.monotonic();tried=[];sources=[];expanded=False
    try:
        plan=plan_research(q,loc,prior_evidence=[]) or {};loc=_infer_location(q,loc,plan);memory=_memory_items(q,loc);app.logger.warning("SMART_SEARCH_STAGE inferred_location=%r query=%r",loc,q)
        businesses=_business_candidates(q,loc);evidence=_dedupe(memory+businesses);names=_candidate_names(businesses);verified=[]
        if names:verified,src=_candidate_verify(names,loc);sources.extend(src);evidence=_dedupe(evidence+verified)
        app.logger.warning("SMART_SEARCH_STAGE location=%r businesses=%s names=%s verified_hits=%s",loc,len(businesses),len(names),len(verified))
        if not evidence:
            live,src=_batch([q],loc);tried.append(q);sources.extend(x for x in src if x not in sources);evidence=_dedupe(evidence+live)
        if len(evidence)<3:
            expansion=_expansion_queries(q,tried,loc);expanded=bool(expansion)
            if expansion:more,src2=_batch(expansion,"");tried.extend(expansion);sources.extend(x for x in src2 if x not in sources);evidence=_dedupe(evidence+more)
        _inspect(verified+evidence,10);evaluation=evaluate_research(q,loc,evidence) or {}
        try:remember_evidence([x for x in evidence if x.get("page_text") or (x.get("subtitle") and not x.get("rag_retrieved"))])
        except Exception:app.logger.exception("RAG_PERSIST_ERROR")
        promoted=_promote(evidence,evaluation,q);app.logger.warning("SMART_SEARCH_STAGE final_evidence=%s promoted=%s runtime_ms=%s",len(evidence),sum(1 for x in promoted if x.get("promotion_status")=="promoted"),int((time.monotonic()-started)*1000))
        return {"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"multi_provider":True,"search_expanded":expanded,"candidate_verification":bool(verified),"framework":"brave-primary-rate-limited-discovery-google-cooldown-rag","intent":plan.get("intent") or "web_research","goal":plan.get("goal") or q,"query":q,"location":loc,"queries_tried":tried,"verification_criteria":plan.get("verification_criteria") or [],"source":" + ".join(dict.fromkeys(sources)) or "Brave Search","count":len(promoted),"promoted_count":sum(1 for x in promoted if x.get("promotion_status")=="promoted"),"business_candidate_count":len(businesses),"verification_hit_count":len(verified),"results":promoted,"answer_summary":evaluation.get("answer_summary") or "","search_exhausted":not bool(promoted),"stop_reason":"evidence returned" if promoted else "no evidence returned by configured sources","runtime_ms":int((time.monotonic()-started)*1000),"message":f"Agent returned {len(promoted)} evidence result(s) from {len(businesses)} discovered business candidate(s), with {len(verified)} candidate-specific verification hit(s)."}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR");p=_fallback(q,loc);p["agent_error"]=type(exc).__name__;p["runtime_ms"]=int((time.monotonic()-started)*1000);return p
@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args;q=_clean(d.get("prompt") or d.get("query") or d.get("keyword"),500);loc=_clean(d.get("location"),200)
    if not q:return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    return jsonify(_smart_search(q,loc))
@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500);loc=_clean(request.args.get("location") or "",200);p=_smart_search(q,loc);app.logger.warning("SMART_SEARCH_DIAGNOSTIC agent=%r count=%s businesses=%s verification_hits=%s runtime_ms=%s query=%r",p.get("agent_mode"),p.get("count",0),p.get("business_candidate_count",0),p.get("verification_hit_count",0),p.get("runtime_ms"),q);return jsonify(p)
