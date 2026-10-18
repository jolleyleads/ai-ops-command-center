"""Matthew's requested archival of existing self/acceptance leads on 2026-10-18."""
import json
import re
from datetime import datetime
from app import app, db
import outreach_automation as oa
from lead_recovery import LeadRecovery

CUTOFF = datetime(2026, 10, 18, 3, 9, 21)
OWNER_EMAILS = {'neyolabs@gmail.com', 'jolleyleads@gmail.com'}
CONTROLLED = {'controlled_e2e', 'controlled_real_inbound', 'controlled_followup_test'}


def is_requested_test(lead):
    if not lead.created_at or lead.created_at > CUTOFF:
        return False
    email = (lead.contact_email or '').strip().casefold()
    name = re.sub(r'[^a-z0-9]', '', (lead.company or '').casefold())
    owner = email in OWNER_EMAILS
    return owner and (lead.verification in CONTROLLED or name in {
        'neolabs', 'neyolabs', 'provideracceptancee2e', 'realinboundacceptancetest',
        'automakecontrolledfollowuptest'} or
        ('acceptance' in name and name.startswith(('automake', 'aiautomate', 'aiops'))))


def archive_requested_tests():
    """Archive only pre-request owner tests; preserve receipts and immutable audit history."""
    ids = []
    names = []
    for lead in oa.OutreachLead.query.filter(oa.OutreachLead.created_at <= CUTOFF,
            oa.OutreachLead.status != 'archived').order_by(oa.OutreachLead.id).all():
        if not is_requested_test(lead):
            continue
        before = lead.status
        lead.status = 'archived'
        lead.follow_up_due_at = None
        lead.updated_at = datetime.utcnow()
        recovery = db.session.get(LeadRecovery, lead.id)
        if recovery:
            recovery.state = 'archived'
            recovery.next_check_at = None
            recovery.lease_token = ''
            recovery.lease_until = None
            recovery.reason_json = json.dumps(['OWNER_REQUESTED_TEST_REMOVAL'])
        oa._audit_actor(lead.id, 'archive_owner_test', {'previous_status': before},
                        {'status': 'archived'}, 'owner-request:2026-10-18')
        ids.append(lead.id)
        names.append(lead.company)
    db.session.commit()
    app.logger.warning('OWNER_TEST_CLEANUP archived_count=%s lead_ids=%s companies=%s', len(ids), ids, names)
    return ids


def run_startup_cleanup():
    with app.app_context():
        archive_requested_tests()
