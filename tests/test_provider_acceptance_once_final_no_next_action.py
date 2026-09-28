from pathlib import Path

def test_acceptance_runner_does_not_use_next_action_field():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "next_action" not in text
