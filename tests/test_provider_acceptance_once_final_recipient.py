from pathlib import Path

def test_acceptance_recipient_is_normalized():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'ACCEPTANCE_RECIPIENT") or "").strip().lower()' in text
