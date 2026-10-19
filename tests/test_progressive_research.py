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
