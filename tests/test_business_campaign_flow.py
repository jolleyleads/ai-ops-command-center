import copy
import json
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace
import pytest
import commercial_app
import smart_search as search
import customer_demo as demo
import campaign_jobs as jobs
import outreach_automation as oa
from src import hunter_discovery as hunter
from src import hunter_mailbox as mailbox
from src.company_identity import page_metadata, visible_page_text
from src.contact_assessment import person_email_supported


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setattr(jobs,'kick_execution_worker',lambda:None)
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN','operator-unit-test')
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','false')
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield oa.app.test_client()
        oa.db.session.remove();oa.db.drop_all()


def company_page(city='Norfolk, Virginia',kind='HVAC'):
    raw=f'<title>Acme</title><script type="application/ld+json">{{"@type":"Organization","name":"Acme","url":"https://acme.example/"}}</script><h1>Acme</h1><p>{kind} services in {city}. Email hello@acme.example</p>'
    return {'url':'https://acme.example/','title':'Home | Acme','research_tool':'exa_search','page_text':visible_page_text(raw),'directly_fetched':True,'http_status':200,'observed_at':datetime.now(timezone.utc).isoformat(),**page_metadata(raw)}


def test_plain_business_search_recovers_real_company_without_model_or_places(env,monkeypatch):
    row=company_page()
    monkeypatch.setattr(search,'plan_research',lambda *a:{'tool_calls':[{'tool':'business_search'}]})
    calls=[]
    monkeypatch.setattr(search,'_run_calls',lambda requests,*a:(calls.extend(requests) or [dict(row)],[],['exa_search']))
    monkeypatch.setattr(search,'_memory',lambda *a:[])
    monkeypatch.setattr(search,'extract_candidates',lambda *a:[])
    monkeypatch.setattr(search,'evaluate_research',lambda *a:{})
    monkeypatch.setattr(search,'remember_evidence',lambda *a:None)
    monkeypatch.setattr(search,'_page_snapshot',lambda *a:dict(row))
    result=search._smart_search('Find 1 current HVAC business','Norfolk, Virginia',runtime_budget=25,target_count=1)
    assert {c['tool'] for c in calls}=={'web_search','exa_search','business_search'}
    assert result['candidate_count']==1 and result['verified_count']==1
    assert result['results'][0]['title']=='Acme'
    assert result['results'][0]['verified_channels']==['business_identity']


@pytest.mark.parametrize('change',[{'city':'Richmond, Virginia'},{'kind':'Florist'}])
def test_plain_company_proof_still_requires_requested_type_and_city(change):
    row={**company_page(**change),'candidate_name':'Acme'}
    assert search._deterministic_need_verification([row],'Find 10 HVAC businesses','Norfolk, Virginia')==[]


def test_snippets_cannot_become_business_identity_proof():
    row={**company_page(),'candidate_name':'Acme','directly_fetched':False}
    assert search._deterministic_need_verification([row],'Find 10 HVAC businesses','Norfolk, Virginia')==[]


def test_places_website_survives_model_candidate_extraction(env,monkeypatch):
    name='Acme Comfort'
    place={'title':name,'url':'https://maps.google.com/place/acme','website':'https://comfort.example/','research_tool':'business_search'}
    page={**company_page(),'source_title':name,'source_heading':name,'source_organizations':[],'url':place['website'],'resolved_url':place['website']}
    monkeypatch.setattr(search,'plan_research',lambda *a:{'tool_calls':[{'tool':'business_search'}]})
    monkeypatch.setattr(search,'_run_calls',lambda *a:([dict(place)],[],['business_search']))
    monkeypatch.setattr(search,'_memory',lambda *a:[])
    monkeypatch.setattr(search,'_inspect_discovery',lambda *a:None)
    monkeypatch.setattr(search,'_inspect',lambda *a:None)
    monkeypatch.setattr(search,'extract_candidates',lambda *a:[{'name':name,'discovery_urls':[place['url']]}])
    monkeypatch.setattr(search,'evaluate_research',lambda *a:{})
    monkeypatch.setattr(search,'remember_evidence',lambda *a:None)
    monkeypatch.setattr(search,'_page_snapshot',lambda *a:dict(page))
    result=search._smart_search('Find 1 HVAC business','Norfolk, Virginia',runtime_budget=25,target_count=1)
    assert result['verified_count']==1


def test_authenticated_campaign_authorization_is_durable_and_idempotent(env,monkeypatch):
    body={'target_customer':'Find 10 HVAC businesses','territory':'Norfolk, VA','target_count':10,'sending_limit':10,'send_emails':True}
    assert env.post('/api/chat/campaigns/launch',json=body).status_code==401
    headers={'X-Operator-Token':'operator-unit-test','Idempotency-Key':'one-authorized-campaign'}
    first=env.post('/api/chat/campaigns/launch',json=body,headers=headers)
    second=env.post('/api/chat/campaigns/launch',json=body,headers=headers)
    assert first.status_code==202 and first.json['job_id']==second.json['job_id']
    stored=oa.db.session.get(jobs.CampaignExecutionJob,first.json['job_id'])
    assert json.loads(stored.payload_json)['send_authorized'] is True
    calls=[]
    monkeypatch.setattr(demo,'_run_campaign',lambda payload:(calls.append(payload) or {'ok':True},None,None))
    jobs.process_next_execution_job();jobs.process_next_execution_job()
    assert len(calls)==1 and calls[0]['send_authorized'] is True
    public=env.post('/api/demo/campaigns/launch',json={**body,'send_authorized':True})
    public_job=oa.db.session.get(jobs.CampaignExecutionJob,public.json['job_id'])
    assert 'send_authorized' not in json.loads(public_job.payload_json)


def test_session_campaign_requires_csrf(env):
    with env.session_transaction() as session:
        with oa.app.test_request_context():session['operator_auth']=oa._session_proof()
    body={'target_customer':'HVAC businesses','territory':'VA','send_emails':True}
    assert env.post('/api/chat/campaigns/launch',json=body).status_code==403
    settings=env.get('/api/chat/campaign-settings')
    assert settings.status_code==200
    assert env.post('/api/chat/campaigns/launch',json=body,headers={'X-CSRF-Token':settings.json['csrf_token']}).status_code==202


@pytest.fixture
def active(env,monkeypatch):
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','true')
    monkeypatch.setenv('HUNTER_API_KEY','secret-test-only')
    monkeypatch.setenv('HUNTER_ACCOUNT_EMAIL','neyolabs@gmail.com')


def transport(domain='acme.example',remaining=50,code=200):
    calls=[]
    def get(url,**kw):
        calls.append((url,kw))
        assert kw['allow_redirects'] is False
        assert 'api_key' not in kw['params'] and 'secret-test-only' not in url
        if url.endswith('/account'):data={'email':'neyolabs@gmail.com','plan_name':'Free','requests':{'credits':{'remaining':remaining}}}
        else:data={'domain':domain,'emails':[{'value':'jane@acme.example','first_name':'Jane','last_name':'Smith','position':'Owner','type':'personal','sources':[{'uri':'https://acme.example/team'}]},{'value':'hello@acme.example','type':'generic'}]}
        return SimpleNamespace(status_code=200 if url.endswith('/account') else code,content=b'{}',json=lambda:{'data':data})
    return get,calls


def test_hunter_discovery_is_cached_and_wrong_domain_never_accepted(active):
    get,calls=transport()
    first=hunter.discover_contacts('https://acme.example',get)
    second=hunter.discover_contacts('https://acme.example',get)
    assert len(first['contacts'])==2 and second['cache_hit']
    assert len(calls)==2
    assert 'secret-test-only' not in json.dumps(first)
    bad,_=transport(domain='unrelated.example')
    result=hunter.discover_contacts('https://other.example',bad)
    assert result['contacts']==[] and result['reason_codes']==['HUNTER_DISCOVERY_UNCONFIRMED']


def test_hunter_quota_does_not_trigger_discovery(active):
    get,calls=transport(remaining=0)
    assert hunter.discover_contacts('https://acme.example',get)['reason_codes']==['HUNTER_FREE_QUOTA_UNAVAILABLE']
    assert len(calls)==1


def enrichment(people=True):
    return {'identity_status':'source_bound','company_name':'Acme','fields':{'website':{'value':'https://acme.example','source_url':'https://acme.example','validated':True}},'validated':True,'contact_assessment':{},'decision_maker_candidates':[{'name':'Jane Smith','title':'Owner','status':'source_supported','source_url':'https://acme.example/team'}] if people else []}


def test_hunter_person_address_requires_primary_role_and_durable_association(active,monkeypatch):
    get,_=transport()
    receipt=hunter.discover_contacts('https://acme.example',get)
    monkeypatch.setattr(hunter,'discover_contacts',lambda *a:receipt)
    monkeypatch.setattr(mailbox,'verify_mailbox',lambda email:{'mailbox_status':'provider_verified','deliverability_status':'provider_reported_valid','reason_codes':[]})
    item=enrichment()
    hunter.enrich_contact(item,'https://acme.example',required_person=True)
    assert item['fields']['email']['value']=='jane@acme.example'
    assert person_email_supported(item['contact_assessment'],'jane@acme.example')
    forged=copy.deepcopy(item['contact_assessment']);forged['hunter_association']['cache_key']='nonexistent'
    assert not person_email_supported(forged,'jane@acme.example')
    unresolved=enrichment(people=False)
    hunter.enrich_contact(unresolved,'https://acme.example',required_person=True)
    assert 'email' not in unresolved['fields']
    generic=enrichment(people=False)
    hunter.enrich_contact(generic,'https://acme.example')
    assert generic['fields']['email']['value']=='hello@acme.example'
    assert not person_email_supported(generic['contact_assessment'],'hello@acme.example')


def test_unverified_mailbox_never_becomes_a_hunter_contact(active,monkeypatch):
    get,_=transport();receipt=hunter.discover_contacts('https://acme.example',get)
    monkeypatch.setattr(hunter,'discover_contacts',lambda *a:receipt)
    monkeypatch.setattr(mailbox,'verify_mailbox',lambda email:mailbox.base_receipt(email,'HUNTER_RESULT_PENDING'))
    item=enrichment();hunter.enrich_contact(item,'https://acme.example',required_person=True)
    assert 'email' not in item['fields']


def test_authorized_job_runs_real_qualification_send_and_followup_handoff(env,monkeypatch):
    """Only external discovery/DNS/Gmail are mocked; all durable gates execute."""
    import v1_orchestration as orchestration
    import src.email_validation as email_validation
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEY_VERSION','v1')
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEYS','v1=integration-test-only')
    monkeypatch.setattr(orchestration,'AUTOSEND_ENABLED',False)
    page=company_page()
    from src.company_identity import identity_proof
    page['company_identity']=identity_proof('Acme',page,'https://acme.example/')
    result={**page,'title':'Acme','company':'Acme','website':'https://acme.example/','location':'Norfolk, Virginia','classification':'Verified Lead','promotion_status':'verified','verification_gate':'passed','intent_score':80,'evidence':[{'url':page['url'],'title':'Acme HVAC services','snippet':page['page_text'],'observed_at':page['observed_at']}]}
    monkeypatch.setattr(demo,'_smart_search',lambda *a,**k:{'results':[result],'verified_count':1})
    monkeypatch.setattr(orchestration,'_public_contact_evidence',lambda *a:([page],{}))
    monkeypatch.setattr(email_validation,'check_email_domain',lambda *a,**k:{'domain_status':'mx_published'})
    sends=[]
    monkeypatch.setattr(oa,'_gmail_send',lambda *args:sends.append(args) or {'ok':True,'message_id':'provider-message','thread_id':'provider-thread'})
    body={'target_customer':'Find 1 current HVAC business','territory':'Norfolk, Virginia','target_count':1,'sending_limit':1,'send_emails':True}
    headers={'X-Operator-Token':'operator-unit-test','Idempotency-Key':'integrated-send'}
    job=env.post('/api/chat/campaigns/launch',json=body,headers=headers)
    assert job.status_code==202
    assert jobs.process_next_execution_job()['ok']
    outcome=env.get(job.json['poll_url']).json['result']['outreach']
    assert outcome['qualified']==outcome['drafted']==outcome['sent']==1
    lead=oa.OutreachLead.query.one()
    assert lead.status=='sent' and lead.gmail_message_id=='provider-message'
    assert lead.follow_up_due_at and lead.gmail_thread_id=='provider-thread'
    assert env.post('/api/chat/campaigns/launch',json=body,headers=headers).json['job_id']==job.json['job_id']
    assert jobs.process_next_execution_job()['processed']==0 and len(sends)==1
