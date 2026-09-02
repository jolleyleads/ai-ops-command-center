import importlib
import sys

import pytest


@pytest.fixture()
def commercial(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SECRET_KEY", "test-secret")
    for name in ["commercial_app", "prospect_app", "prospect_engine", "prospect_sources", "app"]:
        sys.modules.pop(name, None)
    module = importlib.import_module("commercial_app")
    module.app.config.update(TESTING=True)
    return module


def create_prospect(client, company="Manual Send Test Co", email="sales@test.invalid"):
    response = client.post("/api/prospects", json={
        "company": company,
        "email": email,
        "city": "Portsmouth",
        "state": "VA",
        "industry": "Electrical Contractor",
        "hiring_signal": True,
        "growth_signal": True,
        "high_lead_volume_signal": True,
        "manual_followup_signal": True,
        "crm_need_signal": True,
        "review_count": 500,
        "locations_count": 2,
        "automation_opportunities": ["lead follow-up"],
        "evidence": ["test evidence one", "test evidence two"],
    })
    assert response.status_code == 201
    return response.get_json()["prospect"]


def verify_recipient(client, prospect):
    response = client.post(
        f"/api/prospects/{prospect['id']}/recipient-verification",
        json={
            "verified": True,
            "email": prospect["email"],
            "source_url": "https://example.test/contact",
        },
    )
    assert response.status_code == 201
    return response.get_json()


def test_manual_send_requires_explicit_confirmation(commercial, monkeypatch):
    called = {"value": False}
    monkeypatch.setattr(commercial, "send_gmail", lambda *args, **kwargs: called.update(value=True))
    with commercial.app.test_client() as client:
        prospect = create_prospect(client)
        verify_recipient(client, prospect)
        response = client.post(
            f"/api/prospects/{prospect['id']}/manual-send",
            json={
                "confirm_send": False,
                "expected_email": prospect["email"],
                "subject": "Test subject",
                "body": "Test body",
            },
        )
        assert response.status_code == 400
        assert response.get_json()["sent"] is False
        assert called["value"] is False


def test_manual_send_requires_verified_exact_recipient(commercial, monkeypatch):
    called = {"value": False}
    monkeypatch.setattr(commercial, "send_gmail", lambda *args, **kwargs: called.update(value=True))
    with commercial.app.test_client() as client:
        prospect = create_prospect(client)
        response = client.post(
            f"/api/prospects/{prospect['id']}/manual-send",
            json={
                "confirm_send": True,
                "expected_email": prospect["email"],
                "subject": "Test subject",
                "body": "Test body",
            },
        )
        assert response.status_code == 409
        payload = response.get_json()
        assert payload["status"] == "blocked"
        assert payload["sent"] is False
        assert any("not been verified" in reason for reason in payload["send_readiness"]["reasons"])
        assert called["value"] is False


def test_manual_send_rejects_mismatched_expected_email(commercial, monkeypatch):
    called = {"value": False}
    monkeypatch.setattr(commercial, "send_gmail", lambda *args, **kwargs: called.update(value=True))
    with commercial.app.test_client() as client:
        prospect = create_prospect(client)
        verify_recipient(client, prospect)
        response = client.post(
            f"/api/prospects/{prospect['id']}/manual-send",
            json={
                "confirm_send": True,
                "expected_email": "different@test.invalid",
                "subject": "Test subject",
                "body": "Test body",
            },
        )
        assert response.status_code == 400
        assert response.get_json()["sent"] is False
        assert called["value"] is False


def test_manual_send_success_logs_delivery_and_updates_pipeline(commercial, monkeypatch):
    calls = []

    def fake_send(to, subject, body):
        calls.append((to, subject, body))
        return {"id": "gmail_message_test_123", "threadId": "thread_test_123"}

    monkeypatch.setattr(commercial, "send_gmail", fake_send)

    with commercial.app.test_client() as client:
        prospect = create_prospect(client)
        verify_recipient(client, prospect)
        response = client.post(
            f"/api/prospects/{prospect['id']}/manual-send",
            json={
                "confirm_send": True,
                "expected_email": prospect["email"],
                "subject": "Test subject",
                "body": "Test body",
            },
        )
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["status"] == "sent"
        assert payload["sent"] is True
        assert payload["provider_message_id"] == "gmail_message_test_123"
        assert payload["auto_send"] is False
        assert len(calls) == 1

        outreach = client.get(f"/api/prospects/{prospect['id']}/outreach-history").get_json()
        assert any(a["status"] == "sent" and a["provider_message_id"] == "gmail_message_test_123" for a in outreach["attempts"])
        assert outreach["contact_protection"]["blocked"] is True

        pipeline = client.get(f"/api/prospects/{prospect['id']}/history").get_json()
        assert pipeline["current_status"] == "contacted"
        assert any(e["event_type"] == "status_change" and e["to_status"] == "contacted" for e in pipeline["history"])


def test_manual_send_failure_is_logged_and_not_marked_sent(commercial, monkeypatch):
    def fail_send(*args, **kwargs):
        raise RuntimeError("simulated Gmail failure")

    monkeypatch.setattr(commercial, "send_gmail", fail_send)

    with commercial.app.test_client() as client:
        prospect = create_prospect(client)
        verify_recipient(client, prospect)
        response = client.post(
            f"/api/prospects/{prospect['id']}/manual-send",
            json={
                "confirm_send": True,
                "expected_email": prospect["email"],
                "subject": "Test subject",
                "body": "Test body",
            },
        )
        assert response.status_code == 502
        payload = response.get_json()
        assert payload["status"] == "failed"
        assert payload["sent"] is False
        assert payload["auto_send"] is False

        outreach = client.get(f"/api/prospects/{prospect['id']}/outreach-history").get_json()
        assert any(a["status"] == "failed" and "simulated Gmail failure" in a["reason"] for a in outreach["attempts"])
        assert not any(a["status"] == "sent" for a in outreach["attempts"])


def test_duplicate_gate_prevents_second_manual_send(commercial, monkeypatch):
    calls = []
    monkeypatch.setattr(commercial, "send_gmail", lambda *args, **kwargs: calls.append(args) or {"id": "first_send"})

    with commercial.app.test_client() as client:
        prospect = create_prospect(client)
        verify_recipient(client, prospect)
        payload = {
            "confirm_send": True,
            "expected_email": prospect["email"],
            "subject": "Test subject",
            "body": "Test body",
        }
        first = client.post(f"/api/prospects/{prospect['id']}/manual-send", json=payload)
        assert first.status_code == 200
        second = client.post(f"/api/prospects/{prospect['id']}/manual-send", json=payload)
        assert second.status_code == 409
        second_payload = second.get_json()
        assert second_payload["sent"] is False
        assert second_payload["send_readiness"]["contact_protection"]["blocked"] is True
        assert len(calls) == 1
