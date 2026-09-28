from pathlib import Path

def test_runner_seeds_qualified_acceptance_lead():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'status="qualified"' in source
    assert 'verification="SOURCE_VERIFIED"' in source
