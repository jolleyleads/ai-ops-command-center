from pathlib import Path

def test_runner_invokes_scheduler_once():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("cycle = run_scheduled_outreach_cycle()") == 1
