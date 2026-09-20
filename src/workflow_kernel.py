"""Deterministic workflow kernel for the AI Ops Command Center.

The LLM may propose a route. Only this module may authorize state transitions.
External side effects remain execution functions and must report evidence/results
before workflow state advances.
"""
from __future__ import annotations
from typing import Any, Dict, Iterable

STAGES = (
    "discovered", "verified", "enriched", "qualified", "outreach_ready",
    "contacted", "followup_due", "responded", "booking_ready", "booked",
    "crm_synced", "closed",
)

ALLOWED_TRANSITIONS = {
    "discovered": {"verified", "closed"},
    "verified": {"enriched", "closed"},
    "enriched": {"qualified", "closed"},
    "qualified": {"outreach_ready", "closed"},
    "outreach_ready": {"contacted", "closed"},
    "contacted": {"followup_due", "responded", "closed"},
    "followup_due": {"contacted", "responded", "closed"},
    "responded": {"booking_ready", "closed"},
    "booking_ready": {"booked", "closed"},
    "booked": {"crm_synced", "closed"},
    "crm_synced": {"closed"},
    "closed": set(),
}

REQUIRED_PROOF = {
    "verified": ("evidence",),
    "enriched": ("enrichment",),
    "qualified": ("qualification",),
    "outreach_ready": ("approved_message",),
    "contacted": ("send_receipt",),
    "followup_due": ("followup_schedule",),
    "responded": ("reply_evidence",),
    "booking_ready": ("booking_intent",),
    "booked": ("booking_receipt",),
    "crm_synced": ("crm_receipt",),
}


def _present(value: Any) -> bool:
    if value is None or value is False: return False
    if isinstance(value, str): return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)): return bool(value)
    return True


def validate_transition(current: str, target: str, state: Dict[str, Any]) -> Dict[str, Any]:
    """Fail closed. An LLM suggestion can never bypass deterministic requirements."""
    reasons = []
    if current not in ALLOWED_TRANSITIONS:
        reasons.append("unknown_current_stage")
    elif target not in ALLOWED_TRANSITIONS[current]:
        reasons.append("transition_not_allowed")
    for field in REQUIRED_PROOF.get(target, ()):
        if not _present(state.get(field)):
            reasons.append(f"missing_{field}")
    return {"allowed": not reasons, "reasons": reasons, "from": current, "to": target}


def apply_transition(state: Dict[str, Any], target: str) -> Dict[str, Any]:
    current = str(state.get("stage") or "discovered")
    verdict = validate_transition(current, target, state)
    out = dict(state)
    history = list(out.get("history") or [])
    history.append({"from": current, "to": target, "allowed": verdict["allowed"], "reasons": verdict["reasons"]})
    out["history"] = history
    if verdict["allowed"]:
        out["stage"] = target
    return {"ok": verdict["allowed"], "state": out, "gate": verdict}


def deterministic_next_actions(stage: str) -> Iterable[str]:
    return tuple(sorted(ALLOWED_TRANSITIONS.get(stage, set())))
