import json
from datetime import datetime, timedelta
import pytest
import outreach_automation as oa
import smart_search


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
