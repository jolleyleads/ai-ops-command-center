from pathlib import Path

def test_acceptance_constructor_has_contact_fields():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "contact_email=recipient" in text
    assert "contact_name=" in text
