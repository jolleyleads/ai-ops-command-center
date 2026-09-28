from outreach_automation import OutreachLead

def test_acceptance_fields_exist():
    for name in ("company", "contact_email", "status", "gmail_message_id", "gmail_thread_id", "sent_at", "replied_at", "last_error"):
        assert hasattr(OutreachLead, name)
