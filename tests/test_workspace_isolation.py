import time
import pytest
import commercial_app
import customer_auth as auth
import outreach_automation as oa
import campaign_jobs as jobs
import background_research as research
import workspace_security as security

@pytest.fixture
def identities(monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN','isolation-token')
    monkeypatch.setenv('GOOGLE_LOGIN_CLIENT_ID','client')
    monkeypatch.setenv('GOOGLE_LOGIN_CLIENT_SECRET','secret')
    monkeypatch.setenv('GOOGLE_LOGIN_ALLOWED_EMAILS','owner@example.com,customer@example.com')
    monkeypatch.setenv('AUTOMAKE_WORKSPACE_OWNER_EMAILS','owner@example.com')
    monkeypatch.setattr(oa.app,'secret_key','isolated-test-signature')
    monkeypatch.setattr(jobs,'kick_execution_worker',lambda:None)
    monkeypatch.setattr(research,'kick_worker',lambda:None)
    with oa.app.app_context():
        oa.db.drop_all();oa.db.create_all()
        clients=[]
        for email in ['owner@example.com','customer@example.com']:
            client=oa.app.test_client()
            identity={'email':email,'sub':email,'expires':int(time.time())+3600}
            identity['proof']=auth._proof(identity)
            with client.session_transaction() as session:
                session['google_identity']=identity;session['csrf_token']='csrf'
            clients.append(client)
        yield clients
        oa.db.session.remove();oa.db.drop_all()


def test_two_verified_identities_cannot_read_other_workspace(identities):
    owner,customer=identities
    legacy=oa.OutreachLead(company='Owner lead',score=10)
    isolated=oa.OutreachLead(company='Customer lead',score=20)
    oa.db.session.add_all([legacy,isolated]);oa.db.session.flush()
    import hashlib
    security.claim('lead',isolated.id,'customer-'+hashlib.sha256(b'customer@example.com').hexdigest())
    oa.db.session.commit()
    assert [x['company'] for x in owner.get('/api/chat/dashboard').json['leads']]==['Owner lead']
    assert [x['company'] for x in customer.get('/api/chat/dashboard').json['leads']]==['Customer lead']
    assert owner.get(f'/api/chat/dashboard/leads/{isolated.id}').status_code==404
    assert customer.get(f'/api/chat/dashboard/leads/{legacy.id}').status_code==404
    assert customer.post('/api/outreach/leads',json={'company':'x'},headers={'X-CSRF-Token':'csrf'}).status_code==403
    assert customer.get('/api/gmail/status').status_code==403
    assert customer.get('/api/chat/access').json['sending_available'] is False


def test_anonymous_cannot_launch_or_inspect_privileged_jobs(identities):
    client=oa.app.test_client()
    for path in ['/api/demo/campaigns/launch','/api/operator/v1-1-acceptance-once','/api/outreach/leads']:
        assert client.post(path,json={}).status_code==401
    assert client.get('/api/demo/leads').status_code==401
    assert client.get('/api/credentials/status').status_code==401
    assert client.get('/api/gmail/status').status_code==401


def test_public_research_has_cookie_bound_ownership(identities):
    first,second=oa.app.test_client(),oa.app.test_client()
    launch=first.post('/api/research/jobs',json={'prompt':'Find businesses'})
    assert launch.status_code==202
    assert first.get(launch.json['poll_url']).status_code==200
    assert second.get(launch.json['poll_url']).status_code==404
    assert second.post(launch.json['poll_url']+'/cancel').status_code==404
    assert first.post(launch.json['poll_url']+'/cancel',headers={'Origin':'https://attacker.example'}).status_code==403


def test_session_mutations_require_csrf(identities):
    owner,_=identities
    assert owner.post('/api/demo/campaigns/launch',json={'target_customer':'HVAC','territory':'Norfolk'}).status_code==403
    assert owner.post('/api/demo/campaigns/launch',json={'target_customer':'HVAC','territory':'Norfolk'},headers={'X-CSRF-Token':'csrf'}).status_code==202


def test_reply_cron_retains_its_own_authentication(identities,monkeypatch):
    import v1_orchestration as orchestration
    from unittest.mock import Mock
    monkeypatch.setenv('OUTREACH_CRON_TOKEN','scanner-only-token')
    scan=Mock(return_value={'ok':True,'checked':0,'processed':[]})
    monkeypatch.setattr(orchestration,'scan_real_inbound_replies',scan)
    client=oa.app.test_client()
    for headers in [{},{'X-Outreach-Cron-Token':'wrong'},{'X-Outreach-Token':'scanner-only-token'}]:
        assert client.post('/api/outreach/process-inbound',headers=headers).status_code==401
    scan.assert_not_called()
    assert client.post('/api/outreach/process-inbound',headers={'X-Outreach-Cron-Token':'scanner-only-token'}).status_code==200
    scan.assert_called_once()
    assert client.get('/api/chat/dashboard',headers={'X-Outreach-Cron-Token':'scanner-only-token'}).status_code==401


def test_search_get_cannot_trigger_outreach_and_post_requires_csrf(identities,monkeypatch):
    import smart_search
    import smart_search_outreach_hook as bridge
    import v1_orchestration as orchestration
    from unittest.mock import Mock
    owner,_=identities
    monkeypatch.setattr(smart_search,'_smart_search',lambda *args,**kwargs:{'results':[],'count':0})
    ingest,orchestrate=Mock(return_value={}),Mock(return_value={})
    monkeypatch.setattr(bridge,'ingest_verified_results',ingest)
    monkeypatch.setattr(orchestration,'orchestrate_discovery',orchestrate)
    assert owner.get('/api/smart-search?query=businesses').status_code==200
    assert owner.post('/api/smart-search',json={'query':'businesses'}).status_code==403
    ingest.assert_not_called();orchestrate.assert_not_called()
    assert owner.post('/api/smart-search',json={'query':'businesses'},headers={'X-CSRF-Token':'csrf'}).status_code==200
    orchestrate.assert_called_once()
    assert orchestrate.call_args.kwargs=={'draft_only':True}
