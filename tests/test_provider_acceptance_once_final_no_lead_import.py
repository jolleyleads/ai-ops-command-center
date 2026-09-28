from pathlib import Path

def test_acceptance_runner_does_not_import_lead_from_app():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from app import app, db, Lead" not in text
