import importlib
import sys

import pytest


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    for module_name in [
        "commercial_app",
        "prospect_app",
        "prospect_engine",
        "prospect_sources",
        "app",
    ]:
        sys.modules.pop(module_name, None)

    commercial_app = importlib.import_module("commercial_app")
    commercial_app.app.config.update(TESTING=True)

    monkeypatch.setattr(
        commercial_app,
        "openai_text",
        lambda prompt: ("Test outreach preview body.", "resp_test_123"),
    )

    with commercial_app.app.test_client() as test_client:
        yield test_client


def _create_hot_prospect(client):
    response = client.post(
        "/api/prospects",
        json={
            "company": "Safety Test Contractor",
            "city": "Portsmouth",
            "state": "VA",
            "industry": "Electrical Contractor",
            "email": "public@example.com",
            "hiring_signal": True,
            "growth_signal": True,
            "high_lead_volume_signal": True,
            "manual_followup_signal": True,
            "crm_need_signal": True,
            "review_count": 500,
            "locations_count": 3,
            "automation_opportunities": ["lead follow-up"],
            "evidence": ["public reviews", "public hiring page"],
        },
    )
    assert response.status_code == 201
    return response.get_json()["prospect"]


def test_command_center_static_page_loads(client):
    response = client.get("/static/command-center.html")
    assert response.status_code == 200
    assert b"AI Ops Command Center" in response.data


def test_outreach_queue_static_page_loads(client):
    response = client.get("/static/outreach-queue.html")
    assert response.status_code == 200
    assert b"Outreach Readiness Queue" in response.data
    assert b"No auto-send" in response.data


def test_prospect_detail_static_page_loads(client):
    response = client.get("/static/prospect-detail.html?id=1")
    assert response.status_code == 200
    assert b"Prospect profile" in response.data
    assert b"Pipeline history" in response.data
    assert b"Send safeguards" in response.data
    assert b"Manual send" in response.data
    assert b"There is no auto-send" in response.data


def test_pipeline_change_is_recorded_in_history(client):
    prospect = _create_hot_prospect(client)

    updated = client.post(
        f"/api/prospects/{prospect['id']}/pipeline",
        json={"status": "qualified", "note": "Reviewed before outreach."},
    )
    assert updated.status_code == 200
    payload = updated.get_json()
    assert payload["changed"] is True
    assert payload["prospect"]["status"] == "qualified"

    history = client.get(f"/api/prospects/{prospect['id']}/history")
    assert history.status_code == 200
    history_payload = history.get_json()
    assert history_payload["count"] == 1
    event = history_payload["history"][0]
    assert event["event_type"] == "status_change"
    assert event["from_status"] == "new"
    assert event["to_status"] == "qualified"
    assert event["note"] == "Reviewed before outreach."


def test_note_is_recorded_without_changing_stage(client):
    prospect = _create_hot_prospect(client)

    created = client.post(
        f"/api/prospects/{prospect['id']}/notes",
        json={"note": "Call owner after 2 PM."},
    )
    assert created.status_code == 201

    history = client.get(f"/api/prospects/{prospect['id']}/history").get_json()
    assert history["count"] == 1
    assert history["history"][0]["event_type"] == "note"
    assert history["history"][0]["note"] == "Call owner after 2 PM."


def test_invalid_pipeline_stage_is_rejected(client):
    prospect = _create_hot_prospect(client)
    response = client.post(
        f"/api/prospects/{prospect['id']}/pipeline",
        json={"status": "random-stage"},
    )
    assert response.status_code == 400
    assert response.get_json()["error"] == "invalid pipeline status"


def test_outreach_preview_generates_draft_and_never_sends(client):
    prospect = _create_hot_prospect(client)

    response = client.post(
        f"/api/prospects/{prospect['id']}/outreach-preview",
        json={},
    )

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["status"] == "preview"
    assert payload["body"] == "Test outreach preview body."
    assert payload["recipient_email"] == "public@example.com"
    assert payload["recipient_ready"] is True
    assert payload["sent"] is False
