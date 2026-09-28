from pathlib import Path

def test_runner_contains_no_token_literals():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "refresh_token" not in text
    assert "access_token" not in text
