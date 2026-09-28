from pathlib import Path

def test_acceptance_runner_does_not_directly_send_mail():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "send_gmail(" not in text
    assert "_safe_send(" not in text
