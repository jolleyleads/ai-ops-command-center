from outreach_automation import OutreachLead

def test_outreach_lead_has_last_error():
    assert hasattr(OutreachLead, "last_error")
