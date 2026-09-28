from pathlib import Path

def test_runner_reports_before_after_snapshots():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"before": before' in source
    assert '"after": snapshot(lead)' in source
