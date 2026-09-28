from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_does_not_create_provider_receipts():
    lead = OutreachLead(company="x", contact_email="x@example.com")
    before = (lead.gmail_message_id, lead.gmail_thread_id, lead.sent_at, lead.replied_at)
    runner.snapshot(lead)
    after = (lead.gmail_message_id, lead.gmail_thread_id, lead.sent_at, lead.replied_at)
    assert after == before
