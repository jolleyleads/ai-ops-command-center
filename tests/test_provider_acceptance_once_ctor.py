from pathlib import Path

def test_constructs_outreach_lead():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead = OutreachLead(" in text
