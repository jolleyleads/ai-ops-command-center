from pathlib import Path

def test_acceptance_recipient_has_no_fallback_address():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '(os.getenv("ACCEPTANCE_RECIPIENT") or "")' in text
