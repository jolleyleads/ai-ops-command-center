"""Contact research uses Hunter without becoming permission to send."""
import copy
import json
import time
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

import pytest
import commercial_app
from app import app, db
import outreach_automation as oa
import v1_orchestration as workflow
from src import hunter_discovery as discovery, hunter_mailbox as mailbox, hunter_research as research
from src.company_identity import identity_proof
from src.contact_assessment import person_email_supported


@pytest.fixture
def native(monkeypatch):
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','true')
    monkeypatch.setenv('HUNTER_API_KEY','unit-test-secret')
    monkeypatch.setenv('HUNTER_ACCOUNT_EMAIL','owner@example.com')
    with app.app_context():
        db.drop_all();db.create_all()
        yield
        db.session.remove();db.drop_all();db.create_all()


def response(data, status=200):
    return SimpleNamespace(status_code=status,content=b'{}',json=lambda:{'data':data})


def transport(url,**kwargs):
    assert 'api_key' not in kwargs.get('params',{}) and 'unit-test-secret' not in url
    assert kwargs['allow_redirects'] is False
    if url.endswith('/account'):
        return response({'email':'owner@example.com','plan_name':'Free','requests':{'credits':{'remaining':46}}})
    if url.endswith('/domain-search'):
        assert kwargs['params']['decision_maker']=='true'
        assert kwargs['params']['verification_status']=='valid'
        return response({'domain':'acme.example','emails':[{'value':'jane@acme.example','first_name':'Jane',
            'last_name':'Smith','position':'Chief Executive Officer','type':'personal'}]})
    if url.endswith('/email-verifier'):
        return response({'email':'jane@acme.example','status':'valid','smtp_check':True,'accept_all':False,
            'block':False,'disposable':False,'verification':{'date':datetime.now(timezone.utc).date().isoformat(),'status':'valid'}})
    pytest.fail('Unexpected provider endpoint')


def wire(monkeypatch):
    original_discover=discovery.discover_contacts
    original_verify=mailbox.verify_mailbox
    monkeypatch.setattr(discovery,'discover_contacts',lambda website,**kw:original_discover(website,transport,**kw))
    monkeypatch.setattr(mailbox,'verify_mailbox',lambda email,**kw:original_verify(email,transport,**kw))
    page={'url':'https://acme.example','candidate_name':'Acme','title':'Acme',
        'page_text':'Acme is based in Charlotte, North Carolina. Business services.',
        'directly_fetched':True,'http_status':200,'observed_at':datetime.now(timezone.utc).isoformat()}
    page['company_identity']=identity_proof('Acme',page,page['url'])
    monkeypatch.setattr(workflow,'_public_contact_evidence',lambda row:([page],{}))
    import src.email_validation as dns_check
    monkeypatch.setattr(dns_check,'check_email_domain',lambda *a,**kw:{'domain_status':'mx_published'})
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**kw:pytest.fail('Research must not send'))
    monkeypatch.setattr(oa,'_draft_email',lambda *a,**kw:pytest.fail('Contact search must not require a draft'))


def test_direct_discovery_uses_hunter_and_keeps_key_out_of_query(native):
    seen=[]
    def post(url,**kw):
        seen.append(kw)
        assert kw['headers']=={'X-API-KEY':'unit-test-secret'}
        assert kw['json']['limit']==2 and 'Charlotte' in kw['json']['query']
        return response([{'organization':'Acme','domain':'acme.example'},
                         {'organization':'Spoof','domain':'evil.example/path'},
                         {'organization':'Directory','domain':'linkedin.com'}])
    receipt=research.discover_companies('Find businesses','Charlotte, NC',2,get=transport,post=post)
    assert [x['company'] for x in receipt['companies']]==['Acme']
    assert 'unit-test-secret' not in json.dumps(receipt) and len(seen)==1


def test_free_discovery_rechecks_account_despite_cached_lookup_quota_pause(native):
    key,blocked=mailbox._claim_account('owner@example.com','old',time.time())
    assert not blocked
    mailbox._release_account(key,'old',['HUNTER_FREE_QUOTA_UNAVAILABLE'])
    assert mailbox._claim_account('owner@example.com','paid',time.time())[1]=='HUNTER_FREE_QUOTA_UNAVAILABLE'
    receipt=research.discover_companies('Find businesses','Charlotte, NC',1,get=transport,
        post=lambda *a,**kw:response([{'organization':'Acme','domain':'acme.example'}]))
    assert receipt['account_http_status']==200 and receipt['companies']
    assert not receipt['reason_codes']
    # Free discovery released its lease. A subsequent lookup can check the
    # current balance again instead of inheriting the old one-hour pause.
    _,blocked=mailbox._claim_account('owner@example.com','new',time.time())
    assert not blocked


def test_regional_search_retries_real_cities_without_losing_business_filters(native):
    calls=[]
    filters={'headquarters_location':{'include':[{'city':'Hampton Roads','country':'US','state':'VA'}],
                                    'exclude':[{'city':'Suffolk','country':'US','state':'VA'}]},
             'industry':{'include':['Specialty Trade Contractors']},
             'keywords':{'include':['electrical contractor'],'match':'any'},
             'headcount':['11-50']}
    def post(url,**kw):
        payload=kw['json'];calls.append(payload)
        if len(calls)==1:
            assert 'Norfolk' in payload['query'] and 'Chesapeake' in payload['query']
            return SimpleNamespace(status_code=200,content=b'{}',json=lambda:{'data':[],'meta':{'filters':filters}})
        assert 'query' not in payload and payload['limit']==5
        assert payload['industry']==filters['industry'] and payload['keywords']==filters['keywords']
        assert payload['headcount']==filters['headcount']
        assert payload['headquarters_location']['exclude']==filters['headquarters_location']['exclude']
        assert {'city':'Norfolk','country':'US','state':'VA'} in payload['headquarters_location']['include']
        assert all(city['city']!='Hampton Roads' for city in payload['headquarters_location']['include'])
        return response([{'organization':'Local Electrical','domain':'electrical.example'}])
    receipt=research.discover_companies('Give me five electrical businesses with 11–50 employees',
        'Hampton Roads, Virginia',5,get=transport,post=post)
    assert len(calls)==2 and receipt['regional_filter_retry'] is True
    assert receipt['companies'][0]['company']=='Local Electrical' and not receipt['reason_codes']
    assert filters['headquarters_location']['include'][0]['city']=='Hampton Roads'


@pytest.mark.parametrize('location',['Norfolk, VA','Hampton, VA','Charlotte, NC','Hampton Roads, North Carolina'])
def test_city_or_other_territory_is_never_replaced_with_regional_cities(location):
    assert research.regional_discover_locations(location)==[]


def test_regional_retry_failure_is_not_reported_as_zero_matches(native):
    calls=[]
    def post(*args,**kw):
        calls.append(kw)
        if len(calls)==1:
            return SimpleNamespace(status_code=200,content=b'{}',json=lambda:{'data':[],
                'meta':{'filters':{'industry':{'include':['Construction']}}}})
        return response({},status=503)
    receipt=research.discover_companies('Find companies','HRVA',5,get=transport,post=post)
    assert len(calls)==2 and receipt['companies']==[]
    assert receipt['reason_codes']==['HUNTER_DISCOVER_UNAVAILABLE']


@pytest.mark.parametrize('bucket,expected',[
    ({'remaining':46,'available':50,'used':4},46),
    ({'available':50,'used':4},46),
    ({'available':50},None),({'available':True,'used':0},None),
    ({'remaining':0,'available':50,'used':0},0),
    ({'remaining':True,'available':50,'used':0},None),
    ({'available':50,'used':51},0),
])
def test_quota_parser_never_treats_total_allocation_as_remaining(bucket,expected):
    assert mailbox.remaining_requests(bucket)==expected


def test_research_verification_matches_hunter_dates_without_reusing_send_eligibility(native):
    def get(url,**kwargs):
        r=transport(url,**kwargs)
        if url.endswith('/email-verifier'):
            data=r.json()['data'];data['verification']['date']=(datetime.now(timezone.utc)-timedelta(days=17)).date().isoformat()
            return response(data)
        return r
    preview=mailbox.verify_mailbox('jane@acme.example',get,research_only=True)
    assert preview['mailbox_status']=='provider_verified'
    assert preview['verification_policy']=='research-last-known-30-days'
    send=mailbox.verify_mailbox('jane@acme.example',get)
    assert send['mailbox_status']=='unconfirmed' and not send.get('cache_hit')
    assert send['verification_policy']=='send-current-7-days'


@pytest.mark.parametrize('status,reason',[(403,'HUNTER_DISCOVER_ACCESS_REQUIRED'),(429,'HUNTER_DISCOVER_QUOTA_EXHAUSTED'),(500,'HUNTER_DISCOVER_UNAVAILABLE')])
def test_discovery_errors_never_become_empty_success(native,status,reason):
    receipt=research.discover_companies('Find businesses','Charlotte, NC',1,get=transport,post=lambda *a,**kw:response([],status))
    assert receipt['reason_codes']==[reason] and not receipt['companies']


def test_hunter_named_contact_does_not_require_regex_person_on_homepage(native,monkeypatch):
    wire(monkeypatch)
    row={'company':'Acme','website':'https://acme.example','contact_location':'Charlotte, NC',
        '_campaign_context':{'provider_contact_research':True,'require_decision_maker':True}}
    email,source=workflow._verified_public_email(row)
    assert email=='jane@acme.example' and source=='https://acme.example'
    assert row['_contact_name']=='Jane Smith'
    assessment=row['_contact_enrichment']['contact_assessment']
    assert assessment['decision_maker_status']=='provider_supported'
    assert person_email_supported(assessment,email)
    forged=copy.deepcopy(assessment);forged['hunter_association']['name']='Wrong Person'
    assert not person_email_supported(forged,email)


@pytest.mark.parametrize('save_contacts',[True,False])
def test_business_list_enriches_before_qualification_and_public_never_saves_owner_leads(native,monkeypatch,save_contacts):
    wire(monkeypatch)
    monkeypatch.setattr(research,'discover_companies',lambda *a,**kw:{'companies':[{'company':'Acme',
        'title':'Acme','website':'https://acme.example','url':'https://acme.example'}],'reason_codes':[]})
    result,stage,error=research.run_contact_research({'query':'Find businesses in Charlotte, NC with verified emails',
        'territory':'Hampton Roads, VA','target_count':1,'offer':'AI automation'},save_contacts=save_contacts)
    assert not stage and not error and result['contact_research']
    row=result['discovery']['results'][0]
    assert row['contact_name']=='Jane Smith' and row['contact_role']=='Chief Executive Officer'
    assert row['contact_email']=='jane@acme.example' and row['email_status']=='Verified'
    assert row['location']=='Charlotte, NC' and row['email_verified_on']
    assert oa.OutreachLead.query.count()==int(save_contacts)
    if save_contacts:
        from src.manual_outreach import contact_readiness
        assert 'CURRENT_COMPANY_EMAIL_SOURCE_REQUIRED' in contact_readiness(oa.OutreachLead.query.one())['reason_codes']
    assert not oa.OutreachSendAttempt.query.count() and not result['outreach']['sent']
    assert not result['outreach']['drafted']
    from src.selection_refs import annotate
    marked=annotate({'result':result},'research','job')['result']['discovery']['results'][0]
    assert marked['selection']['kind']==('lead' if save_contacts else 'research')


def test_job_and_need_queries_keep_their_evidence_research_flow():
    for query in ['Find businesses hiring AI engineers','Find companies needing automation','Find companies with permits']:
        assert not research.is_contact_list_query(query)
    assert research.is_contact_list_query('Give me businesses in Charlotte NC with verified emails using Hunter')
    assert research.search_location('Find companies in Charlotte, North Carolina.','Norfolk, VA')=='Charlotte, North Carolina'


def test_unknown_mailbox_not_displayed_as_verified(native,monkeypatch):
    wire(monkeypatch)
    monkeypatch.setattr(mailbox,'verify_mailbox',lambda email:mailbox.base_receipt(email,'HUNTER_ACCEPT_ALL_UNCONFIRMED'))
    row={'company':'Acme','website':'https://acme.example','contact_location':'Charlotte, NC',
        '_campaign_context':{'provider_contact_research':True,'require_decision_maker':True}}
    assert workflow._verified_public_email(row)==('','')


def test_research_contact_can_be_prepared_by_existing_workflow_after_company_check(native,monkeypatch):
    wire(monkeypatch)
    monkeypatch.setattr(research,'discover_companies',lambda *a,**kw:{'companies':[{'company':'Acme',
        'title':'Acme','website':'https://acme.example','url':'https://acme.example'}],'reason_codes':[]})
    result,_,_=research.run_contact_research({'query':'Find businesses in Charlotte, NC with verified emails',
        'territory':'Hampton Roads, VA','target_count':1,'offer':'AI automation'})
    lead=oa.OutreachLead.query.one()
    from src.manual_outreach import prepare_contact,contact_readiness
    from src.outreach_copy import initial_email
    prepared=prepare_contact(result['discovery']['results'][0],lead,'Find businesses in Charlotte, NC',
        'Charlotte, NC','AI automation')
    assert prepared.contact_email=='jane@acme.example'
    assert contact_readiness(prepared)['ok']
    assert prepared.subject and prepared.body
    assert not oa.OutreachSendAttempt.query.count()


def test_web_businesses_precede_hunter_and_keep_requested_sector_and_city(native,monkeypatch):
    import smart_search
    seen=[]
    def web(query,location,**kw):
        seen.append((query,location,kw['target_count']))
        return {'results':[{'company':'Acme Plumbing','website':'https://acme.example',
            'classification':'Verified Lead','location':'Charlotte, NC'}]}
    monkeypatch.setattr(smart_search,'_smart_search',web)
    monkeypatch.setattr(mailbox,'_request',lambda *a,**k:pytest.fail('Web discovery must not require Hunter'))
    monkeypatch.delenv('HUNTER_API_KEY')
    receipt=research.discover_companies('Find 2 plumbing businesses in Charlotte, NC. Then use Hunter to verify decision-makers.', 'Charlotte, NC',2)
    assert seen==[('Find 2 plumbing businesses in Charlotte, NC. Then use Hunter to verify decision-makers.','Charlotte, NC',2)]
    assert receipt['provider']=='web' and not receipt['reason_codes']
    assert receipt['companies'][0]['research_source']=='Web research'
    assert receipt['companies'][0]['business_status']=='Business verified'
    terms=smart_search._business_terms('Find plumbing businesses using Hunter with revenue over 1 million','Charlotte, NC')
    assert 'plumbing' in terms and 'revenue' in terms and 'million' in terms
    assert not {'hunter','using','verify','verified'}.intersection(terms)


def test_failed_lookup_keeps_business_and_continues_with_next_contact(native,monkeypatch):
    rows=[{'company':name,'website':'https://'+domain,'url':'https://'+domain}
          for name,domain in [('Broken','broken.example'),('Acme','acme.example')]]
    wire(monkeypatch)
    monkeypatch.setattr(research,'discover_companies',lambda *a,**kw:{'companies':rows,'reason_codes':[]})
    original=discovery.enrich_contact
    def enrich(data,website,**kw):
        if 'broken.example' in website:raise ValueError('malformed provider response')
        return original(data,website,**kw)
    monkeypatch.setattr(discovery,'enrich_contact',enrich)
    result,stage,error=research.run_contact_research({'query':'Find businesses in Charlotte, NC',
        'territory':'Charlotte, NC','target_count':2,'offer':'AI automation'})
    assert not stage and not error
    broken,ready=result['discovery']['results']
    assert broken['company']=='Broken' and broken['contact_email']=='' and broken['contact_issue']
    assert ready['contact_email']=='jane@acme.example' and ready['email_status']=='Verified'
    assert oa.OutreachLead.query.count()==2 and result['outreach']['sent']==0


def test_explicit_verified_company_inbox_fallback_does_not_inherit_person(native,monkeypatch):
    wire(monkeypatch)
    monkeypatch.setattr(research,'discover_companies',lambda *a,**kw:{'companies':[
        {'company':'Acme','website':'https://acme.example'}],'reason_codes':[]})
    def shared(enrichment,website,**kw):
        assert kw['required_person'] is False
        enrichment['fields']['email']={'value':'hello@acme.example','validated':True}
        enrichment['contact_assessment']={'email_person_status':'shared_inbox',
            'mailbox_validation':{'email':'hello@acme.example','mailbox_status':'provider_verified',
                'provider_verified_on':datetime.now(timezone.utc).date().isoformat()}}
    monkeypatch.setattr(discovery,'enrich_contact',shared)
    query='Find businesses in Charlotte, NC with decision-maker emails; if unavailable provide a verified company email.'
    result,_,_=research.run_contact_research({'query':query,'territory':'Charlotte, NC','target_count':1,'offer':''})
    row=result['discovery']['results'][0]
    assert row['contact_type']=='Company inbox' and row['contact_name']==''
    assert row['contact_email']=='hello@acme.example' and row['email_status']=='Verified'
    assert not research.allows_company_inbox('Find decision-maker emails for companies')


@pytest.mark.parametrize('personal_result',['missing','invalid'])
def test_company_fallback_uses_unfiltered_lookup_after_named_contacts_fail(native,monkeypatch,personal_result):
    monkeypatch.setattr(research,'discover_companies',lambda *a,**kw:{'companies':[
        {'company':'Acme','website':'https://acme.example'}],'reason_codes':[]})
    queries=[]
    def get(url,**kw):
        if url.endswith('/domain-search'):
            named=kw['params'].get('decision_maker')=='true';queries.append(named)
            if named:
                return response({'domain':'acme.example','emails':[]}) if personal_result=='missing' else transport(url,**kw)
            return response({'domain':'acme.example','emails':[{'value':'hello@acme.example','type':'generic'}]})
        if url.endswith('/email-verifier'):
            email=kw['params']['email']
            if email=='jane@acme.example':return response({'email':email,'status':'invalid'})
            return response({'email':email,'status':'valid','smtp_check':True,'accept_all':False,
                'block':False,'disposable':False,'verification':{'date':datetime.now(timezone.utc).date().isoformat(),'status':'valid'}})
        return transport(url,**kw)
    original_discover=discovery.discover_contacts
    monkeypatch.setattr(discovery,'discover_contacts',lambda website,**kw:original_discover(website,get,**kw))
    original_verify=mailbox.verify_mailbox
    monkeypatch.setattr(mailbox,'verify_mailbox',lambda email,**kw:original_verify(email,get,**kw))
    query='Find businesses in Charlotte, NC with decision-maker emails; if unavailable provide a verified company email.'
    result,_,_=research.run_contact_research({'query':query,'territory':'Charlotte, NC','target_count':1,'offer':''})
    row=result['discovery']['results'][0]
    assert queries==[True,False]
    assert row['contact_email']=='hello@acme.example' and row['contact_name']==''
    assert row['contact_type']=='Company inbox' and row['email_status']=='Verified'

    # The displayed Hunter inbox need not be printed on the company page:
    # its durable provider association and current company identity bind it.
    page={'url':'https://acme.example','candidate_name':'Acme','title':'Acme',
        'page_text':'Acme business services in Charlotte, NC.', 'directly_fetched':True,
        'http_status':200,'observed_at':datetime.now(timezone.utc).isoformat()}
    page['company_identity']=identity_proof('Acme',page,page['url'])
    monkeypatch.setattr(workflow,'_public_contact_evidence',lambda *a:([page],{}))
    monkeypatch.setattr(oa,'run_ai',lambda **kw:{'ok':False})
    import src.email_validation as dns_check
    monkeypatch.setattr(dns_check,'check_email_domain',lambda *a,**kw:{'domain_status':'mx_published'})
    from src.manual_outreach import prepare_contact,contact_readiness
    lead=prepare_contact(row,oa.OutreachLead.query.one(),query,'Charlotte, NC','Automation')
    assert lead.contact_email=='hello@acme.example' and lead.contact_name==''
    assert contact_readiness(lead)['ok'] and lead.subject and lead.body


def test_cancellation_during_web_research_does_not_start_hunter(native,monkeypatch):
    monkeypatch.setattr(research,'_web_companies',lambda *a:(_ for _ in ()).throw(TimeoutError()))
    monkeypatch.setattr(mailbox,'_request',lambda *a,**k:pytest.fail('Cancelled work reached Hunter'))
    with pytest.raises(TimeoutError):research.discover_companies('Find businesses','Charlotte, NC',2)


def test_hunter_connection_check_reports_account_and_credits_without_secrets(native,monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN','check-test')
    monkeypatch.setattr(mailbox,'_request',lambda *a:({'email':'owner@example.com','plan_name':'Free',
        'requests':{'credits':{'remaining':46}}},200))
    client=app.test_client()
    assert client.post('/api/chat/dashboard/hunter/check').status_code in {401,403}
    response=client.post('/api/chat/dashboard/hunter/check',headers={'X-Operator-Token':'check-test'})
    assert response.json=={'ok':True,'state':'Ready','account':'owner@example.com','credits_remaining':46}
    assert 'unit-test-secret' not in response.text


def test_researched_hunter_recipient_reaches_bulk_send_and_followup_once(native,monkeypatch):
    import campaign_jobs as jobs
    from src.manual_outreach import permitted
    wire(monkeypatch)
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN','hunter-handoff-test')
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEY_VERSION','v1')
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEYS','v1=hunter-handoff-signing-test')
    monkeypatch.setattr(jobs,'kick_execution_worker',lambda:None)
    monkeypatch.setattr(oa,'gmail_access_token',lambda:'test-only-access')
    monkeypatch.setattr(oa,'run_ai',lambda **kw:{'ok':False})
    monkeypatch.setattr(research,'discover_companies',lambda *a,**kw:{'companies':[
        {'company':'Acme','website':'https://acme.example','research_source':'Web research',
         'business_status':'Business verified'}],'reason_codes':[]})
    found,_,_=research.run_contact_research({'query':'Find businesses in Charlotte, NC with decision-maker emails',
        'territory':'Norfolk, VA','target_count':1,'offer':'Inquiry follow-up automation'})
    row=found['discovery']['results'][0]
    assert row['contact_email']=='jane@acme.example'
    sends=[]
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**kw:sends.append(a) or {'ok':True,'message_id':'handoff-sent','thread_id':'handoff-thread'})
    client=app.test_client();headers={'X-Operator-Token':'hunter-handoff-test'}
    body={'activate':True,'offer':'Inquiry follow-up automation',
          'selections':[{'kind':'lead','lead_id':row['lead_id']}]}
    response=client.post('/api/chat/workflows/activate-bulk',json=body,headers=headers)
    assert response.status_code==202,response.json
    assert jobs.process_next_execution_job()['ok']
    result=client.get(response.json['poll_url'],headers=headers).json['result']
    assert result['batch']['sent']==1,result
    lead=oa.db.session.get(oa.OutreachLead,row['lead_id'])
    assert len(sends)==1 and sends[0][0]=='jane@acme.example'
    assert lead.location=='Charlotte, NC' and lead.follow_up_due_at and permitted(lead,'followup')
    repeated=client.post('/api/chat/workflows/activate-bulk',json=body,headers=headers)
    assert repeated.json['job_id']==response.json['job_id']
    assert not jobs.process_next_execution_job()['processed'] and len(sends)==1
