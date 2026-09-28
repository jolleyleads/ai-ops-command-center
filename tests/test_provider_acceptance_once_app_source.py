from pathlib import Path

def test_app_import_is_limited_to_app_and_db():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from app import app, db\n" in text
