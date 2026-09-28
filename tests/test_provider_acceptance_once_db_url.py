from pathlib import Path

def test_runner_does_not_read_database_url_directly():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "DATABASE_URL" not in text
