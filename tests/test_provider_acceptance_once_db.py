from pathlib import Path

def test_runner_uses_application_db_session():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session" in text
