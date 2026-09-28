from pathlib import Path

def test_runner_has_recipient_safety_gate():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "RECIPIENT_MUST_DIFFER_FROM_SENDER" in source
    assert "ACCEPTANCE_RECIPIENT_REQUIRED" in source
