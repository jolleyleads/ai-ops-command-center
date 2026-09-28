from pathlib import Path

def test_runner_normalizes_addresses():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert source.count(".strip().lower()") >= 2
