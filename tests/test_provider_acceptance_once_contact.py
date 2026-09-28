from pathlib import Path

def test_runner_has_acceptance_contact_name():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'contact_name="Acceptance Test"' in source
