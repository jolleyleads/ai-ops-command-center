from pathlib import Path

def test_acceptance_runner_has_no_randomness():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "random" not in text
    assert "uuid" not in text
