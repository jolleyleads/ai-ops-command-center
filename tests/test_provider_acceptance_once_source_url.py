from pathlib import Path

def test_runner_has_acceptance_source_marker():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'source_url="provider-acceptance"' in source
