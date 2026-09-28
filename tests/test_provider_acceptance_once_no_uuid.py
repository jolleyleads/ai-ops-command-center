from pathlib import Path

def test_runner_does_not_randomize_acceptance_identity():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "uuid" not in text
