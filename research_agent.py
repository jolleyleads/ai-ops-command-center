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

def _client():return OpenAI(api_key=os.environ["OPENAI_API_KEY"],timeout=8,max_retries=0)
def _fallback_plan(query,location,error=""):
    base=" ".join(x for x in (query.strip(),location.strip()) if x)
    return {"goal":query,"intent":"web_research","queries":[base or query],"tool_calls":[{"tool":"web_search","query":base or query,"location":location}],"verification_criteria":["directly relevant source-backed evidence"],"sufficient":False,"gaps":[],"planning_degraded":True,"planning_error":error}
def _normalize_plan(value,query,location):
    if not isinstance(value,dict):return _fallback_plan(query,location,"invalid planner payload")
    calls=[]
    for c in value.get("tool_calls") or []:
        if not isinstance(c,dict) or c.get("tool") not in TOOLS:continue
        q=str(c.get("query") or "").strip()[:700]
        if q:calls.append({"tool":c["tool"],"query":q,"location":str(c.get("location") or location).strip()[:200]})
    if not calls:return _fallback_plan(query,location,"planner returned no valid tool calls")
    value["tool_calls"]=calls[:3];value["queries"]=[c["query"] for c in calls[:3]];value["planning_degraded"]=False;return value
def _fallback_evaluation(evidence,error=""):
    urls=[]
    for x in evidence:
        u=str(x.get("url") or "").strip()
        if u and u not in urls:urls.append(u)
    return {"sufficient":False,"answer_summary":"","gaps":["semantic entity/evidence validation unavailable"],"followup_tool_calls":[],"ranked_urls":[],"relevant_urls":[],"verified_results":[],"evaluation_degraded":True,"evaluation_error":error}

def plan_research(query,location="",prior_evidence=None):
    if not os.getenv("OPENAI_API_KEY"):return _fallback_plan(query,location,"OPENAI_API_KEY unavailable")
    instructions="""You are the tool-selection controller for a general-purpose AI search engine. Select retrieval capabilities by the TYPE OF EVIDENCE the user's request requires, not by industry keywords.

Available capabilities:
- web_search: broad live-web discovery and current general information.
- public_records: authoritative/public record evidence such as permits, licenses, filings, inspections, government datasets, court/agency records.
- business_search: business identity, location, website, phone and place verification/enrichment.
- job_search: current employment listings.

Rules:
1. web_search remains the broad discovery tool, but it is NOT a substitute for a specialized evidence source when the user explicitly requires that evidence type.
2. If the answer requires public/government record evidence, include public_records.
3. If it requires current job-listing evidence, include job_search.
4. If named businesses must be verified/enriched, business_search may accompany the primary evidence tool.
5. Multiple tools are normal. Choose up to 3 and preserve the user's location.
6. Do not hard-code an industry, profession, city, state, or example query.
7. Never invent facts, URLs, or tool names.

Return ONLY compact JSON:
{"goal":"...","intent":"...","tool_calls":[{"tool":"...","query":"...","location":"..."}],"verification_criteria":["..."],"sufficient":false,"gaps":[]}"""
    try:
        response=_client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"),instructions=instructions,input=json.dumps({"query":query,"location":location,"prior_evidence":prior_evidence or []},ensure_ascii=False),max_output_tokens=500)
        return _normalize_plan(_json_object(response.output_text),query,location)
    except Exception as exc:return _fallback_plan(query,location,type(exc).__name__)

def evaluate_research(query,location,evidence):
    if not evidence:return _fallback_evaluation([])
    if not os.getenv("OPENAI_API_KEY"):return _fallback_evaluation(evidence,"OPENAI_API_KEY unavailable")
    compact=[]
    for item in evidence[:12]:compact.append({"title":str(item.get("title") or "")[:220],"url":str(item.get("url") or "")[:600],"text":str(item.get("page_text") or item.get("subtitle") or "")[:900],"source":str(item.get("source") or "")[:100],"tool":str(item.get("research_tool") or "")[:50],"type":str(item.get("type") or "")[:50],"phone":str(item.get("phone") or "")[:80],"website":str(item.get("website") or "")[:600],"memory":bool(item.get("rag_retrieved"))})
    instructions="""Judge evidence for a general-purpose AI research engine. Keep only sources that semantically support the exact request. Reject stale/unrelated RAG memory. Also audit evidence coverage: if the request requires a specialized evidence type and current evidence does not contain it, mark insufficient and request the appropriate capability. Never invent evidence or URLs.

Available follow-up capabilities: web_search, public_records, business_search, job_search.
Return ONLY compact JSON with sufficient, answer_summary, gaps, followup_tool_calls, ranked_urls, relevant_urls. URLs may ONLY be supplied URLs. followup_tool_calls are {"tool":"...","query":"...","location":"..."} and use at most 2."""
    try:
        response=_client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"),instructions=instructions,input=json.dumps({"query":query,"location":location,"evidence":compact},ensure_ascii=False),max_output_tokens=550)
        parsed=_json_object(response.output_text)
        if not parsed:return _fallback_evaluation(evidence,"invalid evaluator response")
        parsed["followup_tool_calls"]=[c for c in (parsed.get("followup_tool_calls") or []) if isinstance(c,dict) and c.get("tool") in TOOLS][:2]
        return parsed
    except Exception as exc:return _fallback_evaluation(evidence,type(exc).__name__)
