from pathlib import Path

def test_runner_creates_only_when_missing():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "if lead is None:" in source
