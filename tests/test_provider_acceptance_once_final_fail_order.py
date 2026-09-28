from pathlib import Path

def test_failed_cycle_exits_after_output():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert text.rindex("json.dumps(result") < text.rindex("SystemExit(1)")
