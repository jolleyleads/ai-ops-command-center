from pathlib import Path

def test_runner_imports_only_app_and_db_from_app():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from app import app, db\n" in source
