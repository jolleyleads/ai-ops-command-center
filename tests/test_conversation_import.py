from unittest.mock import Mock
import base64
from datetime import datetime
import pytest


def test_explicit_human_date_and_quoted_history():
    from src.automatic_reply_router import extract_explicit_booking,current_reply_text,classify_reply
    text="Yes I am. Are you free October 11th 2030 at 2 pm On Sat, Oct 10, 2030 Matthew wrote: Hey, are you looking for an automation engineer?"
    clean=current_reply_text(text)
    assert classify_reply(clean)["classification"]=="interested"
    result=extract_explicit_booking(clean)
    assert result==dict(start="2030-10-11T14:00:00-04:00",end="2030-10-11T14:30:00-04:00",timezone="America/New_York")


@pytest.mark.parametrize("text",["Yes, tomorrow at 2 pm", "October 32nd 2030 at 2 pm", "October 11th 2030 at 2 pm Pacific", "October 11th at 2 pm"])
def test_ambiguous_dates_stay_pending(text):
    from src.automatic_reply_router import extract_explicit_booking
    assert not extract_explicit_booking(text)["start"]


@pytest.fixture()
def env(monkeypatch):
    import commercial_app
    import outreach_automation as oa
    monkeypatch.setenv("GMAIL_FROM_EMAIL","jolleyleads@gmail.com")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=test-signing-key")
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield oa
        oa.db.session.remove();oa.db.drop_all()


def gmail_thread(sender="jolleyleads@gmail.com"):
    return {"messages":[{"id":"original","threadId":"thread","payload":{"mimeType":"text/plain","body":{"data":base64.urlsafe_b64encode(b"Are you looking for an automation engineer?").decode()},"headers":[{"name":"From","value":sender},{"name":"To","value":"neyolabs@gmail.com"},{"name":"Subject","value":"Automation engineer"}]}}]}


def setup_provider(monkeypatch,oa):
    import operator_conversation_import as imported
    monkeypatch.setattr(imported.gmail_connect,"gmail_access_token",lambda:"test-grant")
    monkeypatch.setattr(imported.requests,"get",lambda url,**k:Mock(ok=True,json=lambda:{"emailAddress":"jolleyleads@gmail.com"} if url.endswith("/profile") else gmail_thread()))
    monkeypatch.setattr(oa,"classify_inbound",lambda *a,**k:oa._gmail_thread_reply_state("thread"))
    monkeypatch.setattr(oa,"_gmail_thread_reply_state",lambda _:{"ok":True,"replied":True,"reply_evidence":[{"message_id":"reply","thread_id":"thread","from_email":"neyolabs@gmail.com","text":"Yes I am. Are you free October 11th 2030 at 2 pm On Sat, Oct 10, 2030 Matthew wrote: Are you looking for an automation engineer?"}]})
    monkeypatch.setattr(oa,"check_availability",lambda req:dict(ok=True,available=True,checked_start=req["start"],checked_end=req["end"]))
    monkeypatch.setattr(oa,"create_event",lambda req,**kw:dict(ok=True,event_id=kw["idempotency_key"],start=req["start"],end=req["end"]))
    sent=[]
    monkeypatch.setattr(oa,"_gmail_send",lambda *args:sent.append(args) or dict(ok=True,message_id="confirmation",thread_id="thread"))
    return imported,sent


def test_provider_reply_books_and_confirms_once(env,monkeypatch):
    imported,sent=setup_provider(monkeypatch,env)
    data=dict(recipient="neyolabs@gmail.com",company="Neo Labs",thread_id="thread",message_id="original")
    result=imported.import_and_process(data)
    assert result["ok"] and result["stage"]=="booked"
    assert result["real_reply_message_ids"]==["reply"]
    assert env.OutreachReplyEvidence.query.one().message_id=="reply"
    assert env.OutreachBookingAttempt.query.one().status=="confirmed"
    assert len(sent)==1 and sent[0][3]=="thread"
    assert env.OutreachSendAttempt.query.one().kind=="booking_confirmation"
    assert imported.import_and_process(data)["duplicate_suppressed"] is True
    assert len(sent)==1


def test_import_rejects_wrong_provider_sender_and_unapproved_recipient(env,monkeypatch):
    imported,sent=setup_provider(monkeypatch,env)
    data=dict(recipient="neyolabs@gmail.com",company="Neo Labs",thread_id="thread",message_id="original")
    monkeypatch.setattr(imported.requests,"get",lambda url,**k:Mock(ok=True,json=lambda:{"emailAddress":"jolleyleads@gmail.com"} if url.endswith("/profile") else gmail_thread("other@example.com")))
    assert imported.import_and_process(data)["error"]=="provider_envelope_mismatch"
    assert imported.import_and_process({**data,"recipient":"other@example.com"})["ok"] is False
    assert env.OutreachLead.query.count()==0 and sent==[]


def test_import_endpoint_requires_authentication(env):
    client=env.app.test_client()
    assert client.post("/api/operator/conversation-import",json={}).status_code==401
