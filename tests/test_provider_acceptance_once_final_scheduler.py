from pathlib import Path

def test_acceptance_runner_calls_production_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "cycle = run_scheduled_outreach_cycle()" in text
