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


def test_primary_identity_is_retained_when_site_does_not_publish_email(env,monkeypatch):
    import outreach_bridge as bridge
    from src.enrichment import enrich_lead
    raw='<title>Acme</title><h1>Acme</h1><p>HVAC services in Norfolk, Virginia.</p>'
    monkeypatch.setattr(bridge,'public_get',lambda url,**kw:SimpleNamespace(status_code=200,url=url,headers={'content-type':'text/html'},text=raw))
    rows,_=bridge._public_contact_evidence({'title':'Acme','website':'https://acme.example/','location':'Norfolk, Virginia'})
    enriched=enrich_lead({'company':'Acme','website':'https://acme.example/'},rows)
    assert enriched['identity_status']=='source_bound'
    assert 'email' not in enriched['fields']


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
    assert env.post('/api/demo/campaigns/launch',json={**body,'send_authorized':True}).status_code==401
    public=env.post('/api/demo/campaigns/launch',json={**body,'send_authorized':True},headers={'X-Operator-Token':'operator-unit-test'})
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
    outcome=env.get(job.json['poll_url'],headers=headers).json['result']['outreach']
    assert outcome['qualified']==outcome['drafted']==outcome['sent']==1
    lead=oa.OutreachLead.query.one()
    from src.outreach_copy import primary_copy_sources
    assert primary_copy_sources(lead,json.loads(lead.evidence_json))
    assert lead.status=='sent' and lead.gmail_message_id=='provider-message'
    assert lead.follow_up_due_at and lead.gmail_thread_id=='provider-thread'
    assert env.post('/api/chat/campaigns/launch',json=body,headers=headers).json['job_id']==job.json['job_id']
    assert jobs.process_next_execution_job()['processed']==0 and len(sends)==1


def test_generated_email_never_leaves_a_blank_signature(env,monkeypatch):
    monkeypatch.setattr(oa,'run_ai',lambda **kw:{'ok':True,'output':json.dumps({'subject':'Automation for Acme','body':'Hello Acme team,\nWould a brief call help?\n\nBest regards,'})})
    lead=oa.OutreachLead(company='Acme',evidence_json='[]')
    draft=oa._draft_email(lead)
    assert draft['ok'] and draft['body'].endswith('Matthew Jolley\nAutoMake AI\n757 840 9648')


def prepared_activation_lead(env,monkeypatch):
    import v1_orchestration as orchestration
    import src.email_validation as email_validation
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEY_VERSION','v1')
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEYS','v1=activation-test-only')
    # Even a legacy global autosend flag cannot turn preparation into sending.
    monkeypatch.setattr(orchestration,'AUTOSEND_ENABLED',True)
    monkeypatch.setattr(oa,'run_ai',lambda **kw:{'ok':False})
    monkeypatch.setattr(oa,'gmail_access_token',lambda:'isolated-test-access')
    page=company_page()
    # New preparation requires offer-specific need, a supported buyer and an
    # independent mailbox receipt. All provider behavior stays isolated here.
    page['page_text']=page['page_text'].replace('hello@acme.example','alice@acme.example')+' We manually manage customer inquiries and scheduling. Alice Smith | Owner. Norfolk, Virginia. alice@acme.example'
    page['contact_sections']=['Alice Smith | Owner. Norfolk, Virginia. alice@acme.example']
    monkeypatch.setattr(search,'_page_snapshot',lambda *a:copy.deepcopy(page))
    monkeypatch.setattr(mailbox,'verify_mailbox',lambda email,**kw:{'email':email,'mailbox_status':'provider_verified','deliverability_status':'unconfirmed','checked_at':datetime.now(timezone.utc).isoformat(),'reason_codes':[]})
    from src.company_identity import identity_proof
    page['company_identity']=identity_proof('Acme',page,'https://acme.example/')
    result={**page,'title':'Acme','company':'Acme','website':'https://acme.example/','location':'Norfolk, Virginia','classification':'Verified Lead','promotion_status':'verified','verification_gate':'passed','intent_score':80,'evidence':[{'url':page['url'],'title':'Acme HVAC services','snippet':page['page_text'],'observed_at':page['observed_at']}]}
    monkeypatch.setattr(demo,'_smart_search',lambda *a,**k:{'results':[result],'verified_count':1})
    monkeypatch.setattr(orchestration,'_public_contact_evidence',lambda *a:([page],{}))
    monkeypatch.setattr(email_validation,'check_email_domain',lambda *a,**k:{'domain_status':'mx_published'})
    headers={'X-Operator-Token':'operator-unit-test','Idempotency-Key':'activation-preparation'}
    job=env.post('/api/chat/campaigns/prepare',json={'target_customer':'Find 1 HVAC business','territory':'Norfolk, Virginia','target_count':1},headers=headers)
    assert job.status_code==202
    processed=jobs.process_next_execution_job()
    assert processed['ok'], env.get(job.json['poll_url'],headers=headers).json
    outcome=env.get(job.json['poll_url'],headers=headers).json['result']['outreach']
    assert outcome['qualified']==outcome['drafted']==1 and outcome['sent']==0, outcome
    assert oa.OutreachSendAttempt.query.count()==0
    return oa.OutreachLead.query.one(),headers


def test_stale_quality_cannot_activate_or_create_a_send_attempt(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    import src.prospect_quality as quality
    class FutureDatetime(datetime):
        @classmethod
        def now(cls,tz=None):return datetime.now(tz)+timedelta(hours=2)
    monkeypatch.setattr(quality,'datetime',FutureDatetime)
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**k:pytest.fail('Stale prospect must not send'))
    detail=env.get(f'/api/chat/dashboard/leads/{lead.id}',headers=headers).json
    assert not detail['outreach']['can_activate']
    assert env.post(f'/api/chat/leads/{lead.id}/activate-outreach',json={'activate':True},headers=headers).status_code==409
    assert not oa._safe_send(lead,kind='initial',sequence=0,subject=lead.subject,body=lead.body)['ok']
    assert oa.OutreachSendAttempt.query.count()==0



def test_existing_unsent_lead_is_reassessed_for_a_different_offer(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    import v1_orchestration as orchestration
    from lead_recovery import LeadRecovery
    from src.prospect_quality import POLICY,request_spec
    from src.outreach_activation import activation_view
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**k:pytest.fail('Reassessment must not send'))
    payload={'query':'Find 1 HVAC business','location':'Norfolk, Virginia','offer':'Invoice processing automation',
             'prospect_policy':POLICY,'results':[{'company':'Acme','website':'https://acme.example/',
             'classification':'Verified Lead','promotion_status':'verified','verification_gate':'passed','intent_score':80}]}
    payload['request_spec']=request_spec(payload['query'],payload['location'],payload['offer'])
    result=orchestration._orchestrate_discovery_serial(payload,draft_only=True)
    assert result['lead_ids']==[lead.id] and result['sent']==0
    assert oa.OutreachLead.query.count()==1 and oa.OutreachSendAttempt.query.count()==0
    assert not oa._qualification_gate(lead)['ok']
    assert json.loads(oa.db.session.get(LeadRecovery,lead.id).payload_json)['_campaign_context']['offer']==payload['offer']
    with oa.app.test_request_context(headers=headers):
        assert not activation_view(lead)['can_activate']

def test_explicit_activation_sends_approved_copy_once_and_schedules_followup(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    from src.outreach_copy import matches_initial_email,add_resume_attachment,RESUME_PATH
    from email.message import EmailMessage
    captured=[]
    def send(address,subject,body,thread_id=''):
        message=EmailMessage();message.set_content(body);add_resume_attachment(message,body)
        captured.append((address,subject,body,list(message.iter_attachments())))
        return {'ok':True,'message_id':'confirmed-message','thread_id':'confirmed-thread'}
    monkeypatch.setattr(oa,'_gmail_send',send)
    detail=env.get(f'/api/chat/dashboard/leads/{lead.id}',headers=headers).json
    assert detail['outreach']['can_activate'] is True
    assert detail['outreach']['send_status']=='not_sent'
    url=f'/api/chat/leads/{lead.id}/activate-outreach'
    assert env.post(url,json={},headers=headers).status_code==400
    first=env.post(url,json={'activate':True},headers=headers)
    assert first.status_code==200 and first.json['outreach']['state']=='active'
    assert first.json['outreach']['send_status']=='sent' and first.json['outreach']['label']=='Sent'
    assert first.json['outreach']['sent_at']
    due=lead.follow_up_due_at
    assert lead.status=='sent' and due and lead.gmail_thread_id=='confirmed-thread'
    assert len(captured)==1 and captured[0][0]==lead.contact_email
    assert matches_initial_email(lead,json.loads(lead.evidence_json),captured[0][1],captured[0][2])
    assert captured[0][2].count('👋')==captured[0][2].count('🙂')==1
    assert len(captured[0][3])==1 and captured[0][3][0].get_filename()==RESUME_PATH.name
    assert oa.OutreachBookingAttempt.query.count()==0
    second=env.post(url,json={'activate':True},headers=headers)
    assert second.status_code==200 and second.json['already_active'] is True
    assert len(captured)==1 and lead.follow_up_due_at==due
    # Existing scheduler consumes the activation's saved thread and due time.
    monkeypatch.setattr(oa,'_gmail_thread_reply_state',lambda _:dict(ok=True,stop=False))
    lead.follow_up_due_at=datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    processed=oa.process_due_followups()
    assert processed['ok'] and lead.follow_up_count==1 and lead.status=='followup_sent'
    assert len(captured)==2


def test_activation_holds_missing_evidence_and_uncertain_attempts(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:pytest.fail('Blocked contact sent'))
    url=f'/api/chat/leads/{lead.id}/activate-outreach'
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,kind='initial',sequence=0,recipient=lead.contact_email,idempotency_key='uncertain-activation',status='uncertain'))
    oa.db.session.commit()
    held=env.post(url,json={'activate':True},headers=headers)
    assert held.status_code==409 and held.json['outreach']['state']=='review'
    assert held.json['outreach']['send_status']=='unknown'
    assert held.json['outreach']['initial']=='Send status unconfirmed'
    oa.OutreachSendAttempt.query.delete();lead.evidence_json='[]';oa.db.session.commit()
    assert env.post(url,json={'activate':True},headers=headers).status_code==409
    # Incomplete provider receipts must never be represented as definitely unsent.
    lead.gmail_message_id='partial-receipt';oa.db.session.commit()
    detail=env.get(f'/api/chat/dashboard/leads/{lead.id}',headers=headers).json
    assert detail['outreach']['send_status']=='unknown'


def test_activation_preserves_suppression_and_resume_requirement(env,monkeypatch,tmp_path):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:pytest.fail('Suppressed or attachment-less email sent'))
    url=f'/api/chat/leads/{lead.id}/activate-outreach'
    import src.outreach_copy as copy
    monkeypatch.setattr(copy,'RESUME_PATH',tmp_path/'missing.docx')
    response=env.post(url,json={'activate':True},headers=headers)
    assert response.status_code==409 and 'résumé' in response.json['error']
    assert oa.OutreachSendAttempt.query.count()==0
    oa._suppress(lead.contact_email);oa.db.session.commit()
    assert env.post(url,json={'activate':True},headers=headers).status_code==409


def test_activation_reconciles_confirmed_receipt_without_replaying_send(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:pytest.fail('Confirmed receipt replayed'))
    sent_at=datetime.utcnow()-timedelta(hours=2)
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,kind='initial',sequence=0,recipient=lead.contact_email,idempotency_key='confirmed-initial',status='sent',message_id='saved-message',thread_id='saved-thread',updated_at=sent_at))
    oa.db.session.commit()
    detail=env.get(f'/api/chat/dashboard/leads/{lead.id}',headers=headers).json
    assert detail['outreach']['send_status']=='sent' and detail['outreach']['label']=='Sent'
    assert not lead.gmail_message_id  # Read-only display does not schedule or mutate.
    response=env.post(f'/api/chat/leads/{lead.id}/activate-outreach',json={'activate':True},headers=headers)
    assert response.status_code==200 and response.json['already_active']
    assert lead.gmail_message_id=='saved-message' and lead.sent_at==sent_at
    assert lead.follow_up_due_at==sent_at+timedelta(days=oa.FIRST_FOLLOWUP_DAYS)


def test_reconciliation_does_not_reactivate_an_opted_out_contact(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    lead.status='opted_out'
    oa._suppress(lead.contact_email)
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,kind='initial',sequence=0,recipient=lead.contact_email,idempotency_key='historical-confirmed',status='sent',message_id='saved-message',thread_id='saved-thread'))
    oa.db.session.commit()
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:pytest.fail('Opt-out reactivated'))
    response=env.post(f'/api/chat/leads/{lead.id}/activate-outreach',json={'activate':True},headers=headers)
    assert response.status_code==409 and response.json['outreach']['state']=='stopped'
    assert lead.status=='opted_out' and lead.follow_up_due_at is None


def test_activation_checks_expired_google_grant_before_creating_send_attempt(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    monkeypatch.setattr(oa,'gmail_access_token',lambda:(_ for _ in ()).throw(RuntimeError('Google token error invalid_grant')))
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:pytest.fail('Expired Google grant sent email'))
    response=env.post(f'/api/chat/leads/{lead.id}/activate-outreach',json={'activate':True},headers=headers)
    assert response.status_code==409 and response.json['connection_required'] is True
    assert oa.OutreachSendAttempt.query.count()==0 and oa.ExternalSideEffectCommand.query.count()==0


def selected_body(ref):
    return {'selection':ref,'offer':'Inquiry follow-up and appointment scheduling automation','activate':True}


def test_selection_prepares_missing_draft_then_sends_only_chosen_contact_once(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    lead.subject='';lead.body='';lead.status='needs_evidence';oa.db.session.commit()
    other=oa.OutreachLead(company='Unchosen business',source_url='https://unchosen.example/',status='needs_evidence')
    oa.db.session.add(other);oa.db.session.commit()
    captured=[]
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**kw:captured.append(a) or {'ok':True,'message_id':'selected-send','thread_id':'selected-thread'})
    body=selected_body({'kind':'lead','lead_id':lead.id})
    launch=env.post('/api/chat/workflows/activate',json=body,headers=headers)
    assert launch.status_code==202 and captured==[]
    queued=oa.db.session.get(jobs.CampaignExecutionJob,launch.json['job_id'])
    grant=json.loads(queued.payload_json)
    assert grant['_selection_send_authorized'] is True
    assert grant['send_authorized'] is False and grant['draft_only'] is True
    processed=jobs.process_next_execution_job();assert processed['ok']
    result=env.get(launch.json['poll_url'],headers=headers).json['result']
    assert result['workflow']['state']=='active',result
    assert len(captured)==1 and captured[0][0]=='alice@acme.example'
    assert lead.body.count('👋')==lead.body.count('🙂')==1
    assert lead.follow_up_due_at and lead.gmail_thread_id=='selected-thread'
    assert other.status=='needs_evidence' and not other.gmail_message_id
    duplicate=env.post('/api/chat/workflows/activate',json={**body,'selection':{**body['selection'],'ignored_nonce':'cannot-create-another-grant'}},headers=headers)
    assert duplicate.json['job_id']==launch.json['job_id']
    assert jobs.process_next_execution_job().get('processed')==0
    assert oa.OutreachSendAttempt.query.count()==1 and len(captured)==1


def test_selection_on_source_candidate_is_available_before_a_draft_and_does_not_trust_client_fields(env,monkeypatch):
    from background_research import ResearchJob
    from workspace_security import claim,OWNER
    from src.selection_refs import reference
    lead,headers=prepared_activation_lead(env,monkeypatch)
    lead.subject='';lead.body='';lead.status='needs_evidence';oa.db.session.commit()
    row={'company':'Acme','website':'https://acme.example/','location':'Norfolk, Virginia','classification':'Candidate','intent_score':5}
    research=ResearchJob(id='selection-source',prompt_text='Find 10 HVAC businesses',location='Norfolk, Virginia',status='completed',result_json=json.dumps({'results':[row]}))
    oa.db.session.add(research);claim('research',research.id,OWNER);oa.db.session.commit()
    view=env.get('/api/research/jobs/'+research.id,headers=headers).json
    ref=view['result']['results'][0]['selection'];assert ref==reference('research',research.id,row)
    research.result_json=json.dumps({'results':[{'company':'Not chosen','website':'https://not-chosen.example/'},row]});oa.db.session.commit()
    captured=[];monkeypatch.setattr(oa,'_gmail_send',lambda *a,**kw:captured.append(a) or {'ok':True,'message_id':'candidate-send','thread_id':'candidate-thread'})
    body={**selected_body(ref),'_selected_business':{'company':'Injected','website':'https://attacker.example/'},'contact_email':'guessed@attacker.example','draft_only':True}
    launch=env.post('/api/chat/workflows/activate',json=body,headers=headers)
    assert launch.status_code==202
    payload=json.loads(oa.db.session.get(jobs.CampaignExecutionJob,launch.json['job_id']).payload_json)
    assert payload['_selected_business']['company']=='Acme' and payload['_selected_business']['intent_score']==5
    assert jobs.process_next_execution_job()['ok']
    result=env.get(launch.json['poll_url'],headers=headers).json['result']
    assert result['workflow']['state']=='active',result
    assert len(captured)==1 and captured[0][0]=='alice@acme.example'
    assert oa.OutreachLead.query.count()==1


def test_unverified_selected_business_stays_held_without_inventing_contact_or_sending(env,monkeypatch):
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEY_VERSION','v1')
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEYS','v1=held-selection-test')
    from background_research import ResearchJob
    from workspace_security import claim,OWNER
    from src.selection_refs import reference
    row={'company':'Unconfirmed company','website':'https://unconfirmed.example/','classification':'Candidate','intent_score':0}
    research=ResearchJob(id='held-selection',prompt_text='Find 10 HVAC businesses',location='Norfolk, Virginia',status='completed',result_json=json.dumps({'results':[row]}))
    oa.db.session.add(research);claim('research',research.id,OWNER);oa.db.session.commit()
    monkeypatch.setattr(search,'_page_snapshot',lambda *a:{'fetch_error':'HTTP_503'})
    monkeypatch.setattr(search,'_exa_search',lambda *a:{'results':[]})
    import v1_orchestration as orchestration
    monkeypatch.setattr(orchestration,'_public_contact_evidence',lambda *a:([],{}))
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**k:pytest.fail('Unsupported prospect must not send'))
    headers={'X-Operator-Token':'operator-unit-test'}
    launch=env.post('/api/chat/workflows/activate',json=selected_body(reference('research',research.id,row)),headers=headers)
    assert launch.status_code==202
    assert jobs.process_next_execution_job()['ok']
    result=env.get(launch.json['poll_url'],headers=headers).json['result']
    assert result['workflow']['state']=='held'
    assert result['outreach']['sent']==0 and oa.OutreachSendAttempt.query.count()==0
    lead=oa.OutreachLead.query.one();assert not lead.contact_email and not lead.body
    assert 'OFFER_NEED_EVIDENCE_REQUIRED' in result['workflow']['reason_codes']


def test_public_research_selection_survives_sign_in_scope_without_cross_browser_access(env,monkeypatch):
    import background_research as research
    from src.selection_refs import reference
    monkeypatch.setattr(research,'kick_worker',lambda:None)
    launched=env.post('/api/research/jobs',json={'prompt':'Find 10 HVAC businesses','location':'Norfolk, Virginia'})
    row={'company':'Acme','website':'https://acme.example/','classification':'Candidate'}
    saved=oa.db.session.get(research.ResearchJob,launched.json['job_id']);saved.status='completed';saved.result_json=json.dumps({'results':[row]});oa.db.session.commit()
    headers={'X-Operator-Token':'operator-unit-test'}
    ref=reference('research',saved.id,row)
    other=oa.app.test_client()
    assert other.post('/api/chat/workflows/activate',json=selected_body(ref),headers=headers).status_code==404
    # The same browser can observe and select its pre-login public research.
    assert env.get(launched.json['poll_url'],headers=headers).status_code==200
    assert env.post('/api/chat/workflows/activate',json=selected_body(ref),headers=headers).status_code==202


def test_selection_requires_explicit_action_auth_csrf_and_resource_ownership(env,monkeypatch):
    from workspace_security import claim
    lead,headers=prepared_activation_lead(env,monkeypatch)
    body=selected_body({'kind':'lead','lead_id':lead.id})
    assert env.post('/api/chat/workflows/activate',json=body).status_code==401
    assert env.get('/api/chat/workflows/activate',headers=headers).status_code==405
    assert env.post('/api/chat/workflows/activate',json={**body,'activate':False},headers=headers).status_code==400
    claim('lead',lead.id,'another-workspace');oa.db.session.commit()
    assert env.post('/api/chat/workflows/activate',json=body,headers=headers).status_code==404
    monkeypatch.setattr(oa,'_operator_session_authorized',lambda:True)
    monkeypatch.setattr(oa,'_csrf_ok',lambda:False)
    assert env.post('/api/chat/workflows/activate',json=body).status_code==403
    assert oa.OutreachSendAttempt.query.count()==0


def test_selected_workflow_checks_cancellation_after_drafting_before_sending(env,monkeypatch):
    import v1_orchestration as orchestration
    lead,headers=prepared_activation_lead(env,monkeypatch)
    body=selected_body({'kind':'lead','lead_id':lead.id})
    launch=env.post('/api/chat/workflows/activate',json=body,headers=headers)
    serial=orchestration._orchestrate_discovery_serial
    def cancel(*a,**kw):
        result=serial(*a,**kw)
        job=oa.db.session.get(jobs.CampaignExecutionJob,launch.json['job_id']);job.status='cancelled';oa.db.session.commit()
        return result
    monkeypatch.setattr(orchestration,'_orchestrate_discovery_serial',cancel)
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**k:pytest.fail('Cancelled workflow sent'))
    jobs.process_next_execution_job()
    assert oa.db.session.get(jobs.CampaignExecutionJob,launch.json['job_id']).status=='cancelled'
    assert oa.OutreachSendAttempt.query.count()==0


def test_selection_invalid_google_grant_holds_without_send_attempt_and_retry_is_bounded(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    monkeypatch.setattr(oa,'gmail_access_token',lambda:(_ for _ in ()).throw(RuntimeError('invalid_grant')))
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**k:pytest.fail('Expired grant sent'))
    body=selected_body({'kind':'lead','lead_id':lead.id})
    launch=env.post('/api/chat/workflows/activate',json=body,headers=headers)
    assert jobs.process_next_execution_job()['ok']
    result=env.get(launch.json['poll_url'],headers=headers).json['result']
    assert result['workflow']['state']=='held' and 'Reconnect Google' in result['workflow']['reason']
    assert oa.OutreachSendAttempt.query.count()==0
    retry={**body,'retry_from':launch.json['job_id']}
    assert env.post('/api/chat/workflows/activate',json=retry,headers=headers).status_code==429
    previous=oa.db.session.get(jobs.CampaignExecutionJob,launch.json['job_id']);previous.finished_at=datetime.utcnow()-timedelta(minutes=2);oa.db.session.commit()
    next_job=env.post('/api/chat/workflows/activate',json=retry,headers=headers)
    assert next_job.status_code==202 and next_job.json['job_id']!=launch.json['job_id']
    assert env.post('/api/chat/workflows/activate',json=retry,headers=headers).json['job_id']==next_job.json['job_id']


def test_selected_uncertain_send_cannot_replay_or_refresh_existing_conversation(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    original=(lead.subject,lead.body,lead.evidence_json)
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,kind='initial',sequence=0,recipient=lead.contact_email,idempotency_key='selected-uncertain',status='uncertain'));oa.db.session.commit()
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**k:pytest.fail('Uncertain attempt replayed'))
    launch=env.post('/api/chat/workflows/activate',json=selected_body({'kind':'lead','lead_id':lead.id}),headers=headers)
    assert jobs.process_next_execution_job()['ok']
    result=env.get(launch.json['poll_url'],headers=headers).json['result']
    assert result['workflow']['state']=='held' and result['workflow']['outreach']['state']=='review'
    assert (lead.subject,lead.body,lead.evidence_json)==original and oa.OutreachSendAttempt.query.count()==1
    previous=oa.db.session.get(jobs.CampaignExecutionJob,launch.json['job_id']);previous.finished_at=datetime.utcnow()-timedelta(minutes=2);oa.db.session.commit()
    body={**selected_body({'kind':'lead','lead_id':lead.id}),'retry_from':launch.json['job_id']}
    assert env.post('/api/chat/workflows/activate',json=body,headers=headers).status_code==409


def test_selected_recipient_already_sent_on_another_record_is_held(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    other=oa.OutreachLead(company='Another source identity',contact_email=lead.contact_email,status='sent')
    oa.db.session.add(other);oa.db.session.flush()
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=other.id,kind='initial',sequence=0,recipient=lead.contact_email,
        idempotency_key='other-record-send',status='sent',message_id='confirmed-other-send',thread_id='confirmed-other-thread'))
    oa.db.session.commit()
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**k:pytest.fail('Duplicate recipient sent again'))
    launch=env.post('/api/chat/workflows/activate',json=selected_body({'kind':'lead','lead_id':lead.id}),headers=headers)
    assert jobs.process_next_execution_job()['ok']
    result=env.get(launch.json['poll_url'],headers=headers).json['result']
    assert result['workflow']['state']=='held'
    assert 'DUPLICATE_RECIPIENT_SEND_REVIEW_REQUIRED' in result['workflow']['reason_codes']
    assert oa.OutreachSendAttempt.query.count()==1 and not lead.gmail_message_id


def test_selected_verification_retries_have_an_aggregate_hourly_limit(env,monkeypatch):
    lead,headers=prepared_activation_lead(env,monkeypatch)
    body=selected_body({'kind':'lead','lead_id':lead.id})
    current=env.post('/api/chat/workflows/activate',json=body,headers=headers)
    assert current.status_code==202
    for index in range(4):
        job=oa.db.session.get(jobs.CampaignExecutionJob,current.json['job_id'])
        job.status='completed';job.finished_at=datetime.utcnow()-timedelta(minutes=2)
        job.result_json=json.dumps({'ok':True,'workflow':{'state':'held','lead_id':lead.id,'reason':'Contact check held'}})
        oa.db.session.commit()
        retry=env.post('/api/chat/workflows/activate',json={**body,'retry_from':job.id},headers=headers)
        if index<3:
            assert retry.status_code==202;current=retry
        else:
            assert retry.status_code==429 and 'hourly' in retry.json['error']
    assert oa.OutreachSendAttempt.query.count()==0
