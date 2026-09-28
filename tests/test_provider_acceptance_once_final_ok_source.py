from pathlib import Path

def test_acceptance_ok_is_derived_from_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'bool(cycle.get("ok"))' in text
