from pathlib import Path

def test_no_legacy_lead_reload():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "db.session.get(Lead," not in text
