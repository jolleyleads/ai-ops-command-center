from pathlib import Path

def test_acceptance_runner_rejects_sender_as_recipient():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "RECIPIENT_MUST_DIFFER_FROM_SENDER" in text
