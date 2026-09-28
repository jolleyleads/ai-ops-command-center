from pathlib import Path

def test_runner_does_not_use_qualification_status_field():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "qualification_status" not in text
