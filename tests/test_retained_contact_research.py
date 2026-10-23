"""Contact research survives an unconfirmed hiring claim without promoting it."""
import json
from pathlib import Path
import subprocess

import pytest
import commercial_app
import smart_search as search
import customer_demo as demo
import v1_orchestration as workflow
from app import app, db
from outreach_automation import OutreachLead
from src.progressive_campaign import _contact_phone

QUERY='Find businesses looking for automation engineers in Hampton Roads, Virginia. Enrich them using Hunter.io'
ROW={'title':'Acme','candidate_name':'Acme','website':'https://acme.example/',
     'url':'https://maps.google.com/?cid=123','classification':'Candidate'}


def test_unconfirmed_company_is_separate_from_current_hiring_matches():
    kept,excluded=search._scope_search_results([ROW],QUERY,'Hampton Roads, Virginia',[])
    assert not kept and excluded
    candidates=search._contact_research_candidates([ROW],kept,[],QUERY,1)
    assert len(candidates)==1 and candidates[0]['request_match_status']=='unconfirmed'
    assert candidates[0]['classification']=='Candidate' and candidates[0]['verification_gate']=='pending'
    assert not candidates[0]['verified_channels']
    assert not search._contact_research_candidates([{**ROW,'website':''}],[],[],QUERY,1)
    assert not search._contact_research_candidates([{**ROW,'website':'https://linkedin.com/company/acme'}],[],[],QUERY,1)
    assert not search._contact_research_candidates([ROW],[ROW],[],QUERY,1)


def test_only_draft_research_can_add_unconfirmed_companies_to_contact_work():
    candidate={**ROW,'request_match_status':'unconfirmed'}
    discovery={'results':[],'contact_research_candidates':[candidate]}
    campaign={'target_customer':QUERY,'territory':'Hampton Roads, Virginia','sending_limit':1}
    assert demo._orchestration_payload(discovery,campaign)['results']==[]
    payload=demo._orchestration_payload(discovery,campaign,research_contacts=True)
    assert payload['results'][0]['classification']=='Candidate'
    assert discovery['results']==[]


@pytest.fixture
def clean_db(monkeypatch):
    monkeypatch.setenv('AUTOMAKE_ISOLATED_EXECUTION','0')
    with app.app_context():
        db.session.remove();db.drop_all();db.create_all()
        yield
        db.session.remove();db.drop_all()


def test_zero_hiring_matches_still_reaches_contact_lookup_and_keeps_email_without_sending(clean_db,monkeypatch):
    discovery={'results':[],'contact_research_candidates':[{**ROW,'request_match_status':'unconfirmed'}]}
    monkeypatch.setattr(demo,'_smart_search',lambda *a,**kw:discovery)
    monkeypatch.setattr(demo,'enhance_discovery',lambda result,*a:result)
    looked_up=[]
    def contact(row):
        looked_up.append(row['title'])
        enrichment={'identity_status':'source_bound','fields':{
            'website':{'value':ROW['website'],'validated':True},
            'phone':{'value':'(757) 555-0100','source_url':ROW['website'],'validated':True}},
            'contact_assessment':{'mailbox_validation':{'email':'owner@acme.example','mailbox_status':'provider_verified'}}}
        row['_contact_enrichment']=enrichment
        row['_contact_identity']={'enrichment':enrichment}
        return 'owner@acme.example',ROW['website']
    monkeypatch.setattr(workflow,'_verified_public_email',contact)
    monkeypatch.setattr(workflow,'_store_qualification',lambda lead:{'ok':False,'reason_codes':['INTENT_SIGNAL_UNPROVEN']})
    monkeypatch.setattr(workflow,'_draft_email',lambda *a:pytest.fail('Unconfirmed hiring cannot draft'))
    monkeypatch.setattr(workflow,'_safe_send',lambda *a,**k:pytest.fail('Contact research cannot send'))
    import lead_recovery
    monkeypatch.setattr(lead_recovery,'schedule_recovery',lambda *a:None)
    result,stage,error=demo._run_campaign({'target_customer':QUERY,'territory':'Hampton Roads, Virginia',
        'target_count':1,'offer':'Automation engineering','draft_only':True})
    assert result and not stage and not error and looked_up==['Acme']
    assert result['discovery']['results']==[]
    assert len(result['discovery']['contact_research_candidates'])==1
    assert result['outreach']['saved']==1 and result['outreach']['qualified']==0
    assert result['outreach']['sent']==0 and result['outreach']['drafted']==0
    lead=OutreachLead.query.one()
    assert lead.contact_email=='owner@acme.example' and lead.status=='needs_evidence'
    assert _contact_phone(lead)=='(757) 555-0100'
    evidence=json.loads(lead.evidence_json)
    next(r for r in evidence if r.get('enrichment'))['enrichment']['fields']['phone']['source_url']='https://other.example/'
    lead.evidence_json=json.dumps(evidence)
    assert _contact_phone(lead)==''


def test_final_cards_label_unconfirmed_hiring_and_show_available_contact_fields():
    source=Path('demo/access.js').read_text()
    helpers=source[source.index('window.businessMatchNote='):source.index('window.renderResearchProgress=')]
    cards=source[source.index('window.renderBusinessCards='):source.index('// An explicit customer click')]
    email=source[source.index('window.businessEmail=function'):source.index('window.bulkActivationControl=')]
    script="const assert=require('node:assert/strict');const window={businessEmailValue:r=>r.contact_email,businessAction:r=>window.businessEmail(r),contactProgressMessage:()=>''};const esc=String;"+helpers+cards+email+r'''
const result={discovery:{results:[],contact_research_candidates:[{}]}};
assert(window.researchResultHeading(result).includes('No hiring matches confirmed.'));
assert(!window.researchResultHeading(result).includes('Found 0'));
const html=window.renderBusinessCards([{company:'Acme',request_match_status:'unconfirmed',contact_email:'owner@acme.example',contact_phone:'(757) 555-0100'}]);
assert(html.includes('Hiring not confirmed. Contact research only.'));
assert(html.includes('owner@acme.example')&&html.includes('(757) 555-0100'));
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
