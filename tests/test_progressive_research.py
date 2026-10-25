import pytest
import commercial_app
import background_research as r
from src.research_policy import requested_target_count

@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(r,'kick_worker',lambda:None)
    with r.app.app_context():
        r.db.drop_all();r.db.create_all()
        yield r.app.test_client()
        r.db.session.remove();r.db.drop_all()

@pytest.mark.parametrize('count',[10,20])
def test_explicit_supported_targets(client,count):
    result=client.post('/api/research/jobs',json={'prompt':'Find businesses','target_count':count})
    assert result.status_code==202
    assert client.get(result.json['poll_url']).json['target_count']==count

def test_hundred_is_rejected_before_work_starts(client):
    result=client.post('/api/research/jobs',json={'prompt':'Find 100 businesses','target_count':100})
    assert result.status_code==422
    assert result.json['maximum_results']==20 and result.json['work_started'] is False
    assert r.ResearchJob.query.count()==0

def test_progress_survives_phases_and_cancel_fences_result(client,monkeypatch):
    from src.execution_deadline import checkpoint
    launch=client.post('/api/research/jobs',json={'prompt':'Find businesses'})
    def search(*a,**k):
        checkpoint('verifying',candidates=[{'company':'Source business','source_url':'https://source.example','classification':'Candidate'}],discovered=1,requested=10)
        job=r.db.session.get(r.ResearchJob,launch.json['job_id'])
        assert 'Source business' in job.result_json
        checkpoint('contacts')
        assert 'Source business' in job.result_json
        job.status='cancelled';r.db.session.commit()
        return {'results':[]}
    monkeypatch.setattr(r,'_smart_search',search)
    result=r.process_next_research_job()
    assert result['lease_lost'] is True
    assert client.get(launch.json['poll_url']).json['status']=='cancelled'


def test_prompt_only_count_is_not_silently_truncated(client):
    response=client.post('/api/research/jobs',json={'prompt':'Find 100 HVAC businesses'})
    assert response.status_code==422 and response.json['work_started'] is False
    assert r.ResearchJob.query.count()==0
    from src.research_policy import target_count_from_prompt
    assert target_count_from_prompt('Find businesses along Route 17')==10
    assert target_count_from_prompt('Find businesses open 24 hours')==10
    assert target_count_from_prompt('Find 20 HVAC businesses')==20
    assert target_count_from_prompt('Give me five electrical businesses only with their emails available')==5
    assert target_count_from_prompt('Please show me up to TWO electrical companies')==2
    assert target_count_from_prompt('Give me five electrical businesses',explicit=3)==3
    from smart_search import _business_terms
    from src.prospect_quality import request_spec
    assert _business_terms('Give me five electrical businesses','Norfolk, VA')==['electrical']
    assert request_spec('Give me five electrical businesses')['business_terms']==['electrical']


def test_research_retry_resumes_same_owned_job(client):
    data={'prompt':'Find 10 HVAC businesses','location':'Norfolk'}
    first=client.post('/api/research/jobs',json=data,headers={'Idempotency-Key':'retry-one'})
    second=client.post('/api/research/jobs',json=data,headers={'Idempotency-Key':'retry-one'})
    assert first.json['job_id']==second.json['job_id'] and r.ResearchJob.query.count()==1
    assert client.post('/api/research/jobs',json={**data,'location':'Richmond'},headers={'Idempotency-Key':'retry-one'}).status_code==409
    other=r.app.test_client()
    assert other.post('/api/research/jobs',json=data,headers={'Idempotency-Key':'retry-one'}).status_code==404


def test_provider_failure_keeps_discovered_businesses(client,monkeypatch):
    from src.execution_deadline import checkpoint
    launch=client.post('/api/research/jobs',json={'prompt':'Find 10 HVAC businesses'})
    def fail(*a,**kw):
        checkpoint('verifying',candidates=[{'company':'Source-backed candidate','source_url':'https://business.example'}],discovered=1)
        raise RuntimeError('simulated provider failure')
    monkeypatch.setattr(r,'_smart_search',fail)
    r.process_next_research_job()
    state=client.get(launch.json['poll_url']).json
    assert state['status']=='failed'
    assert state['progress']['candidates'][0]['company']=='Source-backed candidate'
    assert state['progress']['requested']==10
