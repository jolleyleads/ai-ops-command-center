from pathlib import Path

def test_sender_is_normalized_lowercase():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'sender = (os.getenv("GMAIL_FROM_EMAIL") or "").strip().lower()' in text
