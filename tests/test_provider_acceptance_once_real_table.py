from outreach_automation import OutreachLead

def test_real_outreach_table_name():
    assert OutreachLead.__tablename__ == "outreach_lead"
