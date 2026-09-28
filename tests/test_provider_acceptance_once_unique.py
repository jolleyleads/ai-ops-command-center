from pathlib import Path

def test_acceptance_lookup_uses_email_and_marker():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "contact_email=recipient" in text
    assert "company=marker" in text
