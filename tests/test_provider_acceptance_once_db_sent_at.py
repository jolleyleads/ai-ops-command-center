from outreach_automation import OutreachLead

def test_outreach_lead_has_sent_at():
    assert hasattr(OutreachLead, "sent_at")
