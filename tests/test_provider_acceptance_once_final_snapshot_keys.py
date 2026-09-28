from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_has_expected_keys():
    lead = OutreachLead(company="x", contact_email="x@example.com")
    snap = runner.snapshot(lead)
    assert set(snap) == {"id", "company", "contact_email", "status", "gmail_message_id", "gmail_thread_id", "sent_at", "replied_at", "last_error"}
