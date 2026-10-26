import json
import time
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
import commercial_app
from app import app,db
from src import verifalia_mailbox as v,mailbox_verification as m,hunter_mailbox
import outreach_automation as oa


@pytest.fixture
def connected(monkeypatch):
    monkeypatch.setenv('VERIFALIA_USERNAME','api-user-test')
    monkeypatch.setenv('VERIFALIA_PASSWORD','credential-test-secret')
    monkeypatch.setenv('SECRET_KEY','test-only-long-credential-encryption-key-123456')
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN','verifalia-owner-test')
    with app.app_context():
        db.session.remove();db.drop_all();db.create_all()
        yield
        db.session.remove();db.drop_all()


def completed(email='hello@acme.example',**changes):
    item={'inputData':email,'classification':'Deliverable','status':'Success',**changes}
    return {'overview':{'status':'Completed','completedOn':datetime.now(timezone.utc).isoformat()},'entries':{'data':[item]}}


def transport(payload=None,balance=None,code=200):
    calls=[]
    def request(method,url,**kw):
        assert url.startswith(v.API+'/') and kw['allow_redirects'] is False
        assert kw['auth']==('api-user-test','credential-test-secret')
        calls.append((method,url,kw))
        data=(balance if balance is not None else {'freeCredits':25,'creditPacks':0}) if url.endswith('/credits/balance') else payload if payload is not None else completed()
        return SimpleNamespace(status_code=200 if url.endswith('/credits/balance') else code,content=b'{}',json=lambda:data)
    return request,calls


def test_free_verification_cached_and_shared_provider_does_not_call_hunter(connected,monkeypatch):
    request,calls=transport()
    monkeypatch.setattr(v.requests,'request',request)
    monkeypatch.setattr(hunter_mailbox,'verify_mailbox',lambda *a,**k:pytest.fail('Paid fallback'))
    result=m.verify_mailbox('hello@acme.example')
    assert m.current(result,'hello@acme.example')
    assert m.verify_mailbox('hello@acme.example',research_only=True)['cache_hit']
    assert len(calls)==2 and calls[1][2]['json']['quality']=='Standard'
    assert 'credential-test-secret' not in json.dumps(result)
    assert all('credential-test-secret' not in row.receipt_json for row in v.VerifaliaCheck.query.all())


@pytest.mark.parametrize('funds',[{'freeCredits':0,'creditPacks':0},{'freeCredits':25,'creditPacks':1},{'freeCredits':True,'creditPacks':0},{'freeCredits':25}])
def test_insufficient_or_paid_or_malformed_balance_never_submits(connected,funds):
    request,calls=transport(balance=funds)
    assert v.verify('hello@acme.example',request)['mailbox_status']!='provider_verified'
    assert len(calls)==1 and calls[0][0]=='GET'


@pytest.mark.parametrize('changes',[{'status':'ServerIsCatchAll'},{'classification':'Risky'},{'status':'MailboxDoesNotExist','classification':'Deliverable'},{'isDisposableEmailAddress':True},{'inputData':'wrong@acme.example'}])
def test_risky_or_custom_classification_or_mismatched_email_never_verified(connected,changes):
    assert v.normalize('hello@acme.example',completed(**changes))['mailbox_status']!='provider_verified'


def test_pending_job_polled_without_second_submission(connected):
    job='54375b5b-a399-4bc4-abd8-b8c02e109e53'
    request,calls=transport({'overview':{'id':job,'status':'InProgress'}},code=202)
    assert v.verify('hello@acme.example',request)['reason_codes']==['VERIFALIA_RESULT_PENDING']
    assert v.verify('hello@acme.example',request)['cache_hit']
    row=v.VerifaliaCheck.query.filter_by(job_id=job).one();row.expires_at=0;db.session.commit()
    get,read_calls=transport(completed())
    assert v.verify('hello@acme.example',get)['mailbox_status']=='provider_verified'
    assert len(read_calls)==1 and read_calls[0][0]=='GET'
    assert len([c for c in calls if c[0]=='POST'])==1


def test_response_loss_never_replays_post(connected):
    request,calls=transport()
    def lost(method,url,**kw):
        if method=='POST':raise TimeoutError('credential-test-secret')
        return request(method,url,**kw)
    result=v.verify('hello@acme.example',lost)
    assert result['reason_codes']==['VERIFALIA_SUBMISSION_UNCONFIRMED']
    assert v.verify('hello@acme.example',lambda *a,**k:pytest.fail('Duplicate submission'))['cache_hit']
    assert 'credential-test-secret' not in json.dumps(result)


def test_daily_app_limit_blocks_twenty_sixth_even_if_provider_balance_is_stale(connected):
    identity=v._hash('api-user-test\0credential-test-secret')
    for _ in range(25):assert v._reserve_daily(identity)
    request,calls=transport()
    assert v.verify('hello@acme.example',request)['reason_codes']==['VERIFALIA_FREE_QUOTA_EXHAUSTED']
    assert len(calls)==1


def test_encrypted_credentials_and_owner_only_connection_routes(connected,monkeypatch):
    monkeypatch.delenv('VERIFALIA_USERNAME');monkeypatch.delenv('VERIFALIA_PASSWORD')
    request,_=transport();monkeypatch.setattr(v.requests,'request',request)
    client=app.test_client();payload={'username':'api-user-test','password':'credential-test-secret','free_only':True}
    assert client.post('/api/chat/dashboard/verifalia/connect',json=payload).status_code==401
    result=client.post('/api/chat/dashboard/verifalia/connect',json=payload,headers={'X-Operator-Token':'verifalia-owner-test'})
    assert result.status_code==200 and 'credential-test-secret' not in result.get_data(as_text=True)
    assert 'credential-test-secret' not in v.VerifaliaConnection.query.one().credentials
    assert v.credentials()==('api-user-test','credential-test-secret')
    monkeypatch.setenv('SECRET_KEY','dev-secret-key')
    assert client.post('/api/chat/dashboard/verifalia/connect',json=payload,headers={'X-Operator-Token':'verifalia-owner-test'}).status_code==503
    monkeypatch.setattr(hunter_mailbox,'verify_mailbox',lambda *a,**kw:pytest.fail('Unreadable free connection fell back to Hunter'))
    assert m.verify_mailbox('hello@acme.example')['reason_codes']==['VERIFALIA_NOT_CONNECTED']


def test_shared_status_expires_across_contact_and_dashboard(connected):
    from src.owned_research import view
    lead=oa.OutreachLead(company='Acme',source_url='https://acme.example/',contact_email='hello@acme.example')
    old=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat()
    record={'source':'automake_contact_research','enrichment':{'fields':{'email':{'validated':True,'value':lead.contact_email}},'contact_assessment':{'mailbox_validation':{'email':lead.contact_email,'provider':'verifalia','mailbox_status':'provider_verified','checked_at':old,'provider_verified_on':old}}}}
    lead.evidence_json=json.dumps([record]);db.session.add(lead);db.session.commit()
    assert view(lead)['email_status']=='Verification expired'
    client=app.test_client();detail=client.get(f'/api/chat/dashboard/leads/{lead.id}',headers={'X-Operator-Token':'verifalia-owner-test'}).json
    assert detail['contact']['email_label']==view(lead)['email_status']
    assert not detail['mailbox_verification']['verified']
    assert not m.current(record['enrichment']['contact_assessment']['mailbox_validation'],lead.contact_email)


def test_newer_rejection_overrides_previous_verified_evidence_everywhere(connected):
    from src.manual_outreach import contact_readiness
    lead=oa.OutreachLead(company='Acme',contact_email='hello@acme.example',source_url='https://acme.example/')
    old=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    lead.evidence_json=json.dumps([{'email':lead.contact_email,'contact_assessment':{'mailbox_validation':{
        'email':lead.contact_email,'mailbox_status':'provider_verified','checked_at':old}}}])
    db.session.add(lead);db.session.commit()
    oa._audit_actor(lead.id,'mailbox_verification',{}, {
        'email':lead.contact_email,'mailbox_status':'provider_rejected','checked_at':datetime.now(timezone.utc).isoformat()},'test')
    db.session.commit()
    assert m.lead_status(lead)['state']=='rejected'
    assert 'VERIFIED_MAILBOX_REQUIRED' in contact_readiness(lead)['reason_codes']


def test_pending_poll_transport_error_retains_job_and_never_reposts(connected):
    job='54375b5b-a399-4bc4-abd8-b8c02e109e53'
    request,_=transport({'overview':{'id':job,'status':'InProgress'}},code=202)
    v.verify('hello@acme.example',request)
    row=v.VerifaliaCheck.query.filter_by(job_id=job).one();row.expires_at=0;db.session.commit()
    failure,calls=transport({},code=503)
    assert v.verify('hello@acme.example',failure)['mailbox_status']!='provider_verified'
    db.session.expire_all();row=v.VerifaliaCheck.query.filter_by(job_id=job).one();row.expires_at=0;db.session.commit()
    success,reads=transport(completed())
    assert v.verify('hello@acme.example',success)['mailbox_status']=='provider_verified'
    assert [c[0] for c in calls+reads]==['GET','GET']
