from datetime import datetime, timedelta
import pytest
import commercial_app
import outreach_automation as oa
import automation_monitor as monitor
from src.automatic_reply_router import classify_reply
from src.grounded_reply import routine_answer
from src import google_calendar_provider as calendar


@pytest.fixture
def env():
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def test_scheduling_question_and_mixed_question_remain_distinct():
    assert classify_reply("Can you reschedule our meeting to November 11 2026 at 2 pm?")["classification"] == "interested"
    assert classify_reply("Can you schedule a meeting, and how much does it cost?")["classification"] == "question"
    assert classify_reply("Unsubscribe. Can you schedule a meeting?")["classification"] == "not_interested"
    assert routine_answer("How long is the call?")
    assert not routine_answer("How long is the call, and what is your price?")


def test_missing_schedule_sends_reply_using_persisted_message_identity(env, monkeypatch):
    lead=oa.OutreachLead(company="Example",contact_email="owner@example.com",subject="Hello",status="sent")
    oa.db.session.add(lead);oa.db.session.commit()
    evidence=oa.OutreachReplyEvidence(lead_id=lead.id,message_id="m1",body_text="Let's schedule a meeting")
    oa.db.session.add(evidence);oa.db.session.commit()
    monkeypatch.setattr(oa,"_qualification_gate",lambda lead:{"ok":True})
    calls=[]
    monkeypatch.setattr(oa,"_safe_send",lambda *a,**k:calls.append(k) or {"ok":True})
    result=oa._route_persisted_reply(lead,{"reply_evidence":[{"message_id":"m1","text":evidence.body_text}]},datetime.utcnow())
    assert result["ok"] and not result["booking_attempted"]
    assert calls[0]["sequence"] == evidence.id
    assert "timezone" in calls[0]["body"]


def test_unpersisted_reply_cannot_send(env, monkeypatch):
    lead=oa.OutreachLead(company="Example",subject="Hello")
    oa.db.session.add(lead);oa.db.session.commit()
    monkeypatch.setattr(oa,"_safe_send",lambda *a,**k:pytest.fail("must not send"))
    assert not oa._send_reply_for_message(lead,{"message_id":"unseen"},"Hello")["ok"]


def test_health_reports_missing_stale_and_failed_workers(env):
    assert monitor.health_snapshot()["workers"][0]["status"] == "missing"
    monitor.record_cycle({"ok":True},{"ok":False},{"ok":True})
    assert monitor.health_snapshot()["workers"][1]["status"] == "failed"
    row=oa.db.session.get(monitor.AutomationHeartbeat,"inbound")
    row.checked_at=datetime.utcnow()-timedelta(minutes=16);oa.db.session.commit()
    assert monitor.health_snapshot()["workers"][0]["status"] == "stale"
    assert oa.app.test_client().get("/api/operator/automation-health").status_code == 401


def test_reschedule_updates_existing_event_with_conditional_write(monkeypatch):
    req={"start":"2026-11-11T14:00:00-05:00","end":"2026-11-11T14:30:00-05:00","timezone":"America/New_York","attendee_email":"owner@example.com"}
    reads=iter([{"ok":True,"etag":"version1","attendees":[{"email":"owner@example.com"}],"start":"old","end":"old"},{"ok":True,"event_id":"existing",**req}])
    monkeypatch.setattr(calendar,"get_event",lambda _:next(reads))
    monkeypatch.setattr(calendar,"check_availability",lambda _:{"ok":True,"available":True})
    monkeypatch.setattr(calendar,"_headers",lambda :{})
    calls=[]
    class Response:ok=True
    monkeypatch.setattr(calendar.requests,"patch",lambda *a,**k:calls.append((a,k)) or Response())
    monkeypatch.setattr(calendar.requests,"post",lambda *a,**k:pytest.fail("reschedule must not insert"))
    assert calendar.reschedule_event("existing",req)["ok"]
    assert calls[0][0][0].endswith("/events/existing")
    assert calls[0][1]["headers"]["If-Match"] == "version1"


def test_reschedule_rejects_unrelated_attendee(monkeypatch):
    monkeypatch.setattr(calendar,"get_event",lambda _:{"ok":True,"etag":"v1","attendees":[{"email":"other@example.com"}]})
    monkeypatch.setattr(calendar.requests,"patch",lambda *a,**k:pytest.fail("must not update unrelated event"))
    req={"start":"2026-11-11T14:00:00-05:00","end":"2026-11-11T14:30:00-05:00","timezone":"America/New_York","attendee_email":"owner@example.com"}
    assert calendar.reschedule_event("existing",req)["error"] == "EVENT_ATTENDEE_MISMATCH"


def test_scheduled_worker_recovers_research_without_customer_poll(env,monkeypatch):
    import outreach_scheduler as scheduler
    import background_research as jobs
    monkeypatch.setattr(scheduler,"_oauth_diagnostics",lambda:None)
    monkeypatch.setattr(scheduler,"scan_real_inbound_replies",lambda:{"ok":True,"processed":[]})
    monkeypatch.setattr(oa,"process_due_followups",lambda:{"ok":True,"processed":[]})
    monkeypatch.setattr(scheduler,"process_durable_followups",lambda:{"ok":True,"processed":[]})
    monkeypatch.setattr(jobs,"_smart_search",lambda *a,**k:{"results":[]})
    jobs.db.session.add(jobs.ResearchJob(id="restart",prompt_text="companies",status="running",started_at=datetime.utcnow()-timedelta(minutes=11)))
    jobs.db.session.commit()
    result=scheduler.run_scheduled_outreach_cycle()
    assert result["research"]["processed"] == 1
    assert jobs.db.session.get(jobs.ResearchJob,"restart").status == "completed"
    assert monitor.health_snapshot()["workers"][2]["status"] == "healthy"
