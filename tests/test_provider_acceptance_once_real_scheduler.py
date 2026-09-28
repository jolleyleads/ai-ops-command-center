from pathlib import Path

def test_runner_imports_real_scheduler():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from outreach_scheduler import run_scheduled_outreach_cycle" in source
