from pathlib import Path

def test_latest_matching_acceptance_lead_is_selected():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "OutreachLead.id.desc()" in text
