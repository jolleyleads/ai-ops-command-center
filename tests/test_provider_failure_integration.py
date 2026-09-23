"""Provider-boundary failure tests. No external Gmail/Calendar calls."""
import json
from datetime import datetime

import pytest
import outreach_automation as oa
import smart_search  # register all routes before clients issue requests


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN","operator-test-token")
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def lead():
    evidence=[{"url":"https://example.com/contact","email":"owner@example.com","title":"Failure Test Electric contact","text":"Failure Test Electric owner contact","observed_at":datetime.utcnow().isoformat()}]
    x=oa.OutreachLead(company="Failure Test Electric",contact_email="owner@example.com",location="Portsmouth, VA",source_url="https://example.com",evidence_json=json.dumps(evidence),status="needs_evidence",subject="s",body="b")
    oa.db.session.add(x);oa.db.session.commit()
    receipt=oa._store_qualification(x,{})
    assert receipt["ok"] is True
    return x


def test_gmail_provider_failure_becomes_uncertain_and_blocks_duplicate(env,monkeypatch):
    x=lead();calls=[]
    def failed_provider(*args):
        calls.append(args)
        return {"ok":False,"error":"injected lost provider response"}
    monkeypatch.setattr(oa,"_gmail_send",failed_provider)
    first=oa._safe_send(x,kind="initial",sequence=0,subject="s",body="b")
    attempt=oa.OutreachSendAttempt.query.one()
    assert first["ok"] is False
    assert attempt.status=="uncertain"
    second=oa._safe_send(x,kind="initial",sequence=0,subject="s",body="b")
    assert second["ok"] is False and second["stage"]=="blocked"
    assert len(calls)==1


def test_two_workers_same_send_identity_do_not_create_two_attempt_rows(env,monkeypatch):
    x=lead()
    monkeypatch.setattr(oa,"_gmail_send",lambda *args:{"ok":False,"error":"injected"})
    oa._safe_send(x,kind="initial",sequence=0,subject="s",body="b")
    oa._safe_send(x,kind="initial",sequence=0,subject="s",body="b")
    assert oa.OutreachSendAttempt.query.count()==1


def test_calendar_create_failure_is_persisted_uncertain_for_reconciliation(env,monkeypatch):
    x=lead()
    text="Interested. Book 2026-10-01T14:00:00 to 2026-10-01T14:30:00 America/New_York"
    monkeypatch.setattr(oa,"extract_explicit_booking",lambda _:{"start":"2026-10-01T14:00:00","end":"2026-10-01T14:30:00","timezone":"America/New_York"})
    monkeypatch.setattr(oa,"process_reply_to_booking",lambda **kwargs:{"ok":False,"stage":"create_failed","booking_execution":{"booking_receipt":{},"error":"injected lost calendar response"}})
    result=oa._route_persisted_reply(x,{"reply_evidence":[{"text":text,"message_id":"reply-1"}]},datetime.utcnow())
    attempt=oa.OutreachBookingAttempt.query.one()
    assert result["ok"] is False
    assert attempt.status=="uncertain"


def test_pending_or_uncertain_booking_reconciles_before_any_recreate(env,monkeypatch):
    x=lead()
    text="Interested. Book it"
    monkeypatch.setattr(oa,"extract_explicit_booking",lambda _:{"start":"2026-10-01T14:00:00","end":"2026-10-01T14:30:00","timezone":"America/New_York"})
    # First execution makes the durable attempt uncertain.
    monkeypatch.setattr(oa,"process_reply_to_booking",lambda **kwargs:{"ok":False,"stage":"create_failed","booking_execution":{"booking_receipt":{},"error":"lost response"}})
    reply={"reply_evidence":[{"text":text,"message_id":"reply-1"}]}
    oa._route_persisted_reply(x,reply,datetime.utcnow())
    attempt=oa.OutreachBookingAttempt.query.one()
    creates=[]
    monkeypatch.setattr(oa,"create_event",lambda *a,**k:creates.append(1) or {"ok":True})
    monkeypatch.setattr(oa,"get_event",lambda event_id:{"ok":True,"found":True,"event_id":event_id,"start":attempt.start,"end":attempt.end,"event_url":"https://calendar.invalid/fake"})
    second=oa._route_persisted_reply(x,reply,datetime.utcnow())
    assert second["ok"] is True and second.get("reconciled") is True
    assert creates==[]
