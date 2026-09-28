from pathlib import Path

def test_acceptance_runner_does_not_delete_data():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "session.delete" not in text
