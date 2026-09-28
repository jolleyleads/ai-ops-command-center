from pathlib import Path

def test_acceptance_message_requests_reply():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "reply" in text.lower()
    assert "interested" in text.lower()
