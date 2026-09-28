from outreach_automation import OutreachLead

def test_acceptance_model_has_durable_timestamps():
    assert hasattr(OutreachLead, "created_at")
    assert hasattr(OutreachLead, "updated_at")
