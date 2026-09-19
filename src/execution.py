"""Deterministic execution primitives for AI Ops."""
from __future__ import annotations
import hashlib
import re
from typing import Any, Dict

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")

def normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())

def normalize_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(lead, dict):
        raise TypeError("lead must be a dictionary")
    out = dict(lead)
    for key in ("company_name", "contact_name", "city", "state", "email", "phone", "website"):
        if key in out:
            out[key] = normalize_text(out[key])
    if out.get("email"):
        out["email"] = out["email"].lower()
    return out

def lead_fingerprint(lead: Dict[str, Any]) -> str:
    normalized = normalize_lead(lead)
    identity = "|".join([
        normalized.get("company_name", "").lower(),
        normalized.get("website", "").lower(),
        normalized.get("email", "").lower(),
        normalized.get("phone", ""),
    ])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()

def verify_lead(lead: Dict[str, Any]) -> Dict[str, Any]:
    lead = normalize_lead(lead)
    reasons = []
    if not lead.get("company_name"):
        reasons.append("missing company_name")
    if lead.get("email") and not EMAIL_RE.match(lead["email"]):
        reasons.append("invalid email format")
    evidence = lead.get("evidence") or lead.get("sources") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    if not evidence:
        reasons.append("missing source evidence")
    return {
        "verified": not reasons,
        "reasons": reasons,
        "lead": lead,
        "fingerprint": lead_fingerprint(lead),
    }
