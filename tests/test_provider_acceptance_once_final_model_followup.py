from outreach_automation import OutreachLead

def test_acceptance_model_has_followup_fields():
    assert hasattr(OutreachLead, "follow_up_due_at")
    assert hasattr(OutreachLead, "follow_up_count")
