from pathlib import Path

def test_reload_uses_outreach_lead():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.get(OutreachLead, lead.id)" in text
