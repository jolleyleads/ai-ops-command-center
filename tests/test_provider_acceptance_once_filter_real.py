from pathlib import Path

def test_uses_real_contact_email_filter():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "contact_email=recipient" in text
    assert "email=recipient" not in text.replace("contact_email=recipient", "")
