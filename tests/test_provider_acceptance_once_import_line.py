from pathlib import Path

def test_corrected_import_line():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from app import app, db" in text
    assert "from outreach_automation import OutreachLead" in text
