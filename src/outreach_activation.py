"""Read-only readiness and explicit activation using existing durable send gates."""
from datetime import timedelta
from app import db
import outreach_automation as oa
from workspace_security import current_workspace, OWNER


def activation_view(lead):
    view={'recipient':lead.contact_email or '', 'contact_name':lead.contact_name or '', 'can_activate':False,'state':'held','label':'Outreach held',
          'reason':'Verify this contact and qualify the business before activating outreach.',
          'send_status':'not_sent','initial':'Not sent','followups':'Not scheduled','booking':'Waiting for an agreed meeting time'}
    confirmed=oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id,kind='initial',status='sent',recipient=oa.normalize_email(lead.contact_email)).filter(
        oa.OutreachSendAttempt.message_id.isnot(None),oa.OutreachSendAttempt.message_id!='',
        oa.OutreachSendAttempt.thread_id.isnot(None),oa.OutreachSendAttempt.thread_id!='').first()
    sent_at=lead.sent_at if lead.gmail_message_id and lead.gmail_thread_id and lead.sent_at else (confirmed.updated_at or confirmed.created_at) if confirmed else None
    if sent_at:
        booking=oa.OutreachBookingAttempt.query.filter_by(lead_id=lead.id,status='confirmed').filter(oa.OutreachBookingAttempt.event_id!='',oa.OutreachBookingAttempt.event_id.isnot(None)).first()
        stopped=lead.status in {'unsubscribed','opted_out','archived'} or oa._is_suppressed(lead.contact_email)
        view.update(state='stopped' if stopped else 'active',label='Sent',send_status='sent',sent_at=sent_at.isoformat()+'Z',reason='Initial email was sent. Further outreach is stopped because this contact is suppressed or has opted out.' if stopped else 'Initial email accepted by Gmail. Delivery is not confirmed.',initial='Send confirmed',
                    followups='Stopped' if stopped else 'Stopped after reply' if lead.replied_at else 'Scheduled' if lead.follow_up_due_at else 'No follow-up pending',
                    booking='Booking confirmed' if booking else 'Waiting for an agreed meeting time',
                    follow_up_due_at=lead.follow_up_due_at.isoformat()+'Z' if lead.follow_up_due_at else None)
        return view
    attempts=oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id).all()
    if attempts or lead.gmail_message_id or lead.gmail_thread_id or lead.sent_at:
        view.update(state='review',label='Review send status',send_status='unknown',initial='Send status unconfirmed',reason='An earlier send attempt must be reconciled before another activation.')
        return view
    if current_workspace()!=OWNER:
        view.update(label='Sign in to activate',reason='An authorized workspace mailbox is required.')
        return view
    from src.manual_outreach import permitted
    manual=permitted(lead,'initial')
    if lead.status in {'archived','unsubscribed','opted_out','completed_no_reply'} or (lead.status=='rejected' and not manual):
        return view
    if (not lead.contact_email or not oa._recipient_matches_source_domain(lead)
            or not oa._recipient_mailbox_allowed(lead.contact_email)):
        return view
    if oa._is_suppressed(lead.contact_email):
        view.update(label='Contact stopped',reason='This contact is suppressed or has opted out.')
        return view
    if manual and lead.subject and lead.body:
        view.update(can_activate=True,state='ready',label='Send email',reason='Your activation authorizes this verified contact.')
        return view
    receipt=oa._qualification_gate(lead)
    if not receipt.get('ok'):
        view['reason_codes']=receipt.get('reason_codes') or []
        return view
    if oa._server_qualification_inputs(lead)[1].get('prospect_policy')=='evidence-led-v1':
        from src.prospect_quality import for_lead
        quality=for_lead(lead)
        if not quality['ready']:
            view.update(reason='Business fit, documented need or buyer/contact evidence requires review.',reason_codes=quality['missing'])
            return view
        if not lead.subject or not lead.body:
            view.update(reason='A persisted approved draft is required before activation.')
            return view
    view.update(can_activate=True,state='ready',label='Activate outreach',
                reason='Sends your approved message with two emojis and résumé, then follows your reply and scheduling workflow. All send checks run again.',
                preview={'recipient':lead.contact_email,'subject':lead.subject,'body':lead.body,'attachment':'Matthew_Jolley_AI_Automation_Resume.docx'})
    return view


def reconcile_confirmed_initial(lead):
    """Recover a persisted send receipt only; never replay a provider request."""
    if lead.gmail_message_id:return
    attempt=oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id,kind='initial',status='sent',recipient=oa.normalize_email(lead.contact_email)).first()
    if not attempt or not attempt.message_id or not attempt.thread_id:return
    sent_at=attempt.updated_at or attempt.created_at
    lead.gmail_message_id=attempt.message_id;lead.gmail_thread_id=attempt.thread_id
    lead.sent_at=sent_at
    if not lead.replied_at and lead.status not in {'unsubscribed','opted_out','archived','booked'} and not oa._is_suppressed(lead.contact_email):
        lead.follow_up_due_at=sent_at+timedelta(days=oa.FIRST_FOLLOWUP_DAYS)
        lead.status='sent';lead.last_error=''
    db.session.commit()


def activate_prepared_contact(lead):
    """Shared verified send path for explicit requests and selected-job grants."""
    from app import app
    from flask import jsonify
    reconcile_confirmed_initial(lead)
    state=activation_view(lead)
    if state['state']=='active':
        return jsonify(ok=True,already_active=True,lead_id=lead.id,outreach=state)
    if not state['can_activate']:
        return jsonify(ok=False,error=state['reason'],outreach=state),409
    # Fail before a provider attempt if the pinned résumé cannot be attached.
    from email.message import EmailMessage
    from src.outreach_copy import add_resume_attachment, RESUME_LINE
    try:add_resume_attachment(EmailMessage(),RESUME_LINE)
    except (OSError,ValueError):return jsonify(ok=False,error='The approved résumé attachment requires attention. No email was sent.'),409
    # Check OAuth before creating a provider attempt: an expired grant should
    # request reconnection rather than strand a never-sent email in review.
    try:oa.gmail_access_token()
    except Exception as exc:
        reconnect=any(term in str(exc).lower() for term in ('invalid_grant','expired','revoked','not connected','not configured'))
        message='Reconnect Google in Menu → Settings → Manage Google connection. No email was sent.' if reconnect else 'Google connection could not be checked. No email was sent; try again after the connection recovers.'
        return jsonify(ok=False,error=message,connection_required=reconnect,outreach=state),409 if reconnect else 503
    from src.execution_deadline import checkpoint
    checkpoint("sending_selected_contact")
    response=app.make_response(oa.send_outreach(lead.id))
    data=response.get_json() or {}
    state=activation_view(lead)
    if not data.get('ok'):
        reasons=((data.get('gate') or {}).get('reasons') or [])+((data.get('send_receipt') or {}).get('reasons') or [])
        return jsonify(ok=False,error=data.get('error') or 'Outreach was held by a send check. Review the contact before retrying.',
                       reason_codes=reasons,outreach=state),response.status_code
    oa._audit_actor(lead.id,'outreach_activated',{'explicit':True},{'state':state['state']},'customer')
    db.session.commit()
    return jsonify(ok=True,lead_id=lead.id,outreach=state)
