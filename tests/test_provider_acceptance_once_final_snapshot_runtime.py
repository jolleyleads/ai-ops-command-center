from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_reads_real_model_attributes():
    lead = OutreachLead(company="x", contact_email="x@example.com")
    snap = runner.snapshot(lead)
    assert snap["company"] == "x"
    assert snap["contact_email"] == "x@example.com"
