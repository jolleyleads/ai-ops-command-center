"""Deterministic durable command/outbox state machine for external side effects.

Provider execution is deliberately outside the transaction that creates a command.
A command must exist durably before a worker may execute it. Leases prevent two
workers from owning the same command; ambiguous provider outcomes become uncertain
and require reconciliation, never blind retry.
"""
from __future__ import annotations
from datetime import datetime, timedelta
import hashlib, json, uuid
from typing import Any, Callable, Dict

TERMINAL={"succeeded","reconciled","failed"}
LIVE={"pending","executing","uncertain"}
ALL=TERMINAL|LIVE


def canonical(v:Any)->str:
    return json.dumps(v,sort_keys=True,separators=(",",":"),default=str)


def command_key(kind:str,lead_id:int,payload:Dict[str,Any])->str:
    return hashlib.sha256(f"{kind}|{lead_id}|{canonical(payload)}".encode()).hexdigest()


def lease_token()->str:
    return uuid.uuid4().hex


def lease_expired(expires_at:datetime|None,now:datetime)->bool:
    return expires_at is None or expires_at<=now


def can_claim(status:str,expires_at:datetime|None,now:datetime)->bool:
    if status=="pending":return True
    # An expired executing command is NOT safe to re-execute: provider may have
    # succeeded before worker death. It must enter uncertainty/reconciliation.
    return False


def provider_outcome(result:Dict[str,Any]|None,exc:BaseException|None=None)->str:
    if exc is not None:return "uncertain"
    if not isinstance(result,dict):return "uncertain"
    if result.get("ok") is True:return "succeeded"
    # A provider call was attempted. Unless the adapter explicitly proves no side
    # effect occurred, failure is ambiguous and therefore uncertain.
    if result.get("definitely_not_executed") is True:return "failed"
    return "uncertain"


def reconciliation_outcome(found:bool,proof:Dict[str,Any]|None=None)->str:
    return "reconciled" if found and isinstance(proof,dict) and bool(proof) else "failed"
