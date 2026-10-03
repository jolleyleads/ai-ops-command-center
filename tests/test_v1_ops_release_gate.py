import json
from datetime import datetime, timedelta
import pytest
import outreach_automation as oa
import smart_search
import v1_orchestration as v1


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN","ops-security-test-token")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=ops-test-signing-key")
    monkeypatch.setenv("OUTREACH_CRON_TOKEN","cron-test-token")
    oa.app.config.update(TESTING=True,SECRET_KEY="test-secret",SESSION_COOKIE_SECURE=False)
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def lead():
    x=oa.OutreachLead(company="Ops Test",contact_email="owner@example.com",status="review")
    oa.db.session.add(x);oa.db.session.commit();return x


def login(client):
    client.get("/operator/login")
    with client.session_transaction() as s: csrf=s["csrf_token"]
    return client.post("/operator/login",data={"token":"ops-security-test-token","csrf_token":csrf})


def test_login_stores_derived_proof_not_raw_operator_secret(env):
    c=oa.app.test_client();assert login(c).status_code==303
    with c.session_transaction() as s:
        assert s.get("operator_auth")
        assert s.get("operator_auth")!="ops-security-test-token"
        assert "operator_token" not in s


def test_operator_pages_are_no_store_and_clickjacking_blocked(env):
    c=oa.app.test_client();login(c);r=c.get("/operator")
    assert r.status_code==200
    assert "no-store" in r.headers["Cache-Control"]
    assert r.headers["X-Frame-Options"]=="DENY"


def test_operator_control_rejects_missing_csrf(env):
    x=lead();c=oa.app.test_client();login(c)
    r=c.post(f"/operator/leads/{x.id}/control",data={"action":"review"})
    assert r.status_code==403


def test_uncertain_command_surfaces_in_recovery_queue(env):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    token=oa._claim_external_command(cmd);oa._finish_external_command(cmd.id,token,{"ok":False,"error":"lost response"})
    c=oa.app.test_client();login(c);r=c.get("/api/operator/recovery")
    data=r.get_json();assert data["alert_count"]==1
    assert data["commands"][0]["kind"]=="gmail_send"


def test_calendar_recovery_uses_deterministic_event_lookup(env,monkeypatch):
    x=lead();cmd=oa._enqueue_external_command(x,"calendar_create",{"provider_idempotency_key":"evt-recover"})
    token=oa._claim_external_command(cmd);oa._finish_external_command(cmd.id,token,{"ok":False,"error":"timeout"})
    monkeypatch.setattr(oa,"get_event",lambda event_id:{"ok":True,"found":True,"event_id":event_id,"event_url":"test"})
    c=oa.app.test_client();login(c)
    with c.session_transaction() as s: csrf=s["csrf_token"]
    r=c.post(f"/api/operator/recovery/{cmd.id}/reconcile",headers={"X-CSRF-Token":csrf})
    assert r.status_code==200 and r.get_json()["status"]=="reconciled"


def test_expired_worker_is_alerted_as_uncertain(env):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"stuck@example.com"})
    oa._claim_external_command(cmd)
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id);cmd.lease_expires_at=datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    c=oa.app.test_client();login(c);data=c.get("/api/operator/recovery").get_json()
    assert data["alert_count"]==1
    assert oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id).status=="uncertain"


def test_scheduler_same_hour_executes_window_only_once(env,monkeypatch):
    c=oa.app.test_client()
    headers={"X-Outreach-Cron-Token":"cron-test-token"}
    first=c.post("/api/outreach/process-followups",headers=headers,json={})
    second=c.post("/api/outreach/process-followups",headers=headers,json={})
    assert first.status_code==200 and first.get_json()["duplicate_run_suppressed"] is False
    assert second.status_code==200 and second.get_json()["duplicate_run_suppressed"] is True
    assert oa.FollowupSchedulerRun.query.count()==1


def test_scheduler_rejects_wrong_secret(env):
    c=oa.app.test_client()
    assert c.post("/api/outreach/process-followups",headers={"X-Outreach-Cron-Token":"wrong"},json={}).status_code==401


def test_verified_public_email_accepts_contact_probe_tuple(env, monkeypatch):
    monkeypatch.setattr(
        v1,
        "_public_contact_evidence",
        lambda result: (
            [{"url": "https://example.com/contact", "subtitle": "owner@example.com", "text": ""}],
            {"attempted": 1, "budget_exhausted": False},
        ),
    )
    monkeypatch.setattr(v1, "_same_company_domain", lambda email, urls: True)
    email, source = v1._verified_public_email({"company": "Example"})
    assert email == "owner@example.com"
    assert source == "https://example.com/contact"


def test_verified_public_email_accepts_source_visible_same_domain_email(env, monkeypatch):
    monkeypatch.setattr(v1, "_public_contact_evidence", lambda result: (_ for _ in ()).throw(AssertionError("probe should not run")))
    email, source = v1._verified_public_email({
        "company": "Example HVAC",
        "website": "https://examplehvac.com",
        "evidence": [{"url": "https://examplehvac.com/careers", "snippet": "Apply: jobs@examplehvac.com"}],
    })
    assert email == "jobs@examplehvac.com"
    assert source == "https://examplehvac.com/careers"


def test_verified_public_email_rejects_source_visible_off_domain_email(env, monkeypatch):
    monkeypatch.setattr(v1, "_public_contact_evidence", lambda result: ([], {"attempted": 0}))
    email, source = v1._verified_public_email({
        "company": "Example HVAC",
        "website": "https://examplehvac.com",
        "evidence": [{"url": "https://examplehvac.com/careers", "snippet": "Apply: recruiter@gmail.com"}],
    })
    assert email == ""
    assert source == ""


def test_outreach_gate_is_universal_for_non_contractor_b2b_search(env):
    payload={"query":"law firms actively hiring paralegals","intent":"law firms actively hiring paralegals","results":[]}
    assert v1._contractor_search(payload) is True


def test_v11_hiring_patterns_are_not_hvac_specific(env):
    import v11_evidence_upgrade as v11
    patterns=v11._intent_patterns("auto repair companies actively hiring mechanics")
    assert patterns
    text="Now hiring experienced mechanics. Apply for an open position today."
    assert any(__import__("re").search(p,text,__import__("re").I|__import__("re").S) for p in patterns)
    assert v11._intent_supported("auto repair companies actively hiring mechanics",text) is True
    assert v11._intent_supported("plumbing companies actively hiring plumbers",text) is False


def test_initial_draft_is_universal_and_not_electrical_specific(env, monkeypatch):
    captured = {}
    def fake_run_ai(*, prompt, instructions):
        captured["prompt"] = prompt
        captured["instructions"] = instructions
        return {"ok": True, "output": json.dumps({"subject": "Hello", "body": "Body"}), "model": "test"}
    monkeypatch.setattr(oa, "run_ai", fake_run_ai)
    x = oa.OutreachLead(company="Example Law", location="Norfolk, VA", score=80, verification="VERIFIED", evidence_json="[]")
    result = oa._draft_email(x)
    assert result["ok"] is True
    combined = (captured["prompt"] + " " + captured["instructions"]).lower()
    assert "master electrician" not in combined
    assert "permit-pulling" not in combined
    assert "verified contractor" not in combined
    assert "business automation" in combined


def test_draft_falls_back_deterministically_when_ai_fails(env, monkeypatch):
    monkeypatch.setattr(oa, "run_ai", lambda **kwargs: {"ok": False, "error": "provider unavailable"})
    x = oa.OutreachLead(company="Example Roofing", location="Chesapeake, VA", score=80, verification="VERIFIED", evidence_json="[]")
    result = oa._draft_email(x)
    assert result["ok"] is True
    assert result["fallback"] is True
    assert result["model"] == "deterministic-fallback"
    assert "Example Roofing" in result["subject"]
    assert "lead generation" in result["body"]


def test_acceptance_pool_is_cross_industry(env):
    import customer_demo
    source = __import__("inspect").getsource(customer_demo.v11_acceptance_once).lower()
    assert "plumbing companies" in source
    assert "law firms" in source
    assert "dental practices" in source
    assert "restaurants" in source
    assert "hvac" not in source
    assert "heating and cooling" not in source


def test_active_orchestration_uses_universal_outreach_gate(env):
    source = __import__("inspect").getsource(v1.orchestrate_discovery)
    assert "_outreach_search(payload)" in source
    assert "not_b2b_outreach_search" in source
