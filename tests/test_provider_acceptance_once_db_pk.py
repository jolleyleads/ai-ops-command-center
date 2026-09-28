from outreach_automation import OutreachLead

def test_outreach_lead_has_id_primary_key():
    assert hasattr(OutreachLead, "id")
