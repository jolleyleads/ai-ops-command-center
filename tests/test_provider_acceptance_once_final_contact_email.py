from pathlib import Path

def test_acceptance_runner_uses_contact_email():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "contact_email=recipient" in text
