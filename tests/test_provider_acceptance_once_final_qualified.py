from pathlib import Path

def test_acceptance_seed_is_qualified_and_verified():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'status="qualified"' in text
    assert 'verification="SOURCE_VERIFIED"' in text
