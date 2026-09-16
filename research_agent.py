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

def _client():
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"],timeout=4.5,max_retries=0)

def _fallback_plan(query,location):
    base=" ".join(x for x in (query.strip(),location.strip()) if x)
    return {"goal":query,"intent":"web_research","concepts":[],"queries":[base or query],"verification_criteria":["source-backed evidence relevant to the user's inquiry"],"sufficient":False,"gaps":[]}

def _fallback_evaluation(evidence,error=""):
    urls=[]
    for x in evidence:
        u=str(x.get("url") or "").strip()
        if u and u not in urls:urls.append(u)
    return {"sufficient":bool(evidence),"answer_summary":"AI evaluation unavailable; returning gathered source-backed evidence without discarding it." if evidence else "","gaps":[],"followup_queries":[],"ranked_urls":urls[:10],"evaluation_degraded":True,"evaluation_error":error}

def plan_research(query,location="",prior_evidence=None):
    if not os.getenv("OPENAI_API_KEY"):return _fallback_plan(query,location)
    evidence=(prior_evidence or [])[-8:]
    prompt={"query":query,"location":location,"prior_evidence":evidence}
    instructions="""Plan one fast web-research pass for an arbitrary user inquiry. Return ONLY one compact valid JSON object with keys: goal, intent, concepts, queries, verification_criteria, sufficient, gaps. queries must contain 1-3 concise targeted web searches. Do not hard-code an industry or location; preserve the supplied location when relevant. Use semantic alternatives. Never invent evidence. Keep the entire JSON response short."""
    try:
        response=_client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"),instructions=instructions,input=json.dumps(prompt,ensure_ascii=False),max_output_tokens=450)
        parsed=_json_object(response.output_text)
        return parsed if parsed.get("queries") else _fallback_plan(query,location)
    except Exception:
        return _fallback_plan(query,location)

def evaluate_research(query,location,evidence):
    if not evidence:return _fallback_evaluation([])
    if not os.getenv("OPENAI_API_KEY"):return _fallback_evaluation(evidence,"OPENAI_API_KEY unavailable")
    compact=[]
    for item in evidence[:8]:compact.append({"title":str(item.get("title") or "")[:200],"url":str(item.get("url") or "")[:600],"text":str(item.get("page_text") or item.get("subtitle") or "")[:700]})
    instructions="""Evaluate supplied research evidence quickly. Return ONLY compact JSON with keys: sufficient, answer_summary, gaps, followup_queries, ranked_urls. Never invent evidence. Use only supplied URLs. At most 2 followup queries. Keep it very short."""
    try:
        response=_client().responses.create(model=os.getenv("OPENAI_MODEL","gpt-5.6-luna"),instructions=instructions,input=json.dumps({"query":query,"location":location,"evidence":compact},ensure_ascii=False),max_output_tokens=400)
        parsed=_json_object(response.output_text)
        return parsed if parsed else _fallback_evaluation(evidence,"invalid evaluator response")
    except Exception as exc:
        return _fallback_evaluation(evidence,type(exc).__name__)
