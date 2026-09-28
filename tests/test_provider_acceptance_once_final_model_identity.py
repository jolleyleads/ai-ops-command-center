from outreach_automation import OutreachLead

def test_acceptance_model_has_identity_fields():
    assert hasattr(OutreachLead, "company")
    assert hasattr(OutreachLead, "contact_email")
    assert hasattr(OutreachLead, "contact_name")
