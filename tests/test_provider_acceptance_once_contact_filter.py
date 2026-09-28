from pathlib import Path

def test_current_contact_email_filter_is_used():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "filter_by(contact_email=recipient, company=marker)" in text
