from pathlib import Path

def test_no_app_lead_import():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "app, db, Lead" not in text
