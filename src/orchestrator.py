"""DOE orchestrator: LLM proposes; deterministic code authorizes and executes."""
from __future__ import annotations
import json
from typing import Any, Dict
from .execution import verify_lead
from .services import run_ai
from .workflow_kernel import deterministic_next_actions, apply_transition

def orchestrate(input_data: Dict[str, Any]) -> Dict[str, Any]:
    lead = input_data.get("lead") or input_data.get("data") or {}
    state = dict(input_data.get("state") or {})
    state.setdefault("stage", "discovered")
    trace = []

    # Verification is deterministic and must complete before the LLM can route onward.
    if state["stage"] == "discovered":
        verification = verify_lead(lead)
        trace.append({"step":"verify_lead","ok":verification["verified"],"reasons":verification["reasons"]})
        if not verification["verified"]:
            return {"status":"needs_verification","action":"stop","lead":verification["lead"],"state":state,"trace":trace}
        lead = verification["lead"]\n        state["evidence"] = lead.get("evidence") or lead.get("sources")
        moved = apply_transition(state, "verified")
        state = moved["state"]
        if not moved["ok"]:
            return {"status":"blocked","action":"stop","state":state,"trace":trace+[{"step":"transition_gate","gate":moved["gate"]}]}

    allowed = list(deterministic_next_actions(state["stage"]))
    routable = [x for x in allowed if x != "closed"]
    if not routable:
        return {"status":"completed","action":"stop","state":state,"trace":trace}

    prompt = (
        "Choose one proposed next workflow stage from the supplied allowed list. "
        "You are routing only: do not claim the operation happened and do not invent evidence. "
        "Return strict JSON with keys target and reason.\n"
        + json.dumps({"stage":state["stage"],"allowed_targets":routable,"lead":lead}, sort_keys=True)
    )
    ai = run_ai(prompt, instructions="Reason and route only. Deterministic software owns execution, validation, side effects, and state.")
    if not ai.get("ok"):
        return {"status":"routing_unavailable","action":"stop","state":state,"trace":trace+[{"step":"route","ok":False,"error":ai.get("error")}]}
    try:
        decision=json.loads(ai["output"])
    except (TypeError,json.JSONDecodeError):
        return {"status":"routing_error","action":"stop","state":state,"trace":trace+[{"step":"route","ok":False,"error":"invalid_ai_json"}]}

    target=decision.get("target")
    if target not in routable:
        return {"status":"routing_error","action":"stop","state":state,"trace":trace+[{"step":"route","ok":False,"error":"unsupported_target"}]}

    # Do NOT apply the transition here. The corresponding deterministic worker must
    # execute first, attach its receipt/evidence, then call apply_transition.
    trace.append({"step":"route","ok":True,"proposed_target":target})
    return {"status":"ready_for_execution","action":target,"reason":decision.get("reason",""),"state":state,"lead":lead,"trace":trace}
