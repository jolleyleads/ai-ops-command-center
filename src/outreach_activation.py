"""Read-only readiness and explicit activation using existing durable send gates."""
from datetime import timedelta
from app import db
import outreach_automation as oa
from workspace_security import current_workspace, OWNER


def activation_view(lead):
    view={'can_activate':False,'state':'held','label':'Outreach held',
          'reason':'Verify this contact and qualify the business before activating outreach.',
          'initial':'Not sent','followups':'Not scheduled','booking':'Waiting for an agreed meeting time'}
    if lead.gmail_message_id and lead.gmail_thread_id and lead.sent_at:
        booking=oa.OutreachBookingAttempt.query.filter_by(lead_id=lead.id,status='confirmed').filter(oa.OutreachBookingAttempt.event_id!='',oa.OutreachBookingAttempt.event_id.isnot(None)).first()
        stopped=lead.status in {'unsubscribed','opted_out','archived'} or oa._is_suppressed(lead.contact_email)
        view.update(state='stopped' if stopped else 'active',label='Outreach stopped' if stopped else 'Outreach active',reason='This contact is suppressed or has opted out.' if stopped else 'Initial email accepted by Gmail. Delivery is not confirmed.',initial='Send confirmed',
                    followups='Stopped' if stopped else 'Stopped after reply' if lead.replied_at else 'Scheduled' if lead.follow_up_due_at else 'No follow-up pending',
                    booking='Booking confirmed' if booking else 'Waiting for an agreed meeting time',
                    follow_up_due_at=lead.follow_up_due_at.isoformat()+'Z' if lead.follow_up_due_at else None)
        return view
    if current_workspace()!=OWNER:
        view.update(label='Sign in to activate',reason='An authorized workspace mailbox is required.')
        return view
    attempts=oa.OutreachSendAttempt.query.filter_by(lead_id=lead.id).all()
    if attempts:
        view.update(state='review',label='Review send status',reason='An earlier send attempt must be reconciled before another activation.')
        return view
    if lead.status in {'archived','rejected','unsubscribed','opted_out','completed_no_reply'}:
        return view
    if (not lead.contact_email or not oa._recipient_matches_source_domain(lead)
            or not oa._recipient_mailbox_allowed(lead.contact_email)):
        return view
    if oa._is_suppressed(lead.contact_email):
        view.update(label='Contact stopped',reason='This contact is suppressed or has opted out.')
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
