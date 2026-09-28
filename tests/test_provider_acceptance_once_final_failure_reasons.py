from pathlib import Path

def test_acceptance_configuration_failures_are_named():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "ACCEPTANCE_RECIPIENT_REQUIRED" in text
    assert "GMAIL_FROM_EMAIL_REQUIRED" in text
    assert "RECIPIENT_MUST_DIFFER_FROM_SENDER" in text
