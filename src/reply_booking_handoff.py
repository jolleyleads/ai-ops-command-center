"""Deterministic handoff from validated reply classification to calendar booking."""
from __future__ import annotations
from typing import Any, Callable, Dict
from src.reply_booking import validate_reply_classification, booking_readiness
from src.calendar_booking import execute_booking

def process_reply_to_booking(
    *,
    reply_text:Any,
    proposed_classification:Dict[str,Any],
    proposed_booking:Dict[str,Any],
    availability_func:Callable,
    event_create_func:Callable,
)->Dict[str,Any]:
    classification=validate_reply_classification(reply_text,proposed_classification)
    label=classification.get("classification")
    if not classification.get("validated"):
        return {"ok":False,"stage":"classification_blocked","classification":classification}
    if label=="not_interested":
        return {"ok":True,"stage":"not_interested","classification":classification,"terminal":True}
    if label=="question":
        return {"ok":True,"stage":"question","classification":classification,"booking_attempted":False}
    if label!="interested":
        return {"ok":True,"stage":"unclear","classification":classification,"booking_attempted":False}

    ready=booking_readiness(classification,proposed_booking)
    if not ready.get("booking_ready"):
        return {"ok":True,"stage":"interested","classification":classification,"booking_ready":ready,"booking_attempted":False}

    execution=execute_booking(ready,availability_func,event_create_func)
    return {
        "ok":execution.get("ok") is True,
        "stage":execution.get("stage"),
        "classification":classification,
        "booking_ready":ready,
        "booking_execution":execution,
        "booking_attempted":True,
    }
