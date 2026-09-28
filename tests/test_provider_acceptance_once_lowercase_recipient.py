from pathlib import Path

def test_recipient_is_normalized_lowercase():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'recipient = (os.getenv("ACCEPTANCE_RECIPIENT") or "").strip().lower()' in text
