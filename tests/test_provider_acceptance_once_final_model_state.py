from outreach_automation import OutreachLead

def test_acceptance_model_has_send_reply_state():
    assert hasattr(OutreachLead, "sent_at")
    assert hasattr(OutreachLead, "replied_at")
    assert hasattr(OutreachLead, "last_error")
