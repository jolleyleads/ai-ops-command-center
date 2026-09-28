from pathlib import Path

def test_acceptance_runner_uses_latest_matching_lead():
    text = Path("scripts/provider_acceptance_once.py").read_text()
    assert "order_by(OutreachLead.id.desc()).first()" in text
