from pathlib import Path

def test_acceptance_runner_only_seeds_when_missing():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "if lead is None:" in text
