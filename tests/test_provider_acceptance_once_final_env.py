from pathlib import Path

def test_acceptance_runner_requires_explicit_recipient():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "ACCEPTANCE_RECIPIENT_REQUIRED" in text
