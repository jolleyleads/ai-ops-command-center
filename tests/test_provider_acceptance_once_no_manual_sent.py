from pathlib import Path

def test_runner_does_not_assign_sent_timestamp():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.sent_at =" not in text
