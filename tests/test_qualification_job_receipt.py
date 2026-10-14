from datetime import datetime, timedelta, timezone
import pytest
from src.job_evidence import check_job_evidence
from src.qualification import qualify_lead


def data(live_job_page):
    row=live_job_page(title='Accounting Assistant')
    query='construction companies actively hiring accounting assistants'
    proof=check_job_evidence(row,query,'Norfolk, Virginia','Acme')
    # Match the actual persisted production shape: a company-only summary,
    # source contact, and a full job receipt; no keyword-filled model text.
    evidence=[{'title':'Acme','snippet':'','url':row['url'],'observed_at':row['observed_at'],'job_validation':proof}]
    validated={'company_name':'Acme','website':'https://acme.example','website_source_url':'https://acme.example',
               'email':'mail@acme.example','email_source_url':row['url'],'evidence':evidence}
    context={'query':query,'intent_signal':query,'target_location':'Norfolk, Virginia','candidate_location':'Norfolk, Virginia'}
    return validated,context


def test_current_source_bound_job_receipt_qualifies_without_summary_keywords(live_job_page):
    validated,context=data(live_job_page)
    result=qualify_lead(validated,context=context)
    assert result['qualified'] and 'intent_signal_fit' in result['passed_checks']


@pytest.mark.parametrize('change',[
    {'company':'Other Company'},
    {'job_title':'Accounting Manager'},
    {'job_locations':['Boston MA US']},
    {'checked_at':(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()},
    {'valid_through':(datetime.now(timezone.utc)-timedelta(days=1)).isoformat()},
    {'open_status':'closed'},
    {'ok':False},
    {'source_url':'https://other.example/jobs/1'},
])
def test_keywords_cannot_override_invalid_or_unbound_job_receipt(live_job_page,change):
    validated,context=data(live_job_page)
    validated['evidence'][0]['snippet']=context['query']
    validated['evidence'][0]['job_validation'].update(change)
    result=qualify_lead(validated,context=context)
    assert not result['qualified'] and 'INTENT_SIGNAL_UNPROVEN' in result['reason_codes']


def test_mailbox_opt_out_does_not_disable_unrelated_qualification_recovery():
    from v1_orchestration import unfinished_lead_reasons
    from src.provider_recovery import recovery_policy
    reasons=unfinished_lead_reasons({'reason_codes':['INTENT_SIGNAL_UNPROVEN']},{'reason_codes':['HUNTER_NOT_ENABLED']})
    assert reasons==['INTENT_SIGNAL_UNPROVEN']
    assert recovery_policy(reasons)['state']=='retry_wait'
    assert unfinished_lead_reasons({'reason_codes':['MISSING_VALIDATED_CONTACT']},{'reason_codes':['HUNTER_FREE_QUOTA_EXHAUSTED']})==['HUNTER_FREE_QUOTA_EXHAUSTED']


def test_false_disabled_hold_is_retried_without_replaying_sent_lead(monkeypatch):
    import outreach_automation as oa
    import lead_recovery as recovery
    import v1_orchestration as v1
    import json
    with oa.app.app_context():
        oa.db.session.remove();oa.db.drop_all();oa.db.create_all()
        pending=oa.OutreachLead(company='Acme',contact_email='mail@acme.example',status='needs_evidence',last_error='INTENT_SIGNAL_UNPROVEN')
        sent=oa.OutreachLead(company='Sent Acme',contact_email='sent@acme.example',status='sent',gmail_message_id='sent-message',last_error='INTENT_SIGNAL_UNPROVEN')
        oa.db.session.add_all([pending,sent]);oa.db.session.commit()
        for lead in (pending,sent):
            oa.db.session.add(recovery.LeadRecovery(lead_id=lead.id,state='disabled',reason_json=json.dumps(['HUNTER_NOT_ENABLED']),payload_json='{}'))
        oa.db.session.commit()
        seen=[]
        def resume(lead,*a):
            seen.append(lead.id);lead.status='drafted';oa.db.session.commit()
            return {'ok':True,'stage':'drafted'}
        monkeypatch.setattr(v1,'resume_discovery_lead',resume)
        result=recovery.process_recoverable_leads()
        assert seen==[pending.id] and result['processed'][0]['state']=='completed'
        assert sent.status=='sent' and oa.db.session.get(recovery.LeadRecovery,sent.id).state=='disabled'
        oa.db.session.remove();oa.db.drop_all()
