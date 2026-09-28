from pathlib import Path

def test_runner_does_not_clear_last_error():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "lead.last_error =" not in text
