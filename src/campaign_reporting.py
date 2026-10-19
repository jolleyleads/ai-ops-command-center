"""Durable first-campaign attribution and receipt-backed ongoing outcomes."""
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime
from app import db, app
from src.campaign_measurement import rate

_active=ContextVar('reporting_campaign',default=None)

class CampaignMembership(db.Model):
    __tablename__='campaign_membership'
    lead_id=db.Column(db.Integer,primary_key=True)
    campaign_id=db.Column(db.String(48),nullable=False,index=True)
    created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)

class CampaignReplyOutcome(db.Model):
    __tablename__='campaign_reply_outcome'
    message_id=db.Column(db.String(255),primary_key=True)
    lead_id=db.Column(db.Integer,nullable=False,index=True)
    classification=db.Column(db.String(32),nullable=False)
    created_at=db.Column(db.DateTime,nullable=False,default=datetime.utcnow)

with app.app_context():db.create_all()

@contextmanager
def reporting_campaign(job_id):
    token=_active.set(job_id)
    try:yield
    finally:_active.reset(token)


def attribute_new_lead(lead):
    campaign_id=_active.get()
    if campaign_id and not db.session.get(CampaignMembership,lead.id):
        db.session.add(CampaignMembership(lead_id=lead.id,campaign_id=campaign_id))


def record_reply_outcome(lead_id,message_id,classification):
    if not message_id or classification not in {'interested','question','not_interested','unclear'}:return
    if not db.session.get(CampaignReplyOutcome,message_id):
        db.session.add(CampaignReplyOutcome(message_id=message_id,lead_id=lead_id,classification=classification))


def load_outcome_data(campaign_ids):
    import outreach_automation as oa
    memberships=CampaignMembership.query.filter(CampaignMembership.campaign_id.in_(campaign_ids)).all()
    ids=[m.lead_id for m in memberships]
    data={'memberships':memberships}
    for key,model in [('leads',oa.OutreachLead),('qualification',oa.OutreachQualificationReceipt),
                      ('sends',oa.OutreachSendAttempt),('replies',oa.OutreachReplyEvidence),
                      ('outcomes',CampaignReplyOutcome),('bookings',oa.OutreachBookingAttempt)]:
        column=model.id if key=='leads' else model.lead_id
        data[key]=model.query.filter(column.in_(ids)).all() if ids else []
    return data


def campaign_outcomes(job,data=None):
    import json
    data=data or load_outcome_data([job.id])
    memberships=[m for m in data['memberships'] if m.campaign_id==job.id]
    counts={'attributed_leads':len(memberships),'qualified':0,'drafted':0,'sent':0,'replies':0,
            'positive_replies':0,'booked':0,'held':0,'failed':0,'pending':0}
    for membership in memberships:
        lead=next((row for row in data['leads'] if row.id==membership.lead_id),None)
        if not lead:continue
        if lead.status in {'needs_evidence','review'}:counts['held']+=1
        if lead.status=='rejected' or lead.last_error:counts['failed']+=1
        if lead.status in {'needs_evidence','review','qualified','drafted'}:counts['pending']+=1
        qualification=next((row for row in data['qualification'] if row.lead_id==lead.id),None)
        try:receipt=json.loads(qualification.receipt_json or '{}') if qualification else {}
        except (TypeError,ValueError):receipt={}
        if receipt.get('ok') is True:counts['qualified']+=1
        if lead.subject and lead.body:counts['drafted']+=1
        sends=[row for row in data['sends'] if row.lead_id==lead.id and row.kind=='initial'
               and row.status=='sent' and row.message_id and row.created_at>=membership.created_at]
        if not sends:continue
        counts['sent']+=1
        first=min(s.created_at for s in sends)
        replies=[row for row in data['replies'] if row.lead_id==lead.id and row.message_id and row.created_at>=first]
        if replies:counts['replies']+=1
        reply_ids={reply.message_id for reply in replies}
        if any(row.lead_id==lead.id and row.message_id in reply_ids and row.classification=='interested' for row in data['outcomes']):
            counts['positive_replies']+=1
        if any(row.lead_id==lead.id and row.status=='confirmed' and row.event_id and row.created_at>=first for row in data['bookings']):
            counts['booked']+=1
    return {'available':bool(memberships),'counts':counts,
            'rates':{'reply_rate_per_sent':rate(counts['replies'],counts['sent']),
                     'positive_reply_rate_per_sent':rate(counts['positive_replies'],counts['sent']),
                     'booking_rate_per_sent':rate(counts['booked'],counts['sent'])},
            'delivered':None,'customers':None,'revenue':None,
            'attribution':'first_campaign_for_new_lead',
            'unavailable_reason':None if memberships else 'No durable lead attribution exists for this campaign; historical snapshots remain available.',
            'updated_at':datetime.utcnow().isoformat()+'Z'}
