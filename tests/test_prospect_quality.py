import copy
import json
from datetime import datetime, timezone, timedelta

import pytest
from src.prospect_quality import POLICY, assess, request_spec, collect_sources, for_lead


@pytest.fixture
def context():
    return {'prospect_policy':POLICY,'query':'Find 10 HVAC businesses','target_location':'Norfolk, VA',
            'offer':'Inquiry follow-up and appointment scheduling automation',
            'request_spec':request_spec('Find 10 HVAC businesses','Norfolk, VA','Inquiry follow-up and appointment scheduling automation')}


def page(need='We manually manage customer inquiries and appointment scheduling.'):
    return {'url':'https://acme.example/','source_title':'Acme','page_text':'Acme HVAC services Norfolk, VA. '+need,
            'directly_fetched':True,'http_status':200,'observed_at':datetime.now(timezone.utc).isoformat()}


def test_valid_email_never_improves_fit_need_or_rank(context):
    bad=page('Schedule service online. We offer appointments.')
    pending=assess('Acme','https://acme.example',context,[bad])
    valid=assess('Acme','https://acme.example',context,[bad],{'person_supported':True,'mailbox_verified':True,'name':'Alice Smith'})
    assert valid['fit']==pending['fit'] and valid['need']==pending['need']
    assert valid['rank']==pending['rank'] and valid['ready'] is False
    assert 'OFFER_NEED_EVIDENCE_REQUIRED' in valid['missing']


def test_supported_business_survives_failed_contact(context):
    q=assess('Acme','https://acme.example',context,[page()],{'email_present':True,'mailbox_status':'accept_all'})
    assert q['well_supported'] and not q['ready']
    assert q['fit']['state']=='Strong' and q['need']['state']=='Supported'
    assert 'RESPONSIBLE_BUYER_REQUIRED' in q['missing']
    assert q['need']['signals'][0]['published_at'] is None
    assert 'publication date unconfirmed' in q['why_now']


@pytest.mark.parametrize('changes',[{'directly_fetched':False},{'http_status':403},
    {'observed_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()},
    {'url':'https://directory.example/acme'},{'rag_retrieved':True}])
def test_stale_snippets_and_other_company_pages_cannot_qualify(context,changes):
    source=page();source.update(changes)
    q=assess('Acme','https://acme.example',context,[source],{'person_supported':True,'mailbox_verified':True})
    assert not q['well_supported'] and not q['ready']


def test_query_does_not_supply_its_own_fit_proof(context):
    source=page();source['page_text']=source['page_text'].replace('HVAC','Dental').replace('Norfolk, VA','Boston, MA')
    q=assess('Acme','https://acme.example',context,[source])
    assert q['fit']['state']!='Strong' and q['need']['state']=='Missing'


def test_current_hiring_signal_is_not_purchase_intent(context,live_job_page):
    source=live_job_page(title='HVAC Customer Service Scheduling Coordinator')
    source['page_text']+=' Acme provides HVAC services in Norfolk, VA.'
    q=assess('Acme','https://acme.example',context,[source])
    assert q['need']['state']=='Supported'
    assert q['need']['signals'][0]['kind']=='current_relevant_hiring'
    assert 'budget are unconfirmed' in q['need']['signals'][0]['interpretation']
    source['source_apply_controls']=[]
    assert assess('Acme','https://acme.example',context,[source])['need']['state']=='Missing'


def test_need_research_follows_only_bounded_owned_sources(context,monkeypatch):
    import smart_search
    calls=[]
    monkeypatch.setattr(smart_search,'_page_snapshot',lambda u:calls.append(u) or page('Schedule service.'))
    monkeypatch.setattr(smart_search,'_exa_search',lambda *a:{'results':[{'url':'https://evil.example/'},
        {'url':'https://acme.example/careers'},{'url':'https://acme.example/about'},{'url':'https://acme.example/four'}]})
    rows=collect_sources({'company':'Acme','website':'https://acme.example/'},context)
    assert len(calls)<=3 and all(u.startswith('https://acme.example') for u in calls)
    assert rows


def test_need_provider_failure_preserves_primary_evidence(context,monkeypatch):
    import smart_search
    monkeypatch.setattr(smart_search,'_page_snapshot',lambda u:page('Schedule service.'))
    def fail(*a):raise TimeoutError('isolated provider failure')
    monkeypatch.setattr(smart_search,'_exa_search',fail)
    rows=collect_sources({'company':'Acme','website':'https://acme.example/'},context)
    assert len(rows)==1


def test_three_assessments_are_persisted_and_bound_before_activation(monkeypatch,context):
    import commercial_app
    import outreach_automation as oa
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEY_VERSION','v1')
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEYS','v1=quality-test')
    with oa.app.app_context():
        oa.db.drop_all();oa.db.create_all()
        source=page('Schedule service.')
        lead=oa.OutreachLead(company='Acme',source_url=source['url'],location='Norfolk, VA',contact_email='alice@acme.example',
            evidence_json=json.dumps([source,{'source':'campaign_context','context':context}]))
        oa.db.session.add(lead);oa.db.session.commit()
        receipt=oa._store_qualification(lead)
        assert not receipt['ok'] and 'OFFER_NEED_EVIDENCE_REQUIRED' in receipt['reason_codes']
        stored=oa.OutreachQualificationReceipt.query.one()
        assert json.loads(stored.receipt_json)['prospect_quality']['version']==POLICY
        with oa.app.test_request_context():
            from src.outreach_activation import activation_view
            assert not activation_view(lead)['can_activate']
        assert oa.OutreachSendAttempt.query.count()==0
        oa.db.session.remove();oa.db.drop_all()


def test_public_search_contract_has_no_new_quality_filter(context,monkeypatch):
    import smart_search
    original=[{'tool':'web_search','query':'Find HVAC businesses'}]
    calls=smart_search._company_discovery_calls('Find HVAC businesses','Norfolk, VA',original)
    assert {c['tool'] for c in calls}=={'web_search','exa_search','business_search'}
    assert all('need' not in c['query'] for c in calls)
