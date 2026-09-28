from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_handles_unsent_lead_defaults():
    lead = OutreachLead(company="x", contact_email="x@example.com")
    snap = runner.snapshot(lead)
    assert not snap["gmail_message_id"]
    assert not snap["gmail_thread_id"]
    assert snap["sent_at"] is None
    assert snap["replied_at"] is None
