"""DOE orchestrator: AI judges; deterministic code executes."""
from __future__ import annotations
import json
from typing import Any, Dict
from .execution import verify_lead
from .services import run_ai

ALLOWED_ACTIONS = {"needs_verification", "enrich", "qualify", "prepare_outreach", "stop"}

def orchestrate(input_data: Dict[str, Any]) -> Dict[str, Any]:
    lead = input_data.get("lead") or input_data.get("data") or {}
    verification = verify_lead(lead)
    trace = [{"step": "verify_lead", "ok": verification["verified"], "reasons": verification["reasons"]}]
    if not verification["verified"]:
        return {"status": "needs_verification", "action": "needs_verification", "lead": verification["lead"], "trace": trace}

    prompt = (
        "Choose exactly one next action for this verified prospect: "
        "enrich, qualify, prepare_outreach, or stop. "
        "Return JSON only with keys action and reason. Never invent facts.\n\n"
        + json.dumps(verification["lead"], sort_keys=True)
    )
    ai = run_ai(prompt, instructions="You route a lead workflow. Use only supplied evidence. Return JSON only.")
    if not ai.get("ok"):
        trace.append({"step": "orchestrate", "ok": False, "error": ai.get("error")})
        return {"status": "error", "action": "stop", "error": ai.get("error"), "trace": trace}

    try:
        decision = json.loads(ai["output"])
    except (TypeError, json.JSONDecodeError):
        trace.append({"step": "orchestrate", "ok": False, "error": "invalid_ai_json"})
        return {"status": "error", "action": "stop", "error": "AI returned invalid JSON", "trace": trace}

    action = decision.get("action")
    if action not in ALLOWED_ACTIONS:
        trace.append({"step": "orchestrate", "ok": False, "error": "invalid_action"})
        return {"status": "error", "action": "stop", "error": "AI selected an unsupported action", "trace": trace}

    trace.append({"step": "orchestrate", "ok": True, "action": action})
    return {"status": "ready", "action": action, "reason": decision.get("reason", ""), "lead": verification["lead"], "trace": trace}
