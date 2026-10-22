from datetime import datetime,timedelta
import pytest
import commercial_app
import outreach_automation as oa
import campaign_jobs as jobs
from src.campaign_reporting import CampaignMembership, campaign_outcomes, reporting_campaign, attribute_new_lead, record_reply_outcome

@pytest.fixture
def setup():
    with oa.app.app_context():
        oa.db.drop_all();oa.db.create_all()
        first=jobs.CampaignExecutionJob(id='first',kind='campaign',payload_json='{}',status='completed')
        other=jobs.CampaignExecutionJob(id='other',kind='campaign',payload_json='{}',status='completed')
        lead=oa.OutreachLead(company='Evidence company',score=80,status='drafted',subject='Saved',body='Draft')
        oa.db.session.add_all([first,other,lead]);oa.db.session.flush()
        with reporting_campaign(first.id):attribute_new_lead(lead)
        oa.db.session.commit()
        yield first,other,lead
        oa.db.session.remove();oa.db.drop_all()


def test_receipts_update_only_origin_campaign_and_do_not_double_count(setup):
    first,other,lead=setup
    with reporting_campaign(other.id):attribute_new_lead(lead)
    oa.db.session.commit()
    before=campaign_outcomes(first)
    assert before['counts']['sent']==0 and before['rates']['reply_rate_per_sent'] is None
    now=datetime.utcnow()+timedelta(seconds=1)
    for i,state in enumerate(['sent','uncertain','failed']):
        oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,kind='initial',sequence=i,recipient='hello@example.com',idempotency_key=str(i),status=state,message_id=str(i),created_at=now))
    oa.db.session.add(oa.OutreachReplyEvidence(lead_id=lead.id,message_id='actual-reply',from_email='hello@example.com',body_text='Yes interested',created_at=now+timedelta(seconds=1)))
    record_reply_outcome(lead.id,'actual-reply','interested');oa.db.session.flush()
    record_reply_outcome(lead.id,'actual-reply','interested')
    for i,state in enumerate(['confirmed','uncertain']):
        oa.db.session.add(oa.OutreachBookingAttempt(lead_id=lead.id,reply_message_id='actual-reply',idempotency_key='book'+str(i),event_id='event'+str(i),start='2026-11-01',end='2026-11-02',timezone='America/New_York',attendee_email='hello@example.com',status=state,created_at=now+timedelta(seconds=2)))
    oa.db.session.commit()
    actual=campaign_outcomes(first)
    assert actual['counts']['sent']==actual['counts']['replies']==actual['counts']['positive_replies']==actual['counts']['booked']==1
    assert actual['rates']['reply_rate_per_sent']==actual['rates']['booking_rate_per_sent']==100
    assert actual['delivered'] is actual['customers'] is actual['revenue'] is None
    assert campaign_outcomes(other)['counts']['sent']==0
    assert CampaignMembership.query.count()==1


def test_historical_sends_cannot_be_claimed_as_new_outcomes(setup):
    first,_,lead=setup
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,kind='initial',sequence=0,recipient='hello@example.com',idempotency_key='old',status='sent',message_id='old',created_at=datetime.utcnow()-timedelta(days=2)))
    oa.db.session.commit()
    assert campaign_outcomes(first)['counts']['sent']==0


def test_automatic_reply_is_not_a_conversation_or_positive_reply(setup):
    first,other,lead=setup
    now=datetime.utcnow()+timedelta(seconds=1)
    oa.db.session.add(oa.OutreachSendAttempt(lead_id=lead.id,kind='initial',sequence=0,recipient='hello@example.com',idempotency_key='send',status='sent',message_id='message',created_at=now))
    oa.db.session.add(oa.OutreachReplyEvidence(lead_id=lead.id,message_id='ooo',from_email='hello@example.com',body_text='Automatic reply: I am out of office and interested in reviewing this later.',created_at=now+timedelta(seconds=1)))
    record_reply_outcome(lead.id,'ooo','interested');oa.db.session.commit()
    result=campaign_outcomes(first)
    assert result['counts']['replies']==1
    assert result['counts']['positive_replies']==result['counts']['conversations']==0
    assert result['rates']['conversation_rate_per_sent']==0
    assert campaign_outcomes(other)['counts']['replies']==0
