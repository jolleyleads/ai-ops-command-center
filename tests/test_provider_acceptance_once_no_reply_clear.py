from pathlib import Path

def test_runner_does_not_clear_reply_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "replied_at=None" not in text
