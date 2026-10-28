from datetime import datetime, timedelta
import json
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
    assert classify_reply("How long is the call")["classification"] == "question"
    assert not routine_answer("How long is the call, and what is your price?")


@pytest.mark.parametrize("text", [
    "Let’s do October 31 1:30 PM Eastern time",
    "October 31 2026 at 1:30 PM Eastern time",
    "2030-01-10 at 2 pm America/New_York",
    "Tuesday at noon",
])
def test_date_time_proposal_needs_no_booking_keyword(text):
    assert classify_reply(text)["classification"] == "interested"


@pytest.mark.parametrize("text, label", [
    ("Unsubscribe. October 31 at 1:30 PM Eastern time", "not_interested"),
    ("Not interested. October 31 at 1:30 PM", "not_interested"),
    ("October 31 at 1:30 PM, and how much does it cost?", "question"),
    ("Received.\n> October 31 2026 at 1:30 PM Eastern", "unclear"),
])
def test_date_time_intent_preserves_stops_questions_and_quotes(text, label):
    assert classify_reply(text)["classification"] == label


def test_natural_scheduling_reply_infers_upcoming_year():
    from src.scheduling_dates import interpret_booking
    from datetime import timezone
    result=interpret_booking("Let’s do November 2 3 PM Eastern time",
        now=datetime(2026,10,28,tzinfo=timezone.utc))
    assert result["ready"]
    assert result["start"].startswith("2026-11-02T15:00")


def test_common_typos_numeric_dates_and_spoken_hour():
    from src.scheduling_dates import interpret_booking
    from datetime import timezone
    now=datetime(2026,10,28,tzinfo=timezone.utc)
    for phrase in ("Novembr 2 at 3pm", "11/2 at three pm", "November 2 at 3 PM"):
        result=interpret_booking(phrase,now=now)
        assert result["ready"],(phrase,result)
        assert result["start"].startswith("2026-11-02T15:00")


def test_time_only_uses_persisted_prior_unavailable_date():
    from src.scheduling_dates import interpret_booking
    from datetime import timezone
    prior=datetime(2026,11,2,14,0,tzinfo=timezone.utc)
    result=interpret_booking("3 PM is fine",now=datetime(2026,10,28,tzinfo=timezone.utc),prior_date=prior)
    assert result["ready"],result
    assert result["start"].startswith("2026-11-02T15:00")


def test_time_only_without_prior_context_never_books():
    from src.scheduling_dates import interpret_booking
    result=interpret_booking("3 PM is fine")
    assert not result["ready"]


def test_previously_unclear_date_proposal_resumes_only_once(env, monkeypatch):
    import v1_orchestration as scanner
    lead=oa.OutreachLead(company="Example", contact_email="owner@example.com", gmail_thread_id="thread", status="responded")
    oa.db.session.add(lead);oa.db.session.commit()
    oa._audit_actor(lead.id,"inbound_processed",{"message_id":"date"},{"stage":"unclear"},"scheduler");oa.db.session.commit()
    monkeypatch.setattr(scanner,"_gmail_thread_reply_state",lambda _:{"ok":True,"replied":True,"reply_evidence":[{"message_id":"date","from_email":lead.contact_email,"text":"October 31 at 1:30 PM Eastern"}]})
    calls=[]
    monkeypatch.setattr(scanner,"_route_persisted_reply",lambda *a:calls.append(1) or {"ok":True,"stage":"interested"})
    assert scanner.scan_real_inbound_replies()["processed"][0]["stage"] == "interested"
    assert scanner.scan_real_inbound_replies()["processed"][0]["stage"] == "already_processed"
    assert calls == [1]


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


def test_booking_metadata_preserves_qualification_evidence(env):
    evidence=[{"url":"https://example.com/contact","email":"owner@example.com","text":"Example hiring"}]
    lead=oa.OutreachLead(company="Example",contact_email="owner@example.com",source_url="https://example.com",evidence_json=json.dumps(evidence))
    oa.db.session.add(lead);oa.db.session.commit()
    validated,context,_=oa._server_qualification_inputs(lead)
    original=oa._qualification_evidence_digest(lead,validated,context)
    lead.evidence_json=json.dumps({"evidence":evidence,"booking":{"event_id":"confirmed"}})
    validated,context,_=oa._server_qualification_inputs(lead)
    assert oa._qualification_evidence_digest(lead,validated,context)==original


def test_imported_booking_reply_is_not_routed_again(env,monkeypatch):
    import v1_orchestration as scanner
    lead=oa.OutreachLead(company="Example",contact_email="owner@example.com",gmail_thread_id="thread",status="booked")
    oa.db.session.add(lead);oa.db.session.commit()
    oa.db.session.add(oa.OutreachBookingAttempt(lead_id=lead.id,reply_message_id="old",idempotency_key="confirmed-key",event_id="event",start="start",end="end",timezone="America/New_York",attendee_email=lead.contact_email,status="confirmed"))
    oa.db.session.commit()
    monkeypatch.setattr(scanner,"_gmail_thread_reply_state",lambda _:{"ok":True,"replied":True,"reply_evidence":[{"message_id":"old","from_email":lead.contact_email,"text":"Yes, book a meeting"}]})
    monkeypatch.setattr(scanner,"_route_persisted_reply",lambda *a:pytest.fail("completed booking must not run again"))
    assert scanner.scan_real_inbound_replies()["processed"][0]["stage"]=="already_booked"
    assert scanner.scan_real_inbound_replies()["processed"][0]["stage"]=="already_processed"


def test_supported_faq_resumes_prior_review_once(env,monkeypatch):
    import v1_orchestration as scanner
    lead=oa.OutreachLead(company="Example",contact_email="owner@example.com",gmail_thread_id="thread",status="responded")
    oa.db.session.add(lead);oa.db.session.commit()
    oa._audit_actor(lead.id,"inbound_processed",{"message_id":"faq"},{"stage":"unclear"},"scheduler")
    oa.db.session.commit()
    monkeypatch.setattr(scanner,"_gmail_thread_reply_state",lambda _:{"ok":True,"replied":True,"reply_evidence":[{"message_id":"faq","from_email":lead.contact_email,"text":"How long is the call"}]})
    calls=[]
    monkeypatch.setattr(scanner,"_route_persisted_reply",lambda *a:calls.append(1) or {"ok":True,"stage":"question_answered"})
    assert scanner.scan_real_inbound_replies()["processed"][0]["stage"]=="question_answered"
    assert scanner.scan_real_inbound_replies()["processed"][0]["stage"]=="already_processed"
    assert calls==[1]


def test_controlled_followup_cannot_target_a_prospect(env):
    lead=oa.OutreachLead(company="Prospect",contact_email="owner@example.com",verification="verified")
    oa.db.session.add(lead);oa.db.session.commit()
    result=oa.process_due_followups(controlled_test_lead_id=lead.id)
    assert not result["ok"] and result["error"]=="CONTROLLED_TEST_LEAD_REQUIRED"
    assert oa.FollowupSchedulerRun.query.count()==0


def test_controlled_followup_uses_real_processor_but_only_test_lead(env,monkeypatch):
    rows=[oa.OutreachLead(company="Test",contact_email="neyolabs@gmail.com",verification="controlled_followup_test",gmail_thread_id="test-thread",status="sent",follow_up_due_at=datetime.utcnow()-timedelta(minutes=1)),oa.OutreachLead(company="Prospect",contact_email="owner@example.com",gmail_thread_id="prospect-thread",status="sent",follow_up_due_at=datetime.utcnow()-timedelta(minutes=1))]
    oa.db.session.add_all(rows);oa.db.session.commit()
    monkeypatch.setattr(oa,"_gmail_thread_reply_state",lambda _:{"ok":True,"stop":False})
    monkeypatch.setattr(oa,"_draft_email",lambda *a,**k:{"ok":True,"subject":"Test","body":"Checking in"})
    sent=[]
    monkeypatch.setattr(oa,"_safe_send",lambda lead,**kw:sent.append(lead.id) or {"ok":True,"send_receipt":{"message_id":"sent","thread_id":"test-thread"}})
    first=oa.process_due_followups(controlled_test_lead_id=rows[0].id)
    second=oa.process_due_followups(controlled_test_lead_id=rows[0].id)
    assert first["ok"] and second["duplicate_run_suppressed"]
    assert sent==[rows[0].id] and rows[1].follow_up_count==0


def test_smoke_disabled_without_explicit_configuration(env,monkeypatch):
    from production_smoke import run_configured_smoke
    monkeypatch.delenv("AUTOMAKE_SMOKE_RUN_ID",raising=False)
    assert run_configured_smoke()=={"enabled":False}


def test_missing_thread_recovered_from_authorized_sent_message(env, monkeypatch):
    import v1_orchestration as scanner
    lead=oa.OutreachLead(company="Provided contact",contact_email="owner@example.com",status="needs_evidence",gmail_thread_id="")
    oa.db.session.add(lead);oa.db.session.flush()
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,recipient=lead.contact_email,
        kind="initial",sequence=0,idempotency_key="recovery-test",status="sent",message_id="sent-message"))
    oa.db.session.commit()
    class GmailMessage:
        ok=True
        def json(self): return {"threadId":"recovered-thread"}
    called=[]
    monkeypatch.setattr(scanner.requests if hasattr(scanner,"requests") else __import__("requests"),"get",
        lambda url, **kwargs: GmailMessage())
    monkeypatch.setattr(oa,"gmail_access_token",lambda:"test-token")
    monkeypatch.setattr(scanner,"_gmail_thread_reply_state",lambda thread:called.append(thread) or {"ok":True,"replied":False})
    result=scanner.scan_real_inbound_replies()
    assert result["ok"] and called==["recovered-thread"]
    assert lead.gmail_thread_id=="recovered-thread"


def test_unactivated_provided_email_never_enters_inbound_recovery(env,monkeypatch):
    import v1_orchestration as scanner
    lead=oa.OutreachLead(company="Unactivated",contact_email="unsent@example.com",status="needs_evidence")
    oa.db.session.add(lead);oa.db.session.commit()
    monkeypatch.setattr(scanner,"_gmail_thread_reply_state",lambda *args:pytest.fail("Unsent email was monitored"))
    assert scanner.scan_real_inbound_replies()["checked"]==0
