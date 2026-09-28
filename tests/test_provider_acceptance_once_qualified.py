from pathlib import Path

def test_acceptance_lead_starts_qualified():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'status="qualified"' in text
