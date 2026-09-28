from pathlib import Path

def test_acceptance_runner_imports_app_and_db():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from app import app, db" in text
