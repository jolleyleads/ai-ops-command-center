from pathlib import Path

def test_runner_does_not_bypass_scheduler_with_direct_send():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "send_gmail(" not in source
    assert "_safe_send(" not in source
