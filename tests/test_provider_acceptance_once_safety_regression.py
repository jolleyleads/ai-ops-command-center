from pathlib import Path

def test_same_sender_recipient_guard_cannot_regress():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "if recipient == sender" in text
    assert "RECIPIENT_MUST_DIFFER_FROM_SENDER" in text
