from pathlib import Path

def test_acceptance_runner_does_not_assign_verified_flag():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "verified=True" not in text
