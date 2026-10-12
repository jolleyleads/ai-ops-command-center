import json
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
import pytest
import outreach_automation as oa
from src import hunter_mailbox as hunter


def result(**changes):
    data={'email':'jane@acme.com','status':'valid','smtp_check':True,'accept_all':False,'block':False,'disposable':False,'verification':{'date':datetime.now(timezone.utc).date().isoformat(),'status':'valid'}}
    data.update(changes);return data


def test_real_valid_result_is_separate_from_identity():
    receipt=hunter.normalize_result('jane@acme.com',result())
    assert receipt['mailbox_status']=='provider_verified'
    assert receipt['deliverability_status']=='provider_reported_valid'
    assert 'person_name' not in receipt and 'company_status' not in receipt


@pytest.mark.parametrize('changes',[{'status':'accept_all'},{'status':'unknown'},{'status':'webmail'},{'accept_all':True},{'block':True},{'smtp_check':False},{'smtp_check':'true'},{'disposable':True},{'email':'other@acme.com'},{'verification':None},{'verification':[]},{'verification':{'date':(datetime.now(timezone.utc)-timedelta(days=8)).date().isoformat(),'status':'valid'}}])
def test_ambiguous_malformed_or_stale_results_do_not_verify(changes):
    assert hunter.normalize_result('jane@acme.com',result(**changes))['mailbox_status']!='provider_verified'


@pytest.fixture
def active(monkeypatch):
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','true')
    monkeypatch.setenv('HUNTER_API_KEY','secret-unit-test-only')
    monkeypatch.setenv('HUNTER_ACCOUNT_EMAIL','jolleyleads@gmail.com')
    with oa.app.app_context():
        oa.db.create_all()
        hunter.HunterMailboxCheck.query.delete();oa.db.session.commit()
        yield
        oa.db.session.rollback()
        hunter.HunterMailboxCheck.query.delete();oa.db.session.commit()


def transport(account=None,verification=None,code=200):
    calls=[]
    account=account or {'email':'jolleyleads@gmail.com','plan_name':'Free','requests':{'credits':{'remaining':50}}}
    def get(url,**kwargs):
        calls.append((url,kwargs))
        assert 'api_key' not in url and 'api_key' not in kwargs.get('params',{})
        assert kwargs['allow_redirects'] is False
        data=account if url.endswith('/account') else verification if verification is not None else result()
        return SimpleNamespace(status_code=200 if url.endswith('/account') else code,content=b'{}',json=lambda:{'data':data})
    return get,calls


def test_free_account_result_is_cached_across_separate_calls(active):
    get,calls=transport()
    first=hunter.verify_mailbox('jane@acme.com',get)
    second=hunter.verify_mailbox('jane@acme.com',get)
    assert first['mailbox_status']=='provider_verified' and second['cache_hit'] is True
    assert len(calls)==2
    row=hunter.HunterMailboxCheck.query.one()
    assert 'secret-unit-test-only' not in row.receipt_json and 'secret-unit-test-only' not in row.key


@pytest.mark.parametrize('account,reason',[
 ({'email':'someone@gmail.com','plan_name':'Free'},'HUNTER_ACCOUNT_MISMATCH'),
 ({'email':'jolleyleads@gmail.com','plan_name':'Growth'},'HUNTER_FREE_PLAN_REQUIRED'),
 ({'email':'jolleyleads@gmail.com','plan_name':'Free','requests':{'credits':{'remaining':0}}},'HUNTER_FREE_QUOTA_UNAVAILABLE'),
 ({'email':'jolleyleads@gmail.com','plan_name':'Free','requests':{'credits':{'remaining':True}}},'HUNTER_FREE_QUOTA_UNAVAILABLE'),
])
def test_wrong_account_paid_plan_and_exhaustion_never_call_verifier(active,account,reason):
    get,calls=transport(account)
    receipt=hunter.verify_mailbox('jane@acme.com',get)
    assert receipt['reason_codes']==[reason] and len(calls)==1


@pytest.mark.parametrize('code',[202,429,451,500,302])
def test_pending_quota_privacy_and_http_errors_do_not_pass(active,code):
    get,calls=transport(code=code)
    assert hunter.verify_mailbox('jane@acme.com',get)['mailbox_status']!='provider_verified'
    assert len(calls)==2


def test_disabled_and_test_key_never_call_network(active,monkeypatch):
    def never(*a,**k):raise AssertionError('No request')
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','false')
    assert hunter.verify_mailbox('jane@acme.com',never)['reason_codes']==['HUNTER_NOT_ENABLED']
    monkeypatch.setenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','true')
    monkeypatch.setenv('HUNTER_API_KEY','test-api-key')
    assert hunter.verify_mailbox('jane@acme.com',never)['reason_codes']==['HUNTER_REAL_CREDENTIAL_REQUIRED']


def test_unknown_gate_preserves_identity_receipt_and_blocks_email(active,monkeypatch):
    monkeypatch.setattr(hunter,'verify_mailbox',lambda e:hunter.base_receipt(e,'HUNTER_RESULT_PENDING'))
    enriched={'fields':{'email':{'value':'jane@acme.com','validated':True}},'contact_assessment':{'company_status':'source_bound','target_location':'Norfolk VA','person_name':'Jane Doe'}}
    hunter.apply_mailbox_check(enriched)
    assert enriched['fields']['email']['validated'] is False
    assert enriched['contact_assessment']['person_name']=='Jane Doe'
    assert enriched['contact_assessment']['target_location']=='Norfolk VA'


def test_reserved_check_does_not_repeat_credit_call(active):
    get,calls=transport()
    def reserved_get(url,**kw):
        assert hunter.verify_mailbox('jane@acme.com',get)['reason_codes']==['HUNTER_CHECK_IN_PROGRESS']
        return get(url,**kw)
    assert hunter.verify_mailbox('jane@acme.com',reserved_get)['mailbox_status']=='provider_verified'
    assert len(calls)==2


def test_exception_does_not_persist_secret(active):
    def failing(*a,**k):raise ValueError('secret-unit-test-only')
    receipt=hunter.verify_mailbox('jane@acme.com',failing)
    assert 'secret-unit-test-only' not in json.dumps(receipt)


def test_send_gate_blocks_pending_check_before_gmail_or_send_attempt(active,monkeypatch):
    lead=oa.OutreachLead(company='Acme',contact_email='jane@acme.com',source_url='https://acme.com/',status='qualified')
    oa.db.session.add(lead);oa.db.session.commit()
    monkeypatch.setattr(oa,'_qualification_gate',lambda lead:{'ok':True})
    monkeypatch.setattr(oa,'_is_suppressed',lambda email:False)
    monkeypatch.setattr(hunter,'verify_mailbox',lambda e:hunter.base_receipt(e,'HUNTER_RESULT_PENDING'))
    monkeypatch.setattr(oa,'_gmail_send',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No Gmail call')))
    proof=oa._safe_send(lead,kind='initial',sequence=0,subject='Hi',body='Hello')
    assert proof['gate']['reasons']==['INDEPENDENT_MAILBOX_VERIFICATION_REQUIRED']
    assert oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id).count()==0
    audit=oa.OperatorAuditEvent.query.filter_by(lead_id=lead.id,action='mailbox_verification').one()
    assert 'HUNTER_RESULT_PENDING' in audit.result_json
    oa.db.session.delete(lead);oa.db.session.delete(audit);oa.db.session.commit()


def test_old_worker_cannot_finish_newer_lease(active):
    get,calls=transport()
    def replaced_lease(url,**kw):
        if url.endswith('/email-verifier'):
            row=hunter.HunterMailboxCheck.query.one();row.lease_token='new-owner';oa.db.session.commit()
        return get(url,**kw)
    receipt=hunter.verify_mailbox('jane@acme.com',replaced_lease)
    assert receipt['reason_codes']==['HUNTER_RECEIPT_STORAGE_FAILED']
    row=hunter.HunterMailboxCheck.query.one()
    assert row.state=='reserved' and row.lease_token=='new-owner'


def test_valid_send_time_gate_keeps_qualification_evidence_unchanged(active,monkeypatch):
    lead=oa.OutreachLead(company='Acme',contact_email='jane@acme.com',source_url='https://acme.com/',evidence_json='[]')
    oa.db.session.add(lead);oa.db.session.commit()
    proof=hunter.normalize_result('jane@acme.com',result())
    monkeypatch.setattr(hunter,'verify_mailbox',lambda e:proof)
    assert oa._independent_mailbox_gate(lead)['ok'] is True
    assert lead.evidence_json=='[]'
    audit=oa.OperatorAuditEvent.query.filter_by(lead_id=lead.id,action='mailbox_verification').one()
    assert 'provider_verified' in audit.result_json
    oa.db.session.delete(audit);oa.db.session.delete(lead);oa.db.session.commit()
