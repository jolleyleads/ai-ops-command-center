from pathlib import Path

def test_runner_has_no_invalid_lead_symbol():
    source = Path("scripts/provider_acceptance_once.py").read_text()
    assert "Lead.query" not in source
    assert "db.session.get(Lead," not in source
