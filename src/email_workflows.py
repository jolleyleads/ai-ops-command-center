"""Explicit workflows for recipients supplied by the signed-in workspace owner."""
import hashlib
import json
import re
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime

from flask import jsonify, request, send_from_directory
from app import app, db
import outreach_automation as oa
from campaign_jobs import CampaignExecutionJob, enqueue_execution, _view
from workspace_security import OWNER, current_workspace, owns, claim, scope
from src.outreach_execution import EMAIL_RE

_active = ContextVar('provided_email_send', default=None)
POLICY = 'user-provided-email-v1'
STOPPED = {'archived', 'unsubscribed', 'opted_out', 'completed_no_reply'}


class EmailWorkflowContact(db.Model):
    __tablename__ = 'email_workflow_contact'
    id = db.Column(db.String(64), primary_key=True)
    workspace_id = db.Column(db.String(96), nullable=False, index=True)
    email = db.Column(db.String(254), nullable=False)
    lead_id = db.Column(db.Integer, nullable=False)
    last_job_id = db.Column(db.String(48))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


with app.app_context():
    db.create_all()


def _json(value):
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (TypeError, ValueError):
        return {}


def _owner():
    return current_workspace() == OWNER


def _usable(lead):
    return bool(lead and owns('lead', lead.id, OWNER) and EMAIL_RE.fullmatch(oa.normalize_email(lead.contact_email))
                and lead.status not in STOPPED and not oa._is_suppressed(lead.contact_email)
                and oa._recipient_mailbox_allowed(lead.contact_email))


def _binding(lead, job_id):
    job = db.session.get(CampaignExecutionJob, job_id)
    if not job or not owns('campaign', job_id, OWNER):
        return None
    payload = _json(job.payload_json)
    if payload.get('_provided_email_policy') != POLICY or payload.get('_selected_workspace') != OWNER:
        return None
    address = oa.normalize_email(lead.contact_email)
    for item in payload.get('recipients') or []:
        row = db.session.get(EmailWorkflowContact, item.get('id'))
        if (row and row.workspace_id == OWNER and row.lead_id == lead.id == item.get('lead_id')
                and row.email == address == item.get('email')):
            return job
    return None


def permitted(lead, kind):
    """A typed address is not researched/verified evidence or a general send grant."""
    if not _usable(lead):
        return False
    address = oa.normalize_email(lead.contact_email)
    if kind == 'initial':
        grant = _active.get()
        if not grant or grant[:2] != (lead.id, address):
            return False
        job = _binding(lead, grant[2])
        return bool(job and job.status == 'running')
    if kind not in {'followup', 'automatic_reply', 'booking_confirmation', 'booking'}:
        return False
    initial = oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id, recipient=address, kind='initial', status='sent').first()
    if not initial or not initial.message_id:
        return False
    audit = oa.OperatorAuditEvent.query.filter_by(lead_id=lead.id, action='provided_email_workflow_approved').order_by(oa.OperatorAuditEvent.id.desc()).first()
    approved = _json(audit.request_json) if audit else {}
    return bool(approved.get('recipient') == address and _binding(lead, approved.get('job_id')))


@contextmanager
def authorize(lead, job_id):
    job = _binding(lead, job_id)
    if not job or job.status != 'running' or not _usable(lead):
        yield False
        return
    oa._audit_actor(lead.id, 'provided_email_workflow_approved',
                    {'recipient': oa.normalize_email(lead.contact_email), 'job_id': job_id, 'policy': POLICY},
                    {'basis': 'explicit_user_provided_recipient', 'source_verified': False}, 'customer')
    db.session.commit()
    token = _active.set((lead.id, oa.normalize_email(lead.contact_email), job_id))
    try:
        yield True
    finally:
        _active.reset(token)


def contact_view(row):
    lead = db.session.get(oa.OutreachLead, row.lead_id)
    job = db.session.get(CampaignExecutionJob, row.last_job_id) if row.last_job_id else None
    state, reason = 'idle', ''
    confirmed = (oa.OutreachSendAttempt.query.filter_by(lead_id=row.lead_id, recipient=row.email, kind='initial', status='sent')
                 .filter(oa.OutreachSendAttempt.message_id != '', oa.OutreachSendAttempt.thread_id != '').first())
    receipt_complete = bool(lead and lead.gmail_message_id and lead.gmail_thread_id and lead.sent_at)
    if confirmed or receipt_complete:
        state = 'active'
    elif lead and (lead.gmail_message_id or lead.gmail_thread_id or lead.sent_at):
        state, reason = 'review', 'Existing email history needs review before another initial message can be sent.'
    elif job and job.status in {'queued', 'running'}:
        state = job.status
    elif job:
        outcomes = _json(job.result_json).get('email_workflows') or (_json(job.result_json).get('progress') or {}).get('email_workflows') or []
        result = next((item for item in outcomes if item.get('id') == row.id), {})
        state = result.get('status') or 'held'
        reason = result.get('reason') or job.error or ''
    if lead and (lead.status in STOPPED or oa._is_suppressed(row.email)):
        state, reason = 'stopped', 'This contact is stopped or has opted out.'
    attempts = oa.OutreachSendAttempt.query.filter_by(recipient=row.email, kind='initial').join(oa.OutreachLead, oa.OutreachLead.id == oa.OutreachSendAttempt.lead_id).filter(scope(oa.OutreachLead, 'lead', OWNER)).all()
    unsafe = any(a.status in {'pending', 'uncertain', 'failed'} for a in attempts)
    if unsafe and state not in {'active', 'queued', 'running', 'stopped'}:
        state, reason = 'review', 'An earlier send attempt needs review. No email will be resent automatically.'
    return {'id': row.id, 'email': row.email, 'lead_id': row.lead_id, 'status': state, 'reason': reason,
            'can_activate': state in {'idle', 'held'} and _usable(lead) and not unsafe,
            'job_id': row.last_job_id, 'source': 'Added by you',
            'follow_up_due_at': lead.follow_up_due_at.isoformat()+'Z' if lead and lead.follow_up_due_at else None}


@app.route('/api/chat/email-workflows', methods=['GET', 'POST'])
def email_workflow_contacts():
    if not _owner():
        return jsonify(ok=False, error='Sign in to the connected workspace to manage email workflows.'), 403
    if request.method == 'GET':
        rows = EmailWorkflowContact.query.filter_by(workspace_id=OWNER).order_by(EmailWorkflowContact.created_at.desc()).limit(500).all()
        return jsonify(ok=True, contacts=[contact_view(row) for row in rows])
    data = request.get_json(silent=True) or {}
    addresses = data.get('emails') if isinstance(data, dict) else None
    if not isinstance(addresses, list) or not 1 <= len(addresses) <= 100:
        return jsonify(ok=False, error='Add between 1 and 100 email addresses at a time.'), 400
    emails = list(dict.fromkeys(oa.normalize_email(value) for value in addresses if isinstance(value, str)))
    if len(emails) == 0 or any(len(value) > 254 or not EMAIL_RE.fullmatch(value) for value in emails) or len(emails) != len(set(oa.normalize_email(value) for value in addresses)):
        return jsonify(ok=False, error='Check the email addresses before adding them. Nothing was activated.'), 400
    rows = []
    from v1_orchestration import discovery_lock
    for email in emails:
        key = hashlib.sha256((OWNER+'\0'+email).encode()).hexdigest()
        with discovery_lock('provided-email-contact', email) as acquired:
            if not acquired:
                return jsonify(ok=False, error='This address is being added. Refresh to check it.'), 409
            row = db.session.get(EmailWorkflowContact, key)
            if not row:
                existing = oa.OutreachLead.query.filter_by(contact_email=email).filter(scope(oa.OutreachLead, 'lead', OWNER)).order_by(oa.OutreachLead.id).all()
                lead = next((lead for lead in existing if lead.gmail_message_id), existing[0] if existing else None)
                if not lead:
                    lead = oa.OutreachLead(company='Email contact', source_url='', contact_email=email, status='needs_evidence',
                                           verification='USER_PROVIDED', score=0, evidence_json=json.dumps([{'source': 'user_provided_email', 'email': email}]))
                    db.session.add(lead); db.session.flush(); claim('lead', lead.id, OWNER)
                row = EmailWorkflowContact(id=key, workspace_id=OWNER, email=email, lead_id=lead.id)
                db.session.add(row); db.session.commit()
            rows.append(contact_view(row))
    return jsonify(ok=True, contacts=rows, message='Email addresses added. No workflow was activated.')


@app.get('/api/chat/email-workflows/<contact_id>/preview')
def preview_email_workflow(contact_id):
    if not _owner():
        return jsonify(ok=False, error='Sign in first.'), 403
    row = db.session.get(EmailWorkflowContact, contact_id)
    if not row or row.workspace_id != OWNER:
        return jsonify(ok=False, error='Email contact not found.'), 404
    from src.outreach_copy import approved_initial, RESUME_PATH
    lead = db.session.get(oa.OutreachLead, row.lead_id)
    return jsonify(ok=True, preview={'recipient': row.email, **approved_initial(lead, oa._server_qualification_inputs(lead)[2]),
                                    'attachment': RESUME_PATH.name})


@app.post('/api/chat/email-workflows/activate')
def activate_email_workflows():
    if not _owner():
        return jsonify(ok=False, error='Sign in to the connected workspace to activate email workflows.'), 403
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify(ok=False, error='Invalid activation request.'), 400
    ids = data.get('ids')
    if data.get('activate') is not True or not isinstance(ids, list) or not 1 <= len(ids) <= 100 or any(not isinstance(key, str) for key in ids):
        return jsonify(ok=False, error='Select 1–100 email addresses and choose Activate workflow.'), 400
    rows = [db.session.get(EmailWorkflowContact, key) for key in dict.fromkeys(ids)]
    if any(not row or row.workspace_id != OWNER or not owns('lead', row.lead_id, OWNER) for row in rows):
        return jsonify(ok=False, error='A selected email contact was not found.'), 404
    selected = [row for row in rows if contact_view(row)['can_activate']]
    if not selected:
        jobs = [db.session.get(CampaignExecutionJob, row.last_job_id) for row in rows if row.last_job_id]
        if jobs:
            return jsonify(_view(jobs[0])), 202
        return jsonify(ok=False, error='The selected contacts are already active, stopped, or need review.'), 409
    offer = str(data.get('offer') or 'Inquiry follow-up and appointment scheduling automation')[:1200]
    recipients = [{'id': row.id, 'email': row.email, 'lead_id': row.lead_id} for row in selected]
    binding = json.dumps([OWNER, sorted((row.id, row.last_job_id or '') for row in selected), offer])
    key = 'provided-email:'+hashlib.sha256(binding.encode()).hexdigest()
    response = app.make_response(enqueue_execution('campaign', {'_provided_email_policy': POLICY, '_selected_workspace': OWNER,
        'recipients': recipients, 'offer': offer, 'target_customer': 'Email workflows', 'target_count': len(recipients)}, key))
    job_id = (response.get_json() or {}).get('job_id')
    if job_id and response.status_code == 202:
        for row in selected:
            row.last_job_id = job_id
        db.session.commit()
    return response


def run_email_workflows(data, job_id):
    import gmail_reconciliation  # noqa: F401 - isolated workers need command-bound send receipts too
    from src.execution_deadline import checkpoint
    from src.outreach_copy import approved_initial, add_resume_attachment, RESUME_LINE
    from email.message import EmailMessage
    from v1_orchestration import discovery_lock
    if data.get('_provided_email_policy') != POLICY or data.get('_selected_workspace') != OWNER:
        return None, 'authorization', 'EMAIL_WORKFLOW_AUTHORIZATION_REQUIRED'
    results = []
    for item in data.get('recipients') or []:
        checkpoint('activating_email_batch', email_workflows=results, batch_requested=len(data['recipients']), batch_completed=len(results))
        row = db.session.get(EmailWorkflowContact, item['id'])
        lead = db.session.get(oa.OutreachLead, row.lead_id) if row else None
        result = {'id': item['id'], 'email': item['email'], 'status': 'held', 'reason': ''}
        if not lead or not _binding(lead, job_id) or not _usable(lead):
            result['reason'] = 'This contact is stopped, unavailable, or no longer matches the selected address.'
            results.append(result); continue
        try:
            with discovery_lock('selected-recipient', row.email) as acquired:
                if not acquired:
                    result['reason'] = 'Another workflow is checking this recipient. Refresh its status.'
                else:
                    prior = oa.OutreachSendAttempt.query.filter_by(recipient=row.email, kind='initial').join(oa.OutreachLead, oa.OutreachLead.id == oa.OutreachSendAttempt.lead_id).filter(scope(oa.OutreachLead, 'lead', OWNER)).first()
                    if lead.gmail_message_id or lead.gmail_thread_id or lead.sent_at:
                        result['status'] = 'active' if lead.gmail_message_id and lead.gmail_thread_id and lead.sent_at else 'review'
                        result['reason'] = 'This contact already has email history; another initial email was not sent.'
                    elif prior:
                        result['status'] = 'active' if prior.status == 'sent' and prior.message_id and prior.thread_id else 'review'
                        result['reason'] = 'A workflow has already sent to this address.' if result['status'] == 'active' else 'An earlier send attempt requires review before another email can be sent.'
                    else:
                        add_resume_attachment(EmailMessage(), RESUME_LINE)
                        oa.gmail_access_token()
                        draft = approved_initial(lead, oa._server_qualification_inputs(lead)[2])
                        lead.subject, lead.body = draft['subject'], draft['body']; db.session.commit()
                        with authorize(lead, job_id) as allowed:
                            if not allowed:
                                result['reason'] = 'The selected workflow authorization is no longer valid.'
                            else:
                                response = app.make_response(oa.send_outreach(lead.id))
                                outcome = response.get_json() or {}
                                if outcome.get('ok') and lead.gmail_message_id and lead.gmail_thread_id:
                                    result.update(status='active', sent=True, reason='Email sent. Follow-ups are scheduled; replies stop follow-ups automatically.')
                                else:
                                    reasons = (outcome.get('gate') or {}).get('reasons') or []
                                    result['reason'] = outcome.get('error') or ', '.join(reasons) or 'Sending could not be confirmed. Review this contact before retrying.'
        except Exception:
            app.logger.exception('EMAIL_WORKFLOW_FAILED job_id=%s contact_id=%s',job_id,item['id'])
            db.session.rollback()
            result['reason'] = 'The workflow could not finish. Check Google connection and saved send status before retrying.'
        results.append(result)
    checkpoint('activating_email_batch', email_workflows=results, batch_requested=len(results), batch_completed=len(results))
    return {'ok': True, 'email_workflows': results, 'outreach': {'sent': sum(item.get('sent') is True for item in results)}}, None, None


@app.get('/api/chat/email-workflows/verified-available')
def available_verified_workflow_contacts():
    """Read-only picker: verified decision makers without prior outreach activation."""
    if not _owner():
        return jsonify(ok=False, error='Sign in to your workspace.'), 403
    from src.verified_contacts import verified_contacts
    results = []
    for person in verified_contacts():
        email = oa.normalize_email(person.get('email') or '')
        if not email or not EMAIL_RE.fullmatch(email) or oa._is_suppressed(email):
            continue
        key = hashlib.sha256((OWNER+'\\0'+email).encode()).hexdigest()
        row = db.session.get(EmailWorkflowContact, key)
        if row and (row.last_job_id or not contact_view(row)['can_activate']):
            continue
        leads = oa.OutreachLead.query.filter_by(contact_email=email).filter(
            scope(oa.OutreachLead, 'lead', OWNER)).all()
        if any(lead.status in STOPPED or lead.gmail_message_id or lead.gmail_thread_id
               or lead.sent_at or lead.follow_up_count for lead in leads):
            continue
        prior = oa.OutreachSendAttempt.query.filter_by(recipient=email, kind='initial').join(
            oa.OutreachLead, oa.OutreachLead.id == oa.OutreachSendAttempt.lead_id).filter(
            scope(oa.OutreachLead, 'lead', OWNER)).first()
        if prior:
            continue
        results.append({key: person.get(key) for key in ('email', 'name', 'role', 'company', 'checked_at')})
    response = jsonify(ok=True, contacts=results, count=len(results))
    response.headers['Cache-Control'] = 'no-store'
    return response
