"""Process-local circuit breakers for permanently unavailable search providers.

A provider that reports a permanent configuration/billing failure is tried once per
worker, then skipped for the rest of that worker lifetime. Healthy providers (Exa,
Places, etc.) continue normally. This does not alter verification or qualification.
"""
import threading

import smart_search
import universal_app

_lock = threading.Lock()
_open = {}


def _is_permanent(message, provider):
    text = str(message or "").lower()
    if provider == "openai_web":
        return ("http 429" in text and ("no credits" in text or "billing" in text or "quota" in text)) or "insufficient_quota" in text
    if provider == "google_public_records":
        return "http 403" in text and ("does not have" in text or "access" in text or "disabled" in text or "forbidden" in text)
    return False


def _state(provider):
    with _lock:
        return _open.get(provider)


def _trip(provider, message):
    with _lock:
        _open[provider] = str(message or "")[:500]


_original_web_search = smart_search._web_search
_original_public_records = smart_search._search_public_records
_original_universal_public_records = universal_app._search_public_records


def _web_search(query, location=""):
    reason = _state("openai_web")
    if reason:
        return {"results": [], "message": "OpenAI Web Search skipped: provider circuit open after permanent billing/quota failure."}
    payload = _original_web_search(query, location)
    message = payload.get("message", "") if isinstance(payload, dict) else ""
    if _is_permanent(message, "openai_web"):
        _trip("openai_web", message)
    return payload


def _public_records(query, location=""):
    reason = _state("google_public_records")
    if reason:
        return {"configured": False, "source": "Google Programmable Search", "message": "Google Programmable Search skipped: provider circuit open after permanent access/configuration failure.", "results": []}
    payload = _original_universal_public_records(query, location)
    message = payload.get("message", "") if isinstance(payload, dict) else ""
    if _is_permanent(message, "google_public_records"):
        _trip("google_public_records", message)
    return payload


# smart_search imported _search_public_records by value, so patch both references.
smart_search._web_search = _web_search
smart_search._search_public_records = _public_records
universal_app._search_public_records = _public_records
