from pathlib import Path

def test_acceptance_cycle_is_application_scheduler_result():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "cycle = run_scheduled_outreach_cycle()" in text
