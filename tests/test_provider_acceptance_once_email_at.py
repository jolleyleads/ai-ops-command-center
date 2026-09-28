from pathlib import Path

def test_recipient_validation_checks_at_sign():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"@" not in recipient' in text
