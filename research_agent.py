import json
import os
from openai import OpenAI

TOOLS=("web_search","public_records","business_search","job_search")

def _json_object(text):
    text=(text or "").strip()
    if text.startswith("```"): text=text.split("\n",1)[-1].rsplit("```",1)[0].strip()
    try:
        value=json.loads(text);return value if isinstance(value,dict) else {}
    except (json.JSONDecodeError,TypeError):
        start=text.find("{")
        if start>=0:
            try:
                value,_=json.JSONDecoder().raw_decode(text[start:]);return value if isinstance(value,dict) else {}
            except json.JSONDecodeError:pass
        return {}

def _client():return OpenAI(api_key=os.environ["OPENAI_API_KEY"],timeout=5,max_retries=0)
def _fallback_plan(query,location):
    base=" ".join(x for x in (query.strip(),location.strip()) if x)
    return {"goal":query,"intent":"web_research","queries":[base or query],"tool_calls":[{"tool":"web_search","query":base or query,"location":location}],"verification_criteria":["directly relevant source-backed evidence"],"sufficient":False,"gaps":[]}
def _normalize_plan(value,query,location):
    if not isinstance(value,dict):return _fallback_plan(query,location)
    calls=[]
    for c in value.get("tool_calls") or []:
        if not isinstance(c,dict) or c.get("tool") not in TOOLS:continue
        q=str(c.get("query") or "").strip()[:700]
        if q:calls.append({"tool":c["tool"],"query":q,"location":str(c.get("location") or location).strip()[:200]})
    if not calls:
        for q in (value.get("queries") or [])[:2]:
            if str(q).strip():calls.append({"tool":"web_search","query":str(q).strip()[:700],"location":location})
    if not calls:return _fallback_plan(query,location)
    value["tool_calls"]=calls[:3];value["queries"]=[c["query"] for c in calls[:3]];return value
def _fallback_evaluation(evidence,error=""):
    urls=[]
    for x in evidence:
        u=str(x.get("url") or "").strip()
        if u and u not in urls:urls.append(u)
    return {"sufficient":bool(evidence),"answer_summary":"","gaps":[],"followup_queries":[],"followup_tool_calls":[],"ranked_urls":urls[:10],"relevant_urls":urls[:10],"evaluation_degraded":True,"evaluation_error":error}

def plan_research(query,location="",prior_evidence=None):
    if not os.getenv("OPENAI_API_KEY"):return _fallback_plan(query,location)
    instructions="""Act as a general-purpose AI research orchestrator. Understand the request semantically and choose tools dynamically. Available tools: web_search for general live web discovery; public_records for permits, licenses, filings, government/public records and record-oriented discovery; business_search for identifying/verifying businesses and business contact/location facts; job_search for job listings. Tools are capabilities, not hard-coded industries or locations. A request may use more than one tool. Return ONLY compact JSON with goal, intent, queries, tool_calls, verification_criteria, sufficient, gaps. Each tool_call is {tool,query,location}. Use at most 3 tool calls. Keep web_search available for every domain and use specialized tools when they materially improve evidence. Never invent facts, URLs, tool names, industries, or locations."""
    try:
        response=_client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"),instructions=instructions,input=json.dumps({"query":query,"location":location,"prior_evidence":prior_evidence or []},ensure_ascii=False),max_output_tokens=450)
        return _normalize_plan(_json_object(response.output_text),query,location)
    except Exception:return _fallback_plan(query,location)

def evaluate_research(query,location,evidence):
    if not evidence:return _fallback_evaluation([])
    if not os.getenv("OPENAI_API_KEY"):return _fallback_evaluation(evidence,"OPENAI_API_KEY unavailable")
    compact=[]
    for item in evidence[:12]:compact.append({"title":str(item.get("title") or "")[:220],"url":str(item.get("url") or "")[:600],"text":str(item.get("page_text") or item.get("subtitle") or "")[:900],"source":str(item.get("source") or "")[:100],"tool":str(item.get("research_tool") or "")[:50],"memory":bool(item.get("rag_retrieved"))})
    instructions="""Act as the semantic evidence judge for a general-purpose AI research engine. Decide which supplied sources actually answer the exact request. Meaning matters more than literal keyword overlap. Reject stale/unrelated RAG memory. Never invent evidence or URLs. Return ONLY compact JSON with sufficient, answer_summary, gaps, followup_queries, followup_tool_calls, ranked_urls, relevant_urls. URLs may ONLY be supplied URLs. followup_tool_calls may use only web_search, public_records, business_search, job_search and must be {tool,query,location}; use at most 2. Choose a specialized tool only when it helps close a real evidence gap."""
    try:
        response=_client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"),instructions=instructions,input=json.dumps({"query":query,"location":location,"evidence":compact},ensure_ascii=False),max_output_tokens=550)
        parsed=_json_object(response.output_text)
        if not parsed:return _fallback_evaluation(evidence,"invalid evaluator response")
        parsed["followup_tool_calls"]=[c for c in (parsed.get("followup_tool_calls") or []) if isinstance(c,dict) and c.get("tool") in TOOLS][:2]
        return parsed
    except Exception as exc:return _fallback_evaluation(evidence,type(exc).__name__)
