from pathlib import Path

def test_runner_does_not_call_google_directly():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "googleapis.com" not in text
