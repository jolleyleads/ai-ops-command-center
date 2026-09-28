from pathlib import Path

def test_runner_reports_whether_lead_was_created():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"created": created' in source
