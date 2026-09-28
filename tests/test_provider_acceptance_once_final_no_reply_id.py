from pathlib import Path

def test_acceptance_runner_does_not_assign_reply_message_id():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "reply_message_id" not in text
