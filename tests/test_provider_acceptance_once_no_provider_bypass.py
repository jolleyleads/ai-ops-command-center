from pathlib import Path

def test_runner_only_invokes_application_scheduler_for_provider_work():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "run_scheduled_outreach_cycle()" in text
    assert "send_gmail(" not in text
