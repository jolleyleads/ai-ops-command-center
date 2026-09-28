from pathlib import Path

def test_acceptance_runner_has_single_cycle_call():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("run_scheduled_outreach_cycle()") == 1
