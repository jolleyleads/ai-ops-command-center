from pathlib import Path

def test_runner_does_not_fabricate_calendar_event():
    source = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "calendar_event_id =" not in source
    assert "event_id =" not in source
