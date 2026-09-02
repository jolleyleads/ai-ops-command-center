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
    monkeypatch.setattr(module, "openai_text", lambda prompt: ("Preview body.", "resp_test"))
    return module


def create_prospect(client, company, email):
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


def test_preview_is_saved_in_outreach_history(commercial):
    with commercial.app.test_client() as client:
        prospect = create_prospect(client, "Preview Test Co", "preview@test.invalid")
        preview = client.post(f"/api/prospects/{prospect['id']}/outreach-preview", json={})
        assert preview.status_code == 200
        payload = preview.get_json()
        assert payload["sent"] is False
        assert payload["outreach_attempt_id"] > 0

        history = client.get(f"/api/prospects/{prospect['id']}/outreach-history")
        assert history.status_code == 200
        data = history.get_json()
        assert data["count"] == 1
        assert data["attempts"][0]["status"] == "preview"
        assert data["attempts"][0]["openai_response_id"] == "resp_test"


def test_missing_email_is_not_eligible(commercial):
    with commercial.app.test_client() as client:
        prospect = create_prospect(client, "Missing Email Co", "")
        response = client.get(f"/api/prospects/{prospect['id']}/outreach-protection")
        data = response.get_json()
        assert data["allowed"] is False
        assert data["blocked"] is True
        assert data["match_type"] == "missing_email"


def test_prior_contact_by_email_blocks_second_record(commercial):
    with commercial.app.test_client() as client:
        first = create_prospect(client, "Alpha Co", "shared@test.invalid")
        first_row = commercial.OutreachAttempt(
            prospect_id=first["id"], company="Alpha Co", company_normalized="alpha co",
            recipient_email="shared@test.invalid", email_normalized="shared@test.invalid",
            subject="Existing contact", status="sent"
        )
        commercial.db.session.add(first_row)
        commercial.db.session.commit()

        second = create_prospect(client, "Beta Co", "SHARED@test.invalid")
        response = client.get(f"/api/prospects/{second['id']}/outreach-protection")
        data = response.get_json()
        assert data["allowed"] is False
        assert data["blocked"] is True
        assert data["match_type"] == "email"


def test_prior_contact_by_company_blocks_new_email(commercial):
    with commercial.app.test_client() as client:
        first = create_prospect(client, "Same Company LLC", "first@test.invalid")
        first_row = commercial.OutreachAttempt(
            prospect_id=first["id"], company="Same Company LLC", company_normalized="same company llc",
            recipient_email="first@test.invalid", email_normalized="first@test.invalid",
            subject="Existing contact", status="sent"
        )
        commercial.db.session.add(first_row)
        commercial.db.session.commit()

        second = create_prospect(client, "SAME-COMPANY LLC", "second@test.invalid")
        response = client.get(f"/api/prospects/{second['id']}/outreach-protection")
        data = response.get_json()
        assert data["allowed"] is False
        assert data["blocked"] is True
        assert data["match_type"] == "company"
