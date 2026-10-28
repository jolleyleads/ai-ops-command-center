"""Source collection and mailbox verification have separate effects and evidence."""
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from types import SimpleNamespace
import subprocess

import pytest
import commercial_app
import outreach_bridge as bridge
import outreach_automation as outreach
from app import app,db
from src import owned_research as owned,hunter_discovery,hunter_mailbox
from src.company_identity import identity_proof
from workspace_security import claim,OWNER

QUERY='Give me five electrical businesses with their emails'
CAMPAIGN={'query':QUERY,'territory':'Norfolk, VA','target_count':1,'offer':'Scheduling automation'}
COMPANY={'company':'Acme Electrical','website':'https://acmeelectrical.example/',
         'listing_location':'Norfolk, VA','discovery_source':'Google Places'}


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN','owned-contact-test')
    monkeypatch.setenv('AUTOMAKE_ISOLATED_EXECUTION','0')
    monkeypatch.setattr(hunter_discovery,'discover_contacts',lambda *a,**k:pytest.fail('Collection purchased Hunter data'))
    monkeypatch.setattr(hunter_mailbox,'verify_mailbox',lambda *a,**k:pytest.fail('Collection verified a mailbox'))
    monkeypatch.setattr(outreach,'_gmail_send',lambda *a,**k:pytest.fail('Research sent email'))
    monkeypatch.setattr(owned,'check_email_domain',lambda email:{'email':email,'domain_status':'mx_published','mailbox_status':'unconfirmed'})
    with app.app_context():
        db.session.remove();db.drop_all();db.create_all()
        yield
        db.session.remove();db.drop_all()


def page(text=None):
    row={'url':'https://acmeelectrical.example/contact','candidate_name':'Acme Electrical',
         'source_title':'Acme Electrical contact','page_text':text or
         'Acme Electrical provides electrical services in Norfolk, VA. Contact hello@acmeelectrical.example or call (757) 555-1234.',
         'directly_fetched':True,'http_status':200,'observed_at':datetime.now(timezone.utc).isoformat()}
    row['company_identity']=identity_proof('Acme Electrical',row,COMPANY['website'])
    return row


def wire(monkeypatch,rows=None):
    import v1_orchestration
    monkeypatch.setattr(owned,'discover',lambda *a:([COMPANY],[]))
    def fetch(row,**kw):
        assert kw=={'use_provider':False}
        return rows if rows is not None else [page()],{}
    monkeypatch.setattr(bridge,'_public_contact_evidence',fetch)
    monkeypatch.setattr(v1_orchestration,'_public_contact_evidence',fetch)


def test_owned_collection_persists_sources_without_any_hunter_calls_or_sending(setup,monkeypatch):
    wire(monkeypatch)
    result,stage,error=owned.run(CAMPAIGN)
    assert not stage and not error and result['owned_contact_research']
    assert result['discovery']['emails_found']==1 and result['discovery']['verified']==0
    row=result['discovery']['results'][0]
    assert row['contact_email']=='hello@acmeelectrical.example'
    assert row['email_status']=='Email found · Mailbox not verified'
    assert row['domain_status']=='mx_published' and not row['contact_check']['mailbox_verified']
    assert row['email_source_url']==page()['url'] and row['email_observed_at']
    assert row['filter_status']=='matched' and row['contact_phone']=='(757) 555-1234'
    lead=outreach.OutreachLead.query.one()
    assert owned.snapshot(lead)['pages'][0]['company_identity']
    assert lead.status=='needs_evidence' and not lead.subject and not lead.body
    assert result['outreach']['sent']==result['outreach']['drafted']==0


def test_real_fetch_can_skip_provider_even_when_hunter_is_enabled(setup,monkeypatch):
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','true')
    raw='<html><title>Acme Electrical</title><p>Acme Electrical in Norfolk, VA. Email hello@acmeelectrical.example</p></html>'
    monkeypatch.setattr(bridge,'public_get',lambda url,**kw:SimpleNamespace(status_code=200,url=url,text=raw,headers={'content-type':'text/html'}))
    rows,receipt=bridge._public_contact_evidence(COMPANY,use_provider=False)
    assert rows and receipt['attempted'] and 'hello@acmeelectrical.example' in rows[0]['validated_emails']


def test_discovery_uses_industry_and_territory_without_email_instructions(setup,monkeypatch):
    import universal_app,smart_search
    calls=[]
    def places(query,location):
        calls.append((query,location));return {'results':[
            {'title':'Acme Electrical','website':COMPANY['website'],'subtitle':'Norfolk, VA','status':'OPERATIONAL'},
            {'title':'Duplicate','website':COMPANY['website']},
            {'title':'Closed','website':'https://closed.example','status':'CLOSED_PERMANENTLY'},
            {'title':'Directory','website':'https://linkedin.com/company/acme'}]}
    monkeypatch.setattr(universal_app,'_search_businesses',places)
    monkeypatch.setattr(smart_search,'_exa_search',lambda *a:pytest.fail('Enough current discovery hints already returned'))
    rows,diagnostics=owned.discover(owned.request_filters(QUERY,'Norfolk, VA'),1)
    assert len(rows)==1 and calls==[('electrical businesses','Norfolk, VA')] and not diagnostics


def test_web_hit_requires_company_identity_from_primary_page(setup,monkeypatch):
    import src.public_fetch as fetch
    def response(text):return SimpleNamespace(status_code=200,url='https://acmeelectrical.example/',text=text)
    monkeypatch.setattr(fetch,'public_get',lambda *a,**k:response('<title>Best electrical companies | Top directory</title>'))
    assert owned._primary_seed({'url':COMPANY['website'],'title':'Made up company'}) is None
    monkeypatch.setattr(fetch,'public_get',lambda *a,**k:response('<title>Acme Electrical</title><p>Acme Electrical in Norfolk, VA.</p>'))
    assert owned._primary_seed({'url':COMPANY['website'],'title':'Made up company'})['company']=='Acme Electrical'


def test_authenticated_contact_request_routes_to_owned_collection_before_legacy_hunter(setup,monkeypatch):
    import customer_demo
    wire(monkeypatch)
    monkeypatch.setattr(customer_demo,'_smart_search',lambda *a,**k:pytest.fail('Contact collection invoked an AI research plan'))
    result,_,_=customer_demo._run_campaign({'target_customer':QUERY,'territory':'Norfolk, VA',
        'target_count':1,'offer':'Scheduling','draft_only':True})
    assert result['owned_contact_research'] and result['discovery']['verified']==0


@pytest.mark.parametrize('change',[{'directly_fetched':False},{'observed_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()},
                                  {'url':'https://other.example/contact'},{'source_title':'Other company','page_text':'Other company hello@acmeelectrical.example'}])
def test_unbound_stale_or_search_snippet_contacts_are_not_promoted(setup,monkeypatch,change):
    row={**page(),**change};wire(monkeypatch,[row])
    result,_,_=owned.run(CAMPAIGN,save_contacts=False)
    assert not result['discovery']['results'][0]['contact_email']
    assert not result['discovery']['verified'] and outreach.OutreachLead.query.count()==0


def test_wrong_geography_excluded_and_unsupported_filters_never_pass(setup,monkeypatch):
    wire(monkeypatch,[page('Acme Electrical serves Charlotte, NC. hello@acmeelectrical.example')])
    monkeypatch.setattr(owned,'discover',lambda *a:([{**COMPANY,'listing_location':'Charlotte, NC'}],[]))
    result,_,_=owned.run(CAMPAIGN)
    assert result['discovery']['results']==[] and not result['discovery']['target_met']
    wire(monkeypatch)
    result,_,_=owned.run({**CAMPAIGN,'query':QUERY+' with revenue over $1 million'})
    assert result['discovery']['results'][0]['filter_status']=='unconfirmed'


def test_null_mx_and_wrong_company_addresses_not_shown_as_contacts(setup,monkeypatch):
    wire(monkeypatch,[page('Acme Electrical in Norfolk, VA. hello@acmeelectrical.example fake@gmail.com')])
    monkeypatch.setattr(owned,'check_email_domain',lambda email:{'email':email,'domain_status':'does_not_accept_mail'})
    result,_,_=owned.run(CAMPAIGN)
    row=result['discovery']['results'][0]
    assert not row['contact_email'] and not row['public_contacts'] and row['email_status']=='No email found'


def test_cached_primary_sources_are_reused_but_only_in_the_owned_workspace(setup,monkeypatch):
    wire(monkeypatch)
    owned.run(CAMPAIGN)
    lead=outreach.OutreachLead.query.one()
    captured=[]
    def discover(filters,limit,cached):captured.extend(cached);return cached,[]
    monkeypatch.setattr(owned,'discover',discover)
    monkeypatch.setattr(bridge,'_public_contact_evidence',lambda *a,**k:pytest.fail('Fresh cached pages were fetched again'))
    owned.run(CAMPAIGN)
    assert captured and owned.snapshot(lead)['cache_hit']
    from workspace_security import ResourceOwnership
    db.session.get(ResourceOwnership,('lead',str(lead.id))).workspace_id='other-customer';db.session.commit()
    captured.clear();owned.run(CAMPAIGN)
    assert not captured


def test_mailbox_verification_is_explicit_owned_and_does_not_send(setup,monkeypatch):
    wire(monkeypatch);owned.run(CAMPAIGN);lead=outreach.OutreachLead.query.one()
    calls=[]
    def verify(email,**kw):
        calls.append((email,kw));return {'email':email,'mailbox_status':'provider_verified',
            'checked_at':datetime.now(timezone.utc).isoformat(),'provider_verified_on':'2026-10-25'}
    monkeypatch.setattr(hunter_mailbox,'verify_mailbox',verify)
    client=app.test_client();path='/api/chat/contacts/verify'
    assert client.post(path,json={'lead_id':lead.id}).status_code==401 and not calls
    headers={'X-Operator-Token':'owned-contact-test'}
    assert client.post(path,json={'lead_id':lead.id+10},headers=headers).status_code==404 and not calls
    result=client.post(path,json={'lead_id':lead.id},headers=headers)
    assert result.status_code==200 and result.json['contact']['email_status']=='Verified'
    assert calls==[(lead.contact_email,{})]
    assert lead.status=='needs_evidence' and not lead.sent_at and not lead.subject


def test_unconfirmed_or_wrong_address_receipts_cannot_verify(setup,monkeypatch):
    wire(monkeypatch);owned.run(CAMPAIGN);lead=outreach.OutreachLead.query.one()
    headers={'X-Operator-Token':'owned-contact-test'};client=app.test_client()
    monkeypatch.setattr(hunter_mailbox,'verify_mailbox',lambda email,**kw:{'email':email,'mailbox_status':'unconfirmed'})
    result=client.post('/api/chat/contacts/verify',json={'lead_id':lead.id},headers=headers)
    assert result.status_code==200 and result.json['contact']['email_status']!='Verified'
    monkeypatch.setattr(hunter_mailbox,'verify_mailbox',lambda email,**kw:{'email':'wrong@acmeelectrical.example','mailbox_status':'provider_verified'})
    assert client.post('/api/chat/contacts/verify',json={'lead_id':lead.id},headers=headers).status_code==502
    assert owned.view(lead)['email_status']!='Verified'


def test_stale_sources_and_other_workspace_contacts_never_purchase_verification(setup,monkeypatch):
    wire(monkeypatch);owned.run(CAMPAIGN);lead=outreach.OutreachLead.query.one()
    client=app.test_client();headers={'X-Operator-Token':'owned-contact-test'}
    rows=json.loads(lead.evidence_json)
    rows[0]['pages'][0]['observed_at']=(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()
    lead.evidence_json=json.dumps(rows);db.session.commit()
    assert client.post('/api/chat/contacts/verify',json={'lead_id':lead.id},headers=headers).status_code==409
    from workspace_security import ResourceOwnership
    db.session.get(ResourceOwnership,('lead',str(lead.id))).workspace_id='other-customer';db.session.commit()
    assert client.post('/api/chat/contacts/verify',json={'lead_id':lead.id},headers=headers).status_code==404
    assert client.post('/api/chat/contacts/verify',json=[1,2],headers=headers).status_code==400


def test_owned_contact_preparation_keeps_verification_but_skips_hunter_discovery(setup,monkeypatch):
    wire(monkeypatch);owned.run(CAMPAIGN);lead=outreach.OutreachLead.query.one()
    calls=[]
    def verify(email,**kw):
        calls.append(email);return {'email':email,'mailbox_status':'provider_verified',
            'checked_at':datetime.now(timezone.utc).isoformat(),'deliverability_status':'provider_verified'}
    monkeypatch.setattr(hunter_mailbox,'verify_mailbox',verify)
    from src.manual_outreach import prepare_contact,contact_readiness
    result=prepare_contact(owned.view(lead),lead,QUERY,'Norfolk, VA','Scheduling automation')
    assert calls==['hello@acmeelectrical.example'] and contact_readiness(result)['ok']
    assert result.subject and result.body and not result.sent_at


def test_frontend_distinguishes_found_from_verified_and_labels_credit_use():
    source=Path('demo/access.js').read_text()
    summary=source[source.index('window.renderContactSummary='):source.index('window.businessMatchNote=')]
    heading=source[source.index('window.researchResultHeading='):source.index('window.verifyOwnedMailbox=')]
    script="const assert=require('node:assert/strict');const window={};const esc=String;"+summary+heading+'''
const row={provider_contact_research:true,owned_contact_research:true,lead_id:1,contact_email:'hello@acme.example',email_status:'Email found · Mailbox not verified',email_source_url:'https://acme.example/contact',research_source:'AutoMake public sources'};
const html=window.renderContactSummary(row);
assert(html.includes('Mailbox not verified')&&html.includes('Email source'));
assert(html.includes('Free daily allowance with Verifalia')&&html.includes('Does not send email'));
assert(!html.includes('Contact checked with Hunter'));
assert(window.researchResultHeading({contact_research:true,owned_contact_research:true,discovery:{results:[row]}}).includes('1 emails found · 0 mailboxes verified'));
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_autohunt_name_and_common_prompt_words_do_not_change_business_filters():
    for query in ['Find 10 electrical businesses in Chesapeake Virginia using AutoHunt',
                  'Use AutoHunt to find 10 electrical businesses in Chesapeake Virginia with current emails',
                  'Give me 10 dentists businesses in Chesapeake Virginia that have updated emails and use autohunt to verify decision makers']:
        assert owned.accepts(query)
        filters=owned.request_filters(query,'Chesapeake Virginia')
        assert filters['industry_terms'] in [['electrical'],['dentists']]
        assert not filters['additional_filters_need_review']
    assert owned.request_filters('Find 10 dental businesses in Chesapeake Virginia using AutoHunt with revenue over $1 million','Chesapeake Virginia')['additional_filters_need_review']


def test_research_keeps_multiple_documented_executives_without_choosing_outreach_buyer(setup,monkeypatch):
    rows=[page('Acme Electrical in Norfolk, VA. Jane Doe, CEO. jane@acmeelectrical.example'),
          {**page('Acme Electrical in Norfolk, VA. Mary Jones, President. mary@acmeelectrical.example'),
           'url':'https://acmeelectrical.example/team'}]
    wire(monkeypatch,rows)
    result,_,_=owned.run({**CAMPAIGN,'query':'Give me five electrical companies with decision-maker contact information'})
    row=result['discovery']['results'][0]
    assert {p['name'] for p in row['decision_makers']}=={'Jane Doe','Mary Jones'}
    assert row['contact_name']==''  # Research does not select one of two equally supported buyers.
    assert len(result['research_presentation'][0]['decision_makers'])==2
    assert result['outreach']['sent']==0


def test_leadership_search_hints_must_be_fetched_on_owned_domain(setup,monkeypatch):
    import smart_search
    fetched=[]
    monkeypatch.setattr(smart_search,'_exa_search',lambda *a:{'results':[
        {'url':'https://acmeelectrical.example/meet-our-team.html','page_text':'invented owner'},
        {'url':'https://other.example/team','page_text':'invented CEO'}]})
    def get(url,**kw):
        fetched.append(url)
        return SimpleNamespace(status_code=200,url=url,headers={'content-type':'text/html'},
            text='<title>Acme Electrical</title><p>Acme Electrical in Norfolk, VA. Jane Doe, CEO. jane@acmeelectrical.example</p>')
    monkeypatch.setattr(bridge,'public_get',get)
    rows,_=bridge._public_contact_evidence({**COMPANY,'location':'Norfolk, VA','query':'business outreach contact','decision_maker_research':True},use_provider=False)
    assert fetched[0]=='https://acmeelectrical.example/meet-our-team.html'
    assert not any('other.example' in url for url in fetched)
    assert rows and all(r['directly_fetched'] for r in rows)
    assert not any('invented' in r['page_text'] for r in rows)


def test_original_chesapeake_request_preserves_industry_and_geography(setup):
    from src.hunter_research import search_location
    query='I give me five HVAC companies in Chesapeake, Virginia, but I need their decision-maker contact information like manager, CEO, etc.'
    location=search_location(query,'Hampton Roads Virginia')
    assert location=='Chesapeake, Virginia'
    filters=owned.request_filters(query,location)
    assert filters['industry_terms']==['hvac']
    assert not filters['additional_filters_need_review']


def test_named_contact_request_refills_beyond_company_only_rows(setup,monkeypatch):
    companies=[{**COMPANY,'company':'Company Only','website':'https://company-only.example/'},
               {**COMPANY,'company':'Named Company','website':'https://named.example/'}]
    monkeypatch.setattr(owned,'discover',lambda *a:(companies,[]))
    def collect(company,*a):
        text=company['company']+' in Norfolk, VA. Electrical services. (757) 555-1234.'
        if company['company']=='Named Company':text+=' Jane Doe, CEO.'
        source=company['website']
        record_page={**page(text),'url':source,'candidate_name':company['company'],'source_title':company['company']}
        from src.enrichment import enrich_lead
        enrichment=enrich_lead({'company':company['company'],'website':source,'target_location':'Norfolk, VA','query':'business outreach'},[record_page])
        return {'source':'automake_contact_research','enrichment':enrichment,'pages':[record_page],
                'contacts':[],'business_research':{'filter_status':'matched'},'excluded':False}
    monkeypatch.setattr(owned,'collect',collect)
    result,_,_=owned.run({**CAMPAIGN,'query':'Give me one electrical company with decision-maker contact information'},save_contacts=False)
    rows=result['discovery']['results']
    assert len(rows)==1 and rows[0]['company']=='Named Company'
    assert rows[0]['contact_name']=='Jane Doe'
    assert result['discovery']['contact_target_met'] is True
    assert result['outreach']['sent']==0


@pytest.mark.parametrize('label,expected',[('Direct:','(757) 555-7777'),('Mobile:','(757) 555-7777'),('Office:','')])
def test_only_explicit_person_direct_numbers_are_labeled_direct(label,expected):
    person={'name':'Jane Doe','evidence_excerpt':'Jane Doe, CEO. '+label+' (757) 555-7777'}
    assert owned._published_direct_phone(person)==expected

def test_another_persons_name_cannot_bless_an_unrelated_direct_number():
    assert not owned._published_direct_phone({'name':'Jane Doe','evidence_excerpt':'Mary Jones, CEO. Direct: (757) 555-7777'})
