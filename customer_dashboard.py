"""Authenticated, read-only views for the existing single-workspace chat app."""
import json
import os
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse

from flask import jsonify
from app import app, db
import outreach_automation as oa
from campaign_jobs import CampaignExecutionJob


def unpack(value, default=None):
    try:
        return json.loads(value or '{}')
    except (ValueError, TypeError):
        return default if default is not None else {}


def iso(value):
    return value.isoformat() + 'Z' if value else None


def protected(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not (oa._operator_authorized() or oa._operator_session_authorized()):
            response = jsonify(ok=False, error='Sign in to view your workspace.')
            response.status_code = 401
        else:
            response = app.make_response(fn(*args, **kwargs))
        response.headers['Cache-Control'] = 'no-store'
        return response
    return wrapped


def safe_url(value):
    try:
        return value if isinstance(value, str) and urlparse(value).scheme in {'http', 'https'} and urlparse(value).hostname else ''
    except ValueError:
        return ''


def evidence_parts(lead):
    evidence = unpack(lead.evidence_json, [])
    rows = evidence if isinstance(evidence, list) else [evidence]
    enrichment, context = {}, {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if isinstance(row.get('enrichment'), dict):
            enrichment = row['enrichment']
        if row.get('source') == 'campaign_context':
            context = row.get('context') or {}
    return rows, enrichment, context


def campaign_view(job):
    payload, result = unpack(job.payload_json), unpack(job.result_json)
    outreach, discovery = result.get('outreach') or {}, result.get('discovery') or {}
    ids = set(x for x in outreach.get('lead_ids') or [] if type(x) is int)
    ids.update(x['lead_id'] for x in outreach.get('skipped') or [] if isinstance(x, dict) and type(x.get('lead_id')) is int)
    return {'id':job.id, 'name':payload.get('target_customer') or payload.get('query') or 'Campaign',
            'territory':payload.get('territory') or '', 'status':job.status, 'created_at':iso(job.created_at),
            'progress':result.get('progress') or {}, 'lead_ids':sorted(ids),
            'research_results':len(discovery.get('results') or []), 'verified':discovery.get('verified') or 0,
            'qualified':outreach.get('qualified') or 0, 'drafted':outreach.get('drafted') or 0,
            'sent':outreach.get('sent') or 0, 'sending_limit':payload.get('sending_limit'),
            'send_authorized':payload.get('send_authorized') is True,
            'needs_attention':job.status == 'failed'}


@app.route('/api/chat/dashboard', methods=['GET'])
@protected
def dashboard():
    # Only persisted reads: opening the dashboard must never launch work.
    leads = oa.OutreachLead.query.order_by(oa.OutreachLead.updated_at.desc()).limit(500).all()
    jobs = CampaignExecutionJob.query.filter_by(kind='campaign').order_by(CampaignExecutionJob.created_at.desc()).limit(100).all()
    campaigns = [campaign_view(job) for job in jobs]
    memberships = {}
    for campaign in campaigns:
        for lead_id in campaign['lead_ids']:
            memberships.setdefault(lead_id, []).append(campaign['id'])
    records = []
    for lead in leads:
        _, _, context = evidence_parts(lead)
        records.append({'id':lead.id, 'company':lead.company, 'location':lead.location,
                        'business_type':context.get('business_type') or context.get('candidate_type') or '',
                        'score':lead.score, 'status':lead.status,
                        'has_sent_message':bool(lead.gmail_message_id), 'replied_at':iso(lead.replied_at),
                        'contact_name':lead.contact_name or '', 'has_email':bool(lead.contact_email),
                        'follow_up_due_at':iso(lead.follow_up_due_at), 'updated_at':iso(lead.updated_at),
                        'campaign_ids':memberships.get(lead.id, [])})
    return jsonify(ok=True, leads=records, campaigns=campaigns, lead_limit=500, campaign_limit=100,
                   generated_at=iso(datetime.utcnow()), scope='operator_workspace')


@app.route('/api/chat/dashboard/leads/<int:lead_id>', methods=['GET'])
@protected
def lead_details(lead_id):
    lead = db.session.get(oa.OutreachLead, lead_id)
    if not lead:
        return jsonify(ok=False, error='This lead was not found.'), 404
    rows, enrichment, context = evidence_parts(lead)
    fields = enrichment.get('fields') or {}
    qualification = oa.OutreachQualificationReceipt.query.filter_by(lead_id=lead.id).first()
    q = unpack(qualification.receipt_json) if qualification else {}
    assessment = enrichment.get('contact_assessment') or {}
    mailbox_row = oa.OperatorAuditEvent.query.filter_by(lead_id=lead.id, action='mailbox_verification').order_by(oa.OperatorAuditEvent.id.desc()).first()
    mailbox = unpack(mailbox_row.result_json) if mailbox_row else assessment.get('mailbox_validation') or {}
    email_verified = mailbox.get('email', '').casefold() == (lead.contact_email or '').casefold() and mailbox.get('mailbox_status') == 'provider_verified'
    sources = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        nested = row.get('outreach_copy_sources') or []
        for item in [row] + nested:
            if not isinstance(item, dict):continue
            url = safe_url(item.get('url') or item.get('source_url'))
            if url and url not in [s['url'] for s in sources]:
                sources.append({'url':url, 'title':item.get('title') or urlparse(url).hostname,
                                'observed_at':item.get('observed_at'),
                                'summary':str(item.get('verified_claim') or item.get('snippet') or item.get('evidence_basis') or '')[:600]})
    timeline = []
    messages = {}
    for command in oa.ExternalSideEffectCommand.query.filter_by(lead_id=lead.id, kind='gmail_send').all():
        payload = unpack(command.payload_json)
        if payload.get('send_key'):messages[payload['send_key']] = payload
    for attempt in oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id).order_by(oa.OutreachSendAttempt.created_at).all():
        timeline.append({'type':'email', 'kind':attempt.kind, 'status':attempt.status,
                         'confirmed':attempt.status == 'sent' and bool(attempt.message_id),
                         'at':iso(attempt.created_at), 'message_id':attempt.message_id,
                         'subject':messages.get(attempt.idempotency_key, {}).get('subject') or '',
                         'text':messages.get(attempt.idempotency_key, {}).get('body') or ''})
    for reply in oa.OutreachReplyEvidence.query.filter_by(lead_id=lead.id).order_by(oa.OutreachReplyEvidence.created_at).all():
        timeline.append({'type':'reply', 'at':iso(reply.received_at or reply.created_at),
                         'from':reply.from_email, 'text':reply.body_text, 'opted_out':reply.opted_out})
    bookings = [{'status':b.status, 'confirmed':b.status == 'confirmed' and bool(b.event_id),
                 'start':b.start, 'end':b.end, 'timezone':b.timezone, 'url':safe_url(b.event_url)}
                for b in oa.OutreachBookingAttempt.query.filter_by(lead_id=lead.id).order_by(oa.OutreachBookingAttempt.created_at.desc()).all()]
    phone = fields.get('phone') or {}
    person = fields.get('decision_maker') or {}
    return jsonify(ok=True, id=lead.id, company=lead.company, location=lead.location,
                   score=lead.score, score_description='Research fit score, not a probability of buying or a mailbox verification result.',
                   score_checks=q.get('passed_checks') or q.get('passed') or [],
                   reasons=q.get('reason_codes') or [], status=lead.status,
                   contact={'name':lead.contact_name or '', 'role':person.get('title') if lead.contact_name else '',
                            'email':lead.contact_email or '', 'email_label':'Hunter verified' if email_verified else 'Company contact found' if lead.contact_email else 'Contact research pending',
                            'checked_at':mailbox.get('checked_at') if email_verified else None,
                            'type':'Named contact' if lead.contact_name else ('Company inbox' if (lead.contact_email or '').split('@')[0].lower() in {'info','hello','contact','support','customersupport','sales','office','admin','service','customerservice','general'} else 'Company contact · Person not confirmed') if lead.contact_email else 'No contact yet',
                            'phone':phone.get('value') if phone.get('validated') is True else ''},
                   sources=sources, subject=lead.subject, body=lead.body, timeline=timeline, bookings=bookings,
                   follow_up_due_at=iso(lead.follow_up_due_at), follow_up_count=lead.follow_up_count,
                   business_type=context.get('business_type') or context.get('candidate_type') or '')


@app.route('/api/chat/dashboard/appointments', methods=['GET'])
@protected
def appointments():
    bookings = oa.OutreachBookingAttempt.query.filter_by(status='confirmed').order_by(oa.OutreachBookingAttempt.start).limit(500).all()
    rows = []
    for booking in bookings:
        if not booking.event_id:continue
        lead = db.session.get(oa.OutreachLead, booking.lead_id)
        rows.append({'lead_id':booking.lead_id, 'company':lead.company if lead else 'Saved contact',
                     'start':booking.start, 'end':booking.end, 'timezone':booking.timezone,
                     'url':safe_url(booking.event_url), 'attendee':booking.attendee_email})
    return jsonify(ok=True, appointments=rows)


@app.route('/api/chat/dashboard/settings', methods=['GET'])
@protected
def settings():
    from gmail_connect import _stored_connection
    connection = _stored_connection()
    return jsonify(ok=True, sender_name=os.getenv('OUTREACH_SENDER_NAME') or 'Matthew Jolley',
                   sender_company=os.getenv('OUTREACH_SENDER_COMPANY') or 'AutoMake AI',
                   sender_email=(connection.email if connection else '') or os.getenv('GMAIL_FROM_EMAIL') or '',
                   google_configured=bool((connection and connection.refresh_token) or os.getenv('GOOGLE_REFRESH_TOKEN')),
                   first_followup_days=oa.FIRST_FOLLOWUP_DAYS, maximum_followups=oa.MAX_FOLLOWUPS)
