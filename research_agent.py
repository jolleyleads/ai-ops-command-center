import json
import os

from openai import OpenAI


def _json_object(text):
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def plan_research(query, location="", prior_evidence=None):
    """Interpret arbitrary research intent and generate targeted discovery queries."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    evidence = (prior_evidence or [])[-12:]
    prompt = {
        "query": query,
        "location": location,
        "prior_evidence": evidence,
        "task": "Plan the next web-research pass. Do not assume a topic, industry, or geography not stated by the user.",
    }
    instructions = """You are the planning brain for a general-purpose research agent. Return ONLY valid JSON with keys: goal (string), intent (short free-form string), concepts (array of strings), queries (array of 1-4 targeted web search strings), verification_criteria (array of strings), sufficient (boolean), gaps (array of strings). Use semantic alternatives and source-type clues where useful. Preserve the user's location if supplied, but never hard-code any city or industry. If prior evidence already answers the goal with credible direct evidence, set sufficient true. Otherwise produce focused follow-up queries that address evidence gaps. Keep queries concise."""
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=json.dumps(prompt, ensure_ascii=False),
        max_output_tokens=900,
    )
    return _json_object(response.output_text)


def evaluate_research(query, location, evidence):
    """Rank evidence and decide whether another research pass is needed."""
    if not os.getenv("OPENAI_API_KEY"):
        return None
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
    compact = []
    for item in evidence[-20:]:
        compact.append({
            "title": str(item.get("title") or "")[:300],
            "url": str(item.get("url") or "")[:1200],
            "text": str(item.get("page_text") or item.get("subtitle") or "")[:2500],
        })
    instructions = """You evaluate web research evidence. Return ONLY valid JSON with keys: sufficient (boolean), answer_summary (string), gaps (array of strings), followup_queries (array of 0-3 strings), ranked_urls (array of URLs best supporting the answer). Be conservative: search snippets alone are weaker than inspected page text. Never invent evidence. If evidence is incomplete, make follow-up queries meaningfully different from searches already represented."""
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=json.dumps({"query": query, "location": location, "evidence": compact}, ensure_ascii=False),
        max_output_tokens=1000,
    )
    return _json_object(response.output_text)
