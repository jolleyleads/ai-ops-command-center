from pathlib import Path

def test_runner_rejects_same_sender_recipient():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "if recipient == sender" in text
