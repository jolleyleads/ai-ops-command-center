from pathlib import Path

def test_runner_has_no_randomized_behavior():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "random" not in text
