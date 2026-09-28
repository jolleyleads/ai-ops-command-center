from pathlib import Path

def test_acceptance_lead_has_dedicated_marker():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'marker = "Provider Acceptance E2E"' in text
