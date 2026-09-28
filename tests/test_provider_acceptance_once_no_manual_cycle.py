from pathlib import Path

def test_cycle_is_returned_by_scheduler():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "cycle = run_scheduled_outreach_cycle()" in text
