from pathlib import Path

def test_acceptance_constructor_uses_required_fields():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    for field in ("company=marker", "contact_email=recipient", "score=100", 'verification="SOURCE_VERIFIED"', 'status="qualified"'):
        assert field in text
