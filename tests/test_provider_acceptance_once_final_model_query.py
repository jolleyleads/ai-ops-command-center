from outreach_automation import OutreachLead

def test_acceptance_model_has_query():
    assert hasattr(OutreachLead, "query")
