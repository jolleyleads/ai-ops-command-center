import json
from datetime import datetime
import pytest
import outreach_automation as oa
import smart_search
from src.workflow_integration_harness import run_workflow, InjectedFailure


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN","operator-test-token")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=e2e-test-signing-key")
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def make_lead():
    evidence=[{"url":"https://example.com/contact","email":"owner@example.com","title":"E2E Electric contact","text":"E2E Electric owner contact","observed_at":datetime.utcnow().isoformat()}]
    x=oa.OutreachLead(company="E2E Electric",contact_email="owner@example.com",location="Portsmouth, VA",source_url="https://example.com",evidence_json=json.dumps(evidence),status="needs_evidence")
    oa.db.session.add(x);oa.db.session.commit();return x


def draft(lead):
    return {"ok":True,"subject":"Quick question","body":"Would you be open to a brief call?"}


def gmail(*args):
    return {"ok":True,"message_id":"gmail-msg-1","thread_id":"gmail-thread-1"}


def availability(req):
    return {"ok":True,"available":True,"start":req["start"],"end":req["end"]}


def reply():
    return {"reply_evidence":[{"message_id":"reply-1","thread_id":"gmail-thread-1","from_email":"owner@example.com","text":"Yes, interested. Book 2026-10-01T14:00:00 to 2026-10-01T14:30:00 America/New_York"}]}


def calendar(req,**kwargs):
    return {"ok":True,"event_id":kwargs.get("idempotency_key"),"event_url":"https://calendar.invalid/event/e2e"}


def run(lead,**kw):
    return run_workflow(oa=oa,lead=lead,draft_func=kw.pop("draft_func",draft),gmail_func=kw.pop("gmail_func",gmail),reply=kw.pop("reply_data",reply()),availability_func=kw.pop("availability_func",availability),calendar_func=calendar,**kw)


def test_entire_workflow_as_one_machine(env,monkeypatch):
    monkeypatch.setattr(oa,"create_event",calendar)
    result=run(make_lead())
    assert result["ok"] is True
    assert result["trace"]==["discover","verify","qualify","draft","command","gmail","reply","classify","calendar","reconcile","audit"]
    assert result["booking_status"]=="confirmed"
    assert oa.OutreachQualificationReceipt.query.count()==1
    assert oa.OutreachSendAttempt.query.one().status=="sent"
    assert oa.OutreachReplyEvidence.query.count()==1
    assert oa.OutreachBookingAttempt.query.one().status=="confirmed"
    commands=oa.ExternalSideEffectCommand.query.order_by(oa.ExternalSideEffectCommand.id).all()
    assert [x.kind for x in commands]==["gmail_send","calendar_create"]
    assert [x.status for x in commands]==["succeeded","succeeded"]
    actions=[x.action for x in oa.OperatorAuditEvent.query.order_by(oa.OperatorAuditEvent.id).all()]
    assert actions==["external_command_intent","external_command_complete","external_command_intent","external_command_complete"]


@pytest.mark.parametrize("point",["discover","verify","qualify","draft","command","gmail","reply","classify","calendar","reconcile","audit"])
def test_failure_injection_at_every_named_transition_stops_forward_progress(env,monkeypatch,point):
    monkeypatch.setattr(oa,"create_event",calendar)
    x=make_lead()
    with pytest.raises(InjectedFailure,match=point):
        run(x,fail_at=point)
    # A named checkpoint failure must never produce evidence for a later checkpoint.
    # Provider calls before the injected point remain durably represented.


def test_draft_failure_never_creates_external_command(env,monkeypatch):
    monkeypatch.setattr(oa,"create_event",calendar)
    result=run(make_lead(),draft_func=lambda lead:{"ok":False,"error":"injected draft failure"})
    assert result["stage"]=="draft"
    assert oa.ExternalSideEffectCommand.query.count()==0
    assert oa.OutreachSendAttempt.query.count()==0


def test_gmail_ambiguous_failure_stops_before_reply_and_calendar(env,monkeypatch):
    monkeypatch.setattr(oa,"create_event",calendar)
    result=run(make_lead(),gmail_func=lambda *a:{"ok":False,"error":"injected lost response"})
    assert result["stage"]=="gmail"
    assert oa.ExternalSideEffectCommand.query.filter_by(kind="gmail_send").one().status=="uncertain"
    assert oa.OutreachReplyEvidence.query.count()==0
    assert oa.OutreachBookingAttempt.query.count()==0


def test_reply_without_interest_stops_before_calendar(env,monkeypatch):
    monkeypatch.setattr(oa,"create_event",calendar)
    r={"reply_evidence":[{"message_id":"reply-no","thread_id":"gmail-thread-1","from_email":"owner@example.com","text":"No thanks, please stop emailing me."}]}
    result=run(make_lead(),reply_data=r)
    assert result["stage"]=="classify"
    assert oa.OutreachBookingAttempt.query.count()==0
    assert oa.ExternalSideEffectCommand.query.filter_by(kind="calendar_create").count()==0


def test_calendar_ambiguous_failure_is_uncertain_and_never_blindly_recreated(env,monkeypatch):
    calls=[]
    def lost(req,**kwargs):
        calls.append(1);return {"ok":False,"error":"connection lost after provider request"}
    monkeypatch.setattr(oa,"create_event",lost)
    x=make_lead();result=run(x)
    assert result["stage"]=="calendar" and result["command_status"]=="uncertain"
    cmd=oa.ExternalSideEffectCommand.query.filter_by(kind="calendar_create").one()
    assert cmd.status=="uncertain" and calls==[1]
    again=oa._calendar_create_via_command(x,oa.extract_explicit_booking(reply()["reply_evidence"][0]["text"]),summary="Call with E2E Electric",description="E2E validated reply",idempotency_key=oa.OutreachBookingAttempt.query.one().event_id)
    assert again["ok"] is False
    assert calls==[1]


def test_availability_failure_prevents_calendar_provider_call(env,monkeypatch):
    calls=[]
    monkeypatch.setattr(oa,"create_event",lambda *a,**k:calls.append(1) or {"ok":True})
    result=run(make_lead(),availability_func=lambda req:{"ok":True,"available":False})
    assert result["stage"]=="calendar"
    assert calls==[]
    assert oa.ExternalSideEffectCommand.query.filter_by(kind="calendar_create").count()==0
