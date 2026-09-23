import json
from datetime import datetime, timedelta
import pytest
import outreach_automation as oa
import smart_search


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN","operator-test-token")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=test-only-signing-key")
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def lead():
    x=oa.OutreachLead(company="Outbox Test",contact_email="owner@example.com",location="Portsmouth, VA",status="needs_evidence")
    oa.db.session.add(x);oa.db.session.commit();return x


def test_command_and_intent_audit_exist_before_provider_execution(env):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    assert cmd.status=="pending"
    audit=oa.OperatorAuditEvent.query.filter_by(action="external_command_intent").one()
    assert audit.lead_id==x.id
    assert json.loads(audit.result_json)["status"]=="pending"


def test_crash_before_provider_call_leaves_durable_executing_then_expires_uncertain(env):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    token=oa._claim_external_command(cmd,lease_seconds=1)
    assert token
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    cmd.lease_expires_at=datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    assert oa._expire_stale_external_commands()==1
    oa.db.session.expire_all();cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    assert cmd.status=="uncertain"
    assert oa._claim_external_command(cmd)==""


def test_provider_success_then_worker_crash_is_not_blindly_reexecuted(env):
    x=lead();calls=[]
    cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    token=oa._claim_external_command(cmd,lease_seconds=1)
    calls.append("provider-accepted")
    # Simulate process death before completion persistence.
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    cmd.lease_expires_at=datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    oa._expire_stale_external_commands()
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    assert cmd.status=="uncertain" and calls==["provider-accepted"]
    assert oa._claim_external_command(cmd)==""


def test_two_claimers_only_first_gets_lease(env):
    x=lead();cmd=oa._enqueue_external_command(x,"calendar_create",{"event_id":"evt-1"})
    first=oa._claim_external_command(cmd)
    oa.db.session.expire_all();fresh=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    second=oa._claim_external_command(fresh)
    assert first and second==""


def test_provider_receipt_and_completion_audit_are_committed(env):
    x=lead();cmd=oa._enqueue_external_command(x,"calendar_create",{"event_id":"evt-1"})
    token=oa._claim_external_command(cmd)
    done=oa._finish_external_command(cmd.id,token,{"ok":True,"event_id":"evt-1"})
    assert done["status"]=="succeeded"
    oa.db.session.expire_all();cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    assert json.loads(cmd.provider_receipt_json)["event_id"]=="evt-1"
    assert oa.OperatorAuditEvent.query.filter_by(action="external_command_complete").count()==1


def test_ambiguous_provider_failure_is_uncertain_not_retryable(env):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    token=oa._claim_external_command(cmd)
    done=oa._finish_external_command(cmd.id,token,{"ok":False,"error":"connection lost after request"})
    assert done["status"]=="uncertain"
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    assert oa._claim_external_command(cmd)==""


def test_proven_no_side_effect_can_be_failed(env):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    token=oa._claim_external_command(cmd)
    done=oa._finish_external_command(cmd.id,token,{"ok":False,"definitely_not_executed":True,"error":"validation rejected before provider"})
    assert done["status"]=="failed"


def test_same_command_payload_is_idempotent(env):
    x=lead();a=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    b=oa._enqueue_external_command(x,"gmail_send",{"recipient":"owner@example.com"})
    assert a.id==b.id
    assert oa.ExternalSideEffectCommand.query.count()==1
    assert oa.OperatorAuditEvent.query.filter_by(action="external_command_intent").count()==1


def test_database_failure_after_provider_response_recovers_as_uncertain(env,monkeypatch):
    x=lead();cmd=oa._enqueue_external_command(x,"gmail_send",{"recipient":"dbfail@example.com"})
    token=oa._claim_external_command(cmd,lease_seconds=1)
    real_commit=oa.db.session.commit
    monkeypatch.setattr(oa.db.session,"commit",lambda:(_ for _ in ()).throw(RuntimeError("injected commit failure")))
    with pytest.raises(RuntimeError):
        oa._finish_external_command(cmd.id,token,{"ok":True,"message_id":"provider-accepted"})
    oa.db.session.rollback()
    monkeypatch.setattr(oa.db.session,"commit",real_commit)
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    # Completion did not commit, so durable state remains executing. Recovery must
    # expire it to uncertain rather than re-execute the provider call.
    cmd.lease_expires_at=datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    oa._expire_stale_external_commands()
    assert oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id).status=="uncertain"


def test_uncertain_command_can_only_finish_through_reconciliation(env):
    x=lead();cmd=oa._enqueue_external_command(x,"calendar_create",{"event_id":"evt-r"})
    token=oa._claim_external_command(cmd)
    oa._finish_external_command(cmd.id,token,{"ok":False,"error":"lost response"})
    cmd=oa.db.session.get(oa.ExternalSideEffectCommand,cmd.id)
    result=oa._reconcile_external_command(cmd,True,{"event_id":"evt-r","source":"calendar_get"})
    assert result["status"]=="reconciled"
    assert oa.OperatorAuditEvent.query.filter_by(action="external_command_reconciled").count()==1
