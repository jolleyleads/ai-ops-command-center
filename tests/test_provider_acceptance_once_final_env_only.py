from pathlib import Path

def test_acceptance_addresses_come_from_environment():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "ACCEPTANCE_RECIPIENT" in text
    assert "GMAIL_FROM_EMAIL" in text
