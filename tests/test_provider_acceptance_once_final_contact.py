from pathlib import Path

def test_acceptance_seed_has_test_contact_marker():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'contact_name="Acceptance Test"' in text
