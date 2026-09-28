from pathlib import Path

def test_acceptance_runner_does_not_bypass_application_provider_path():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "send_gmail(" not in text
    assert "requests." not in text
