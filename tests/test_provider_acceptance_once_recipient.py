from pathlib import Path

def test_runner_reports_recipient():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"recipient": recipient' in source
