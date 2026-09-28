from pathlib import Path

def test_acceptance_ok_comes_from_real_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'bool(cycle.get("ok"))' in text
