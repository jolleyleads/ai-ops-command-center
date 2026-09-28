from pathlib import Path

def test_runner_does_not_start_background_scheduler():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "outreach_scheduler.start" not in text
