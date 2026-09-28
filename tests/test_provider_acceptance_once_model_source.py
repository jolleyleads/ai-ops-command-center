from pathlib import Path

def test_outreach_model_comes_from_outreach_automation():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "outreach_automation import OutreachLead" in text
