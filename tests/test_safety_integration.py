import json
import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "integration-test-secret")

import outreach_automation as oa


@pytest.fixture()
def env(monkeypatch):
    oa.app.config.update(TESTING=True, SQLALCHEMY_DATABASE_URI="sqlite:///:memory:")
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN", "operator-test-token")
    monkeypatch.setenv("OUTREACH_CRON_TOKEN", "cron-test-token")
    with oa.app.app_context():
        oa.db.session.remove()
        oa.db.drop_all()
        oa.db.create_all()
        yield
        oa.db.session.remove()
        oa.db.drop_all()


def lead(email="owner@example.com"):
    row=oa.OutreachLead(company="Example Electric",contact_email=email,location="Portsmouth, VA",status="needs_evidence",subject="Hello",body="Body")
    oa.db.session.add(row);oa.db.session.commit()
    return row


def qualify(row):
    receipt={"ok":True,"qualified":True,"status":"Qualified","reason_codes":[]}
    oa.db.session.add(oa.OutreachQualificationReceipt(lead_id=row.id,status="Qualified",qualified=True,ok=True,receipt_json=json.dumps(receipt)))
    row.status="qualified";oa.db.session.commit()


def test_unqualified_safe_send_never_calls_provider(env,monkeypatch):
    row=lead();calls=[]
    monkeypatch.setattr(oa,"execute_outreach_send",lambda *a,**k:calls.append(1) or {"ok":True})
    result=oa._safe_send(row,kind="initial",sequence=0,subject="s",body="b")
    assert result["ok"] is False
    assert "QUALIFICATION_REQUIRED" in result["gate"]["reasons"]
    assert calls==[]
    assert oa.OutreachSendAttempt.query.count()==0


def test_suppressed_qualified_recipient_never_calls_provider(env,monkeypatch):
    row=lead();qualify(row)
    oa.db.session.add(oa.OutreachSuppression(normalized_email=row.contact_email,reason="opt_out"));oa.db.session.commit()
    calls=[]
    monkeypatch.setattr(oa,"execute_outreach_send",lambda *a,**k:calls.append(1) or {"ok":True})
    result=oa._safe_send(row,kind="initial",sequence=0,subject="s",body="b")
    assert result["ok"] is False
    assert calls==[]


def test_unqualified_automatic_booking_never_calls_calendar(env,monkeypatch):
    row=lead();calls=[]
    monkeypatch.setattr(oa,"check_availability",lambda *a,**k:calls.append("availability") or {"ok":True})
    monkeypatch.setattr(oa,"create_event",lambda *a,**k:calls.append("create") or {"ok":True})
    reply={"reply_evidence":[{"text":"Interested. Book 2026-10-01T14:00:00 to 2026-10-01T14:30:00 America/New_York","message_id":"m1"}]}
    result=oa._route_persisted_reply(row,reply,datetime.utcnow())
    assert result["ok"] is False and result["stage"]=="booking_blocked"
    assert calls==[]
    assert oa.OutreachBookingAttempt.query.count()==0


def test_explicit_booking_unauthorized_and_unqualified_never_calls_calendar(env,monkeypatch):
    row=lead();calls=[]
    monkeypatch.setattr(oa,"process_reply_to_booking",lambda **k:calls.append(1) or {"ok":True,"stage":"booked"})
    client=oa.app.test_client()
    payload={"reply_text":"interested","classification":{"classification":"interested"},"booking":{"start":"2026-10-01T14:00:00","end":"2026-10-01T14:30:00","timezone":"America/New_York"}}
    r=client.post(f"/api/outreach/leads/{row.id}/process-reply-booking",json=payload)
    assert r.status_code==401 and calls==[]
    r=client.post(f"/api/outreach/leads/{row.id}/process-reply-booking",json=payload,headers={"X-Operator-Token":"operator-test-token"})
    assert r.status_code==409 and calls==[]


def test_dashboard_and_control_are_unauthorized_without_credentials(env):
    row=lead();client=oa.app.test_client()
    assert client.get("/api/operator/dashboard").status_code==401
    assert client.post(f"/api/operator/leads/{row.id}/control",json={"action":"review"}).status_code==401
    assert oa.OperatorAuditEvent.query.count()==0


def test_uncertain_send_cannot_be_operator_retried(env,monkeypatch):
    row=lead();qualify(row)
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=row.id,kind="initial",sequence=0,recipient=row.contact_email,idempotency_key="uncertain-key",status="uncertain"));oa.db.session.commit()
    calls=[]
    monkeypatch.setattr(oa,"_safe_send",lambda *a,**k:calls.append(1) or {"ok":True})
    client=oa.app.test_client()
    r=client.post(f"/api/operator/leads/{row.id}/control",json={"action":"retry"},headers={"X-Operator-Token":"operator-test-token"})
    assert r.status_code==409 and calls==[]
    assert oa.OperatorAuditEvent.query.count()==1


def test_operator_mutation_and_audit_commit_together(env):
    row=lead();qualify(row);client=oa.app.test_client()
    r=client.post(f"/api/operator/leads/{row.id}/control",json={"action":"close"},headers={"X-Operator-Token":"operator-test-token","X-Operator-Actor":"integration"})
    assert r.status_code==200
    oa.db.session.expire_all()
    assert oa.db.session.get(oa.OutreachLead,row.id).status=="closed"
    audit=oa.OperatorAuditEvent.query.one()
    assert audit.action=="close" and audit.actor=="integration" and len(audit.event_hash)==64


def test_audit_failure_rolls_back_database_mutation(env,monkeypatch):
    row=lead();qualify(row);client=oa.app.test_client()
    monkeypatch.setattr(oa,"_audit",lambda *a,**k:(_ for _ in ()).throw(RuntimeError("audit failed")))
    with pytest.raises(RuntimeError):
        client.post(f"/api/operator/leads/{row.id}/control",json={"action":"close"},headers={"X-Operator-Token":"operator-test-token"})
    oa.db.session.rollback();oa.db.session.expire_all()
    assert oa.db.session.get(oa.OutreachLead,row.id).status=="qualified"
    assert oa.OperatorAuditEvent.query.count()==0


def test_followup_endpoint_fails_closed_without_or_with_wrong_secret(env,monkeypatch):
    client=oa.app.test_client()
    monkeypatch.delenv("OUTREACH_CRON_TOKEN",raising=False)
    assert client.post("/api/outreach/process-followups").status_code==401
    monkeypatch.setenv("OUTREACH_CRON_TOKEN","cron-test-token")
    assert client.post("/api/outreach/process-followups",headers={"X-Outreach-Cron-Token":"wrong"}).status_code==401
