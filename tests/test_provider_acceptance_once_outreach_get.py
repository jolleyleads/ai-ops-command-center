from pathlib import Path

def test_current_outreach_reload_is_used():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "session.get(OutreachLead, lead.id)" in text
