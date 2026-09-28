from pathlib import Path

def test_no_legacy_lead_query():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "Lead.query" not in text
