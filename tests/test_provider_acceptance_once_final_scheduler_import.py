from pathlib import Path

def test_acceptance_runner_imports_production_scheduler():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from outreach_scheduler import run_scheduled_outreach_cycle" in text
