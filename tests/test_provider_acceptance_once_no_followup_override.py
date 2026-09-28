from pathlib import Path

def test_runner_does_not_override_followup_fields():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "follow_up_due_at=" not in text
    assert "follow_up_count=" not in text
