from pathlib import Path

def test_acceptance_runner_reports_cycle_result():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"cycle": cycle' in text
