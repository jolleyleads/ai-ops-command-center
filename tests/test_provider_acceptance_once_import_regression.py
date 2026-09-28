from pathlib import Path

def test_original_import_error_cannot_regress():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from app import app, db, Lead" not in text
    assert "from outreach_automation import OutreachLead" in text
