from pathlib import Path

def test_snapshot_does_not_use_nonexistent_calendar_fields():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "calendar_event_id" not in text
    assert "calendar_event_link" not in text
