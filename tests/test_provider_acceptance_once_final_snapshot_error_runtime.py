from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_reads_last_error():
    lead = OutreachLead(company="x", contact_email="x@example.com", last_error="boom")
    assert runner.snapshot(lead)["last_error"] == "boom"
