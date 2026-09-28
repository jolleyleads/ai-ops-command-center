from pathlib import Path

def test_failed_cycle_prints_result_before_exit():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.rindex("print(") < text.rindex("raise SystemExit(1)")
