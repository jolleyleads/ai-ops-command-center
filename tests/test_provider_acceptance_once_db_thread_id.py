from outreach_automation import OutreachLead

def test_outreach_lead_has_gmail_thread_id():
    assert hasattr(OutreachLead, "gmail_thread_id")
