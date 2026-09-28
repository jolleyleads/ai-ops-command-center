from pathlib import Path

def test_acceptance_seed_requests_interested_reply():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "interested" in text
    assert "meeting time" in text
