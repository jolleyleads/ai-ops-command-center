from pathlib import Path

def test_acceptance_runner_reports_recipient():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"recipient": recipient' in text
