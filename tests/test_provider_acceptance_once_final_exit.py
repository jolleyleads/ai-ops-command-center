from pathlib import Path

def test_acceptance_runner_exits_nonzero_on_failed_cycle():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'if not result["ok"]: raise SystemExit(1)' in text
