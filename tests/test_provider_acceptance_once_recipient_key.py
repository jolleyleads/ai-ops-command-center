from pathlib import Path

def test_runner_reports_recipient_key():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"recipient"' in text
