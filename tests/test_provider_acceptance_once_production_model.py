from outreach_automation import OutreachLead

def test_production_model_has_required_acceptance_fields():
    required = ["company", "contact_email", "gmail_message_id", "gmail_thread_id", "sent_at", "replied_at"]
    assert all(hasattr(OutreachLead, name) for name in required)
