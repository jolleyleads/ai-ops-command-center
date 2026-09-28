from outreach_automation import OutreachLead

def test_outreach_lead_has_contact_email():
    assert hasattr(OutreachLead, "contact_email")
