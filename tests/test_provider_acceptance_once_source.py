from pathlib import Path

def test_runner_does_not_import_nonexistent_lead():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "from app import app, db, Lead" not in source
    assert "from outreach_automation import OutreachLead" in source
