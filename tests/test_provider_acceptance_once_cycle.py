from pathlib import Path

def test_runner_includes_cycle_result():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert '"cycle": cycle' in source
