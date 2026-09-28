from pathlib import Path

def test_no_legacy_lead_get():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "session.get(Lead" not in text
