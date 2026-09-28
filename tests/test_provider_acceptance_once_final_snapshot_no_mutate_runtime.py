from outreach_automation import OutreachLead
import scripts.provider_acceptance_once as runner

def test_snapshot_does_not_mutate_identity_or_status():
    lead = OutreachLead(company="x", contact_email="x@example.com", status="qualified")
    runner.snapshot(lead)
    assert lead.company == "x"
    assert lead.contact_email == "x@example.com"
    assert lead.status == "qualified"
