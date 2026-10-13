from datetime import datetime, timezone
from types import SimpleNamespace
import pytest
from src.company_identity import page_metadata, identity_proof
from src.job_evidence import check_job_evidence


def test_source_heading_whitespace_matches_visible_job(live_job_page):
    row=live_job_page(body='<h1>AI Automation Engineer  \n</h1><p>Acme Job location: Norfolk, VA</p>')
    assert row['source_heading']=='AI Automation Engineer'
    assert check_job_evidence(row,'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']


def test_named_logo_proves_abbreviated_owned_domain_not_directory(live_job_page):
    row=live_job_page(company='Example Services',url='https://jobs.es.example/jobs/1')
    row['source_organizations']=[]
    row.update(page_metadata('<a href="https://es.example/"><img alt="Example Services logo"></a>'))
    assert identity_proof('Example Services',row)['basis']=='named_logo_on_owned_root'
    assert not identity_proof('Different Services',row)
    row['resolved_url']='https://directory.example/jobs/1'
    assert not identity_proof('Example Services',row)


def test_other_named_image_without_owned_root_is_not_identity(live_job_page):
    row=live_job_page(company='Example Services',url='https://es.example/jobs/1')
    row['source_organizations']=[]
    row.update(page_metadata('<a href="/news/example-services"><img alt="Example Services"></a>'))
    assert not identity_proof('Example Services',row)


def test_visible_requisition_bridges_frontend_and_ats_job_ids(live_job_page):
    row=live_job_page(url='https://acme.example/jobs/987654321',
        body='<h1>AI Automation Engineer</h1><p>Acme Job location: Norfolk, VA. Req ID: 2026-1705908</p>',
        apply_html='<a href="https://acme.icims.com/jobs/1705908/engineer/job/login">Apply</a>')
    assert check_job_evidence(row,'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']
    row['source_apply_controls'][0]['url']='https://acme.icims.com/jobs/9999/engineer/job/login'
    assert not check_job_evidence(row,'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']


def test_multiple_visible_requisitions_cannot_bless_another_job(live_job_page):
    row=live_job_page(url='https://acme.example/jobs/987654321',
        body='<h1>AI Automation Engineer</h1><p>Acme Job location: Norfolk, VA. Req ID: 2026-1705908 Req ID: 2026-9999</p>',
        apply_html='<a href="https://acme.icims.com/jobs/9999/engineer/job/login">Apply</a>')
    assert not check_job_evidence(row,'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']


def test_structured_identifier_is_bound_to_the_current_job(live_job_page):
    row=live_job_page(url='https://acme.example/jobs/987654321',changes={'identifier':{'value':'1705908'}},
        apply_html='<a href="https://acme.icims.com/jobs/1705908/engineer/job/login">Apply</a>')
    assert check_job_evidence(row,'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']


@pytest.mark.parametrize('instructions,ok',[
    ('How to Apply: Download our employment application and email it to mail@acme.example. Benefits: Insurance.',True),
    ('How to Apply: Email your resume to mail@acme.example. Benefits: Insurance.',True),
    ('Contact us: Email mail@acme.example for more information.',False),
    ('How to Apply: Email your resume to someone@other.example.',False),
    ('How to Apply: For accommodation questions email mail@acme.example.',False),
    ('How to Apply: Email your resume to mail@acme.example or staff@acme.example.',False),
])
def test_email_application_requires_explicit_owned_application_instructions(live_job_page,instructions,ok):
    instructions=instructions.replace('mail@acme.example','<a href="mailto:mail@acme.example">mail@acme.example</a>')
    row=live_job_page(apply_html='',body='<h1>AI Automation Engineer</h1><p>Acme Job location: Norfolk, VA</p><p>'+instructions+'</p>')
    proof=check_job_evidence(row,'companies hiring AI automation engineers','Norfolk VA','Acme')
    assert proof['ok'] is ok
    if ok:
        assert not check_job_evidence(row,'companies hiring AI automation engineers','Boston MA','Acme')['ok']
        row['job_detail_text']+=' This position is filled.'
        assert not check_job_evidence(row,'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']


@pytest.mark.parametrize('opening',['<div hidden>','<fieldset disabled>','<div style="display:none">'])
def test_hidden_or_disabled_email_application_is_not_open(live_job_page,opening):
    row=live_job_page(apply_html='',body='<h1>AI Automation Engineer</h1><p>Acme Job location: Norfolk, VA</p>'+opening+'How to Apply: Email your application to <a href="mailto:mail@acme.example">mail@acme.example</a></div>')
    assert not check_job_evidence(row,'companies hiring AI automation engineers','Norfolk VA','Acme')['ok']


def test_contact_fetch_starts_with_verified_owned_job_source(monkeypatch):
    import outreach_bridge as bridge
    job='https://acme.example/employment/accounting-assistant'
    seen=[]
    def fetch(url,**kwargs):
        seen.append(url)
        assert kwargs['max_bytes']>=400000
        return SimpleNamespace(status_code=200,url=url,headers={'content-type':'text/html'},
            text='<title>Acme</title><p>Acme Location: Norfolk, VA. Email mail@acme.example</p>' if url==job else '')
    monkeypatch.setattr(bridge,'public_get',fetch)
    rows,_=bridge._public_contact_evidence({'company':'Acme','website':'https://acme.example/',
        'supporting_urls':[job,'https://other.example/contact'],'contact_location':'Norfolk VA'})
    assert seen==[job]
    assert rows[0]['validated_emails']==['mail@acme.example']
