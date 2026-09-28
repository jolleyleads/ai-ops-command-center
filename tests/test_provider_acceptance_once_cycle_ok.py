from pathlib import Path

def test_runner_uses_real_cycle_ok():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"ok": bool(cycle.get("ok"))' in source
