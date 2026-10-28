import json
from datetime import datetime
import pytest
import commercial_app
from app import app, db
import outreach_automation as oa
import campaign_jobs as jobs
from src import email_workflows as desk
from workspace_security import OWNER, claim

HEADERS={'X-Operator-Token':'provided-workflow-test'}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN','provided-workflow-test')
    monkeypatch.setattr(jobs,'kick_execution_worker',lambda:None)
    monkeypatch.setattr(oa,'gmail_access_token',lambda:'test-access-token')
    monkeypatch.setattr(oa,'_independent_mailbox_gate',lambda *a:pytest.fail('A provided recipient was sent through a research/enrichment gate'))
    with app.app_context():
        db.session.remove();db.drop_all();db.create_all()
        yield app.test_client()
        db.session.remove();db.drop_all()


def add(client,*emails):
    response=client.post('/api/chat/email-workflows',headers=HEADERS,json={'emails':list(emails)})
    assert response.status_code==200,response.json
    return response.json['contacts']


def activate(client,ids):
    return client.post('/api/chat/email-workflows/activate',headers=HEADERS,json={'activate':True,'ids':ids})


def run_job(response):
    assert response.status_code==202,response.json
    job=db.session.get(jobs.CampaignExecutionJob,response.json['job_id'])
    job.status='running';job.started_at=datetime.utcnow();db.session.commit()
    assert jobs.execute_claimed_job(job.id)['processed']==1
    db.session.refresh(job)
    return job,json.loads(job.result_json)


def test_add_is_durable_deduplicated_and_never_sends_or_qualifies(client,monkeypatch):
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:pytest.fail('Adding sent mail'))
    rows=add(client,'Owner@Example.com','owner@example.com','person@gmail.com')
    assert len(rows)==2 and desk.EmailWorkflowContact.query.count()==2
    assert jobs.CampaignExecutionJob.query.count()==0
    assert all(row['status']=='idle' and row['can_activate'] for row in rows)
    assert client.get('/api/chat/email-workflows',headers=HEADERS).json['contacts']
    assert all(lead.verification=='USER_PROVIDED' and not lead.source_url for lead in oa.OutreachLead.query.all())
    assert not any(oa._qualification_gate(lead)['ok'] for lead in oa.OutreachLead.query.all())


def test_invalid_input_has_no_partial_saved_contacts(client):
    for value in [{'emails':['good@example.com','bad address']},{'emails':['good@example.com',42]},['bad']]:
        assert client.post('/api/chat/email-workflows',headers=HEADERS,json=value).status_code==400
    assert desk.EmailWorkflowContact.query.count()==0
    assert oa.OutreachLead.query.count()==0


def test_selective_activation_only_sends_selected_and_starts_followups(client,monkeypatch):
    sent=[]
    monkeypatch.setattr(oa,'_gmail_send',lambda email,*a:(sent.append(email) or {'ok':True,'message_id':'message-'+email,'thread_id':'thread-'+email}))
    rows=add(client,'first@example.com','second@gmail.com','excluded@example.com')
    response=activate(client,[rows[0]['id'],rows[1]['id']])
    # Queuing and status reads cannot execute a send.
    assert not sent
    assert client.get('/api/chat/email-workflows',headers=HEADERS).status_code==200
    assert not sent
    job,result=run_job(response)
    assert job.status=='completed' and set(sent)=={'first@example.com','second@gmail.com'}, result
    assert len(result['email_workflows'])==2
    assert all(row['status']=='active' for row in result['email_workflows'])
    assert db.session.get(oa.OutreachLead,rows[2]['lead_id']).gmail_message_id in (None,'')
    for row in rows[:2]:
        lead=db.session.get(oa.OutreachLead,row['lead_id'])
        assert lead.follow_up_due_at and not oa._qualification_gate(lead)['ok']
        assert desk.permitted(lead,'followup') and not desk.permitted(lead,'initial')
    # Existing explicit workflow grants do not authorize a different recipient.
    lead.contact_email='changed@example.com';db.session.commit()
    assert not desk.permitted(lead,'followup')


def test_double_activation_reuses_pending_job_and_cannot_duplicate_send(client,monkeypatch):
    sent=[]
    monkeypatch.setattr(oa,'_gmail_send',lambda email,*a:(sent.append(email) or {'ok':True,'message_id':'m','thread_id':'t'}))
    row=add(client,'owner@example.com')[0]
    first=activate(client,[row['id']]);second=activate(client,[row['id']])
    assert first.json['job_id']==second.json['job_id']
    run_job(first)
    third=activate(client,[row['id']])
    assert third.json['job_id']==first.json['job_id'] and sent==['owner@example.com']
    assert oa.OutreachSendAttempt.query.count()==1


def test_initial_send_has_no_permission_without_exact_running_job_grant(client):
    row=add(client,'owner@example.com')[0]
    lead=db.session.get(oa.OutreachLead,row['lead_id'])
    assert not desk.permitted(lead,'initial') and not desk.permitted(lead,'followup')
    assert not oa._send_authorization_gate(lead,'initial')['ok']
    assert client.post('/api/outreach/leads/'+str(lead.id)+'/send',headers=HEADERS).status_code==409
    response=activate(client,[row['id']])
    with desk.authorize(lead,response.json['job_id']) as allowed:assert not allowed
    job=db.session.get(jobs.CampaignExecutionJob,response.json['job_id']);job.status='running';db.session.commit()
    with desk.authorize(lead,job.id) as allowed:
        assert allowed and desk.permitted(lead,'initial')
    assert not desk.permitted(lead,'initial')


def test_foreign_selection_and_missing_activation_cannot_schedule_work(client):
    row=add(client,'owner@example.com')[0]
    assert client.post('/api/chat/email-workflows/activate',headers=HEADERS,json={'ids':[row['id']]}).status_code==400
    assert activate(client,[row['id'],'foreign-id']).status_code==404
    assert jobs.CampaignExecutionJob.query.count()==0
    assert client.get('/api/chat/email-workflows').status_code==401
    assert client.post('/api/chat/email-workflows',json={'emails':['test@example.com']}).status_code==401


def test_preview_is_read_only_and_uses_the_same_unresearched_message(client,monkeypatch):
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:pytest.fail('Preview sent mail'))
    row=add(client,'owner@example.com')[0]
    preview=client.get('/api/chat/email-workflows/'+row['id']+'/preview',headers=HEADERS).json['preview']
    assert preview['recipient']=='owner@example.com' and preview['body'].startswith('Hey there')
    assert 'Your work at' not in preview['body'] and preview['attachment'].endswith('.docx')
    assert jobs.CampaignExecutionJob.query.count()==0


def test_suppressed_recipient_cannot_be_activated(client,monkeypatch):
    row=add(client,'owner@example.com')[0]
    monkeypatch.setattr(oa,'_is_suppressed',lambda email:True)
    assert activate(client,[row['id']]).status_code==409
    assert jobs.CampaignExecutionJob.query.count()==0


def test_uncertain_provider_receipt_is_not_reported_sent_or_retried(client,monkeypatch):
    calls=[]
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:(calls.append(1) or {'ok':True,'message_id':'incomplete'}))
    row=add(client,'owner@example.com')[0]
    _,result=run_job(activate(client,[row['id']]))
    assert result['email_workflows'][0]['status']!='active'
    assert not desk.permitted(db.session.get(oa.OutreachLead,row['lead_id']),'followup')
    latest=client.get('/api/chat/email-workflows',headers=HEADERS).json['contacts'][0]
    assert latest['status']=='review' and not latest['can_activate']
    activate(client,[row['id']])
    assert calls==[1]


def test_spoken_addresses_normalize_without_sending_or_page_actions():
    import subprocess
    script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let sent=0;
const context={window:{location:{search:''}},Set,Array,String,URLSearchParams,workspaceMutation:()=>{sent++;}};
vm.runInNewContext(fs.readFileSync('static/email-workflows.js','utf8'),context);
const parse=context.window.parseWorkflowEmails;
assert.equal(JSON.stringify(parse('Owner at Company dot com\nowner@company.com; person@gmail.com')),JSON.stringify(['owner@company.com','person@gmail.com']));
assert.equal(JSON.stringify(parse('first underscore last at coastal dash hvac dot com')),JSON.stringify(['first_last@coastal-hvac.com']));
assert.equal(JSON.stringify(parse('name @ example . com')),JSON.stringify(['name@example.com']));
assert.equal(sent,0);
'''
    subprocess.run(['node','-e',script],check=True,capture_output=True,text=True)


def test_isolated_worker_loads_command_bound_gmail_sender(tmp_path):
    import os,subprocess,sys
    env=dict(os.environ,DATABASE_URL='sqlite:///'+str(tmp_path/'isolated-worker.db'))
    script="""
from app import app
with app.app_context():
    import customer_demo
    import outreach_automation as oa
    from src.email_workflows import run_email_workflows
    assert run_email_workflows({},'not-a-job')[1]=='authorization'
    assert oa._safe_send.__module__=='gmail_reconciliation'
"""
    subprocess.run([sys.executable,'-c',script],env=env,check=True,capture_output=True,text=True)


@pytest.mark.parametrize('complete',[True,False])
def test_existing_gmail_history_cannot_be_resent_without_an_attempt_row(client,complete,monkeypatch):
    monkeypatch.setattr(oa,'_gmail_send',lambda *a:pytest.fail('Existing conversation was resent'))
    lead=oa.OutreachLead(company='Existing contact',contact_email='already@example.com',gmail_message_id='old-message',
                         gmail_thread_id='old-thread' if complete else '',sent_at=datetime.utcnow() if complete else None)
    db.session.add(lead);db.session.flush();claim('lead',lead.id,OWNER);db.session.commit()
    row=add(client,'already@example.com')[0]
    assert row['status']==('active' if complete else 'review') and not row['can_activate']
    assert activate(client,[row['id']]).status_code==409
    assert jobs.CampaignExecutionJob.query.count()==0


def test_provided_email_reply_recovers_review_then_books_once(client,monkeypatch):
    import v1_orchestration as scanner
    sent=[];events=[];checks=[]
    monkeypatch.setattr(oa,'_gmail_send',lambda email,*args:(sent.append((email,args)) or {'ok':True,'message_id':'sent-'+str(len(sent)),'thread_id':'thread'}))
    row=add(client,'recipient@example.com')[0]
    run_job(activate(client,[row['id']]))
    lead=db.session.get(oa.OutreachLead,row['lead_id'])
    # Reproduce a scheduling question held by the old scanner, including AOL footer.
    text="I'm Interested, when can you chat? Sent from the all new AOL app for iOS"
    evidence={'message_id':'interest','from_email':lead.contact_email,'text':text,'internal_date':'1'}
    oa._audit_actor(lead.id,'inbound_processed',{'message_id':'interest'},{'stage':'question'},'scheduler')
    lead.status='question';db.session.commit()
    monkeypatch.setattr(scanner,'_gmail_thread_reply_state',lambda _:{'ok':True,'replied':True,'reply_evidence':[evidence]})
    monkeypatch.setattr(oa,'check_availability',lambda req:(checks.append(req) or {'ok':True,'available':True,'checked_start':req['start'],'checked_end':req['end']}))
    monkeypatch.setattr(oa,'_calendar_create_via_command',lambda lead,req,**k:(events.append(k) or {'ok':True,'event_id':'calendar-event','event_url':'https://calendar.google.com/event','start':req['start'],'end':req['end']}))
    result=scanner.scan_real_inbound_replies()
    assert result['ok'] and result['processed'][0]['stage']=='interested',result
    assert len(sent)==2 and not events and not checks
    assert 'date' in sent[-1][1][1] and 'timezone' in sent[-1][1][1]
    assert scanner.scan_real_inbound_replies()['processed'][0]['stage']=='already_processed'
    assert len(sent)==2
    evidence.update(message_id='chosen-time',text='November 11 2030 at 2 pm America/New_York',internal_date='2')
    result=scanner.scan_real_inbound_replies()
    assert result['ok'] and result['processed'][0]['stage']=='booked',result
    assert len(checks)==len(events)==1 and len(sent)==3
    assert lead.status=='booked' and lead.follow_up_due_at is None
    assert oa.OutreachBookingAttempt.query.one().event_id=='calendar-event'
    assert scanner.scan_real_inbound_replies()['processed'][0]['stage']=='already_processed'
    assert len(sent)==3 and len(events)==1
