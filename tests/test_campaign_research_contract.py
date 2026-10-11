import json
from datetime import datetime, timedelta
import pytest
import commercial_app
import background_research as research
import campaign_jobs as jobs
import customer_demo as demo
import smart_search as search
from src.research_policy import research_budget_seconds, research_target_count
from scripts.smart_search_smoke import validate_payload, CASES


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(jobs,"kick_execution_worker",lambda:None)
    monkeypatch.setattr(research,"kick_worker",lambda:None)
    with jobs.app.app_context():
        jobs.db.session.remove();jobs.db.drop_all();jobs.db.create_all()
        yield jobs.app.test_client()
        jobs.db.session.remove();jobs.db.drop_all()


@pytest.mark.parametrize("target,budget",[(1,240),(3,252),(10,420),(17,540),(20,540)])
def test_campaign_and_background_research_share_budget(env,monkeypatch,target,budget):
    calls=[]
    def discover(q,loc,**kw):
        calls.append(kw)
        return {"results":[],"target_met":False,"runtime_budget_seconds":kw["runtime_budget"]}
    monkeypatch.setattr(research,"_smart_search",discover)
    monkeypatch.setattr(demo,"_smart_search",discover)
    monkeypatch.setattr(demo,"enhance_discovery",lambda data,*a:data)
    monkeypatch.setattr(demo,"orchestrate_discovery",lambda data:{"qualified":0,"drafted":0,"sent":0})
    job=research.ResearchJob(id="research",prompt_text="Find companies hiring engineers",target_count=target)
    jobs.db.session.add(job);jobs.db.session.commit()
    research.process_next_research_job()
    payload,stage,reason=demo._run_campaign({"target_customer":job.prompt_text,"territory":"Norfolk, VA","target_count":target})
    assert calls==[{"runtime_budget":budget,"target_count":target}]*2
    assert payload["discovery"]["target_met"] is False
    assert payload["outreach"]["sent"]==0


@pytest.mark.parametrize("value,expected",[(None,10),(0,1),(-2,1),(100,20)])
def test_bounded_target_policy(value,expected):
    assert research_target_count(value)==expected
    assert 240<=research_budget_seconds(value)<=540


def test_campaign_launch_is_async_and_idempotent(env,monkeypatch):
    calls=[]
    monkeypatch.setattr(demo,"_run_campaign",lambda data:(calls.append(data) or {"ok":True,"outreach":{"sent":0}},None,None))
    body={"target_customer":"Find companies hiring engineers","territory":"Norfolk, VA","target_count":3}
    first=env.post("/api/demo/campaigns/launch",json=body,headers={"Idempotency-Key":"demo-one"})
    assert first.status_code==202 and calls==[]
    second=env.post("/api/demo/campaigns/launch",json=body,headers={"Idempotency-Key":"demo-one"})
    assert first.json["job_id"]==second.json["job_id"]
    assert env.get(first.json["poll_url"]).json["status"]=="queued"
    assert jobs.process_next_execution_job()["ok"]
    assert jobs.process_next_execution_job()["processed"]==0
    final=env.get(first.json["poll_url"])
    assert final.json["status"]=="completed" and final.json["result"]["ok"]
    assert final.headers["Cache-Control"]=="no-store" and len(calls)==1
    assert env.post("/api/demo/campaigns/launch",json={**body,"territory":"Richmond, VA"},headers={"Idempotency-Key":"demo-one"}).status_code==409


def test_execution_failure_is_persisted_without_retry(env,monkeypatch):
    def fail(data):raise RuntimeError("interrupted")
    monkeypatch.setattr(demo,"_run_campaign",fail)
    launch=env.post("/api/demo/campaigns/launch",json={"target_customer":"companies","territory":"VA"})
    assert not jobs.process_next_execution_job()["ok"]
    final=env.get(launch.json["poll_url"])
    assert final.json["status"]=="failed"
    assert final.json["error"]=="EXECUTION_FAILED_REVIEW_REQUIRED"
    assert jobs.process_next_execution_job()["processed"]==0


def test_stale_execution_is_not_replayed(env,monkeypatch):
    monkeypatch.setattr(demo,"_run_campaign",lambda data:pytest.fail("Interrupted execution must not replay"))
    job=jobs.CampaignExecutionJob(id="interrupted",kind="campaign",payload_json="{}",status="running",started_at=datetime.utcnow()-timedelta(minutes=61))
    jobs.db.session.add(job);jobs.db.session.commit()
    assert jobs.process_next_execution_job()["processed"]==0
    assert env.get("/api/demo/campaigns/jobs/interrupted").json["status"]=="failed"


def test_acceptance_persists_real_nonpass_receipt(env,monkeypatch):
    monkeypatch.setattr(demo,"_run_acceptance",lambda:({"ok":False,"pass":False,"stage":"fresh_lead_proof","reason":"NO_FRESH_LEAD_REACHED_QUALIFIED_AND_DRAFTED"},409))
    launch=env.post("/api/operator/v1-1-acceptance-once",headers={"Idempotency-Key":"acceptance-test"})
    assert launch.status_code==202
    assert not jobs.process_next_execution_job()["ok"]
    final=env.get(launch.json["poll_url"]).json
    assert final["result_http_status"]==409
    assert final["result"]["pass"] is False


def test_campaign_research_error_never_reaches_outreach(env,monkeypatch):
    monkeypatch.setattr(demo,"_smart_search",lambda *a,**k:{"agent_error":"RuntimeError","results":[]})
    monkeypatch.setattr(demo,"orchestrate_discovery",lambda *a:pytest.fail("Search failure cannot launch outreach"))
    assert demo._run_campaign({"target_customer":"companies","territory":"VA"})==(None,"discovery","RESEARCH_AGENT_FAILED")


@pytest.mark.parametrize("degraded",[False,True])
@pytest.mark.parametrize("intent,query,location",CASES+[("web_research","Explain public data sources","")])
def test_semantic_planner_prose_does_not_change_intent_contract(monkeypatch,intent,query,location,degraded):
    monkeypatch.setattr(search,"plan_research",lambda *a:{"intent":"planning_unavailable" if degraded else "A detailed natural language research goal","planning_degraded":degraded,"tool_calls":[{"tool":"web_search","query":query}]})
    monkeypatch.setattr(search,"recover_tool_plan",lambda *a:None)
    monkeypatch.setattr(search,"_run_calls",lambda *a:([],[],["web_search"]))
    monkeypatch.setattr(search,"_memory",lambda *a:[])
    monkeypatch.setattr(search,"remember_evidence",lambda *a:None)
    result=search._smart_search(query,location,runtime_budget=12)
    assert result["intent"]==intent
    assert result["research_intent"]==("planning_unavailable" if degraded else "A detailed natural language research goal")
    assert result["runtime_budget_seconds"]==12
    assert validate_payload(result,intent)==[]


@pytest.mark.parametrize("bad",[{"agent_error":"TypeError"},{"intent":"planner prose"},{"results":[None],"count":1},{"verified_count":1},{"configured":False}])
def test_smoke_rejects_failures_not_just_label_mismatches(bad):
    valid={"intent":"jobs","configured":True,"agent_mode":True,"verification_gate":True,"source":"web_search","count":0,"verified_count":0,"results":[]}
    assert validate_payload({**valid,**bad},"jobs")
