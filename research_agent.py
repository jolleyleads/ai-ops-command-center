import json
import os

from openai import OpenAI


def _json_object(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def _client():
    # Hard request bounds keep the synchronous web endpoint inside Gunicorn's 30s limit.
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], timeout=7.0, max_retries=0)


def plan_research(query, location="", prior_evidence=None):
    if not os.getenv("OPENAI_API_KEY"):
        return None
    evidence = (prior_evidence or [])[-8:]
    prompt = {"query": query, "location": location, "prior_evidence": evidence}
    instructions = """Plan one fast web-research pass for an arbitrary user inquiry. Return ONLY valid JSON with keys: goal, intent, concepts, queries, verification_criteria, sufficient, gaps. queries must contain 1-3 concise targeted web searches. Do not hard-code an industry or location; preserve the supplied location when relevant. Use semantic alternatives. Never invent evidence."""
    response = _client().responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        instructions=instructions,
        input=json.dumps(prompt, ensure_ascii=False),
        max_output_tokens=500,
    )
    return _json_object(response.output_text)


def evaluate_research(query, location, evidence):
    if not os.getenv("OPENAI_API_KEY"):
        return None
    compact=[]
    for item in evidence[:10]:
        compact.append({"title":str(item.get("title") or "")[:250],"url":str(item.get("url") or "")[:800],"text":str(item.get("page_text") or item.get("subtitle") or "")[:1000]})
    instructions = """Evaluate supplied research evidence quickly. Return ONLY valid JSON with keys: sufficient, answer_summary, gaps, followup_queries, ranked_urls. Never invent evidence. followup_queries may contain at most 2 concise searches. Direct page text is stronger than snippets."""
    response = _client().responses.create(
        model=os.getenv("OPENAI_MODEL", "gpt-5.6-luna"),
        instructions=instructions,
        input=json.dumps({"query":query,"location":location,"evidence":compact},ensure_ascii=False),
        max_output_tokens=500,
    )
    return _json_object(response.output_text)
