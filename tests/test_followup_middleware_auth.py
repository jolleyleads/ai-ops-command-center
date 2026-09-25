import importlib

import pytest


def _client(monkeypatch):
    monkeypatch.setenv("OUTREACH_CRON_TOKEN", "test-secret")
    import smart_search_outreach_hook as hook
    importlib.reload(hook)
    return hook.app.test_client()


def test_followup_middleware_accepts_cron_header(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/api/outreach/process-followups",
        headers={"X-Outreach-Cron-Token": "test-secret"},
    )
    # Middleware must not reject the canonical header. The route may return a
    # non-401 status depending on its test dependencies, but auth passed.
    assert response.status_code != 401


def test_followup_middleware_rejects_legacy_header(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/api/outreach/process-followups",
        headers={"X-Outreach-Token": "test-secret"},
    )
    assert response.status_code == 401


def test_followup_middleware_rejects_missing_header(monkeypatch):
    client = _client(monkeypatch)
    response = client.post("/api/outreach/process-followups")
    assert response.status_code == 401
