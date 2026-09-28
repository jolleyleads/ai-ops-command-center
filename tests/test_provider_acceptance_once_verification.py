from pathlib import Path

def test_runner_sets_source_verification():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'verification="SOURCE_VERIFIED"' in text
