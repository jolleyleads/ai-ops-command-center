"""Owned workspace views and explicit per-contact outreach activation."""
import json
import hashlib
import os
from datetime import datetime
from functools import wraps
from urllib.parse import urlparse

from flask import jsonify, request
from app import app, db
import outreach_automation as oa
from campaign_jobs import CampaignExecutionJob
from workspace_security import scope, owns, current_workspace, OWNER
from src.campaign_reporting import campaign_outcomes, load_outcome_data
from src import verifalia_mailbox


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


def draft_preview(lead):
    """Read the same approved copy used by the initial send, without saving it."""
    if (not lead.subject or not lead.body or lead.gmail_message_id or lead.gmail_thread_id
            or lead.sent_at or lead.follow_up_count
            or lead.status in {'archived','unsubscribed','opted_out','completed_no_reply'}
            or oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id).first()):
        return None
    from src.outreach_copy import approved_initial, RESUME_PATH
    preview={'recipient':lead.contact_email or '', **{k:v for k,v in approved_initial(lead,unpack(lead.evidence_json,[])).items() if k in {'subject','body'}},
             'attachment':RESUME_PATH.name,
             'note':'Sending also activates scheduled follow-ups. Replies and opt-outs control further outreach.'}
    preview['revision']=hashlib.sha256(json.dumps(preview,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    return preview


def campaign_view(job,outcome_data=None):
    payload, result = unpack(job.payload_json), unpack(job.result_json)
    outreach, discovery = result.get('outreach') or {}, result.get('discovery') or {}
    ids = set(x for x in outreach.get('lead_ids') or [] if type(x) is int)
    ids.update(x['lead_id'] for x in outreach.get('skipped') or [] if isinstance(x, dict) and type(x.get('lead_id')) is int)
    if outcome_data:
        ids.update(m.lead_id for m in outcome_data['memberships'] if m.campaign_id==job.id)
    ids={lead_id for lead_id in ids if owns('lead',lead_id)}
    return {'id':job.id, 'name':payload.get('target_customer') or payload.get('query') or 'Campaign',
            'territory':payload.get('territory') or '', 'status':job.status, 'created_at':iso(job.created_at),
            'progress':result.get('progress') or {}, 'lead_ids':sorted(ids),
            'research_results':len(discovery.get('results') or []), 'verified':discovery.get('verified') or 0,
            'qualified':outreach.get('qualified') or 0, 'drafted':outreach.get('drafted') or 0,
            'sent':outreach.get('sent') or 0, 'sending_limit':payload.get('sending_limit'),
            'send_authorized':payload.get('send_authorized') is True,
            'needs_attention':job.status == 'failed',
            'snapshot':{'research_results':len(discovery.get('results') or []),'verified':discovery.get('verified') or 0,'qualified':outreach.get('qualified') or 0,'drafted':outreach.get('drafted') or 0,'sent':outreach.get('sent') or 0},
            'live_outcomes':campaign_outcomes(job,outcome_data)}


@app.route('/api/chat/dashboard', methods=['GET'])
@protected
def dashboard():
    # Only persisted reads: opening the dashboard must never launch work.
    try:
        lead_offset=max(0,int(request.args.get('lead_offset',0)))
        campaign_offset=max(0,int(request.args.get('campaign_offset',0)))
    except (TypeError,ValueError):return jsonify(ok=False,error='Invalid pagination offset.'),400
    lead_query=oa.OutreachLead.query.filter(oa.OutreachLead.status!='archived',scope(oa.OutreachLead,'lead'))
    campaign_query=CampaignExecutionJob.query.filter(CampaignExecutionJob.kind=='campaign',scope(CampaignExecutionJob,'campaign'))
    folder=request.args.get('folder','')
    if folder not in {'','sent','drafts','conversations'}:
        return jsonify(ok=False,error='Unknown email folder.'),400
    confirmed=oa.OutreachSendAttempt.query.filter(
        oa.OutreachSendAttempt.lead_id==oa.OutreachLead.id,
        oa.OutreachSendAttempt.kind=='initial',oa.OutreachSendAttempt.status=='sent',
        oa.OutreachSendAttempt.message_id.isnot(None),oa.OutreachSendAttempt.message_id!='',
        oa.OutreachSendAttempt.thread_id.isnot(None),oa.OutreachSendAttempt.thread_id!='').exists()
    # Sort each folder by its own event before applying pagination.
    sent_time = db.session.query(db.func.max(oa.OutreachSendAttempt.updated_at)).filter(
        oa.OutreachSendAttempt.lead_id==oa.OutreachLead.id,
        oa.OutreachSendAttempt.status=='sent',
        oa.OutreachSendAttempt.message_id.isnot(None),oa.OutreachSendAttempt.message_id!='').correlate(oa.OutreachLead).scalar_subquery()
    reply_time = db.session.query(db.func.max(db.func.coalesce(
        oa.OutreachReplyEvidence.received_at,oa.OutreachReplyEvidence.created_at))).filter(
        oa.OutreachReplyEvidence.lead_id==oa.OutreachLead.id).correlate(oa.OutreachLead).scalar_subquery()
    last_sent = db.func.coalesce(sent_time,oa.OutreachLead.sent_at,oa.OutreachLead.created_at)
    last_reply = db.func.coalesce(reply_time,oa.OutreachLead.replied_at,oa.OutreachLead.created_at)
    activity_time = db.case((last_reply>last_sent,last_reply),else_=last_sent)
    order_time = oa.OutreachLead.updated_at
    if folder=='sent':
        order_time = last_sent
        lead_query=lead_query.filter(db.or_(confirmed,db.and_(
            oa.OutreachLead.gmail_message_id.isnot(None),oa.OutreachLead.gmail_message_id!='',
            oa.OutreachLead.gmail_thread_id.isnot(None),oa.OutreachLead.gmail_thread_id!='',oa.OutreachLead.sent_at.isnot(None))))
    elif folder=='drafts':
        lead_query=lead_query.filter(
            oa.OutreachLead.subject.isnot(None),oa.OutreachLead.subject!='',oa.OutreachLead.body.isnot(None),oa.OutreachLead.body!='',
            db.or_(oa.OutreachLead.gmail_message_id.is_(None),oa.OutreachLead.gmail_message_id==''),
            db.or_(oa.OutreachLead.gmail_thread_id.is_(None),oa.OutreachLead.gmail_thread_id==''),
            oa.OutreachLead.sent_at.is_(None),oa.OutreachLead.follow_up_count==0,
            oa.OutreachLead.status.notin_(['unsubscribed','opted_out','completed_no_reply']),
            ~oa.OutreachSendAttempt.query.filter(oa.OutreachSendAttempt.lead_id==oa.OutreachLead.id).exists())
    elif folder=='conversations':
        lead_query=lead_query.filter(db.or_(oa.OutreachLead.gmail_message_id!='',
            oa.OutreachLead.replied_at.isnot(None),oa.OutreachLead.status=='drafted'))
        order_time=db.case((db.or_(oa.OutreachLead.gmail_message_id!='',
            oa.OutreachLead.replied_at.isnot(None)),activity_time),else_=oa.OutreachLead.updated_at)
    leads = lead_query.add_columns(order_time.label('activity_at')).order_by(order_time.desc(),oa.OutreachLead.id.desc()).offset(lead_offset).limit(500).all()
    jobs = CampaignExecutionJob.query.filter(CampaignExecutionJob.kind=='campaign',scope(CampaignExecutionJob,'campaign')).order_by(CampaignExecutionJob.created_at.desc(),CampaignExecutionJob.id.desc()).offset(campaign_offset).limit(100).all()
    outcome_data=load_outcome_data([job.id for job in jobs])
    campaigns = [campaign_view(job,outcome_data) for job in jobs]
    memberships = {}
    for campaign in campaigns:
        for lead_id in campaign['lead_ids']:
            memberships.setdefault(lead_id, []).append(campaign['id'])
    from src.outreach_activation import activation_view
    from src.prospect_quality import for_lead
    records = []
    for lead, activity_at in leads:
        _, _, context = evidence_parts(lead)
        records.append({'id':lead.id, 'company':lead.company, 'location':lead.location,
                        'business_type':context.get('business_type') or context.get('candidate_type') or '',
                        'score':lead.score, 'status':lead.status,
                        'has_sent_message':bool(lead.gmail_message_id), 'replied_at':iso(lead.replied_at),
                        'contact_name':lead.contact_name or '', 'contact_email':lead.contact_email or '', 'has_email':bool(lead.contact_email),
                        'follow_up_due_at':iso(lead.follow_up_due_at), 'updated_at':iso(lead.updated_at),
                        'created_at':iso(lead.created_at), 'activity_at':iso(activity_at),
                        'campaign_ids':memberships.get(lead.id, []),'outreach':activation_view(lead), 'prospect_quality':for_lead(lead),'selection':{'kind':'lead','lead_id':lead.id}})
    return jsonify(ok=True, leads=records, campaigns=campaigns, lead_limit=500, campaign_limit=100,lead_offset=lead_offset,campaign_offset=campaign_offset,lead_total=lead_query.count(),campaign_total=campaign_query.count(),
                   generated_at=iso(datetime.utcnow()), scope='customer_workspace')


@app.route('/api/chat/dashboard/leads/<int:lead_id>', methods=['GET'])
@protected
def lead_details(lead_id):
    lead = db.session.get(oa.OutreachLead, lead_id)
    if not lead or lead.status == 'archived' or not owns('lead',lead_id):
        return jsonify(ok=False, error='This lead was not found.'), 404
    from src.outreach_activation import activation_view
    from src.prospect_quality import for_lead
    rows, enrichment, context = evidence_parts(lead)
    fields = enrichment.get('fields') or {}
    qualification = oa.OutreachQualificationReceipt.query.filter_by(lead_id=lead.id).first()
    q = unpack(qualification.receipt_json) if qualification else {}
    assessment = enrichment.get('contact_assessment') or {}
    from src.mailbox_verification import lead_status
    verification=lead_status(lead)
    mailbox=verification['receipt']
    email_verified=verification['verified']
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
                         'recipient':attempt.recipient,
                         'subject':messages.get(attempt.idempotency_key, {}).get('subject') or '',
                         'text':messages.get(attempt.idempotency_key, {}).get('body') or ''})
    for reply in oa.OutreachReplyEvidence.query.filter_by(lead_id=lead.id).order_by(oa.OutreachReplyEvidence.created_at).all():
        timeline.append({'type':'reply', 'at':iso(reply.received_at or reply.created_at),
                         'from':reply.from_email, 'text':reply.body_text, 'opted_out':reply.opted_out})
    bookings = [{'status':b.status, 'confirmed':b.status == 'confirmed' and bool(b.event_id),
                 'start':b.start, 'end':b.end, 'timezone':b.timezone, 'url':safe_url(b.event_url)}
                for b in oa.OutreachBookingAttempt.query.filter_by(lead_id=lead.id).order_by(oa.OutreachBookingAttempt.start.desc(),oa.OutreachBookingAttempt.id.desc()).all()]
    timeline.sort(key=lambda row: row.get('at') or '', reverse=True)
    phone = fields.get('phone') or {}
    person = fields.get('decision_maker') or {}
    preview=draft_preview(lead)
    draft_send_allowed=bool(preview and current_workspace()==OWNER and oa._recipient_matches_source_domain(lead) and oa._recipient_mailbox_allowed(lead.contact_email) and not oa._is_suppressed(lead.contact_email))
    return jsonify(ok=True, id=lead.id, company=lead.company, location=lead.location,
                   score=lead.score, score_description='Discovery evidence score from the source result or evidence-status fallback. Not a purchase probability or mailbox verification.',score_method='discovery_evidence_v1',
                   score_checks=q.get('passed_checks') or q.get('passed') or [],
                   reasons=q.get('reason_codes') or [], status=lead.status,
                   contact={'name':lead.contact_name or '', 'role':person.get('title') if lead.contact_name else '',
                            'email':lead.contact_email or '', 'email_label':verification['label'],
                            'checked_at':mailbox.get('checked_at') if email_verified else None,
                            'type':'Named contact' if lead.contact_name else ('Company inbox' if (lead.contact_email or '').split('@')[0].lower() in {'info','hello','contact','support','customersupport','sales','office','admin','service','customerservice','general'} else 'Company contact · Person not confirmed') if lead.contact_email else 'No contact yet',
                            'phone':phone.get('value') if phone.get('validated') is True else ''},
                   sources=sources, subject=lead.subject, body=lead.body, draft_preview=preview,draft_send_allowed=draft_send_allowed, timeline=timeline, bookings=bookings,
                   outreach=activation_view(lead),mailbox_verification={k:v for k,v in verification.items() if k!='receipt'},prospect_quality=for_lead(lead),
                   follow_up_due_at=iso(lead.follow_up_due_at), follow_up_count=lead.follow_up_count,
                   business_type=context.get('business_type') or context.get('candidate_type') or '')


@app.route('/api/chat/dashboard/appointments', methods=['GET'])
@protected
def appointments():
    bookings = oa.OutreachBookingAttempt.query.filter_by(status='confirmed').order_by(oa.OutreachBookingAttempt.start.desc(),oa.OutreachBookingAttempt.id.desc()).limit(500).all()
    rows = []
    for booking in bookings:
        if not booking.event_id:continue
        lead = db.session.get(oa.OutreachLead, booking.lead_id)
        if not lead or lead.status == 'archived' or not owns('lead',lead.id):continue
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
                   integrations={
                       'autohunt':{'configured':True,'purpose':'Business discovery and public contact collection, with automatic Hunter mailbox verification when connected.'},
                       'verifalia':{'configured':verifalia_mailbox.configured(),'purpose':'Free daily mailbox verification. No paid fallback.'},
                       'hunter':{'configured':bool(os.getenv('HUNTER_API_KEY','').strip() and os.getenv('HUNTER_ACCOUNT_EMAIL','').strip()
                           and os.getenv('HUNTER_MAILBOX_VERIFICATION_ENABLED','false').lower()=='true'),
                           'account':os.getenv('HUNTER_ACCOUNT_EMAIL','').strip(),
                           'purpose':'Verifies emails collected by AutoHunt during email research when connected.'},
                       'web_research':{'configured':bool(os.getenv('EXA_API_KEY','').strip()),'purpose':'Current web sources and business research'},
                       'places':{'configured':bool(os.getenv('GOOGLE_PLACES_API_KEY','').strip()),'purpose':'Local business discovery and company websites'},
                       'google':{'configured':bool((connection and connection.refresh_token) or os.getenv('GOOGLE_REFRESH_TOKEN')),
                           'purpose':'Outreach, reply detection, follow-ups and Calendar booking'}},
                   first_followup_days=oa.FIRST_FOLLOWUP_DAYS, maximum_followups=oa.MAX_FOLLOWUPS)


@app.post('/api/chat/dashboard/hunter/check')
@protected
def check_hunter_connection():
    """An explicit account check, never a contact purchase or outreach launch."""
    from src import hunter_mailbox as mailbox
    import requests
    if current_workspace()!=OWNER:return jsonify(ok=False,error='Open the connected owner workspace to check Hunter.'),403
    expected=os.getenv('HUNTER_ACCOUNT_EMAIL','').strip().lower()
    key=os.getenv('HUNTER_API_KEY','').strip()
    result={'ok':False,'state':'Needs attention','account':expected}
    if not mailbox.enabled() or not key or not expected:return jsonify(result)
    try:
        data,status=mailbox._request('account',key,{},requests.get)
        if status!=200 or not isinstance(data,dict) or str(data.get('email') or '').lower()!=expected:
            return jsonify(result)
        if str(data.get('plan_name') or '').lower()!='free':return jsonify(result)
        usage=data.get('requests') or {}
        credits=mailbox.remaining_requests(usage.get('credits') or usage.get('searches') or {})
        available=isinstance(credits,(int,float)) and not isinstance(credits,bool) and credits>=1
        result.update(ok=True,state='Ready' if available else 'Email lookups paused',credits_remaining=credits)
    except Exception:
        result['state']='Connection unavailable'
    return jsonify(result)


@app.post('/api/chat/leads/<int:lead_id>/activate-outreach')
@protected
def activate_contact_outreach(lead_id):
    """An explicit click activates one owned contact, never a search GET."""
    if current_workspace()!=OWNER:
        return jsonify(ok=False,error='A connected workspace mailbox is required.'),403
    lead=db.session.get(oa.OutreachLead,lead_id)
    if not lead or not owns('lead',lead_id) or lead.status=='archived':
        return jsonify(ok=False,error='This lead was not found.'),404
    payload=request.get_json(silent=True) or {}
    if not isinstance(payload,dict) or payload.get('activate') is not True:
        return jsonify(ok=False,error='Explicit outreach activation is required.'),400
    if 'draft_revision' in payload:
        preview=draft_preview(lead)
        if not preview or payload['draft_revision']!=preview['revision']:
            return jsonify(ok=False,error='This draft changed or already has a send attempt. Refresh and review it before sending.'),409
    if 'draft_revision' in payload:
        from src.selection_workflows import enqueue_selected_workflow
        context=oa._server_qualification_inputs(lead)[1]
        return enqueue_selected_workflow({'activate':True,'selection':{'kind':'lead','lead_id':lead.id},
            'offer':context.get('offer') or 'Inquiry follow-up and appointment scheduling automation',
            'draft_revision':payload['draft_revision']})
    from src.outreach_activation import activate_prepared_contact
    return activate_prepared_contact(lead)


@app.post('/api/chat/dashboard/verifalia/connect')
@protected
def connect_verifalia():
    from src import verifalia_mailbox as provider
    data=request.get_json(silent=True) or {}
    if not isinstance(data,dict):return jsonify(ok=False,error='Invalid connection request.'),400
    username=str(data.get('username') or '').strip()
    password=data.get('password')
    if not username or not isinstance(password,str) or not password or len(username)>500 or len(password)>1000:
        return jsonify(ok=False,error='Enter your Verifalia API username and password.'),400
    if data.get('free_only') is not True:
        return jsonify(ok=False,error='Confirm free-only verification before connecting.'),400
    try:provider._cipher()
    except ValueError:return jsonify(ok=False,error='Secure credential storage needs configuration. No credentials were saved.'),503
    result=provider.balance((username,password))
    if not result['ok']:return jsonify(ok=False,error=result['state']),409
    provider.save_credentials(username,password)
    return jsonify(ok=True,**{k:v for k,v in result.items() if k!='ok'})


@app.post('/api/chat/dashboard/verifalia/check')
@protected
def check_verifalia():
    from src.verifalia_mailbox import balance
    return jsonify(balance())
