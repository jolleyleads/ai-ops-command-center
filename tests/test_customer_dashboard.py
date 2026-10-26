import json
from datetime import datetime, timedelta, timezone
import pytest
import commercial_app
import outreach_automation as oa
import campaign_jobs as jobs
import customer_dashboard as dash


@pytest.fixture
def workspace(monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN','dashboard-test-token')
    monkeypatch.setattr(jobs,'kick_execution_worker',lambda:pytest.fail('Dashboard started outreach'))
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield oa.app.test_client()
        oa.db.session.remove();oa.db.drop_all()


AUTH={'X-Operator-Token':'dashboard-test-token'}


def saved_lead(**extra):
    lead=oa.OutreachLead(company='Acme Comfort',location='Norfolk, Virginia',score=85,
                         contact_email='hello@acme.example',evidence_json='[]',**extra)
    oa.db.session.add(lead);oa.db.session.commit()
    return lead


def test_every_dashboard_data_route_requires_authentication(workspace):
    for url in ['/api/chat/dashboard','/api/chat/dashboard/leads/1',
                '/api/chat/dashboard/appointments','/api/chat/dashboard/settings']:
        response=workspace.get(url)
        assert response.status_code==401
        assert response.headers['Cache-Control']=='no-store'


def test_campaign_filter_uses_persisted_ids_not_company_name_guessing(workspace):
    first=saved_lead();second=saved_lead()
    job=jobs.CampaignExecutionJob(id='exact-campaign',kind='campaign',status='completed',
        payload_json=json.dumps({'target_customer':'Find HVAC businesses','territory':'Norfolk'}),
        result_json=json.dumps({'outreach':{'lead_ids':[first.id],'sent':1},'discovery':{'results':[{'company':'Acme Comfort'}]}}))
    legacy=jobs.CampaignExecutionJob(id='older-campaign',kind='campaign',status='completed',payload_json='{}',
        result_json=json.dumps({'outreach':{'skipped':[{'lead_id':first.id,'reason':'already_queued'}]}}))
    oa.db.session.add_all([job,legacy]);oa.db.session.commit()
    result=workspace.get('/api/chat/dashboard',headers=AUTH)
    assert result.status_code==200 and result.headers['Cache-Control']=='no-store'
    leads={row['id']:row for row in result.json['leads']}
    assert set(leads[first.id]['campaign_ids'])=={'exact-campaign','older-campaign'}
    assert leads[second.id]['campaign_ids']==[]
    assert result.json['campaigns'][0]['research_results'] in {0,1}
    assert oa.OutreachSendAttempt.query.count()==0


def test_details_keep_contact_type_mailbox_proof_and_actual_email_history(workspace):
    lead=saved_lead(contact_name='')
    lead.subject='Your business';lead.body='Saved initial message'
    lead.evidence_json=json.dumps([{'url':'https://acme.example/contact','enrichment':{
        'fields':{'phone':{'value':'757 555 0100','validated':True}},
        'contact_assessment':{'mailbox_validation':{'email':'hello@acme.example','mailbox_status':'provider_verified','checked_at':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()}}}}])
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,kind='initial',sequence=0,recipient=lead.contact_email,idempotency_key='send-key',status='sent',message_id='gmail-message'))
    oa.db.session.add(oa.ExternalSideEffectCommand(lead_id=lead.id,kind='gmail_send',idempotency_key='command-key',payload_json=json.dumps({'send_key':'send-key','subject':'Actual sent subject','body':'Actual sent body'})))
    oa.db.session.add(oa.OutreachReplyEvidence(lead_id=lead.id,message_id='reply-message',from_email=lead.contact_email,body_text='Could we talk tomorrow?'))
    oa.db.session.commit()
    result=workspace.get(f'/api/chat/dashboard/leads/{lead.id}',headers=AUTH).json
    assert result['contact']['type']=='Company inbox'
    assert result['contact']['email_label']=='Verified'
    assert result['contact']['phone']=='757 555 0100'
    assert result['timeline'][0]['confirmed'] is True
    assert result['timeline'][0]['text']=='Actual sent body'
    assert result['timeline'][1]['text']=='Could we talk tomorrow?'
    lead.contact_email='new@acme.example';oa.db.session.commit()
    result=workspace.get(f'/api/chat/dashboard/leads/{lead.id}',headers=AUTH).json
    assert result['contact']['email_label']!='Verified'
    assert result['contact']['type']!='Named contact'


def test_only_confirmed_calendar_receipts_appear_as_appointments(workspace):
    lead=saved_lead(status='booked')
    for state in ['pending','uncertain','failed','confirmed']:
        oa.db.session.add(oa.OutreachBookingAttempt(lead_id=lead.id,reply_message_id=state,
            idempotency_key=state,event_id=state,start='2026-10-20T10:00:00-04:00',
            end='2026-10-20T10:30:00-04:00',timezone='America/New_York',attendee_email=lead.contact_email,
            status=state,event_url='https://calendar.google.com/calendar/event?eid=verified'))
    oa.db.session.commit()
    result=workspace.get('/api/chat/dashboard/appointments',headers=AUTH).json
    assert len(result['appointments'])==1
    assert result['appointments'][0]['company']==lead.company
    detail=workspace.get(f'/api/chat/dashboard/leads/{lead.id}',headers=AUTH).json
    assert sum(row['confirmed'] for row in detail['bookings'])==1


def test_settings_do_not_disclose_tokens_or_start_work(workspace,monkeypatch):
    monkeypatch.setenv('GOOGLE_REFRESH_TOKEN','never-return-this-secret')
    response=workspace.get('/api/chat/dashboard/settings',headers=AUTH)
    assert response.status_code==200
    assert 'never-return-this-secret' not in response.get_data(as_text=True)
    assert response.json['google_configured'] is True
    assert jobs.CampaignExecutionJob.query.count()==0


def test_dashboard_script_is_served_and_chat_stays_the_home_screen(workspace):
    result=workspace.get('/chat-operator')
    assert b'id="workspace-menu"' in result.data
    assert b'id="workspace-panel" aria-label="Workspace results" hidden' in result.data
    script=workspace.get('/chat-operator/dashboard.js')
    assert script.status_code==200 and 'javascript' in script.content_type
    assert b'/api/chat/dashboard' in script.data


def test_email_folders_filter_before_pagination_and_require_confirmed_sends(workspace):
    draft=saved_lead(status='drafted',subject='Saved',body='Draft')
    sent=saved_lead(status='replied',subject='Saved',body='Sent',gmail_message_id='m',gmail_thread_id='t',sent_at=datetime.utcnow())
    unknown=saved_lead(status='drafted',subject='Saved',body='Uncertain')
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=unknown.id,kind='initial',sequence=0,recipient=unknown.contact_email,idempotency_key='unknown-send',status='uncertain'))
    recovered=saved_lead(status='review',subject='Saved',body='Sent receipt')
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=recovered.id,kind='initial',sequence=0,recipient=recovered.contact_email,idempotency_key='confirmed-send',status='sent',message_id='receipt-m',thread_id='receipt-t'))
    saved_lead(status='qualified')
    oa.db.session.commit()
    result=workspace.get('/api/chat/dashboard?folder=drafts',headers=AUTH).json
    assert [r['id'] for r in result['leads']]==[draft.id]
    assert result['lead_total']==1
    result=workspace.get('/api/chat/dashboard?folder=sent',headers=AUTH).json
    assert {r['id'] for r in result['leads']}=={sent.id,recovered.id}
    assert result['lead_total']==2
    page=workspace.get('/api/chat/dashboard?folder=sent&lead_offset=1',headers=AUTH).json
    assert len(page['leads'])==1 and page['lead_total']==2
    assert workspace.get('/api/chat/dashboard?folder=invalid',headers=AUTH).status_code==400


def test_draft_preview_is_read_only_and_changed_preview_cannot_send(workspace,monkeypatch):
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**kw:pytest.fail('Changed preview must not send'))
    lead=saved_lead(status='drafted',subject='Old draft',body='Legacy copy')
    preview=workspace.get(f'/api/chat/dashboard/leads/{lead.id}',headers=AUTH).json['draft_preview']
    assert preview['recipient']==lead.contact_email
    assert preview['body'].count('👋')==preview['body'].count('🙂')==1
    assert preview['attachment'].endswith('.docx')
    assert lead.body=='Legacy copy' and oa.OutreachSendAttempt.query.count()==0
    lead.contact_email='changed@acme.example';oa.db.session.commit()
    response=workspace.post(f'/api/chat/leads/{lead.id}/activate-outreach',headers=AUTH,json={'activate':True,'draft_revision':preview['revision']})
    assert response.status_code==409 and 'Refresh and review' in response.json['error']
