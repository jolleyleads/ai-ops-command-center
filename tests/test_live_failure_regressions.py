"""Reproduce production failures without external messages or calendar writes."""
from unittest.mock import Mock
import pytest


def test_every_json_mode_research_input_requests_json(monkeypatch):
    import research_agent as agent
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        assert "json" in kwargs["input"].lower()
        return Mock(output_text='{"intent":"businesses","tool_calls":[{"tool":"business_search","query":"Example"}],"candidates":[],"relevant_urls":[]}')
    monkeypatch.setenv("OPENAI_API_KEY","test-only-key")
    monkeypatch.setattr(agent,"_client",lambda:Mock(responses=Mock(create=create)))
    assert agent.plan_research("Example")["planning_degraded"] is False
    assert agent.recover_tool_plan("Example")["planning_recovered"] is True
    agent.extract_candidates("Example","",[{"url":"https://example.com"}])
    agent.evaluate_research("Example","",[{"url":"https://example.com"}])
    assert len(calls)==4


@pytest.fixture()
def oauth(monkeypatch):
    import gmail_connect as google
    google._token_cache.clear()
    monkeypatch.setattr(google,"_client_credentials",lambda:("test-client","test-secret"))
    monkeypatch.setattr(google.time,"sleep",lambda _:None)
    yield google
    google._token_cache.clear()


def response(ok=True,status=200,**data):
    return Mock(ok=ok,status_code=status,json=lambda:data)


def test_transient_google_refresh_recovers_and_reuses_grant(oauth,monkeypatch):
    post=Mock(side_effect=[response(False,500,error="internal_failure"),response(access_token="test-grant",expires_in=3600)])
    monkeypatch.setattr(oauth.requests,"post",post)
    assert oauth._refresh_access_token("test-refresh")=="test-grant"
    assert oauth._refresh_access_token("test-refresh")=="test-grant"
    assert post.call_count==2


def test_invalid_grant_is_not_retried(oauth,monkeypatch):
    post=Mock(return_value=response(False,400,error="invalid_grant"))
    monkeypatch.setattr(oauth.requests,"post",post)
    with pytest.raises(RuntimeError,match="invalid_grant"):
        oauth._refresh_access_token("test-refresh")
    assert post.call_count==1


def test_refresh_retry_budget_stops_failure(oauth,monkeypatch):
    post=Mock(return_value=response(False,500,error="internal_failure"))
    monkeypatch.setattr(oauth.requests,"post",post)
    with pytest.raises(RuntimeError,match="internal_failure"):
        oauth._refresh_access_token("test-refresh")
    assert post.call_count==3 and oauth._token_cache=={}


def test_expiry_and_changed_credentials_refresh_again(oauth,monkeypatch):
    post=Mock(return_value=response(access_token="test-grant",expires_in=3600))
    monkeypatch.setattr(oauth.requests,"post",post)
    clock=[0.0]
    monkeypatch.setattr(oauth.time,"monotonic",lambda:clock[0])
    oauth._refresh_access_token("first")
    clock[0]=3541
    oauth._refresh_access_token("first")
    oauth._refresh_access_token("second")
    assert post.call_count==3


@pytest.mark.parametrize("data",[{}, {"calendars":{"primary":{"errors":[{"reason":"notFound"}]}}}, {"calendars":{"primary":{"busy":None}}}])
def test_missing_or_failed_calendar_is_never_available(monkeypatch,data):
    from src import google_calendar_provider as calendar
    monkeypatch.setattr(calendar,"_headers",lambda:{})
    monkeypatch.setattr(calendar.requests,"post",Mock(return_value=response(**data)))
    assert calendar.check_availability({"start":"start","end":"end","timezone":"UTC"})["ok"] is False


def test_booking_window_must_match_availability_receipt():
    from src.calendar_booking import execute_booking
    req=dict(booking_ready=True,validated=True,start="2030-01-01T12:00:00+00:00",end="2030-01-01T12:30:00+00:00",timezone="UTC",attendee_email="test@example.com")
    create=Mock()
    result=execute_booking(req,lambda _:dict(ok=True,available=True,checked_start="2030-01-02T12:00:00+00:00",checked_end=req["end"]),create)
    assert result["stage"]=="unavailable"
    create.assert_not_called()


def test_records_fallback_accepts_only_government_sources(monkeypatch):
    import smart_search as search
    monkeypatch.setattr(search,"_search_public_records",lambda *a:{"configured":False,"results":[],"message":"Google HTTP 403"})
    monkeypatch.setattr(search,"_exa_search",lambda *a:{"results":[{"url":"https://city.gov/permits"},{"url":"https://city.gov.example.com/permits"},{"url":"https://example.com/directory"}]})
    rows,message=search._run_tool({"tool":"public_records","query":"permits"})
    assert [x["url"] for x in rows]==["https://city.gov/permits"]
    assert "claims still require verification" in message


def test_controlled_e2e_passes_domain_gate_without_bypassing_it(monkeypatch):
    import commercial_app
    import production_e2e as e2e
    import outreach_automation as oa
    monkeypatch.setenv("OPERATOR_CONTROL_TOKEN","test-operator")
    monkeypatch.setenv("PRODUCTION_E2E_RECIPIENT","jolleysalesfloor@gmail.com")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEY_VERSION","v1")
    monkeypatch.setenv("QUALIFICATION_SIGNING_KEYS","v1=test-signing-key")
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        called=[]
        def send(lead,**kwargs):
            called.append(lead)
            assert oa._recipient_matches_source_domain(lead) is True
            return {"ok":True,"stage":"sent","send_receipt":{"message_id":"test-message","thread_id":"test-thread"}}
        monkeypatch.setattr(oa,"_safe_send",send)
        monkeypatch.setattr(e2e,"_next_available_slot",lambda _:(None,[{"ok":False}]))
        client=oa.app.test_client()
        assert client.post("/api/operator/production-e2e",json={}).status_code==401
        assert called==[]
        denied=client.post("/api/operator/production-e2e",headers={"X-Operator-Token":"test-operator"},json={"recipient":"other@example.com"})
        assert denied.status_code==403 and called==[]
        result=client.post("/api/operator/production-e2e",headers={"X-Operator-Token":"test-operator"},json={}).get_json()
        assert result["steps"]["gmail"]["pass"] is True
        assert result["steps"]["interested_reply"]["pass"] is None
        assert result["steps"]["interested_reply"]["simulated"] is True
        oa.db.session.remove();oa.db.drop_all()
