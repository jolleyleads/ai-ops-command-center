from pathlib import Path

def test_acceptance_sender_and_recipient_must_differ():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "if recipient == sender" in text
