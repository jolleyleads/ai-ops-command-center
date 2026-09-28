from pathlib import Path

def test_cycle_variable_is_assigned_once():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.count("cycle =") == 1
