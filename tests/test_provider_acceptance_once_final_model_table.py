from outreach_automation import OutreachLead

def test_acceptance_uses_outreach_lead_table():
    assert OutreachLead.__tablename__ == "outreach_lead"
