from pathlib import Path

def test_failure_is_machine_readable():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'json.dumps({"ok": False, "reason": reason}' in source
