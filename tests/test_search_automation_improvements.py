import json
from datetime import datetime, timedelta
import pytest
import smart_search as search
import outreach_automation as oa
import v1_orchestration as orchestration


def test_hiring_role_does_not_include_location_or_review_alternative():
    query="Find companies hiring AI automation engineers in Hampton Roads or with missed calls"
    assert search._requested_role_terms(query)==["ai","automation","engineers"]
    assert "response_complaints" in search._verification_intent(query)


def test_wrong_company_cannot_pass_deterministic_promotion():
    row=dict(candidate_name="Coastal HVAC",verification_research=True,url="https://another.example/jobs",title="Other Company",page_text="We are hiring technicians")
    assert search._deterministic_need_verification([row],"Find companies hiring technicians")==[]


def test_actual_callback_complaint_supports_review_channel():
    row=dict(candidate_name="Coastal HVAC",verification_research=True,url="https://reviews.example/coastal",title="Coastal HVAC review",page_text="They never called me back.")
    result=search._deterministic_need_verification([row],"Find businesses with missed callbacks")
    assert result[0]["verified_channels"]==["response_complaints"]


def test_stale_snippet_is_not_current_contact_proof(monkeypatch):
    monkeypatch.setattr(orchestration,"_public_contact_evidence",lambda _:([],{"attempted":1}))
    assert orchestration._verified_public_email(dict(website="https://example.com",evidence=[dict(url="https://example.com/contact",text="owner@example.com")]))==("", "")


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=test-key")
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def test_scanner_handles_later_reply_once_and_ignores_other_sender(env,monkeypatch):
    lead=oa.OutreachLead(company="Example",contact_email="owner@example.com",gmail_thread_id="t1",status="interested",replied_at=datetime.utcnow())
    oa.db.session.add(lead);oa.db.session.commit()
    messages=[dict(message_id="m1",from_email="owner@example.com",internal_date="100",text="Interested")]
    monkeypatch.setattr(orchestration,"_gmail_thread_reply_state",lambda _:dict(ok=True,replied=True,reply_evidence=messages))
    calls=[]
    monkeypatch.setattr(orchestration,"_route_persisted_reply",lambda lead,reply,now:calls.append(reply["reply_evidence"][-1]["message_id"]) or dict(ok=True,stage="interested"))
    orchestration.scan_real_inbound_replies();orchestration.scan_real_inbound_replies()
    messages.append(dict(message_id="m2",from_email="owner@example.com",internal_date="200",text="October 11th"))
    orchestration.scan_real_inbound_replies()
    messages.append(dict(message_id="m3",from_email="stranger@example.net",internal_date="300",text="Book a meeting"))
    orchestration.scan_real_inbound_replies()
    assert calls==["m1","m2"]


def test_shared_followup_processor_delivers_due_lead_once(env,monkeypatch):
    lead=oa.OutreachLead(company="Example",contact_email="owner@example.com",gmail_thread_id="t1",status="sent",follow_up_due_at=datetime.utcnow()-timedelta(days=1))
    oa.db.session.add(lead);oa.db.session.commit()
    monkeypatch.setattr(oa,"_gmail_thread_reply_state",lambda _:dict(ok=True,stop=False))
    monkeypatch.setattr(oa,"_draft_email",lambda *a,**k:dict(ok=True,subject="Follow-up",body="Checking in"))
    calls=[]
    monkeypatch.setattr(oa,"_safe_send",lambda *a,**k:calls.append(k) or dict(ok=True,send_receipt=dict(message_id="out1",thread_id="t1")))
    first=oa.process_due_followups();second=oa.process_due_followups()
    assert first["ok"] and first["processed"][0]["status"]=="followup_sent"
    assert second["duplicate_run_suppressed"]
    assert len(calls)==1 and lead.follow_up_count==1
