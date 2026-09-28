from pathlib import Path

def test_runner_uses_production_scheduler():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "run_scheduled_outreach_cycle()" in source
