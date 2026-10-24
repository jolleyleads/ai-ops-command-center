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
