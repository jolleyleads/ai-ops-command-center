from outreach_automation import OutreachLead

def test_acceptance_model_fields_exist():
    assert hasattr(OutreachLead, "company")
    assert hasattr(OutreachLead, "contact_email")
    assert hasattr(OutreachLead, "gmail_message_id")
    assert hasattr(OutreachLead, "gmail_thread_id")
