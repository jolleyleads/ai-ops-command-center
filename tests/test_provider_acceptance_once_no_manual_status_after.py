from pathlib import Path

def test_runner_does_not_force_sent_status():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert 'lead.status = "sent"' not in text
