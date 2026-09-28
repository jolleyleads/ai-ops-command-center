from pathlib import Path

def test_no_obsolete_email_constructor_field():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "OutreachLead(company=marker, email=" not in text
