from pathlib import Path

def test_acceptance_runner_reports_creation_state():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "created = False" in text
    assert "created = True" in text
