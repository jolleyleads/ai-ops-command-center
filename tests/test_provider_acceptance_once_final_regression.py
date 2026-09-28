from pathlib import Path

def test_acceptance_runner_uses_current_production_model():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "OutreachLead" in text
    assert "contact_email" in text
