from pathlib import Path

def test_acceptance_runner_does_not_use_outreach_status_field():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "outreach_status" not in text
