from pathlib import Path

def test_acceptance_runner_does_not_assign_calendar_proof():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "calendar_event_id" not in text
