from datetime import datetime, timedelta
import pytest
import commercial_app
import outreach_automation as oa
from owner_test_cleanup import archive_requested_tests, CUTOFF
from lead_recovery import LeadRecovery


@pytest.fixture
def records(monkeypatch):
    monkeypatch.setenv('OPERATOR_CONTROL_TOKEN', 'cleanup-test')
    with oa.app.app_context():
        oa.db.session.remove(); oa.db.drop_all(); oa.db.create_all()
        yield
        oa.db.session.remove(); oa.db.drop_all()


def row(company, email='neyolabs@gmail.com', verification='', created=None):
    lead = oa.OutreachLead(company=company, contact_email=email, verification=verification,
        created_at=created or CUTOFF-timedelta(days=1), status='sent',
        follow_up_due_at=datetime.utcnow(), gmail_message_id='saved-receipt', body='Saved message')
    oa.db.session.add(lead); oa.db.session.commit()
    return lead


def test_only_requested_existing_owner_tests_are_archived_and_hidden(records):
    neo = row('Neo Labs', verification='controlled_real_inbound')
    acceptance = row('AutoMake AI Acceptance', email='acceptance@example.com')
    internal = row('AI Ops Production E2E abc', verification='controlled_e2e')
    real = row('Acme Electrical', email='owner@acme.example')
    similar = row('Neo Labs', email='owner@another.example')
    future = row('Neo Labs', created=CUTOFF+timedelta(seconds=1))
    recovery = LeadRecovery(lead_id=neo.id, payload_json='{}', state='retry_wait')
    oa.db.session.add(recovery); oa.db.session.commit()
    assert archive_requested_tests() == [neo.id, acceptance.id, internal.id]
    assert archive_requested_tests() == []
    assert neo.gmail_message_id == 'saved-receipt' and neo.body == 'Saved message'
    assert neo.follow_up_due_at is None and recovery.state == 'archived'
    assert all(lead.status == 'sent' for lead in [real, similar, future])
    client = oa.app.test_client(); auth = {'X-Operator-Token': 'cleanup-test'}
    shown = client.get('/api/chat/dashboard', headers=auth).json['leads']
    assert {lead['id'] for lead in shown} == {real.id, similar.id, future.id}
    assert client.get('/api/chat/dashboard/leads/%s' % neo.id, headers=auth).status_code == 404
    assert oa.OperatorAuditEvent.query.filter_by(action='archive_owner_test').count() == 3
    old = row('V1 Controlled Acceptance', email='old-test@example.com', verification='controlled_acceptance')
    provider = row('Provider Acceptance E2E', email='provider-test@example.com', verification='SOURCE_VERIFIED')
    assert archive_requested_tests() == [old.id, provider.id]
