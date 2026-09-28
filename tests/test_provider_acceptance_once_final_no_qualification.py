from pathlib import Path

def test_acceptance_runner_does_not_use_qualification_status():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "qualification_status" not in text
