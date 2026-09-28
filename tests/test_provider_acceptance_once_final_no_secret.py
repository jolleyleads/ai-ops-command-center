from pathlib import Path

def test_acceptance_runner_contains_no_credentials():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "client_secret" not in text
    assert "refresh_token" not in text
    assert "password" not in text
