from outreach_automation import OutreachLead

def test_outreach_lead_has_source_url():
    assert hasattr(OutreachLead, "source_url")
