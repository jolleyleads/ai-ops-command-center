from pathlib import Path

def test_acceptance_runner_has_no_hardcoded_sender():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "jolleyleads@gmail.com" not in text
