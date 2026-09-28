from pathlib import Path

def test_current_outreach_constructor_is_used():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "OutreachLead(company=marker, contact_email=recipient" in text
