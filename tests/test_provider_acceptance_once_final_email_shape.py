from pathlib import Path

def test_acceptance_recipient_has_basic_email_validation():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"@" not in recipient' in text
