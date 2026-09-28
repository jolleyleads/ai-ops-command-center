from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_reads_identity_values():
    lead = OutreachLead(company="Provider Acceptance E2E", contact_email="test@example.com")
    snap = runner.snapshot(lead)
    assert snap["company"] == "Provider Acceptance E2E"
    assert snap["contact_email"] == "test@example.com"
