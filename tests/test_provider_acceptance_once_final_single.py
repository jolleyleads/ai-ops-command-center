from pathlib import Path

def test_acceptance_runner_runs_one_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("cycle = run_scheduled_outreach_cycle()") == 1
