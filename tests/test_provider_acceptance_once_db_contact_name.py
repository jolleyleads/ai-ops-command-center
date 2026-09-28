from outreach_automation import OutreachLead

def test_outreach_lead_has_contact_name():
    assert hasattr(OutreachLead, "contact_name")
