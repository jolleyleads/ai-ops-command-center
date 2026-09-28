from pathlib import Path

def test_failure_payload_is_explicitly_false():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert '{"ok": False, "reason": reason}' in text
