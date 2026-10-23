import json
import time
from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
import smart_search as search
import gmail_connect as gmail
from app import app, db
from src.job_evidence import job_page_metadata, check_job_evidence


def test_business_only_hiring_plan_adds_current_job_retrieval():
    calls=search._company_discovery_calls('companies hiring security officers','Chesapeake VA',[
        {'tool':'business_search','query':'security companies','location':'Chesapeake VA'}])
    assert calls[0]['tool']=='web_search'
    assert 'security officers' in calls[0]['query']
    assert {x['tool'] for x in calls}=={'web_search','exa_search','business_search'}


def test_hiring_plan_without_requested_role_gets_focused_queries():
    calls=search._company_discovery_calls('construction companies hiring accounting assistants','Norfolk VA',[
        {'tool':'exa_search','query':'construction assistant managers Norfolk'}])
    assert 'accounting assistants' in calls[0]['query'] and 'construction' in calls[0]['query']


def test_hampton_roads_hiring_queries_separate_enrichment_and_search_cities(monkeypatch):
    monkeypatch.setattr(search,'adzuna_ready',lambda:False)
    q='Find construction companies in Hampton Roads, Virginia looking for automation engineers. Enrich them using Hunter.io and give me their email and phone.'
    calls=search._company_discovery_calls(q,'Hampton Roads, Virginia',[
        {'tool':'web_search','query':q}])
    assert len(calls)<=3
    assert all('hunter' not in c['query'].lower() and 'email' not in c['query'].lower() for c in calls)
    assert 'construction' in calls[0]['query'] and 'automation engineers' in calls[0]['query']
    assert 'Norfolk' in calls[0]['query'] and 'Newport News' in calls[0]['query']
    assert 'Hampton Roads' not in calls[0]['query']
    assert all(c['tool']!='business_search' for c in calls)
    follow=search._company_discovery_calls(q,'Hampton Roads, Virginia',[
        {'tool':'exa_search','query':'Acme automation engineers current careers'}])
    assert follow[0]['query'].startswith('Acme')  # Keep targeted employer follow-ups.
    city=search._additional_discovery(q,'Hampton Roads, VA',0)
    normalized=search._company_discovery_calls(q,'Hampton Roads, VA',[city])
    assert normalized[0]['location']=='Norfolk, Virginia'
    assert ' OR ' not in normalized[0]['query']


def test_regional_hiring_fallback_varies_city_and_preserves_business_constraint():
    q='construction companies hiring automation engineers. Enrich them using Hunter.io'
    calls=[search._additional_discovery(q,'Hampton Roads, VA',n) for n in range(3)]
    assert len({c['query'] for c in calls})==3
    assert all('construction' in c['query'] and 'Hunter' not in c['query'] for c in calls)
    assert [c['location'] for c in calls]==['Norfolk, Virginia','Portsmouth, Virginia','Chesapeake, Virginia']


def test_job_links_ignore_script_markup_assets_and_page_fragments():
    raw='''<script>const fake='<a href="/careers/logo.png">Jobs</a>';</script>
    <a href="#about">Careers</a><a href="/careers/logo.svg">Jobs</a>
    <a href="/jobs/1">Automation Engineer</a>'''
    links=job_page_metadata(raw,'https://acme.example/careers')['source_job_links']
    assert links==[{'url':'https://acme.example/jobs/1','label':'Automation Engineer'}]


def test_inspection_prioritizes_employer_over_shared_job_directory(monkeypatch,live_job_page):
    seen=[]
    monkeypatch.setattr(search,'_page_snapshot',lambda url:seen.append(url) or live_job_page(url=url))
    employer={'url':'https://acme.example/employment/accounting-assistant','page_text':'cached','verification_intents':['hiring']}
    shared={'url':'https://www.linkedin.com/jobs/view/1','verification_intents':['hiring']}
    search._inspect([shared,employer],1)
    assert seen==[employer['url']]


def test_page_verified_employer_survives_omitted_model_candidate(monkeypatch,live_job_page):
    row=live_job_page(title='Accounting Assistant')
    row['source_job_postings']=[]
    row['source_organizations']=[{'name':'Acme','url':'https://acme.example'}]
    row['job_detail_text']='Accounting Assistant Acme Location: Norfolk, VA. Hiring now.'
    q='construction companies hiring accounting assistants'
    monkeypatch.setattr(search,'plan_research',lambda *a:{'tool_calls':[{'tool':'exa_search','query':q}]})
    monkeypatch.setattr(search,'_run_calls',lambda *a:([row],[],['exa_search']))
    monkeypatch.setattr(search,'_memory',lambda *a:[])
    monkeypatch.setattr(search,'extract_candidates',lambda *a:[])
    monkeypatch.setattr(search,'evaluate_research',lambda *a:{})
    monkeypatch.setattr(search,'remember_evidence',lambda *a:None)
    monkeypatch.setattr(search,'_contact_followups',lambda *a:[])
    monkeypatch.setattr(search,'_candidate_followups',lambda *a:pytest.fail('Already verified employer should not need model retrieval'))
    result=search._smart_search(q,'Norfolk VA',runtime_budget=240,target_count=1)
    assert result['verified_count']==1 and result['results'][0]['title']=='Acme'


def test_employer_metadata_does_not_override_wrong_city(live_job_page):
    row=live_job_page(title='Accounting Assistant',city='Boston',state='MA')
    candidates,verified=search._bind_primary_hiring_candidates([row],[],'companies hiring accounting assistants','Norfolk VA')
    assert not candidates and not verified and not row.get('job_validation',{}).get('ok')


def test_cached_exa_hiring_text_must_be_live_fetched(monkeypatch,live_job_page):
    row={'url':'https://acme.example/jobs/1','page_text':'cached snippet','research_tool':'exa_search',
         'verification_intents':['hiring']}
    fetched=[]
    monkeypatch.setattr(search,'_page_snapshot',lambda url:fetched.append(url) or live_job_page(url=url))
    search._inspect([row],1)
    assert fetched==[row['url']] and row['directly_fetched'] is True

def test_initial_cached_hiring_discovery_gets_live_fetch(monkeypatch,live_job_page):
    row={'url':'https://acme.example/jobs/1','page_text':'cached snippet','research_tool':'exa_search'}
    fetched=[]
    monkeypatch.setattr(search,'_page_snapshot',lambda url:fetched.append(url) or live_job_page(url=url))
    search._inspect_discovery([row],'companies hiring AI automation engineers',1)
    assert fetched==[row['url']] and row['directly_fetched'] is True
    assert 'hiring' in row['verification_intents']


def test_job_detail_fetch_has_priority_over_generic_contact(monkeypatch,live_job_page):
    rows=[{'url':'https://acme.example/contact','verification_research':True},
          {'url':'https://acme.example/jobs/1','verification_research':True}]
    fetched=[]
    monkeypatch.setattr(search,'_page_snapshot',lambda url:fetched.append(url) or live_job_page(url=url))
    search._inspect(rows,1)
    assert fetched==['https://acme.example/jobs/1']


def test_web_fallback_job_is_fetched_before_final_verification(monkeypatch,live_job_page):
    url='https://acme.example/jobs/1'
    def retrieve(calls,*a):
        if calls[0]['tool']=='exa_search':return [{'url':'https://acme.example/contact','page_text':'Acme contact'}],[],['exa_search']
        return [{'url':url,'title':'AI Automation Engineer at Acme'}],[],['web_search']
    monkeypatch.setattr(search,'_run_calls',retrieve)
    monkeypatch.setattr(search,'_page_snapshot',lambda u:live_job_page(url=u) if u==url else {})
    evidence,_,_=search._candidate_followups('companies hiring AI automation engineers','Norfolk VA',
        [{'name':'Acme','discovery_urls':['https://acme.example']}],time.monotonic()+90)
    source=next(x for x in evidence if x['url']==url)
    assert check_job_evidence(source,'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']


def test_source_advertised_job_link_is_discovery_not_automatic_proof(monkeypatch,live_job_page):
    root=live_job_page(url='https://acme.example/careers')
    root['source_job_links']=[{'url':'https://acme.example/jobs/1','label':'AI Automation Engineer'},
                              {'url':'https://other.example/jobs/2','label':'AI Automation Engineer'}]
    fetched=[]
    monkeypatch.setattr(search,'_page_snapshot',lambda u:fetched.append(u) or live_job_page(url=u,city='Boston',state='MA'))
    rows=search._follow_job_links([root],'companies hiring AI automation engineers','Norfolk VA',time.monotonic()+30)
    assert fetched==['https://acme.example/jobs/1']
    assert not check_job_evidence(rows[0],'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']


def test_expired_job_link_budget_makes_no_request(monkeypatch,live_job_page):
    row=live_job_page();row['source_job_links']=[{'url':'https://acme.example/jobs/2','label':'AI Automation Engineer'}]
    monkeypatch.setattr(search,'_page_snapshot',lambda u:pytest.fail('Budget exhausted'))
    assert search._follow_job_links([row],'hiring AI automation engineers','Norfolk VA',time.monotonic())==[]


def test_job_listing_metadata_retains_explicit_detail_links():
    raw='<main><a href="/jobs/123">Security Officer</a><a href="https://other.example/jobs/1">Other job</a></main>'
    metadata=job_page_metadata(raw,'https://acme.example/careers')
    assert metadata['source_job_links'][0]['url']=='https://acme.example/jobs/123'
    assert not metadata['source_apply_controls']


@pytest.fixture
def oauth(monkeypatch):
    monkeypatch.delenv('GMAIL_ACCESS_TOKEN',raising=False)
    monkeypatch.setenv('GOOGLE_REFRESH_TOKEN','existing-alternate-test-grant')
    monkeypatch.setenv('GMAIL_FROM_EMAIL','jolleyleads@gmail.com')
    with app.app_context():
        db.create_all();gmail.GmailOAuthConnection.query.delete();db.session.commit()
        row=gmail.GmailOAuthConnection(refresh_token='revoked-test-grant',email='jolleyleads@gmail.com')
        db.session.add(row);db.session.commit()
        yield row
        db.session.rollback();gmail.GmailOAuthConnection.query.delete();db.session.commit()


def test_revoked_stored_grant_can_recover_existing_same_sender(oauth,monkeypatch):
    calls=[]
    def refresh(grant):
        calls.append(grant)
        if grant=='revoked-test-grant':raise RuntimeError('Google token error invalid_grant')
        return 'test-access-never-live'
    monkeypatch.setattr(gmail,'_refresh_access_token',refresh)
    monkeypatch.setattr(gmail.requests,'get',lambda *a,**k:SimpleNamespace(ok=True,json=lambda:{'emailAddress':'jolleyleads@gmail.com'}))
    assert gmail.gmail_access_token()=='test-access-never-live'
    db.session.refresh(oauth)
    assert oauth.refresh_token=='existing-alternate-test-grant'
    assert calls==['revoked-test-grant','existing-alternate-test-grant']


def test_wrong_sender_alternate_is_never_persisted(oauth,monkeypatch):
    monkeypatch.setattr(gmail,'_refresh_access_token',lambda g:(_ for _ in ()).throw(RuntimeError('invalid_grant')) if g=='revoked-test-grant' else 'test-access')
    monkeypatch.setattr(gmail.requests,'get',lambda *a,**k:SimpleNamespace(ok=True,json=lambda:{'emailAddress':'other@example.com'}))
    with pytest.raises(RuntimeError,match='does not match'):gmail.gmail_access_token()
    db.session.refresh(oauth);assert oauth.refresh_token=='revoked-test-grant'


def test_transient_refresh_failure_never_switches_grants(oauth,monkeypatch):
    calls=[]
    def refresh(grant):calls.append(grant);raise RuntimeError('temporarily unavailable')
    monkeypatch.setattr(gmail,'_refresh_access_token',refresh)
    with pytest.raises(RuntimeError):gmail.gmail_access_token()
    assert calls==['revoked-test-grant']


def test_unbound_existing_account_never_tries_alternate(oauth,monkeypatch):
    oauth.email='someone@example.com';db.session.commit()
    calls=[]
    def refresh(grant):calls.append(grant);raise RuntimeError('invalid_grant')
    monkeypatch.setattr(gmail,'_refresh_access_token',refresh)
    with pytest.raises(RuntimeError):gmail.gmail_access_token()
    assert calls==['revoked-test-grant']
