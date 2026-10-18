import base64
import hashlib
import json
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace

import pytest
import outreach_automation as oa
import gmail_reconciliation as gmail
from src import outreach_copy as copy


def lead():
    return SimpleNamespace(company='Acme Comfort', contact_name='Jane Doe', source_url='https://acme.example/',
                           evidence_json='[]', location='Norfolk', score=80, verification='VERIFIED')


def test_selected_quote_must_be_exactly_supported_on_primary_company_page():
    x=lead()
    row={'url':x.source_url,'directly_fetched':True,'http_status':200,
         'page_text':'We provide heating and cooling services throughout Norfolk.'}
    valid=copy.initial_email(x,[row],'heating and cooling services throughout Norfolk')
    assert valid['compliment_source_backed']
    assert 'heating and cooling services throughout Norfolk' in valid['body']
    for rows,quote in [([row],'five star customer reviews'),([{**row,'directly_fetched':False}],'heating and cooling services throughout Norfolk'),([{**row,'url':'https://other.example'}],'heating and cooling services throughout Norfolk')]:
        assert not copy.initial_email(x,rows,quote)['compliment_source_backed']


def test_template_is_stable_personal_and_does_not_invent_private_response_metrics(monkeypatch):
    monkeypatch.setattr(oa,'run_ai',lambda **kw:{'ok':True,'output':json.dumps({'compliment_quote':''})})
    draft=oa._draft_email(lead())
    assert draft['body'].startswith('Hey Jane 👋')
    assert 'without you lifting a finger' in draft['body']
    assert 'two quick questions' in draft['body']
    assert 'lower than average' not in draft['body']
    assert 'I’ve noticed your competition' not in draft['body']
    assert draft['body'].endswith('Matthew Jolley\nAutoMake AI\n757 840 9648')
    assert draft['body'].count('👋')==draft['body'].count('🙂')==1
    assert not any(dash in draft['body'] for dash in ['-', '—', '–'])
    monkeypatch.setattr(oa,'run_ai',lambda **kw:{'ok':False})
    assert oa._draft_email(lead())['body']==draft['body']


@pytest.mark.parametrize('identified',[True,False])
def test_actual_gmail_transport_contains_pinned_resume_and_message_identity(monkeypatch,identified):
    bodies=[]
    monkeypatch.setattr(oa,'gmail_access_token',lambda:'test')
    monkeypatch.setattr(gmail,'gmail_access_token',lambda:'test')
    monkeypatch.setattr(gmail.requests,'post',lambda url,**kw:bodies.append(kw['json']) or SimpleNamespace(ok=True,json=lambda:{'id':'sent-id','threadId':'thread-id'}))
    draft=copy.initial_email(lead(),[])
    if identified:
        result=gmail._gmail_send_identified('jane@acme.example',draft['subject'],draft['body'],command_key='a'*64)
    else:
        result=oa._gmail_send('jane@acme.example',draft['subject'],draft['body'])
    assert result['ok'] and result['message_id']=='sent-id'
    message=BytesParser(policy=policy.default).parsebytes(base64.urlsafe_b64decode(bodies[0]['raw']+'==='))
    assert message['To']=='jane@acme.example'
    assert message.get_body(preferencelist=('plain',)).get_content().strip()==draft['body']
    attachment=list(message.iter_attachments())
    assert len(attachment)==1
    assert attachment[0].get_filename()=='Matthew_Jolley_AI_Automation_Resume.docx'
    assert hashlib.sha256(attachment[0].get_payload(decode=True)).hexdigest()==copy.RESUME_SHA256
    if identified:
        assert message['Message-ID']==gmail._message_identity('a'*64)
        assert message['X-AI-Ops-Command-ID']=='a'*64


def test_missing_resume_prevents_provider_send_and_followups_do_not_attach(monkeypatch,tmp_path):
    monkeypatch.setattr(copy,'RESUME_PATH',tmp_path/'missing.docx')
    monkeypatch.setattr(gmail,'gmail_access_token',lambda:'test')
    calls=[]
    monkeypatch.setattr(gmail.requests,'post',lambda *a,**k:calls.append(k))
    draft=copy.initial_email(lead(),[])
    assert not gmail._gmail_send_identified('jane@acme.example',draft['subject'],draft['body'],command_key='b'*64)['ok']
    assert not calls
    from email.message import EmailMessage
    message=EmailMessage();message.set_content('Following up on my earlier message.')
    copy.add_resume_attachment(message,'Following up on my earlier message.')
    assert not list(message.iter_attachments())


def test_approved_template_recognition_keeps_source_compliment_and_rejects_old_copy():
    x = lead()
    rows = [{'url': x.source_url, 'directly_fetched': True, 'http_status': 200,
             'page_text': 'heating and cooling services throughout Norfolk'}]
    draft = copy.initial_email(x, rows, rows[0]['page_text'])
    assert copy.matches_initial_email(x, rows, draft['subject'], draft['body'])
    assert not copy.matches_initial_email(x, rows, 'Hello', 'Generic old message')
    assert not copy.matches_initial_email(x, [], draft['subject'], draft['body'])
    assert not copy.matches_initial_email(x, rows, draft['subject'], draft['body'].replace('757 840 9648', ''))


@pytest.mark.parametrize('saved_history', [False, True])
def test_explicit_send_refreshes_legacy_unsent_copy_only(monkeypatch, saved_history):
    oa.app.config.update(TESTING=True)
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN', 'approved-copy-test')
    monkeypatch.setattr(oa, '_qualification_gate', lambda row: {'ok': True})
    monkeypatch.setattr(oa, 'run_ai', lambda **kw: {'ok': False})
    captured = []
    monkeypatch.setattr(oa, '_safe_send', lambda row, **kw: captured.append(kw) or
                        {'ok': False, 'stage': 'blocked', 'gate': {'reasons': ['TEST_NO_SEND']}})
    with oa.app.app_context():
        oa.db.session.remove(); oa.db.drop_all(); oa.db.create_all()
        try:
            row = oa.OutreachLead(company='Acme Comfort', contact_name='Jane Doe',
                contact_email='jane@acme.example', source_url='https://acme.example/',
                subject='Old subject', body='Old saved copy', gmail_message_id='prior-message' if saved_history else '')
            oa.db.session.add(row); oa.db.session.commit()
            result = oa.app.test_client().post('/api/outreach/leads/%s/send' % row.id,
                headers={'X-Operator-Token': 'approved-copy-test'})
            assert result.status_code == 409
            if saved_history:
                assert captured[0]['body'] == 'Old saved copy'
            else:
                expected = copy.initial_email(row, [])
                assert captured[0]['body'] == expected['body']
                assert captured[0]['subject'] == expected['subject']
                assert row.body == expected['body']
                assert row.body.count('👋') == row.body.count('🙂') == 1
                assert copy.RESUME_LINE in row.body and '757 840 9648' in row.body
        finally:
            oa.db.session.remove(); oa.db.drop_all()
