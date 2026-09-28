from pathlib import Path

def test_runner_reports_timestamp_key():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"timestamp"' in text
