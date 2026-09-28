from pathlib import Path

def test_runner_requires_configured_sender():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'os.getenv("GMAIL_FROM_EMAIL")' in source
    assert "GMAIL_FROM_EMAIL_REQUIRED" in source
