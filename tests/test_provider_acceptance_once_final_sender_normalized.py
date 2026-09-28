from pathlib import Path

def test_acceptance_sender_is_normalized():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'GMAIL_FROM_EMAIL") or "").strip().lower()' in text
