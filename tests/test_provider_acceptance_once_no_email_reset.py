from pathlib import Path

def test_existing_lead_email_is_not_mutated():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.contact_email =" not in text
