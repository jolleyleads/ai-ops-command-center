from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_reads_provider_receipts():
    lead = OutreachLead(company="x", contact_email="x@example.com", gmail_message_id="m1", gmail_thread_id="t1")
    snap = runner.snapshot(lead)
    assert snap["gmail_message_id"] == "m1"
    assert snap["gmail_thread_id"] == "t1"
