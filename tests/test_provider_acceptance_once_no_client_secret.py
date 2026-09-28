from pathlib import Path

def test_runner_contains_no_client_credentials():
    text = Path("scripts/provider_acceptance_once.py").read_text().lower()
    assert "client_secret" not in text
    assert "client_id" not in text
