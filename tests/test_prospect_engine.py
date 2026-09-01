import importlib
import os
import sys

import pytest


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "sqlite://")
    monkeypatch.setenv("SECRET_KEY", "test-secret")

    for module_name in ["prospect_app", "prospect_engine", "app"]:
        sys.modules.pop(module_name, None)

    prospect_app = importlib.import_module("prospect_app")
    prospect_app.app.config.update(TESTING=True)

    with prospect_app.app.test_client() as test_client:
        yield test_client


def test_score_preview_requires_evidence_for_hot_score(client):
    response = client.post(
        "/api/prospects/score",
        json={
            "hiring_signal": True,
            "growth_signal": True,
            "high_lead_volume_signal": True,
            "manual_followup_signal": True,
            "crm_need_signal": True,
            "review_count": 800,
            "locations_count": 4,
            "automation_opportunities": ["lead follow-up", "booking"],
            "evidence": [],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["score"] <= 69
    assert body["qualified"] is False


def test_score_preview_qualifies_evidence_backed_prospect(client):
    response = client.post(
        "/api/prospects/score",
        json={
            "hiring_signal": True,
            "growth_signal": True,
            "high_lead_volume_signal": True,
            "manual_followup_signal": True,
            "crm_need_signal": True,
            "review_count": 800,
            "locations_count": 4,
            "automation_opportunities": ["lead follow-up", "booking"],
            "evidence": ["hiring page", "review profile"],
        },
    )

    assert response.status_code == 200
    body = response.get_json()
    assert 80 <= body["score"] <= 100
    assert body["score_band"] == "hot"
    assert body["qualified"] is True


def test_create_and_list_prospect(client):
    created = client.post(
        "/api/prospects",
        json={
            "company": "Test HVAC Company",
            "city": "Portsmouth",
            "state": "VA",
            "industry": "HVAC",
            "hiring_signal": True,
            "growth_signal": True,
            "high_lead_volume_signal": True,
            "manual_followup_signal": True,
            "crm_need_signal": True,
            "review_count": 500,
            "locations_count": 3,
            "automation_opportunities": ["instant lead response", "follow-up"],
            "evidence": ["public hiring listing", "public reviews"],
        },
    )

    assert created.status_code == 201
    prospect = created.get_json()["prospect"]
    assert prospect["company"] == "Test HVAC Company"
    assert prospect["score"] >= 80
    assert prospect["score_band"] == "hot"

    listed = client.get("/api/prospects?min_score=80")
    assert listed.status_code == 200
    payload = listed.get_json()
    assert payload["count"] == 1
    assert payload["prospects"][0]["company"] == "Test HVAC Company"


def test_company_is_required(client):
    response = client.post("/api/prospects", json={"hiring_signal": True})
    assert response.status_code == 400
    assert response.get_json()["error"] == "company is required"


def test_update_rescores_prospect(client):
    created = client.post(
        "/api/prospects",
        json={"company": "Example Contractor"},
    ).get_json()["prospect"]

    assert created["score"] == 0

    updated = client.patch(
        f"/api/prospects/{created['id']}",
        json={
            "hiring_signal": True,
            "growth_signal": True,
            "high_lead_volume_signal": True,
            "manual_followup_signal": True,
            "crm_need_signal": True,
            "review_count": 500,
            "locations_count": 3,
            "automation_opportunities": ["lead follow-up"],
            "evidence": ["source one", "source two"],
        },
    )

    assert updated.status_code == 200
    prospect = updated.get_json()["prospect"]
    assert prospect["score"] >= 80
    assert prospect["score_band"] == "hot"


def test_hot_endpoint_only_returns_80_plus(client):
    client.post("/api/prospects", json={"company": "Cold Company"})
    client.post(
        "/api/prospects",
        json={
            "company": "Hot Company",
            "hiring_signal": True,
            "growth_signal": True,
            "high_lead_volume_signal": True,
            "manual_followup_signal": True,
            "crm_need_signal": True,
            "review_count": 500,
            "locations_count": 3,
            "evidence": ["source one", "source two"],
        },
    )

    response = client.get("/api/prospects/hot")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] == 1
    assert payload["prospects"][0]["company"] == "Hot Company"
    assert payload["prospects"][0]["score"] >= 80
