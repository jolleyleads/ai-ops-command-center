from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_reads_status():
    lead = OutreachLead(company="x", contact_email="x@example.com", status="qualified")
    assert runner.snapshot(lead)["status"] == "qualified"
