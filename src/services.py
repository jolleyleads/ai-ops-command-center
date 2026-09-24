"""Service layer for AI Ops Command Center."""

import json
import os
import re
from typing import Any, Dict

from openai import OpenAI

_URL_RE = re.compile(r"https?://[^\s)>\]\}\"']+", re.I)


def _structured_draft_gate(output: str, prompt: str, instructions: str) -> Dict[str, Any]:
    """Validate structured outreach JSON before it leaves the AI service."""
    instruction_text = str(instructions or "").lower()
    is_outreach_json = "subject" in instruction_text and "body" in instruction_text and "json" in instruction_text
    if not is_outreach_json:
        return {"ok": True, "structured_outreach": False}
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
    if not isinstance(parsed, dict):
        return {"ok": False, "reason": "INVALID_JSON_OBJECT"}
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
    """Send a workflow task to OpenAI and return the result."""

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"ok": False, "error": "OPENAI_API_KEY is not configured"}

    client = OpenAI(api_key=api_key)
    selected_model = model or os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
    last_reason = ""
    try:
        # Only structured outreach drafts get bounded regeneration. Other AI calls
        # retain their original single-call behavior.
        structured = "subject" in (instructions or "").lower() and "body" in (instructions or "").lower() and "json" in (instructions or "").lower()
        max_attempts = 3 if structured else 1
        for attempt in range(max_attempts):
            retry_instruction = ""
            if attempt and last_reason:
                retry_instruction = (
                    "\nPrevious output was rejected by deterministic validation: "
                    f"{last_reason}. Correct that issue; do not weaken or bypass the rule."
                )
            response = client.responses.create(
                model=selected_model,
                instructions=(instructions or (
                    "You are the AI processing engine inside an automation workflow platform."
                )) + retry_instruction,
                input=prompt,
            )
            output = response.output_text
            gate = _structured_draft_gate(output, prompt, instructions)
            if gate.get("ok"):
                return {"ok": True, "output": output, "model": selected_model, "generation_attempts": attempt + 1}
            last_reason = str(gate.get("reason") or "STRUCTURED_OUTPUT_REJECTED")
        return {"ok": False, "error": f"AI output failed deterministic validation after {max_attempts} attempts: {last_reason}"}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def run(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """Process data sent to the service layer."""
    if not isinstance(input_data, dict):
        raise TypeError("input_data must be a dictionary")
    return {"status": "processed", "input": input_data}
