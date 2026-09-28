from pathlib import Path

def test_runner_does_not_assign_verified_attribute():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert ".verified =" not in text
