from outreach_automation import OutreachLead

def test_outreach_lead_has_query_interface():
    assert hasattr(OutreachLead, "query")
