from pathlib import Path

def test_acceptance_seed_has_explicit_reply_instruction():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "Please reply that you are interested" in text
