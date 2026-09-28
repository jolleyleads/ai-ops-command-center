from pathlib import Path

def test_provider_work_flows_through_scheduler_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("run_scheduled_outreach_cycle") == 2
