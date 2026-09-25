import json
from datetime import datetime, timedelta
from types import SimpleNamespace
import pytest
import outreach_automation as oa
import gmail_reconciliation as gr

@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN","operator-test-token")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=test-only-signing-key")
    monkeypatch.setenv("GMAIL_FROM_EMAIL","sender@example.com")
    monkeypatch.setattr(gr,"NEGATIVE_GRACE_SECONDS",60)
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all();yield;oa.db.session.remove();oa.db.drop_all()

def lead():
    x=oa.OutreachLead(company="Gmail Recovery",contact_email="owner@example.com",location="Portsmouth, VA",status="qualified",subject="Test",body="Hello")
    oa.db.session.add(x);oa.db.session.commit();return x

def uncertain(x):
    payload={"recipient":"owner@example.com","kind":"initial","sequence":0,"subject":"Test","body":"Hello","send_key":"send-key-1"}
    a=oa.OutreachSendAttempt(lead_id=x.id,kind="initial",sequence=0,recipient="owner@example.com",idempotency_key="send-key-1",status="uncertain")
    oa.db.session.add(a);oa.db.session.commit()
    cmd=oa._enqueue_external_command(x,"gmail_send",payload);token=oa._claim_external_command(cmd);oa._finish_external_command(cmd.id,token,{"ok":False,"error":"lost response"})
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id);cmd.updated_at=datetime.utcnow()-timedelta(minutes=5);oa.db.session.commit();return cmd,a

class R:
    def __init__(self,ok=True,status=200,data=None,text=""): self.ok=ok;self.status_code=status;self._data=data or {};self.text=text
    def json(self): return self._data

def test_deterministic_message_identity_is_stable():
    key="a"*64
    assert gr._message_identity(key)==gr._message_identity(key)
    assert key in gr._message_identity(key)

def test_found_reconciliation_records_provider_receipt_and_send(env,monkeypatch):
    x=lead();cmd,a=uncertain(x);identity=gr._message_identity(cmd.idempotency_key)
    monkeypatch.setattr(gr,"gmail_access_token",lambda:"t")
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        if url.endswith("/messages"): return R(data={"messages":[{"id":"gm1","threadId":"th1"}]})
        return R(data={"id":"gm1","threadId":"th1","payload":{"headers":[{"name":"Message-ID","value":identity},{"name":"To","value":"owner@example.com"},{"name":"Subject","value":"Test"},{"name":"X-AI-Ops-Command-ID","value":cmd.idempotency_key}]}})
    monkeypatch.setattr(gr.requests,"get",get)
    out=gr.reconcile_gmail_command(cmd)
    assert out["outcome"]=="found"
    assert oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id).status=="reconciled"
    assert oa.db.session.get(oa.OutreachSendAttempt,a.id).status=="sent"
    assert json.loads(oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id).provider_receipt_json)["message_id"]=="gm1"
    assert oa.OperatorAuditEvent.query.filter_by(action="gmail_reconciliation_applied").count()==1

def test_zero_exact_matches_after_grace_proves_no_side_effect(env,monkeypatch):
    x=lead();cmd,a=uncertain(x);monkeypatch.setattr(gr,"gmail_access_token",lambda:"t");monkeypatch.setattr(gr.requests,"get",lambda *args,**kwargs:R(data={"messages":[]}))
    out=gr.reconcile_gmail_command(cmd)
    assert out["outcome"]=="not_found"
    assert oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id).status=="failed"
    assert oa.db.session.get(oa.OutreachSendAttempt,a.id).error=="RECONCILIATION_PROVED_NO_SIDE_EFFECT"

def test_zero_matches_inside_grace_stays_uncertain(env,monkeypatch):
    x=lead();cmd,a=uncertain(x);cmd.updated_at=datetime.utcnow();oa.db.session.commit();monkeypatch.setattr(gr,"gmail_access_token",lambda:"t");monkeypatch.setattr(gr.requests,"get",lambda *args,**kwargs:R(data={"messages":[]}))
    out=gr.reconcile_gmail_command(cmd)
    assert out["status"]=="uncertain"
    assert oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id).status=="uncertain"

def test_gmail_lookup_error_stays_uncertain(env,monkeypatch):
    x=lead();cmd,a=uncertain(x);monkeypatch.setattr(gr,"gmail_access_token",lambda:"t");monkeypatch.setattr(gr.requests,"get",lambda *args,**kwargs:R(ok=False,status=503,text="down"))
    out=gr.reconcile_gmail_command(cmd)
    assert out["status"]=="uncertain"

def test_retry_requires_negative_reconciliation_and_is_single_generation(env,monkeypatch):
    x=lead();cmd,a=uncertain(x);a.status="failed";a.error="RECONCILIATION_PROVED_NO_SIDE_EFFECT";oa.db.session.commit();calls=[]
    def fake(lead,**kwargs): calls.append(kwargs);return {"ok":True,"send_receipt":{"message_id":"new","thread_id":"newt"}}
    monkeypatch.setattr(gr,"hardened_safe_send",fake)
    one=gr.retry_after_negative_reconciliation(x,a);two=gr.retry_after_negative_reconciliation(x,a)
    assert one["ok"] and two["ok"]
    assert calls[0]["kind"]=="reconciled_retry" and calls[0]["sequence"]==a.id
    assert calls[1]["sequence"]==a.id

def test_retry_without_negative_proof_is_blocked(env):
    x=lead();cmd,a=uncertain(x);a.status="failed";a.error="some other failure";oa.db.session.commit()
    assert gr.retry_after_negative_reconciliation(x,a)["error"]=="NEGATIVE_GMAIL_RECONCILIATION_REQUIRED"
