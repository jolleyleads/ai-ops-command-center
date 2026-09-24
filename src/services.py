"""Service layer for AI Ops Command Center."""

import json
import os
import re
from typing import Any, Dict

from openai import OpenAI

_URL_RE = re.compile(r"https?://[^\s)>\]\}\"']+", re.I)


def _structured_draft_gate(output: str, prompt: str) -> Dict[str, Any]:
    """Validate outreach-like structured JSON before it leaves the AI service.

    This does not replace the production outreach gate. It prevents a stochastic
    model response that is obviously malformed/oversized or introduces a URL not
    present in the source prompt from becoming the only draft attempt.
    """
    text = str(output or "").strip()
    try:
        parsed = json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            return {"ok": False, "reason": "INVALID_JSON"}
        try:
            parsed = json.loads(text[start:end + 1])
        except Exception:
            return {"ok": False, "reason": "INVALID_JSON"}
    if not isinstance(parsed, dict) or "subject" not in parsed or "body" not in parsed:
        return {"ok": True, "structured_outreach": False}
    subject = str(parsed.get("subject") or "").strip()
    body = str(parsed.get("body") or "").strip()
    if not subject or not body:
        return {"ok": False, "reason": "MISSING_SUBJECT_OR_BODY"}
    if len(subject) > 160:
        return {"ok": False, "reason": "SUBJECT_TOO_LONG"}
    if len(body) > 5000:
        return {"ok": False, "reason": "BODY_TOO_LONG"}
    prompt_urls = {u.rstrip(".,;:!?") for u in _URL_RE.findall(prompt or "")}
    for url in _URL_RE.findall(body):
        if url.rstrip(".,;:!?") not in prompt_urls:
            return {"ok": False, "reason": "UNSUPPORTED_URL_IN_MESSAGE"}
    return {"ok": True, "structured_outreach": True}


def run_ai(
    prompt: str,
    instructions: str = "",
    model: str = "",
) -> Dict[str, Any]:
    """Send a workflow task to OpenAI and return a bounded validated result."""

    api_key = os.getenv("OPENAI_API_KEY")

    if not api_key:
        return {
            "ok": False,
            "error": "OPENAI_API_KEY is not configured",
        }

    client = OpenAI(api_key=api_key)

    selected_model = model or os.getenv(
        "OPENAI_MODEL",
        "gpt-4.1-mini",
    )

    last_reason = ""
    try:
        # Bounded regeneration handles stochastic structured-draft violations.
        # The downstream deterministic outreach gate still makes the final decision.
        for attempt in range(3):
            retry_instruction = ""
            if attempt and last_reason:
                retry_instruction = (
                    "\nPrevious output was rejected by deterministic validation: "
                    f"{last_reason}. Correct that issue; do not weaken or bypass the rule."
                )
            response = client.responses.create(
                model=selected_model,
                instructions=(instructions or (
                    "You are the AI processing engine inside an "
                    "automation workflow platform."
                )) + retry_instruction,
                input=prompt,
            )
            output = response.output_text
            gate = _structured_draft_gate(output, prompt)
            if gate.get("ok"):
                return {
                    "ok": True,
                    "output": output,
                    "model": selected_model,
                    "generation_attempts": attempt + 1,
                }
            last_reason = str(gate.get("reason") or "STRUCTURED_OUTPUT_REJECTED")
        return {
            "ok": False,
            "error": f"AI output failed deterministic validation after 3 attempts: {last_reason}",
        }

    except Exception as exc:
        return {
            "ok": False,
            "error": str(exc),
        }


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process data sent to the service layer."""

    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dictionary")

    return {
        "status": "processed",
        "input": input_data,
    }
