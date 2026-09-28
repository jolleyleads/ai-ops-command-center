from pathlib import Path

def test_acceptance_failed_cycle_exits_nonzero():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'if not result["ok"]' in text
