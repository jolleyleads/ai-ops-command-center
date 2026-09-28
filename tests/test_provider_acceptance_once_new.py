from pathlib import Path

def test_missing_acceptance_lead_is_created():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead = OutreachLead(" in text
    assert "created = True" in text
