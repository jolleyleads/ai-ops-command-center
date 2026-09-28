from pathlib import Path

def test_acceptance_seed_has_test_location_marker():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'location="Production Acceptance"' in text
