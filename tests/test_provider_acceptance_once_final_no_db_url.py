from pathlib import Path

def test_acceptance_runner_does_not_read_database_url():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "DATABASE_URL" not in text
