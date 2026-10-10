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
    assert calls==[{"runtime_budget":540,"target_count":17}]
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
    assert calls[:2]==["initial","Fresh official careers page"]
    assert len(calls)==7 and len(set(calls))==7
    assert result["research_rounds"]==6
    assert result["verified_count"]==1 and result["target_met"] is False


def test_company_search_replaces_broad_job_feed_with_claim_searches():
    q="Find businesses hiring automation engineers or with unanswered call reviews"
    calls=search._company_discovery_calls(q,"Norfolk Virginia",[{"tool":"job_search","query":q}])
    assert {c["tool"] for c in calls}=={"web_search","exa_search"}
    assert "automation engineers" in calls[0]["query"]
    assert "unanswered calls" in calls[1]["query"]


def test_discovery_url_can_be_reused_as_company_verification():
    rows=search._dedupe([dict(url="https://acme.example/jobs",title="Jobs"),dict(url="https://acme.example/jobs",candidate_name="Acme",verification_research=True,page_text="Acme hiring engineers")])
    assert len(rows)==1 and rows[0]["verification_research"]
    display=search._company_discovery_rows([dict(name="Acme",discovery_urls=[rows[0]["url"]])],rows)
    assert display[0]["title"]=="Acme"


def test_evaluator_sees_company_proof_after_large_job_feed(monkeypatch):
    import research_agent as agent
    from types import SimpleNamespace
    captured=[]
    def respond(**kw):
        captured.append(json.loads(kw["input"].split("\n",1)[1]))
        return SimpleNamespace(output_text='{"sufficient":false}')
    monkeypatch.setenv("OPENAI_API_KEY","test")
    monkeypatch.setattr(agent,"_client",lambda:SimpleNamespace(responses=SimpleNamespace(create=respond)))
    feed=[dict(title=f"Unrelated role {i}",url=f"https://jobs.example/{i}",research_tool="job_search") for i in range(60)]
    proof=dict(title="Acme",url="https://acme.example/jobs",verification_research=True,candidate_name="Acme",page_text="Acme hiring automation engineers")
    agent.evaluate_research("companies hiring automation engineers","Norfolk",feed+[proof])
    assert captured[0]["evidence"][0]["candidate_name"]=="Acme"


def test_contacts_require_company_bound_source_and_remain_unconfirmed():
    rows=[dict(title="Acme",candidate_name="Acme")]
    evidence=[dict(candidate_name="Acme",title="Other firm",page_text="Other firm email other@example.com",url="https://other.example"),dict(candidate_name="Acme",title="Acme contact",page_text="Acme email info@acme.example",url="https://acme.example/contact")]
    result=search._attach_source_contacts(rows,evidence)[0]
    assert [c["email"] for c in result["contacts"]]==["info@acme.example"]
    assert result["contacts"][0]["source_url"]=="https://acme.example/contact"
    assert "unconfirmed" in result["contacts"][0]["status"]


def test_provider_deadline_keeps_fast_evidence_without_waiting_for_stalled_call(monkeypatch):
    import time
    def run(call):
        if call["tool"]=="exa_search":time.sleep(.2);return [],"timeout"
        return [dict(url="https://acme.example",title="Acme")],""
    monkeypatch.setattr(search,"_run_tool",run)
    started=time.monotonic()
    rows,messages,used=search._run_calls([dict(tool="exa_search"),dict(tool="web_search")],started+.05)
    assert rows[0]["title"]=="Acme" and used==["web_search"]
    assert time.monotonic()-started<.15
    assert any("deadline" in m for m in messages)


def test_candidate_timeout_falls_back_to_web_and_retains_contact_source(monkeypatch):
    monkeypatch.setattr(search,"_exa_search",lambda *a:{"results":[],"message":"Exa Search failed: ReadTimeout."})
    monkeypatch.setattr(search,"_web_search",lambda *a:{"results":[dict(title="Acme contact",url="https://acme.example/contact",page_text="Acme hiring engineers. Apply now. Email info@acme.example or call (757) 555-1234.")],"message":""})
    rows,msg,used=search._candidate_followups("Find companies hiring engineers","",[dict(name="Acme",discovery_urls=[])],10**12,1)
    assert "web_search" in used
    contact=search._attach_source_contacts([dict(title="Acme",candidate_name="Acme")],rows)[0]
    assert {c.get("email") or c.get("phone") for c in contact["contacts"]}=={"info@acme.example","(757) 555-1234"}


def test_search_only_acceptance_creates_job_without_mailbox_access(env,monkeypatch):
    import production_smoke as smoke
    import operator_conversation_import as importer
    monkeypatch.setenv("AUTOMAKE_SMOKE_RUN_ID","search-only-regression")
    monkeypatch.setenv("AUTOMAKE_SMOKE_SEARCH_ONLY","1")
    monkeypatch.setattr(importer,"import_and_process",lambda *a:pytest.fail("search-only test must not use email"))
    state=smoke.run_configured_smoke()
    assert state["prepared"] and state["test_lead_id"] is None
    job=jobs.db.session.get(jobs.ResearchJob,state["research_job_id"])
    job.status="completed";job.result_json=json.dumps({"results":[],"verified_count":0,"target_met":False});jobs.db.session.commit()
    assert smoke.run_configured_smoke()["completed"]
