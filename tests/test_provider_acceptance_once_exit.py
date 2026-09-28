from pathlib import Path

def test_runner_exits_nonzero_when_cycle_fails():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'if not result["ok"]: raise SystemExit(1)' in source
