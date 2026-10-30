import json
import os
from pathlib import Path
import subprocess
from unittest.mock import Mock

import pytest
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
import commercial_app
from src.research_intent import parse_research_request
from src import owned_research as owned


@pytest.mark.parametrize('query',[
    'Give me 5 HVAC managers contacts in Norfolk',
    'Give me 5 HVAC presidents email addresses in Norfolk',
    'I am looking for 5 HVAC decisionmakers mobile numbers in Norfolk',
    'Give me 5 HVAC decision–makers phone numbers in Norfolk',
])
def test_role_and_channel_requests_route_without_needing_company_word(query):
    assert owned.accepts(query)
    assert 'decision_maker' in parse_research_request(query)['fields']


def test_public_profile_email_is_research_evidence_without_locality_or_mailbox_claim():
    person={'name':'Jane Doe','source_url':'https://acme.example/team/jane',
            'evidence_excerpt':'Jane Doe, CEO. Contact jane.doe@acme.example.'}
    assert owned._published_person_email(person,'https://acme.example')=='jane.doe@acme.example'
    for text in ['Jane Doe, CEO. info@acme.example',
                 'Jane Doe, CEO. mary@acme.example',
                 'Jane Doe, CEO. Jane Smith, President. jane@acme.example']:
        assert not owned._published_person_email({**person,'evidence_excerpt':text},'https://acme.example')
    assert not owned._published_person_email({**person,'source_url':'https://unrelated.example/team'},'https://acme.example')


def test_source_search_falls_back_to_web_without_hunter(monkeypatch):
    import smart_search
    from src.contact_sources import search
    monkeypatch.setattr(smart_search,'_exa_search',Mock(return_value={'results':[]}))
    web=Mock(return_value={'results':[{'url':'https://acme.example/team'}]})
    monkeypatch.setattr(smart_search,'_web_search',web)
    assert search('company owner','Norfolk')['results'][0]['url']=='https://acme.example/team'
    web.assert_called_once_with('company owner','Norfolk')


def test_working_source_provider_and_cancellation_do_not_launch_another_search(monkeypatch):
    import smart_search
    from src.contact_sources import search
    exa=Mock(return_value={'results':[{'url':'https://acme.example/contact'}]})
    web=Mock(side_effect=AssertionError('Unexpected extra lookup'))
    monkeypatch.setattr(smart_search,'_exa_search',exa)
    monkeypatch.setattr(smart_search,'_web_search',web)
    assert search('owners')['results']
    exa.side_effect=TimeoutError
    with pytest.raises(TimeoutError):search('owners')
    assert not web.called


def test_research_mode_does_not_depend_on_login_or_start_campaign_preparation():
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('demo/index.html','utf8');
const code=html.slice(html.indexOf('function deepSearch(q){'),html.indexOf('\nfunction publicResearch(q){'));
let calls=[];
const context={window:{workspaceAccessReady:Promise.resolve({drafting_available:true})},
 publicResearch:q=>{calls.push(q);return 'research-job';},campaignSearch:()=>{throw Error('Research entered campaign preparation');}};
vm.runInNewContext(code,context);assert.equal(context.deepSearch('owner phones'),'research-job');assert.deepEqual(calls,['owner phones']);
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_contact_list_shows_only_requested_channels_and_their_actual_sources():
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const html=fs.readFileSync('demo/index.html','utf8');
const code=html.slice(html.indexOf('window.renderResearchTable=function(d){'),html.indexOf('\nfunction run(){'));
const context={window:{},esc:s=>String(s||'').replaceAll('<','&lt;').replaceAll('"','&quot;')};vm.runInNewContext(code,context);
const item={company:'Acme <script>',location:'Norfolk',source_url:'https://acme.example',decision_maker:'Jane Doe',decision_maker_role:'Owner',email:'jane@acme.example',email_type:'Named decision-maker email',email_status:'Email found · Mailbox not verified',phone:'757-555-0100',decision_makers:[{name:'Jane Doe',role:'Owner',email:'jane@acme.example',direct_phone:'757-555-0100',source_url:'https://acme.example/team'}],sources:[{label:'Email source',url:'https://acme.example/contact'},{label:'Phone source',url:'https://acme.example/team'}]};
let output=context.window.renderResearchTable({research_intent:{fields:['company','decision_maker','phone']},research_presentation:[item]});
assert(output.includes('<ol class="research-contact-list">'));assert(!output.includes('<table'));
assert(output.includes('Jane Doe')&&output.includes('757-555-0100')&&output.includes('https://acme.example/team'));
assert(!output.includes('jane@acme.example')&&!output.includes('Email source'));assert(!output.includes('<script>'));
output=context.window.renderResearchTable({research_intent:{fields:['company','decision_maker','email']},research_presentation:[item]});
assert(output.includes('jane@acme.example')&&!output.includes('757-555-0100'));assert(output.includes('Mailbox not verified'));
assert(!output.includes('Qualified:')&&!output.includes('Activate workflow'));
const noPerson={company:'Acme',business_phone:'757-555-9999',source_url:'https://acme.example',decision_makers:[]};
output=context.window.renderResearchTable({research_intent:{fields:['company','decision_maker','phone']},research_presentation:[noPerson]});
assert(output.includes('Other company contact options'));assert(output.includes('Not confirmed as the decision-maker'));
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)
