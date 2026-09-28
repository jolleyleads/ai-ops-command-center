from pathlib import Path

def test_runner_has_deterministic_failure_reasons():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    for reason in ("ACCEPTANCE_RECIPIENT_REQUIRED", "GMAIL_FROM_EMAIL_REQUIRED", "RECIPIENT_MUST_DIFFER_FROM_SENDER"):
        assert reason in text
