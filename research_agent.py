import json
import os
from openai import OpenAI


def _json_object(text):
    text=(text or "").strip()
    if text.startswith("```"): text=text.split("\n",1)[-1].rsplit("```",1)[0].strip()
    try:
        value=json.loads(text); return value if isinstance(value,dict) else {}
    except (json.JSONDecodeError,TypeError):
        start=text.find("{")
        if start>=0:
            try:
                value,_=json.JSONDecoder().raw_decode(text[start:]); return value if isinstance(value,dict) else {}
            except json.JSONDecodeError: pass
        return {}

def _client(): return OpenAI(api_key=os.environ["OPENAI_API_KEY"],timeout=5,max_retries=0)
def _fallback_plan(query,location):
    base=" ".join(x for x in (query.strip(),location.strip()) if x)
    return {"goal":query,"intent":"web_research","queries":[base or query],"verification_criteria":["directly relevant source-backed evidence"],"sufficient":False,"gaps":[]}
def _fallback_evaluation(evidence,error=""):
    urls=[]
    for x in evidence:
        u=str(x.get("url") or "").strip()
        if u and u not in urls:urls.append(u)
    return {"sufficient":bool(evidence),"answer_summary":"","gaps":[],"followup_queries":[],"ranked_urls":urls[:10],"relevant_urls":urls[:10],"evaluation_degraded":True,"evaluation_error":error}

def plan_research(query,location="",prior_evidence=None):
    if not os.getenv("OPENAI_API_KEY"):return _fallback_plan(query,location)
    instructions="""Act as a general-purpose web research planner like a modern AI search assistant. Understand the user's natural-language goal semantically. Return ONLY compact JSON: goal, intent, queries, verification_criteria, sufficient, gaps. Produce 1-2 strong live-web queries that preserve the user's meaning and location when relevant. Never hard-code industries, professions, cities, or special cases. Never invent facts or URLs."""
    try:
        response=_client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"),instructions=instructions,input=json.dumps({"query":query,"location":location,"prior_evidence":prior_evidence or []},ensure_ascii=False),max_output_tokens=350)
        parsed=_json_object(response.output_text); return parsed if parsed.get("queries") else _fallback_plan(query,location)
    except Exception:return _fallback_plan(query,location)

def evaluate_research(query,location,evidence):
    if not evidence:return _fallback_evaluation([])
    if not os.getenv("OPENAI_API_KEY"):return _fallback_evaluation(evidence,"OPENAI_API_KEY unavailable")
    compact=[]
    for item in evidence[:10]:compact.append({"title":str(item.get("title") or "")[:220],"url":str(item.get("url") or "")[:600],"text":str(item.get("page_text") or item.get("subtitle") or "")[:900],"memory":bool(item.get("rag_retrieved"))})
    instructions="""Act as the semantic evidence judge for a general-purpose AI web search engine. Decide which supplied sources actually help answer the user's exact request. Meaning matters more than literal keyword overlap. Reject stale or topically unrelated RAG memory. Never invent evidence or URLs. Return ONLY compact JSON with: sufficient, answer_summary, gaps, followup_queries, ranked_urls, relevant_urls. relevant_urls and ranked_urls may contain ONLY supplied URLs. Use at most 2 followup_queries. If evidence is weak, say insufficient and propose better searches."""
    try:
        response=_client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"),instructions=instructions,input=json.dumps({"query":query,"location":location,"evidence":compact},ensure_ascii=False),max_output_tokens=450)
        parsed=_json_object(response.output_text); return parsed if parsed else _fallback_evaluation(evidence,"invalid evaluator response")
    except Exception as exc:return _fallback_evaluation(evidence,type(exc).__name__)
