from outreach_automation import OutreachLead

def test_acceptance_model_has_provider_receipt_fields():
    assert hasattr(OutreachLead, "gmail_message_id")
    assert hasattr(OutreachLead, "gmail_thread_id")
