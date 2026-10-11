from urllib.parse import urlparse
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FutureTimeout
from datetime import datetime, timezone
import os,re,time,requests
from flask import jsonify,request
from app import app
from research_agent import plan_research,recover_tool_plan,evaluate_research,extract_candidates
from rag_research import retrieve_context,remember_evidence,annotate_evidence
from universal_app import _search_public_records,_search_businesses,_normalize_jobs
from src.company_identity import identity_proof, host, owned_host, email_on_domain, page_metadata, page_text, visible_page_text, contact_context_matches, shared_host, location_matches
from src.job_evidence import job_page_metadata, check_job_evidence, receipt_is_current, requested_role_terms, is_hiring_query, requested_location, alternative_claim_allowed
from src.record_evidence import check_record_evidence, record_receipt_is_current
from src.company_identity import current_contact_source
from src.company_identity import name_key
from src.public_fetch import public_get


def _clean(v,limit=500):return str(v or "").strip()[:limit]
def _source_summary(item):
    row=dict(item)
    for key in ("page_text","job_detail_text","source_job_postings","source_apply_controls"):row.pop(key,None)
    return row

def _dedupe(items):
    out=[];seen={}
    for x in items:
        if not isinstance(x,dict):continue
        k=_clean(x.get("url"),1600).lower()
        if not k:continue
        if k not in seen:seen[k]=len(out);out.append(x)
        elif x.get("verification_research") and not out[seen[k]].get("verification_research"):
            # Re-fetching the discovery URL is useful proof, not a duplicate to discard.
            out[seen[k]]={**out[seen[k]],**x}
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
        r=requests.post("https://api.openai.com/v1/responses",headers={"Authorization":f"Bearer {key}","Content-Type":"application/json"},json=body,timeout=30)
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

def _exa_search(query,location=""):
    """Deterministic verification retrieval using Exa Search + returned contents."""
    key=os.getenv("EXA_API_KEY") or ""
    if not key:return {"results":[],"message":"EXA_API_KEY is not configured.","source":"Exa"}
    text=" ".join(x for x in (query,location) if x).strip()[:1400]
    body={"query":text,"numResults":5,"type":"auto","contents":{"text":{"maxCharacters":8000},"highlights":{"numSentences":5,"highlightsPerUrl":3},"livecrawl":"preferred"}}
    try:
        r=requests.post("https://api.exa.ai/search",headers={"x-api-key":key,"Content-Type":"application/json"},json=body,timeout=15)
        if not r.ok:
            try: detail=_clean(r.json().get("error"),700)
            except Exception: detail=_clean(r.text,700)
            return {"results":[],"message":f"Exa Search returned HTTP {r.status_code}: {detail}","source":"Exa"}
        rows=[]
        for item in r.json().get("results") or []:
            if not isinstance(item,dict):continue
            url=_clean(item.get("url"),1600)
            if not url.startswith(("http://","https://")):continue
            highlights=item.get("highlights") or []
            rows.append({"title":_clean(item.get("title"),500) or urlparse(url).netloc,"url":url,"subtitle":_clean(" ".join(highlights),3000),"page_text":_clean(item.get("text"),8000),"published_at":item.get("publishedDate"),"observed_at":datetime.now(timezone.utc).isoformat(),"freshness":"live_retrieval_publication_date_unconfirmed" if not item.get("publishedDate") else "dated_source","source":"Exa","research_tool":"exa_search"})
        return {"results":_dedupe(rows),"message":"","source":"Exa"}
    except requests.RequestException as exc:return {"results":[],"message":f"Exa Search failed: {type(exc).__name__}.","source":"Exa"}

def _run_tool(call):
    tool=_clean(call.get("tool"),50);q=_clean(call.get("query"),700);loc=_clean(call.get("location"),200)
    try:
        if tool=="exa_search":payload=_exa_search(q,loc)
        elif tool=="web_search":payload=_web_search(q,loc)
        elif tool=="public_records":
            payload=_search_public_records(q,loc)
            if not payload.get("results") and (not payload.get("configured") or payload.get("message")):
                # Retrieval remains deterministic when Google denies API access.
                # Only government-hosted URLs enter this official-record route.
                fallback=_exa_search(q+" site:gov",loc)
                official=[x for x in fallback.get("results") or [] if (urlparse(x.get("url") or "").hostname or "").lower().endswith(".gov")]
                if official:
                    payload={"configured":True,"source":"Exa official government sources","results":official,"message":"Google records provider unavailable; retrieved government-source candidates through Exa. Record claims still require verification."}
                else:
                    payload=dict(payload)
                    payload["message"]=_clean(payload.get("message") or "Records provider unavailable",350)+"; official-source fallback returned no evidence."
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
    selected=(calls or [])[:max_calls]
    if not selected or time.monotonic()>=deadline:return results,messages,used
    # Independent providers run together, leaving time for candidate verification.
    pool=ThreadPoolExecutor(max_workers=min(3,len(selected)))
    futures={pool.submit(_run_tool,call):call for call in selected}
    try:
        for future in as_completed(futures,timeout=max(0.01,deadline-time.monotonic())):
            call=futures[future]
            rows,msg=future.result();results.extend(rows);used.append(_clean(call.get("tool"),50))
            for row in rows:
                row.setdefault("observed_at",datetime.now(timezone.utc).isoformat())
                row.setdefault("freshness","live_retrieval_publication_date_unconfirmed")
            if msg:messages.append(msg)
    except FutureTimeout:
        messages.append("Research deadline reached; unfinished provider calls were skipped.")
    finally:pool.shutdown(wait=False,cancel_futures=True)
    return _dedupe(results),messages,used

def _page_snapshot(url):
    try:
        p=urlparse(_clean(url,1600));host=(p.hostname or "").lower()
        if p.scheme not in ("http","https") or not host or host in ("localhost","127.0.0.1","::1") or host.endswith(".local"):return {}
        r=public_get(url,timeout=2)
        if r.status_code>=400 or "text/html" not in (r.headers.get("content-type") or "").lower():return {}
        raw=r.text[:100000];metadata={**page_metadata(raw),**job_page_metadata(raw,r.url)}
        return {**metadata,"page_text":visible_page_text(raw)[:8000],"resolved_url":r.url,"observed_at":datetime.now(timezone.utc).isoformat(),"directly_fetched":True,"http_status":r.status_code,"job_page_fetched_at":datetime.now(timezone.utc).isoformat()}
    except Exception:return {}
def _page(url):
    return _page_snapshot(url).get("page_text","")
def _inspect(items,limit=5):
    targets=[x for x in items if x.get("url") and not x.get("rag_retrieved") and (not x.get("page_text") or (not x.get("directly_fetched") and (x.get("research_tool")=="public_records" or "permit_license" in (x.get("verification_intents") or []) or x.get("verification_research") and (not shared_host(host(x["url"])) or "hiring" in (x.get("verification_intents") or [])))))][:limit]
    if not targets:return
    with ThreadPoolExecutor(max_workers=min(5,len(targets))) as pool:
        fs={pool.submit(_page_snapshot,x["url"]):x for x in targets}
        for f in as_completed(fs):
            try:snapshot=f.result()
            except Exception:snapshot={}
            if snapshot.get("page_text"):fs[f].update(snapshot)

def _memory(q,loc):
    try:return [{"title":x["title"],"url":x["url"],"subtitle":x["text"],"source":"RAG memory","last_seen":x["last_seen"],"rag_retrieved":True,"research_tool":"rag"} for x in retrieve_context(q,loc,limit=4)]
    except Exception:return []
def _semantic_keep(evidence,evaluation):
    relevant={_clean(u,1600) for u in (evaluation.get("relevant_urls") or []) if _clean(u,1600)}
    return [x for x in evidence if _clean(x.get("url"),1600) in relevant] if relevant else evidence

def _deterministic_route_intent(q):
    """Stable API routing label, independent of semantic planner prose."""
    ql=_clean(q,1200).lower()
    if any(x in ql for x in ("contractor","contractors")):return "contractors"
    if "master electrician" in ql and any(x in ql for x in ("lead","leads","pull permit","permit pulling")):return "permit_leads"
    if any(x in ql for x in ("permit","permits","inspection","inspections","license","licensing")):return "permits"
    if any(x in ql for x in ("job","jobs","hiring","hire ","career","careers","open role","opening")) and not any(x in ql for x in ("company","companies","business","businesses","firm","firms")):return "jobs"
    if any(x in ql for x in ("company","companies","business","businesses","firm","firms")):return "businesses"
    return "web_research"

def _claim_terms(q):
    """Extract meaningful requested-claim terms without encoding any industry."""
    ql=_clean(q,1200).lower()
    stop={
        "find","show","give","list","business","businesses","company","companies","firm","firms",
        "contractor","contractors","clinic","clinics","agency","agencies","shop","shops",
        "in","near","around","that","who","which","with","and","or","the","a","an","of","for",
        "current","currently","active","actively","evidence","proof","recent","latest",
    }
    return [x for x in re.findall(r"[a-z0-9]+",ql) if len(x)>=4 and x not in stop]


def _verification_intent(q):
    """Classify claim channels generically; industry names never change verification rules."""
    ql=_clean(q,1200).lower()
    intents=[]
    if is_hiring_query(q):
        intents.append("hiring")
    if re.search(r"\b(?:unanswered|callbacks?|call\s*backs?|missed calls?|slow responses?|reviews?)\b",ql):
        intents.append("response_complaints")
    if re.search(r"\b(?:permit|permits|inspection|inspections|license|licenses|licensed|licensing)\b",ql):
        intents.append("permit_license")
    if re.search(r"\b(?:project|projects|contract|contracts|bid|bids|awarded|expanding|expansion|opening|launching)\b",ql):
        intents.append("projects")
    if not intents:
        intents.append("claim")
    return tuple(dict.fromkeys(intents))


def _needs_candidate_verification(q):
    """Any requested business condition beyond plain discovery requires candidate proof."""
    ql=_clean(q,1200).lower()
    discovery_terms=("business","businesses","company","companies","firm","firms","contractor","contractors","clinic","clinics","agency","agencies","shop","shops")
    return any(x in ql for x in discovery_terms) and _verification_intent(q)!=("claim",)


def _requested_role_terms(q):
    return requested_role_terms(q)


def _verification_queries(name,q,intents=None):
    """Build candidate-specific research queries from the user's claim, never from an industry whitelist."""
    intents=tuple(intents or _verification_intent(q))
    queries=[]
    if "hiring" in intents:
        role=" ".join(_requested_role_terms(q))
        queries.extend([
            f'"{name}" (jobs OR careers OR hiring OR opening) "{role}"' if role else f'"{name}" (jobs OR careers OR hiring OR opening)',
            f'"{name}" (seeking OR recruiting OR hiring OR "looking for") "{role}"' if role else f'"{name}" (seeking OR recruiting OR hiring OR "looking for")',
        ])
    if "permit_license" in intents:
        queries.append(f'"{name}" (permit OR permits OR inspection OR inspections OR license OR licensing OR licensed)')
    if "projects" in intents:
        queries.append(f'"{name}" (project OR projects OR contract OR awarded OR bid OR expansion OR opening)')
    if "response_complaints" in intents:
        queries.append(f'"{name}" reviews ("unanswered calls" OR "never called back" OR "missed calls" OR "slow response")')
    if not queries:queries=[f'"{name}" {_clean(q,700)}']
    queries.append(f'"{name}" official website contact email phone')
    return list(dict.fromkeys(queries))


def _company_discovery_calls(q,loc,calls):
    """Company requests must discover employers rather than generic remote-job feeds."""
    if not _needs_candidate_verification(q):return calls
    kept=[c for c in calls if c.get("tool")!="job_search"]
    if len(kept)==len(calls):return calls
    intents=_verification_intent(q);role=" ".join(_requested_role_terms(q))
    focused=[]
    if "hiring" in intents:
        focused.append({"tool":"web_search","query":f'{loc} employers hiring {role} careers apply current openings',"location":loc})
    if "response_complaints" in intents:
        focused.append({"tool":"exa_search","query":f'{loc} business reviews "never called back" "unanswered calls" dates',"location":loc})
    return (focused+kept)[:3]


def _company_discovery_rows(candidates,discovery):
    by_url={x.get("url"):x for x in discovery}
    rows=[]
    for cand in candidates:
        source=next((by_url[u] for u in cand.get("discovery_urls",[]) if u in by_url),None)
        if source:
            rows.append({**source,"title":cand["name"],"candidate_name":cand["name"]})
    return rows


def _additional_discovery(q,loc,round_number):
    intents=_verification_intent(q)
    if "response_complaints" in intents and ("hiring" not in intents or round_number%2):
        topic='business reviews "never called back" OR "unanswered calls" dated local branch'
    elif "hiring" in intents:
        topic='employers "'+" ".join(_requested_role_terms(q))+'" hiring careers application current openings'
    else:topic=q
    detail=("official company sources","recent postings and contact pages","additional employers and direct sources","company application and service pages","current company locations and contact details","dated evidence and primary sources")[round_number%6]
    return {"tool":"web_search" if round_number%2 else "exa_search","query":f"{loc} {topic} {detail}","location":loc}


def _contact_followups(rows,evidence,deadline):
    """Spend reserved time on explicit employer-owned contact sources."""
    tasks=[]
    for row in rows:
        if row.get("classification")!="Verified Lead":continue
        name=row.get("candidate_name") or row.get("company") or row.get("title")
        roots=set();website=row.get("website")
        if website and not shared_host(host(website)):roots.add(website)
        bound=set(row.get("supporting_urls") or [])
        for source in evidence:
            if source.get("url") not in bound or not current_contact_source(source):continue
            proof=identity_proof(name,source)
            if proof:roots.add("https://"+proof["official_host"])
            for record in source.get("source_job_postings") or []:
                org=record.get("hiringOrganization") if isinstance(record,dict) else None
                if not isinstance(org,dict) or name_key(org.get("name"))!=name_key(name):continue
                anchor=org.get("url") or org.get("sameAs")
                if isinstance(anchor,str) and anchor.startswith(("https://","http://")) and not shared_host(host(anchor)):roots.add(anchor)
        normalized={host(r):r for r in roots if host(r)}
        if len(normalized)!=1:continue
        root=next(iter(normalized.values()))
        parsed=urlparse(root);root=f"{parsed.scheme}://{parsed.netloc}/"
        tasks.append((name,root))
        if len(tasks)>=3:break
    def fetch(task):
        name,root=task;out=[]
        for url in (root+"contact",root):
            if time.monotonic()>=deadline-2:break
            snapshot=_page_snapshot(url)
            if not current_contact_source(snapshot) or not owned_host(snapshot.get("resolved_url") or url,root):continue
            row={**snapshot,"url":snapshot.get("resolved_url") or url,"candidate_name":name,"source":"employer_contact_followup"}
            if identity_proof(name,row):out.append(row)
        return out
    if not tasks or time.monotonic()>=deadline-2:return []
    with ThreadPoolExecutor(max_workers=3) as pool:
        return [source for group in pool.map(fetch,tasks) for source in group]


def _attach_source_contacts(rows,evidence,location=""):
    """Contacts require one resolved company domain and source-local evidence."""
    for row in rows:
        name=row.get("candidate_name") or row.get("title")
        website=row.get("website") or ""
        proofs=[]
        bound_urls=set(row.get("supporting_urls") or [])
        if row.get("job_validation"):bound_urls.add(row["job_validation"].get("source_url"))
        for item in evidence:
            if not current_contact_source(item):continue
            label=item.get("candidate_name")
            if label and _candidate_key(label)!=_candidate_key(name):continue
            if not label and item.get("url") not in bound_urls and not (website and owned_host(item.get("resolved_url") or item.get("url"),website)):continue
            proof=identity_proof(name,item,website)
            if proof:proofs.append((item,proof))
        domains={p["official_host"] for _,p in proofs}
        # Normalize child hosts to an explicit company anchor, never to a guessed suffix.
        if website:domains={host(website)} if proofs else set()
        acronym=bool(re.fullmatch(r"[A-Z0-9]{2,4}",str(name or "")))
        primary_claim=any(host(u) in domains for u in row.get("supporting_urls") or [])
        unresolved=len(domains)!=1 or (acronym and not website and not primary_claim)
        contacts=[]
        if unresolved:
            row.update(contacts=[],contact_status="identity_unresolved",company_identity_status="ambiguous" if len(domains)>1 else "unproven",contact_reason="Company ownership must be resolved before attaching contacts.")
            continue
        official_host=next(iter(domains));official_site=website or "https://"+official_host
        row["website"]=official_site
        row["contact_location"]=location
        row["company_identity_status"]="source_bound"
        row["company_identity_sources"]=list(dict.fromkeys(p["source_url"] for _,p in proofs))
        for item,proof in proofs:
            if not owned_host(proof["source_url"],official_site):continue
            text=str(item.get("page_text") or item.get("text") or "")
            for email in dict.fromkeys(re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",text)):
                if not email_on_domain(email,official_site) or email.lower().endswith((".png",".jpg",".svg")):continue
                if not contact_context_matches(text,email,location):continue
                contacts.append({"email":email.lower(),"source_url":proof["source_url"],"observed_at":item.get("observed_at"),"status":"source_observed_deliverability_unconfirmed","company_identity":proof,"location":location,"location_status":"source_context_matched" if location else "not_requested"})
            for phone in dict.fromkeys(re.findall(r"(?<!\d)(?:\+1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]\d{3}[ .-]\d{4}(?!\d)",text)):
                if not contact_context_matches(text,phone,location):continue
                contacts.append({"phone":phone,"source_url":proof["source_url"],"observed_at":item.get("observed_at"),"status":"source_observed_reachability_unconfirmed","company_identity":proof,"location":location,"location_status":"source_context_matched" if location else "not_requested"})
        row["contacts"]=list({(c.get("email") or c.get("phone"),c["source_url"]):c for c in contacts}.values())
        row["contact_status"]="source_observed" if contacts else "not_found"
    return rows


def _deterministic_need_verification(evidence,q,location=""):
    """Fail closed: candidate-specific evidence must support the exact requested claim channel."""
    intents=_verification_intent(q)
    role_terms=_requested_role_terms(q) if "hiring" in intents else []
    channel_patterns={
        "hiring":r"\b(?:hiring|hire|seeking|recruiting|looking for|job opening|open position|careers?|apply)\b",
        "permit_license":r"\b(?:permit|permits|inspection|inspections|license|licenses|licensed|licensing)\b",
        "projects":r"\b(?:project|projects|contract|contracts|bid|bids|awarded|expanding|expansion|opening|launching)\b",
        "response_complaints":r"\b(?:unanswered calls?|never called (?:me |us )?back|did(?:n't| not) (?:answer|call back)|missed calls?|slow responses?|no (?:response|callback))\b",
    }
    if intents==("claim",):
        return []
    out=[];seen=set()
    for item in evidence:
        url=_clean(item.get("url"),1600)
        text=" ".join(_clean(item.get(k),8000) for k in ("title","subtitle","page_text")).lower()
        candidate=_clean(item.get("candidate_name"),300)
        if not item.get("verification_research") or not candidate or not url or url in seen:
            continue
        # A search query's candidate label does not establish source identity.
        identity_terms=[t for t in re.findall(r"[a-z0-9]+",candidate.lower()) if t not in {"inc","llc","ltd","the","company"}]
        plain_identity_supported=bool(identity_terms and all(re.search(rf"\b{re.escape(t)}\b",text) for t in identity_terms))
        if "hiring" not in intents and not plain_identity_supported:
            continue
        if "hiring" not in intents and not location_matches(text,location):continue
        job_check=check_job_evidence(item,q,location,candidate) if "hiring" in intents else None
        if job_check is not None:item["job_validation"]=job_check
        record_check=check_record_evidence(item,q,location) if "permit_license" in intents else None
        if record_check is not None:item["record_validation"]=record_check
        matched=[]
        for intent in intents:
            if intent=="hiring":
                if job_check.get("ok"):matched.append(intent)
                continue
            pattern=channel_patterns.get(intent)
            if intent=="permit_license" and not record_check.get("ok"):continue
            if pattern and re.search(pattern,text,re.I|re.S):
                if intent=="hiring" and not job_check.get("ok"):continue
                if intent!="hiring" and (not plain_identity_supported or not location_matches(text,location)):continue
                matched.append(intent)
        if not matched or ("hiring" in intents and "hiring" not in matched and not alternative_claim_allowed(q,matched)):
            continue
        x=_source_summary(item);x["candidate_name"]=candidate;x["title"]=candidate
        x["classification"]="Verified Lead";x["promotion_status"]="verified";x["verification_gate"]="passed"
        x["verified_claim"]="Candidate-specific source evidence supports the requested claim."
        x["supporting_urls"]=[url];x["confidence"]="high"
        x["verified_channels"]=matched
        if job_check and "hiring" in matched:x["job_validation"]=job_check;x["job_title"]=job_check["job_title"];x["job_location"]=job_check["job_locations"];x["job_status"]=job_check["open_status"];x["published_at"]=job_check["date_posted"]
        if record_check and "permit_license" in matched:x["record_validation"]=record_check;x["record_location"]=record_check["record_locations"];x["published_at"]=record_check["record_date"]
        x["evidence_basis"]="candidate-specific evidence matched requested claim channel: "+",".join(matched)
        out.append(x);seen.add(url)
    return out


def _verified_results(evidence,evaluation,q,location=""):
    by_url={_clean(x.get("url"),1600):x for x in evidence if _clean(x.get("url"),1600)}
    out=[];seen=set()
    for verdict in evaluation.get("verified_results") or []:
        if not isinstance(verdict,dict):continue
        url=_clean(verdict.get("url"),1600);item=by_url.get(url)
        if not item or url in seen or not item.get("verification_research") or not _clean(item.get("candidate_name"),300):continue
        entity=_clean(verdict.get("entity_name"),300);claim=_clean(verdict.get("claim"),1200)
        supporting=[_clean(u,1600) for u in (verdict.get("supporting_urls") or []) if _clean(u,1600) in by_url]
        if not entity or not claim or not supporting or item.get("rag_retrieved"):continue
        if _candidate_key(entity)!=_candidate_key(item.get("candidate_name")):continue
        if is_hiring_query(q) or "permit_license" in _verification_intent(q):
            supported=_deterministic_need_verification([item],q,location)
            if not supported:continue
            # Model confidence cannot replace current job, role, city, or closure proof.
            out.extend(supported);seen.add(url);continue
        x=_source_summary(item);x["candidate_name"]=_clean(item.get("candidate_name"),300);x["title"]=entity;x["verified_claim"]=claim;x["supporting_urls"]=supporting;x["confidence"]=_clean(verdict.get("confidence"),20) or "medium";x["promotion_status"]="verified";x["evidence_basis"]="candidate-specific requested claim semantically verified from supplied evidence";seen.add(url);out.append(x)
    annotate_evidence(out,q)
    return out

def _candidate_key(name):
    return re.sub(r"[^a-z0-9]+","",_clean(name,300).lower())


def rank_research_results(rows,limit=10,query="",location=""):
    """Rank distinct companies by supported claims and dated evidence."""
    by_company={}
    now=datetime.now(timezone.utc)
    for raw in rows:
        x=dict(raw);key=_candidate_key(x.get("candidate_name") or x.get("title"))
        if not key:continue
        publication=x.get("published_at")
        if not publication:
            dates=[str(e.get("published_at")) for e in x.get("evidence",[]) if isinstance(e,dict) and e.get("published_at")]
            if dates:publication=max(dates);x["published_at"]=publication
        age=None
        try:
            stamp=datetime.fromisoformat(str(publication).replace("Z","+00:00"))
            if not stamp.tzinfo:stamp=stamp.replace(tzinfo=timezone.utc)
            age=(now-stamp).total_seconds()/86400
        except (ValueError,TypeError):pass
        verified=x.get("promotion_status")=="verified"
        text=" ".join(str(x.get(k) or "") for k in ("subtitle","verified_claim"))
        missing_review_date=age is None and "response_complaints" in x.get("verified_channels",[])
        invalid_job=is_hiring_query(query) and ("hiring" in x.get("verified_channels",[]) or not alternative_claim_allowed(query,x.get("verified_channels"))) and not receipt_is_current(x.get("job_validation"),query,location,company=x.get("candidate_name") or x.get("title"))
        invalid_record="permit_license" in x.get("verified_channels",[]) and not record_receipt_is_current(x.get("record_validation"),query,location)
        if invalid_job or invalid_record or missing_review_date or (age is not None and (age<0 or age>180)) or re.search(r"\b(?:position filled|no longer accepting|job closed|applications closed)\b",text,re.I):
            verified=False;x.update(classification="Candidate",promotion_status="candidate",verification_gate="pending",evidence_basis="Requested current status requires fresh supporting evidence.")
        if verified:
            x.update(classification="Verified Lead",verification_gate="passed")
        x["evidence_age_days"]=round(age,1) if age is not None else None
        x["freshness_note"]="Publication date unconfirmed; fetched now does not mean published now." if age is None else "Dated source; current status may still change."
        sources=list(dict.fromkeys(x.get("supporting_urls") or ([x["url"]] if x.get("url") else [])))
        score=(70 if verified else 0 if x.get("promotion_status")=="rejected" else 20)+(15 if age is not None and 0<=age<=30 else 5 if age is not None and 0<=age<=180 else 0)+min(10,len(sources)*3)
        x["prospect_score"]=score;x["ranking_basis"]="Claim support, publication recency, and distinct supporting sources."
        old=by_company.get(key)
        if not old or score>old["prospect_score"]:by_company[key]=x
    return sorted(by_company.values(),key=lambda x:x["prospect_score"],reverse=True)[:limit]

def _promoted_by_candidate(promoted):
    out={}
    for item in promoted or []:
        name=_clean(item.get("candidate_name") or item.get("title"),300);key=_candidate_key(name)
        if key:out.setdefault(key,[]).append(item)
    return out

def _verification_gate(items,promoted,evaluation,query="",location="",evidence=None):
    promoted=[v for v in promoted if "permit_license" not in v.get("verified_channels",[]) or record_receipt_is_current(v.get("record_validation"),query,location)]
    if is_hiring_query(query):
        promoted=[v for v in promoted if ("hiring" not in v.get("verified_channels",[]) and alternative_claim_allowed(query,v.get("verified_channels"))) or receipt_is_current(v.get("job_validation"),query,location,company=v.get("candidate_name") or v.get("title"))]
    promoted_candidates=_promoted_by_candidate(promoted)
    rejected_urls={_clean(x.get("url"),1600) for x in (evaluation.get("rejected_results") or []) if isinstance(x,dict) and _clean(x.get("url"),1600)}
    relevant_urls={_clean(u,1600) for u in (evaluation.get("relevant_urls") or []) if _clean(u,1600)}
    out=[]
    for item in items:
        x=_source_summary(item);url=_clean(x.get("url"),1600)
        name=_clean(x.get("candidate_name") or x.get("title") or x.get("name"),300)
        verified_sources=promoted_candidates.get(_candidate_key(name),[])
        if verified_sources:
            supporting=[];claims=[]
            for v in verified_sources:
                supporting.extend(v.get("supporting_urls") or ([_clean(v.get("url"),1600)] if _clean(v.get("url"),1600) else []))
                if _clean(v.get("verified_claim"),1200):claims.append(_clean(v.get("verified_claim"),1200))
            x["classification"]="Verified Lead";x["promotion_status"]="verified";x["verification_gate"]="passed";x["verified_claim"]=claims[0] if claims else "Candidate-specific verification evidence passed the deterministic gate.";x["supporting_urls"]=list(dict.fromkeys(u for u in supporting if u));x["evidence_basis"]="candidate-specific verification evidence deterministically joined to discovery identity"
            x["verified_channels"]=list(dict.fromkeys(c for v in verified_sources for c in v.get("verified_channels",[])))
            job_checks=[v["job_validation"] for v in verified_sources if receipt_is_current(v.get("job_validation"),query,location,company=v.get("candidate_name") or v.get("title"))]
            if job_checks:x.update(job_validation=job_checks[0],job_title=job_checks[0]["job_title"],job_location=job_checks[0]["job_locations"],job_status=job_checks[0]["open_status"],published_at=job_checks[0]["date_posted"])
            records=[v["record_validation"] for v in verified_sources if record_receipt_is_current(v.get("record_validation"),query,location)]
            if records:x.update(record_validation=records[0],record_location=records[0]["record_locations"])
            x["evidence"]=[{"job_validation":v.get("job_validation"),"url":v.get("url"),"title":v.get("candidate_name"),"snippet":v.get("subtitle"),"observed_at":v.get("observed_at"),"published_at":v.get("published_at"),"verified_claim":v.get("verified_claim")} for v in verified_sources]
            x["current_status_guaranteed"]=False
            out.append(x);continue
        if url in rejected_urls or (relevant_urls and url not in relevant_urls):
            x["classification"]="Rejected";x["promotion_status"]="rejected";x["verification_gate"]="failed";x["evidence_basis"]="rejected: evidence does not support the requested lead claim";out.append(x);continue
        job_failures=[r.get("job_validation") for r in evidence or [] if _candidate_key(r.get("candidate_name"))==_candidate_key(name) and r.get("job_validation") and not r["job_validation"].get("ok")]
        if job_failures:x["job_verification_status"]="unverified";x["job_verification_reasons"]=list(dict.fromkeys(reason for check in job_failures for reason in check.get("reasons",[])))
        x["classification"]="Candidate";x["promotion_status"]="candidate";x["verification_gate"]="pending";x["evidence_basis"]="discovery evidence only; requested claim still requires candidate-specific supporting source evidence";out.append(x)
    return out


def _scope_search_results(rows,query,location,evidence):
    """Do not display unrelated job/record discovery as requested results."""
    route=_deterministic_route_intent(query)
    if is_hiring_query(query):route="jobs"
    if route=="permit_leads":route="permits"
    if route not in {"jobs","permits"}:return rows,[]
    kept=[];excluded=[]
    for item in rows:
        row=dict(item)
        if route=="jobs":
            if row.get("classification")=="Verified Lead" and alternative_claim_allowed(query,row.get("verified_channels")):
                kept.append(row);continue
            proof=row.get("job_validation")
            company=row.get("candidate_name") or row.get("company") or (row.get("title") if row.get("type")!="job" else "")
            if not receipt_is_current(proof,query,location,company=company):
                source=next((s for s in evidence if s.get("url")==row.get("url")),row)
                if not row.get("candidate_name") and not row.get("company"):
                    names={r.get("hiringOrganization",{}).get("name") for r in source.get("source_job_postings") or [] if isinstance(r,dict) and isinstance(r.get("hiringOrganization"),dict) and isinstance(r["hiringOrganization"].get("name"),str)}
                    if len(names)==1:company=names.pop()
                proof=check_job_evidence(source,query,location,company) if company else {"ok":False,"reasons":["job_employer_identity_required"]}
            ok=bool(company) and receipt_is_current(proof,query,location,company=company)
            if ok:
                row["subtitle"]=proof["job_title"]+" | "+", ".join(proof["job_locations"])+" | Application option observed on employer/ATS page."
                row.update(job_validation=proof,company=company,candidate_name=company,title=company,job_title=proof["job_title"],job_location=proof["job_locations"],job_status=proof["open_status"],job_verification_status="verified",published_at=proof["date_posted"],current_status_guaranteed=False,classification="Verified Lead",promotion_status="verified",verification_gate="passed",verified_channels=["hiring"],supporting_urls=[proof["source_url"]],verified_claim="Employer job page matches the requested role and city; an enabled application target for this posting was observed.")
            reasons=(proof or {}).get("reasons") or row.get("job_verification_reasons") or ["current_role_and_city_job_evidence_required"]
        else:
            proof=row.get("record_validation")
            if not record_receipt_is_current(proof,query,location):
                source=next((s for s in evidence if s.get("url")==row.get("url")),row)
                proof=check_record_evidence(source,query,location)
            ok=record_receipt_is_current(proof,query,location)
            reasons=(proof or {}).get("reasons") or ["current_record_and_city_evidence_required"]
        if not ok:
            excluded.append({"url":row.get("url"),"reasons":reasons});continue
        row["relevance_status"]="source_matched"
        if route=="permits":row.update(record_validation=proof,record_location=proof["record_locations"])
        kept.append(row)
    return kept,excluded

def _fallback_candidates(discovery,limit=10):
    out=[];seen=set()
    for item in discovery or []:
        if item.get("research_tool")!="business_search":continue
        name=_clean(item.get("title") or item.get("name"),300);url=_clean(item.get("url"),1600);key=_candidate_key(name)
        if not name or not url or key in seen:continue
        seen.add(key);out.append({"name":name,"discovery_urls":[url],"candidate_source":"deterministic_business_discovery"})
        if len(out)>=limit:break
    return out

def _candidate_followups(q,loc,candidates,deadline,max_candidates=10):
    # Verify three companies together rather than spending the whole budget
    # on the first company's sources. Child calls preserve candidate identity.
    selected=(candidates or [])[:max_candidates]
    if len(selected)>1:
        evidence=[];messages=[];tools=[]
        with ThreadPoolExecutor(max_workers=3) as pool:
            futures=[pool.submit(_candidate_followups,q,loc,[cand],deadline,1) for cand in selected]
            for future in futures:
                rows,msg,used=future.result();evidence.extend(rows);messages.extend(msg);tools.extend(used)
        return _dedupe(evidence),messages,tools
    evidence=[];messages=[];tools=[];intents=_verification_intent(q)
    for cand in (candidates or [])[:max_candidates]:
        if time.monotonic()>=deadline-6:break
        name=_clean(cand.get("name"),300)
        if not name:continue
        candidate_rows=[]
        queries=_verification_queries(name,q,intents)
        for verify_query in queries:
            if time.monotonic()>=deadline-4:break
            rows,msg,used=_run_calls([{"tool":"exa_search","query":verify_query,"location":loc}],deadline,1);messages+=msg;tools+=used
            if not rows and time.monotonic()<deadline-20:
                fallback,msg2,used2=_run_calls([{"tool":"web_search","query":verify_query,"location":loc}],deadline,1)
                rows.extend(fallback);messages+=msg2;tools+=used2
            for x in rows:
                x["candidate_name"]=name;x["candidate_discovery_urls"]=cand.get("discovery_urls") or [];x["verification_research"]=True;x["verification_query"]=verify_query;x["verification_intents"]=list(intents)
            candidate_rows.extend(rows)
        if "hiring" in intents and time.monotonic()<deadline-3:_inspect(candidate_rows,5)
        # Irrelevant Exa hits are not success. Try the other provider for missing proof.
        if not _deterministic_need_verification(candidate_rows,q,loc) and time.monotonic()<deadline-20:
            verify_query=queries[0]
            rows2,msg2,used2=_run_calls([{"tool":"web_search","query":verify_query,"location":loc}],deadline,1);messages+=msg2;tools+=used2
            for x in rows2:
                x["candidate_name"]=name;x["candidate_discovery_urls"]=cand.get("discovery_urls") or [];x["verification_research"]=True;x["verification_query"]=verify_query;x["verification_intents"]=list(intents)
            candidate_rows.extend(rows2)
        evidence.extend(candidate_rows)
    return _dedupe(evidence),messages,tools

def _smart_search(q,loc,runtime_budget=25,target_count=10):
    if is_hiring_query(q):loc=requested_location(q,loc)
    runtime_budget=max(8,min(int(runtime_budget or 25),540))
    target_count=max(1,min(int(target_count or 10),20))
    started=time.monotonic();total_deadline=started+runtime_budget;deadline=total_deadline-(8 if runtime_budget>25 else 0);messages=[];tools=[]
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
        calls=_company_discovery_calls(q,loc,calls)
        live,msg,used=_run_calls(calls,deadline,3);messages+=msg;tools+=used
        discovery=_dedupe(live+_memory(q,loc))
        if time.monotonic()<deadline-9:_inspect(discovery,6)
        candidates=extract_candidates(q,loc,discovery) if discovery and time.monotonic()<deadline-9 else []
        # The LLM is optional at this handoff: grounded business results become
        # candidates deterministically so verification still runs when planning/extraction is unavailable.
        if not candidates and _needs_candidate_verification(q):
            candidates=_fallback_candidates(discovery,10)
        # Reserve time to evaluate company-specific proof after retrieval.
        joined,msgc,usedc=_candidate_followups(q,loc,candidates,deadline-25 if runtime_budget>25 else deadline,min(6,target_count*2)) if candidates else ([],[],[])
        messages+=msgc;tools+=usedc
        evidence=_dedupe(discovery+joined)
        if time.monotonic()<deadline-5:_inspect(evidence,8)
        evaluation=evaluate_research(q,loc,evidence) if evidence and time.monotonic()<deadline-5 else {}
        research_rounds=0;seen_calls=set()
        while runtime_budget>25 and research_rounds<6 and time.monotonic()<deadline-35:
            promoted_so_far=_deterministic_need_verification(evidence,q,loc)
            if len({_candidate_key(x.get("candidate_name")) for x in promoted_so_far})>=target_count:break
            follow=evaluation.get("followup_tool_calls") or []
            if not follow:
                follow=[{"tool":"exa_search","query":q+" current official company sources","location":loc}]
            follow=[c for c in follow if isinstance(c,dict) and (c.get("tool"),c.get("query")) not in seen_calls]
            if not follow:
                # Repeated model suggestions must not terminate a short search early.
                follow=[_additional_discovery(q,loc,research_rounds)]
            follow=_company_discovery_calls(q,loc,follow)
            seen_calls.update((c.get("tool"),c.get("query")) for c in follow)
            extra,msg2,used2=_run_calls(follow,deadline,2);messages+=msg2;tools+=used2
            discovery=_dedupe(discovery+extra);_inspect(extra,4)
            new_candidates=extract_candidates(q,loc,extra) or _fallback_candidates(extra,target_count)
            known={_candidate_key(x.get("name")) for x in candidates}
            new_candidates=[x for x in new_candidates if _candidate_key(x.get("name")) not in known]
            candidates+=new_candidates
            verified_extra,msg3,used3=_candidate_followups(q,loc,new_candidates,deadline,target_count)
            messages+=msg3;tools+=used3;evidence=_dedupe(evidence+extra+verified_extra)
            evaluation=evaluate_research(q,loc,evidence) if time.monotonic()<deadline-15 else evaluation
            research_rounds+=1
        contact_evidence=list(evidence)
        if evaluation:
            evidence=_semantic_keep(evidence,evaluation)
        else:
            # Preserve source-backed discovery as candidates; never mislabel it verified.
            for x in evidence:
                x["promotion_status"]="candidate"
                x["evidence_basis"]="source-backed candidate; semantic verification unavailable"
        try:remember_evidence([x for x in evidence if not x.get("rag_retrieved") and (x.get("page_text") or x.get("subtitle"))])
        except Exception:app.logger.exception("RAG_PERSIST_ERROR")
        promoted=_verified_results(evidence,evaluation,q,loc) if evaluation else []
        deterministic_promoted=_deterministic_need_verification(evidence,q,loc)
        if deterministic_promoted:
            promoted=_dedupe(promoted+deterministic_promoted)
        # Never discard grounded discovery just because semantic promotion found zero verified claims.
        # Verified entities stay first-class; otherwise expose source-backed candidates explicitly as unverified.
        discovery_visible=_company_discovery_rows(candidates,discovery) if _needs_candidate_verification(q) else discovery[:10]
        visible=_verification_gate(discovery_visible,promoted,evaluation,q,loc,contact_evidence)
        if runtime_budget>25:
            visible=rank_research_results(visible+promoted,target_count,q,loc)
        visible,excluded=_scope_search_results(visible,q,loc,contact_evidence)
        contact_followups=_contact_followups(visible,contact_evidence,total_deadline) if runtime_budget>25 else []
        contact_evidence+=contact_followups
        visible=_attach_source_contacts(visible,contact_evidence,loc)
        verified_count=sum(1 for x in visible if x.get("classification")=="Verified Lead")
        candidate_count_visible=sum(1 for x in visible if x.get("classification")=="Candidate")
        rejected_count=sum(1 for x in visible if x.get("classification")=="Rejected")
        runtime=int((time.monotonic()-started)*1000);unique_tools=list(dict.fromkeys(t for t in tools if t))
        provider_message=" ".join(dict.fromkeys(messages))
        scope_summary={"relevance_gate":True,"excluded_result_count":len(excluded),"excluded_results":excluded,"availability_status":"matching_results" if visible else "no_confirmed_matches"}
        answer_summary=evaluation.get("answer_summary") or ""
        if is_hiring_query(q) or _deterministic_route_intent(q) in {"permits","permit_leads"}:
            answer_summary=f"{len(visible)} source-confirmed matches for the requested role or record and location." if visible else "No source-confirmed matches for the requested role or record and location."
        if provider_message: app.logger.warning("SMART_SEARCH_PROVIDER_DIAGNOSTIC query=%r location=%r tools=%r live_source_count=%d message=%s",q,loc,unique_tools,len(live),provider_message)
        return {**scope_summary,"configured":True,"agent_mode":True,"rag_enabled":True,"adaptive_search":True,"dynamic_tool_selection":True,"research_rounds":research_rounds,"target_count":target_count,"target_met":verified_count>=target_count,"planning_degraded":bool(plan.get("planning_degraded")),"planning_recovered":bool(plan.get("planning_recovered")),"planning_error":plan.get("planning_error") or "","semantic_relevance":True,"framework":"discover-extract-candidates-verify-identity-join-evidence-promote-rag","intent":_deterministic_route_intent(q),"research_intent":_clean(plan.get("intent"),1200),"runtime_budget_seconds":runtime_budget,"budget_exhausted":time.monotonic()>=total_deadline,"contact_followup_source_count":len(contact_followups),"goal":plan.get("goal") or q,"query":q,"location":loc,"source":" + ".join(unique_tools+["semantic RAG"]),"tools_used":unique_tools,"live_source_count":len(live),"candidate_count":len(candidates),"joined_evidence_count":len(joined),"count":len(visible),"promoted_count":len(promoted),"verified_count":verified_count,"unverified_candidate_count":candidate_count_visible,"rejected_count":rejected_count,"verification_gate":True,"results":visible,"answer_summary":answer_summary,"provider_message":provider_message,"runtime_ms":runtime,"message":(f"Verification gate: {verified_count} Verified Leads, {candidate_count_visible} Candidates, {rejected_count} Rejected. Verified Lead requires direct source evidence for the requested claim.")}
    except Exception as exc:
        app.logger.exception("RESEARCH_AGENT_ERROR");return {"configured":True,"agent_mode":False,"query":q,"location":loc,"count":0,"results":[],"intent":_deterministic_route_intent(q),"runtime_budget_seconds":runtime_budget,"agent_error":type(exc).__name__,"message":"Search agent failed safely without fabricating results."}

@app.route("/api/smart-search",methods=["GET","POST"])
def smart_search():
    d=(request.get_json(silent=True) or {}) if request.method=="POST" else request.args;q=_clean(d.get("prompt") or d.get("query") or d.get("keyword"),500);loc=_clean(d.get("location"),200)
    if not q:return jsonify({"error":"Enter a search inquiry.","results":[],"count":0}),400
    result=_smart_search(q,loc)
    try: result["outreach_limit"]=max(0,int(d.get("outreach_limit") or 0))
    except (TypeError,ValueError): result["outreach_limit"]=0
    return jsonify(result)
@app.route("/api/test-smart-search",methods=["GET"])
def test_smart_search():
    # Deployment smoke route must finish well inside the platform request timeout.
    # It exercises the same fail-closed engine with a bounded verification budget.
    q=_clean(request.args.get("query") or "machine learning engineer jobs",500);loc=_clean(request.args.get("location") or "",200);return jsonify(_smart_search(q,loc,runtime_budget=12))
