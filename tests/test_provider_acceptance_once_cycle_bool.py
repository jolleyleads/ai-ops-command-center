from pathlib import Path

def test_result_normalizes_cycle_ok_to_bool():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'bool(cycle.get("ok"))' in text
