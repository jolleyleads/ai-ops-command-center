import json
from datetime import datetime,timedelta
import pytest
import commercial_app  # Register all routes before any test request.
import background_research as jobs
import smart_search as search


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(jobs,"kick_worker",lambda:None)
    with jobs.app.app_context():
        jobs.db.session.remove();jobs.db.drop_all();jobs.db.create_all()
        yield
        jobs.db.session.remove();jobs.db.drop_all()


def test_background_job_returns_immediately_and_persists_result(env,monkeypatch):
    calls=[]
    monkeypatch.setattr(jobs,"_smart_search",lambda q,loc,**kw:calls.append(kw) or {"results":[],"verified_count":0,"target_met":False})
    client=jobs.app.test_client()
    response=client.post("/api/research/jobs",json={"query":"Find 17 companies", "target_count":17})
    assert response.status_code==202 and calls==[]
    url=response.json["poll_url"]
    assert client.get(url).json["status"]=="queued"
    assert jobs.process_next_research_job()["ok"]
    result=client.get(url)
    assert result.json["status"]=="completed"
    assert result.json["result"]["target_met"] is False
    assert calls==[{"runtime_budget":180,"target_count":17}]
    assert result.headers["Cache-Control"]=="no-store"


def test_interrupted_read_only_job_is_recovered(env,monkeypatch):
    job=jobs.ResearchJob(id="interrupted",prompt_text="companies",status="running",started_at=datetime.utcnow()-timedelta(minutes=11))
    jobs.db.session.add(job);jobs.db.session.commit()
    monkeypatch.setattr(jobs,"_smart_search",lambda *a,**k:{"results":[]})
    assert jobs.process_next_research_job()["processed"]==1
    assert job.status=="completed"


def test_ranking_removes_duplicates_and_downgrades_stale_sources():
    rows=[dict(title="Acme",promotion_status="verified",published_at="2020-01-01T00:00:00Z"),dict(title="Fresh",promotion_status="verified",url="https://fresh.example",published_at=datetime.utcnow().isoformat()),dict(title="Fresh",promotion_status="candidate")]
    result=search.rank_research_results(rows)
    assert [x["title"] for x in result]==["Fresh","Acme"]
    assert result[1]["promotion_status"]=="candidate"


def test_recent_review_requires_publication_date():
    row=dict(title="Acme",promotion_status="verified",verified_channels=["response_complaints"])
    assert search.rank_research_results([row],query="Find recent callback complaints")[0]["promotion_status"]=="candidate"


def test_closed_job_and_wrong_location_do_not_pass():
    row=dict(candidate_name="Acme",verification_research=True,url="https://acme.example",title="Acme hiring engineers",page_text="Acme Norfolk Virginia hiring engineers. Applications closed.")
    assert search._deterministic_need_verification([row],"Find companies hiring engineers")==[]
    row["page_text"]="Acme Norfolk Virginia hiring engineers. Apply now."
    assert search._deterministic_need_verification([row],"Find companies hiring engineers","Washington DC")==[]


def test_deep_search_uses_evidence_followups_and_returns_shortfall(monkeypatch):
    calls=[]
    monkeypatch.setattr(search,"plan_research",lambda *a:{"tool_calls":[{"tool":"web_search","query":"initial"}]})
    monkeypatch.setattr(search,"_memory",lambda *a:[])
    monkeypatch.setattr(search,"_inspect",lambda *a:None)
    monkeypatch.setattr(search,"remember_evidence",lambda *a:None)
    monkeypatch.setattr(search,"extract_candidates",lambda q,loc,rows:[dict(name=r["title"],discovery_urls=[r["url"]]) for r in rows])
    def retrieve(plan,*a):
        calls.extend(c["query"] for c in plan)
        if plan[0]["query"]=="initial":return [dict(title="Acme",url="https://acme.example")],[],["web_search"]
        return [dict(title="Fresh",url="https://fresh.example")],[],["web_search"]
    monkeypatch.setattr(search,"_run_calls",retrieve)
    def verify(q,loc,candidates,*a):
        return ([dict(candidate_name="Fresh",verification_research=True,title="Fresh hiring engineers",subtitle="Fresh hiring engineers. Apply now.",url="https://fresh.example/jobs",published_at=datetime.utcnow().isoformat())] if any(c["name"]=="Fresh" for c in candidates) else []),[],[]
    monkeypatch.setattr(search,"_candidate_followups",verify)
    monkeypatch.setattr(search,"evaluate_research",lambda *a:{"sufficient":False,"followup_tool_calls":[dict(tool="web_search",query="Fresh official careers page")]})
    result=search._smart_search("Find companies hiring engineers","",runtime_budget=180,target_count=2)
    assert calls==["initial","Fresh official careers page"]
    assert result["research_rounds"]==1
    assert result["verified_count"]==1 and result["target_met"] is False
