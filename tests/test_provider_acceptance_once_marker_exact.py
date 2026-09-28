from pathlib import Path

def test_exact_acceptance_marker():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"Provider Acceptance E2E"' in text
