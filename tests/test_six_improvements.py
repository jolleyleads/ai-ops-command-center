import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import pytest
import commercial_app
import outreach_automation as oa
import lead_recovery as recovery
import v1_orchestration as v1
from src import hunter_mailbox as hunter
from src.grounded_reply import routine_answer
from src.provider_recovery import recovery_policy
from src.qualification import qualify_lead


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEY_VERSION', 'test')
    monkeypatch.setenv('QUALIFICATION_SIGNING_KEYS', 'test=isolated-six-checks')
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED', 'false')
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        yield
        oa.db.session.remove();oa.db.drop_all()


def result():
    return {'company': 'Acme', 'website': 'https://acme.com', 'source_url': 'https://acme.com',
            'location': 'Norfolk VA', 'contact_location': 'Norfolk VA', 'query': 'hiring AI automation engineers',
            'verification': 'VERIFIED', 'intent_score': 80,
            'evidence': [{'url': 'https://acme.com/jobs', 'text': 'Acme hiring AI automation engineers',
                          'observed_at': datetime.now(timezone.utc).isoformat()}],
            '_campaign_context': {'target_location': 'Norfolk VA', 'query': 'hiring AI automation engineers'}}


def selected_contact(row):
    row['_contact_name'] = 'Jane Doe'
    row['_contact_identity'] = {'contact_assessment': {'decision_maker_status': 'source_supported',
        'email_person_status': 'same_source_card', 'person_email': 'jane@acme.com'}}
    return 'jane@acme.com', 'https://acme.com/contact'


def test_pending_lead_recovers_once_to_draft_without_sending(env, monkeypatch):
    lead = oa.OutreachLead(company='Acme', location='Norfolk VA', source_url='https://acme.com', status='needs_evidence')
    oa.db.session.add(lead);oa.db.session.commit()
    recovery.schedule_recovery(lead, result(), ['HUNTER_RESULT_PENDING'])
    row = oa.db.session.get(recovery.LeadRecovery, lead.id)
    row.next_check_at = datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    monkeypatch.setattr(v1, '_verified_public_email', selected_contact)
    monkeypatch.setattr(v1, '_draft_email', lambda _: {'ok': True, 'subject': 'Hi', 'body': 'Hello'})
    monkeypatch.setattr(v1, '_safe_send', lambda *a, **k: pytest.fail('Recovery must not fire an old campaign'))
    first = recovery.process_recoverable_leads()
    assert first['processed'][0]['state'] == 'completed'
    assert lead.status == 'drafted' and lead.contact_email == 'jane@acme.com'
    assert oa._qualification_gate(lead)['ok']
    assert recovery.process_recoverable_leads()['processed'] == []
    assert oa.OutreachLead.query.count() == 1
    assert oa.OutreachSendAttempt.query.count() == 0


def test_quota_wait_keeps_failed_lead_and_bounded_recovery(env, monkeypatch):
    lead = oa.OutreachLead(company='Acme', location='Norfolk VA', source_url='https://acme.com', status='needs_evidence')
    oa.db.session.add(lead);oa.db.session.commit()
    recovery.schedule_recovery(lead, result(), ['HUNTER_FREE_QUOTA_EXHAUSTED'])
    row = oa.db.session.get(recovery.LeadRecovery, lead.id)
    assert row.state == 'quota_wait' and row.next_check_at > datetime.utcnow()
    row.attempts = 7;row.next_check_at = datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    monkeypatch.setattr(v1, 'resume_discovery_lead', lambda *a: {'ok': False, 'reason_codes': ['HUNTER_FREE_QUOTA_EXHAUSTED']})
    recovery.process_recoverable_leads();oa.db.session.refresh(row)
    assert row.state == 'review_required' and row.next_check_at is None


@pytest.mark.parametrize('status', ['opted_out', 'sent', 'booked', 'paused', 'not_interested'])
def test_recovery_cannot_rewrite_stopped_or_sent_lead(env, monkeypatch, status):
    lead = oa.OutreachLead(company='Acme', status=status)
    oa.db.session.add(lead);oa.db.session.commit()
    recovery.schedule_recovery(lead, result(), ['HUNTER_RESULT_PENDING'])
    row = oa.db.session.get(recovery.LeadRecovery, lead.id)
    row.next_check_at = datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    monkeypatch.setattr(v1, 'resume_discovery_lead', lambda *a: pytest.fail('Do not resume'))
    recovery.process_recoverable_leads()
    assert lead.status == status


def test_expired_read_only_recovery_lease_resumes(env, monkeypatch):
    lead = oa.OutreachLead(company='Acme', status='needs_evidence')
    oa.db.session.add(lead);oa.db.session.commit()
    recovery.schedule_recovery(lead, result(), ['HUNTER_RESULT_PENDING'])
    row = oa.db.session.get(recovery.LeadRecovery, lead.id)
    row.state='running';row.lease_token='killed';row.lease_until=datetime.utcnow()-timedelta(seconds=1)
    oa.db.session.commit()
    monkeypatch.setattr(v1, 'resume_discovery_lead', lambda *a: {'ok': True})
    assert recovery.process_recoverable_leads()['processed'][0]['state'] == 'completed'


def test_active_recovery_lease_blocks_second_worker(env, monkeypatch):
    lead = oa.OutreachLead(company='Acme', status='needs_evidence')
    oa.db.session.add(lead);oa.db.session.commit()
    recovery.schedule_recovery(lead, result(), ['HUNTER_RESULT_PENDING'])
    row = oa.db.session.get(recovery.LeadRecovery, lead.id)
    row.next_check_at=datetime.utcnow()-timedelta(seconds=1)
    row.lease_until=datetime.utcnow()+timedelta(minutes=10);oa.db.session.commit()
    monkeypatch.setattr(v1, 'resume_discovery_lead', lambda *a: pytest.fail('Lease occupied'))
    assert recovery.process_recoverable_leads()['processed'] == []


def test_lost_lease_cannot_finish_queue(env, monkeypatch):
    lead = oa.OutreachLead(company='Acme', status='needs_evidence')
    oa.db.session.add(lead);oa.db.session.commit()
    recovery.schedule_recovery(lead, result(), ['HUNTER_RESULT_PENDING'])
    row=oa.db.session.get(recovery.LeadRecovery,lead.id)
    row.next_check_at=datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    def replace(*args):
        row.lease_token='new-owner';oa.db.session.commit()
        return {'ok':True}
    monkeypatch.setattr(v1,'resume_discovery_lead',replace)
    recovery.process_recoverable_leads();oa.db.session.refresh(row)
    assert row.state=='running' and row.lease_token=='new-owner'
    assert not oa.OperatorAuditEvent.query.filter_by(action='lead_recovery').first()


def test_named_campaign_cannot_qualify_shared_inbox():
    validated={'company_name':'Acme','email':'info@acme.com','email_source_url':'https://acme.com',
               'website':'https://acme.com','website_source_url':'https://acme.com',
               'evidence':[{'url':'https://acme.com','observed_at':datetime.now(timezone.utc).isoformat()}]}
    receipt=qualify_lead(validated,context={'require_decision_maker':True})
    assert 'NAMED_DECISION_MAKER_EMAIL_REQUIRED' in receipt['reason_codes']


def test_campaign_city_context_survives_signed_qualification(env):
    evidence=[{'email':'info@acme.com','url':'https://acme.com','observed_at':datetime.now(timezone.utc).isoformat()},
              {'source':'campaign_context','context':{'target_location':'Norfolk VA'}}]
    lead=oa.OutreachLead(company='Acme',location='Boston MA',contact_email='info@acme.com',source_url='https://acme.com',evidence_json=json.dumps(evidence))
    oa.db.session.add(lead);oa.db.session.commit()
    assert 'GEOGRAPHIC_MISMATCH' in oa._store_qualification(lead)['reason_codes']


def test_recovery_endpoint_requires_operator(env):
    assert oa.app.test_client().get('/api/operator/lead-recovery').status_code==401


def test_hunter_account_serializes_different_addresses(env,monkeypatch):
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','true')
    monkeypatch.setenv('HUNTER_API_KEY','six-tests-only')
    monkeypatch.setenv('HUNTER_ACCOUNT_EMAIL','jolleyleads@gmail.com')
    calls=[]
    def get(url,**kwargs):
        calls.append(url)
        assert hunter.verify_mailbox('other@acme.com',get)['reason_codes']==['HUNTER_CHECK_IN_PROGRESS']
        data={'email':'jolleyleads@gmail.com','plan_name':'Free','requests':{'credits':{'remaining':0}}}
        return SimpleNamespace(status_code=200,content=b'{}',json=lambda:{'data':data})
    assert hunter.verify_mailbox('jane@acme.com',get)['reason_codes']==['HUNTER_FREE_QUOTA_UNAVAILABLE']
    assert calls==['https://api.hunter.io/v2/account']
    assert hunter.verify_mailbox('third@acme.com',get)['reason_codes']==['HUNTER_FREE_QUOTA_UNAVAILABLE']
    assert len(calls)==1


def test_restriction_database_failure_is_fail_closed(env,monkeypatch):
    class Broken:
        def __init__(self,*a,**k):raise RuntimeError('database offline')
    monkeypatch.setattr(hunter,'Session',Broken)
    assert oa._is_suppressed('jane@acme.com') is True


def test_approved_paraphrases_and_multiple_questions(monkeypatch):
    monkeypatch.setenv('AUTOMAKE_APPROVED_BUSINESS_FAQ',json.dumps([
        {'approved':True,'questions':['What is your price?'],'answer':'The approved price is $500.',
         'paraphrases':['What is your monthly fee?']}]))
    assert routine_answer('Could you tell me how much do you charge?')=='The approved price is $500.'
    assert routine_answer('What is your monthly fee?')=='The approved price is $500.'
    combined=routine_answer('How long will the call last? What is your price?')
    assert '30 minutes' in combined and '$500' in combined
    assert not routine_answer('What is your price? Will you guarantee results?')
    assert not routine_answer('What is your price if I demand a discount?')


def test_supported_mixed_scheduling_reply_requires_confirmation(monkeypatch):
    monkeypatch.setenv('AUTOMAKE_APPROVED_BUSINESS_FAQ','[]')
    answer=routine_answer('Can you schedule a meeting? How long is the call?')
    assert '30 minutes' in answer and 'check availability before confirming' in answer


def test_conflicting_or_expired_faq_does_not_answer(monkeypatch):
    monkeypatch.setenv('AUTOMAKE_APPROVED_BUSINESS_FAQ',json.dumps([
        {'approved':True,'questions':['What is the price?'],'answer':'$1'},
        {'approved':True,'questions':['How much do you charge?'],'answer':'$2'}]))
    assert not routine_answer('What does it cost?')
    assert not routine_answer('What is the price?')


def test_scheduler_lease_blocks_overlapping_cycle_and_recovers(env,monkeypatch):
    import outreach_scheduler as scheduler
    calls=[]
    token=scheduler._claim_cycle()
    monkeypatch.setattr(scheduler,'_run_scheduled_outreach_cycle',lambda:calls.append(1) or {'ok':True})
    assert scheduler.run_scheduled_outreach_cycle()['duplicate_cycle_suppressed']
    row=oa.db.session.get(scheduler.SchedulerLease,'outreach')
    row.expires_at=datetime.utcnow()-timedelta(seconds=1);oa.db.session.commit()
    assert scheduler.run_scheduled_outreach_cycle()['ok']
    assert calls==[1] and token!=row.token


def test_configuration_diagnostics_do_not_expose_secrets():
    from scripts.check_configuration import check_configuration
    result=check_configuration({'SECRET_KEY':'private-test-only','HUNTER_MAILBOX_VERIFICATION_ENABLED':'true'})
    assert not result['ok'] and 'HUNTER_API_KEY' in result['missing_settings']
    assert 'private-test-only' not in json.dumps(result)


def test_bounded_recovery_distinguishes_permanent_rejection():
    assert recovery_policy(['HUNTER_PROCESSING_RESTRICTED'])['next_check_at'] is None
    assert recovery_policy(['HUNTER_RESULT_PENDING'],8)['state']=='review_required'


def test_discovery_lock_suppresses_competing_company_source(env):
    with v1.discovery_lock('Acme','https://acme.com') as first:
        assert first
        with v1.discovery_lock('Acme','https://acme.com') as second:
            assert not second
    with v1.discovery_lock('Acme','https://acme.com') as after:
        assert after


def test_expired_research_owner_cannot_overwrite_new_result(env,monkeypatch):
    import background_research as research
    job=research.ResearchJob(id='fenced',prompt_text='companies',status='queued')
    oa.db.session.add(job);oa.db.session.commit()
    def replaced(*a,**k):
        job.started_at=datetime.utcnow()+timedelta(seconds=1)
        job.result_json='{"new_owner":true}'
        oa.db.session.commit()
        return {'results':[]}
    monkeypatch.setattr(research,'_smart_search',replaced)
    result=research.process_next_research_job()
    oa.db.session.refresh(job)
    assert result['lease_lost'] and job.result_json=='{"new_owner":true}'


def test_html_heading_title_card_increases_grounded_contact_coverage():
    from src.enrichment import enrich_lead
    from src.contact_assessment import contact_sections
    from src.company_identity import visible_page_text
    raw='<title>Acme</title><section><h3>Jane Doe</h3><p>Talent Acquisition Manager</p><p>Norfolk VA jane@acme.com</p></section>'
    row={'url':'https://acme.com/team','page_text':visible_page_text(raw),'contact_sections':contact_sections(raw),
         'directly_fetched':True,'http_status':200,'observed_at':datetime.now(timezone.utc).isoformat()}
    enriched=enrich_lead({'company':'Acme','location':'Norfolk VA','query':'companies hiring AI engineers'},[row])
    assert enriched['contact_assessment']['person_email']=='jane@acme.com'
    assert enriched['fields']['decision_maker']['value']=='Jane Doe'
