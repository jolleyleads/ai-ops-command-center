from pathlib import Path

def test_runner_uses_dedicated_acceptance_marker():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'marker = "Provider Acceptance E2E"' in source
